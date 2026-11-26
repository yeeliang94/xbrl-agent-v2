"""An Excel run's sheets: where each sits in the reading copy, a sheet's cells
for the review screen, the sheet and cell behind a figure, and bringing in a
hidden sheet.

A figure is saved with its reading-copy page, like any other. Its sheet and
cell are worked out when it is shown: the page names the sheet, the printed
label names the row, and the amount names the cell. Nothing extra is asked
of the agent, and a figure a person typed is found the same way. When the
row or the cell cannot be told apart, the source says only as much as is
known (the sheet, or the sheet and row).
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Optional

from app.documents import file_lines, intake, store
from app.documents.reading_copy import Line, parse_amount
from app.documents.source_file import EXCEL
from app.utils.paths import output_dir, safe_path


class SheetRefused(ValueError):
    """`str()` is one plain sentence."""


def _used(row: sqlite3.Row) -> list[dict]:
    return [s for s in store.sheets(row) if s["used"]]


def sheet_of_page(row: sqlite3.Row, page: Optional[int]) -> Optional[str]:
    if page is None:
        return None
    return next((s["name"] for s in _used(row) if s["first_page"] <= page <= s["last_page"]), None)


def grid(conn: sqlite3.Connection, run_id: int, name: str) -> Optional[dict]:
    """One sheet's filled cells as the review screen draws them, or None when the run has no such sheet."""
    row = store.document_row(conn, run_id)
    used = sorted(_used(row), key=lambda s: s["first_page"])
    found = next((s for s in used if s["name"] == name), None)
    if found is None:
        return None
    lines = file_lines.of_run(conn, run_id, sheet=name)
    letters = sorted({cell[0] for line in lines for cell in line.cells}, key=lambda c: (len(c), c))
    return {"name": name, "position": used.index(found) + 1, "count": len(used), "columns": letters,
            "first_page": found["first_page"], "last_page": found["last_page"],
            "rows": [{"row": line.row, "cells": {cell[0]: cell[1] for cell in line.cells}} for line in lines]}


def index_note(run_id: int) -> str:
    """For the Reader's opening message: which pages each sheet of the workbook is laid out on. Empty for a
    run that did not start from a workbook."""
    from app import db

    with db.connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE run_id = ?", (run_id,)).fetchone()
    if row is None or row["kind"] != EXCEL:
        return ""
    used = sorted(_used(row), key=lambda s: s["first_page"])
    where = "; ".join(f"{s['name']} on p{s['first_page']}"
                      + (f"-{s['last_page']}" if s["last_page"] != s["first_page"] else "") for s in used)
    return f"\nThe workbook's sheets, by reading-copy page: {where}."


# The sheet and cell behind a figure ----------------------------------------

def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _amounts(row: dict) -> list[tuple[str, float]]:
    """(column key, amount as printed) for each of the row's cells that holds a figure, in column order."""
    out = []
    for key, cell in row.get("cells", {}).items():
        amount = cell.get("printed") if cell.get("printed") is not None else cell.get("value")
        if cell.get("figure_id") is not None and amount is not None:
            out.append((key, float(amount)))
    return out


def _holding(line: Line, amount: float, taken: set[str]) -> Optional[str]:
    """The first cell of the line, not yet used, that holds the amount whatever its sign: as the sheet
    shows it (a rounded or scaled cell shows less than it saves) or as it saves it."""
    def holds(cell: list) -> bool:
        return any(found is not None and abs(abs(found) - abs(amount)) < 0.005
                   for found in (parse_amount(str(cell[1] or "")), cell[2]))
    return next((cell[0] for cell in line.cells if cell[0] not in taken and holds(cell)), None)


def _find_line(lines: list[Line], label: str, amounts: list[tuple[str, float]]) -> Optional[Line]:
    def score(line: Line) -> int:
        taken: set[str] = set()
        for _, amount in amounts:
            letter = _holding(line, amount, taken)
            if letter:
                taken.add(letter)
        return len(taken)

    wanted = _key(label)
    named = [line for line in lines if wanted and any(cell[2] is None and _key(cell[1]) == wanted
                                                      for cell in line.cells)]
    pool = named or [line for line in lines if amounts and score(line) == len(amounts)]
    if not pool:
        return None
    best = max(pool, key=score)
    # Two lines with the same label (a repeated sub-heading) and no amount to tell them apart: not known.
    return best if len(pool) == 1 or sum(score(line) == score(best) for line in pool) == 1 else None


def annotate(conn: sqlite3.Connection, run_id: int, view: dict) -> dict:
    """Say what the run started from (`source_kind`: pdf, word or excel), and for an Excel run add each
    row's `source` ({sheet, row}) and each cell's `source_cell`."""
    row = conn.execute("SELECT * FROM documents WHERE run_id = ?", (run_id,)).fetchone()
    view["source_kind"] = row["kind"] if row is not None else "pdf"
    if row is None or row["kind"] != EXCEL:
        return view
    by_page: dict[int, list[Line]] = {}
    pages = {item["page"] for item in view["rows"] if item.get("page") is not None}
    for line in file_lines.of_run(conn, run_id, pages=pages) if pages else []:
        by_page.setdefault(line.page, []).append(line)
    for item in view["rows"]:
        sheet = sheet_of_page(row, item.get("page"))
        if sheet is None:
            continue
        amounts = _amounts(item)
        line = _find_line(by_page.get(item["page"], []), item.get("printed_label") or item.get("label") or "",
                          amounts)
        item["source"] = {"sheet": sheet, "row": line.row if line else None}
        taken: set[str] = set()
        for key, amount in amounts if line else []:
            letter = _holding(line, amount, taken)
            if letter:
                taken.add(letter)
                item["cells"][key]["source_cell"] = f"{letter}{line.row}"
    return view


# Bringing in a hidden sheet --------------------------------------------------

def _checked(conn: sqlite3.Connection, run: sqlite3.Row, name: str) -> tuple[sqlite3.Row, list[str]]:
    """The run's document row and the hidden sheets brought in once this one is, or SheetRefused."""
    row = store.document_row(conn, int(run["id"]))
    if row["kind"] != EXCEL:
        raise SheetRefused("This run did not start from an Excel workbook.")
    if run["status"] != "setup":
        raise SheetRefused("A sheet can be brought in only while the run waits at setup.")
    known = {s["name"]: s for s in store.sheets(row)}
    if name not in known:
        raise SheetRefused(f"The workbook has no sheet called {name}.")
    if known[name]["used"]:
        raise SheetRefused(f"The sheet {name} is already in use.")
    return row, json.loads(row["source_json"]).get("brought_in", []) + [name]


def bring_in(run_id: int, user, name: str) -> None:
    """Lay a hidden sheet out after the pages already read, and read the document again: only the new
    pages are transcribed, then the Reader maps the whole document. The workbook is laid out again
    outside any transaction, so the write lock is held only for the short write at the end."""
    from app import db
    from app.runs import store as runs

    with db.connect() as conn:
        row, extra = _checked(conn, runs.open_run(conn, run_id, user), name)
    data = safe_path(output_dir() / row["source_path"]).read_bytes()
    upload = intake.prepare(row["filename"], data, brought_in=extra)
    added = next(s for s in upload.sheets if s["name"] == name)
    if not added["used"]:
        raise SheetRefused(f"The sheet {name} has nothing on it.")
    relative, _ = store.write_files(run_id, upload)
    with db.connect(immediate=True) as conn:
        now_row, now_extra = _checked(conn, runs.open_run(conn, run_id, user), name)
        if now_extra != extra:            # another sheet was brought in meanwhile
            raise SheetRefused("The workbook changed while this sheet was laid out, so try again.")
        old_count = int(now_row["page_count"])
        conn.execute("UPDATE documents SET stored_path = ?, page_count = ?, source_json = ? WHERE id = ?",
                     (relative, len(upload.pages),
                      json.dumps({"sheets": upload.sheets, "brought_in": extra}, ensure_ascii=False), now_row["id"]))
        store.add_pages(conn, now_row["id"], [p for p in upload.pages if p.page > old_count])
        file_lines.save(conn, now_row["id"], [line for line in upload.lines if line.sheet == name],
                        start=file_lines.count(conn, now_row["id"]))
        pages = added["last_page"] - added["first_page"] + 1
        conn.execute(
            "INSERT INTO events(run_id, source, kind, message, created_at) VALUES (?, 'upload', 'finished', ?, ?)",
            (run_id, f"The hidden sheet {name} is brought in: {pages} more page{'s' if pages != 1 else ''}.",
             store.now()))
        conn.execute("DELETE FROM document_maps WHERE run_id = ?", (run_id,))
        store.start_reading(conn, run_id)
        runs.touch(conn, run_id)
