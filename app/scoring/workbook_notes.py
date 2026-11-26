"""Read which note fields a person filled in a workbook, and compare them with the run's notes.

Rebuilt from v1 `eval/human_file.py` (`_read_notes`, `_note_fragment`) and
`eval/human_compare.py` (`compare_notes`). As for figures, a field is never
found by position alone:

- **mTool**: the field's row is found by its SSM name, exactly as the fill
  finds it (`app/filing/notes.text_block_cell`). The text is the entry of
  mTool's hidden note store that the text-block cell points at, or text typed
  straight into that cell.
- **template** (the app's own template layout): the text sits in column B of
  the field's row, trusted only when the row's label is the field's label.

The comparison is "same field" only: wording is not compared (owner,
18 November 2026). It builds an answer key from the workbook and scores it
with the existing notes scoring (`app/scoring/notes.py`). A note is told
apart two ways, and nothing else of the words is used:

- the run has a note in a field the workbook filled: that field is one of
  the note's fields in the workbook (v1's rule: both filled the field);
- a line of the workbook's text is exactly a run note's printed number and
  title ("5. Trade and other receivables"): the workbook holds that note in
  that field, and the run must have part of it there. This is what tells a
  note the run placed in a different field from one it left out.

A filled workbook field neither way names is a workbook note with no match
in the run, listed as missing under the field's own label.
"""
from __future__ import annotations

import html
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Iterable, Optional
from xml.etree import ElementTree

from app.catalog.note_fields import NoteField, run_note_fields
from app.filing.notes import text_block_cell
from app.scoring import notes as notes_scoring
from app.scoring.notes import Placement
from app.workbook import mtool_layout, offline_fill
from app.workbook.xlsx_cells import WorkbookUnreadable, read_workbook, resolve_sheet_name, split_ref

HEADING_LINE_CHARS = 200   # a longer line is body text, never a note's printed heading
TEMPLATE_TEXT_COLUMN = "B"

# Excel's escapes in stored text: _xHHHH_ is one character; _x005F_ before another keeps it as written.
_XSTRING_ESCAPE = re.compile(r"_x005[fF]_(_x[0-9a-fA-F]{4}_)|_x([0-9a-fA-F]{4})_")
_BODY = re.compile(r"<body\b[^>]*>(.*)</body>", re.DOTALL | re.IGNORECASE)
_LINE_BREAK = re.compile(r"<\s*(?:br|/p|/div|/h[1-6]|/li|/tr|/table)\b[^>]*>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]*>")


@dataclass(frozen=True)
class WorkbookNote:
    """One note field the person filled. `lines` are its short lines, tags removed."""
    field_id: str
    workbook_cell: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class RunNote:
    """One stored note of the run, or one part of it (`notes` table)."""
    id: int
    number: str
    title: str
    field_id: Optional[str]
    pages: tuple[int, ...]


def text_lines(text: str) -> list[str]:
    """The visible lines of a note's stored text. mTool's XHTML shell is dropped."""
    text = _XSTRING_ESCAPE.sub(lambda m: m.group(1) or chr(int(m.group(2), 16)), text or "")
    body = _BODY.search(text)
    text = _TAG.sub("", _LINE_BREAK.sub("\n", body.group(1) if body else text))
    return [line for raw in html.unescape(text).splitlines() if (line := " ".join(raw.split()))]


def _cell_text(cells: dict, sheet: str, ref: str) -> str:
    col, row = split_ref(ref)
    kind, raw = cells.get(sheet, {}).get(row, {}).get(col, ("E", ""))
    return str(raw or "") if kind == "S" else ""


def _template_cell(note_field: NoteField, cells: dict) -> Optional[tuple[str, str]]:
    sheet = resolve_sheet_name(note_field.sheet, cells)
    if sheet is None:
        return None
    label = _cell_text(cells, sheet, f"A{note_field.row}").lstrip("*").strip()
    return (sheet, f"{TEMPLATE_TEXT_COLUMN}{note_field.row}") if label == note_field.label else None


def read_filled_notes(conn: sqlite3.Connection, run_id: int, path: str) -> list[WorkbookNote]:
    """The note fields of the run's templates that hold text in the workbook. Stores nothing.

    Raises `xlsx_cells.WorkbookUnreadable`."""
    data, cells = read_workbook(path)
    fields = [f for f in run_note_fields(conn, run_id) if not f.heading]
    mtool = mtool_layout.has_taxonomy_names(cells)
    stored: dict[tuple[str, str], str] = {}
    occurrences: mtool_layout.Occurrences = {}
    if mtool:
        occurrences = mtool_layout.index_taxonomy(cells)
        try:
            rows = offline_fill.read_footnote_rows(data, offline_fill.get_sheet_paths(data),
                                                   offline_fill.get_shared_strings(data))
            stored = {(d["sheet"], d["cell"]): rows[name]["payload_text"] or ""
                      for name, d in offline_fill.get_defined_names(data, "fn_").items() if name in rows}
        except (ElementTree.ParseError, KeyError, ValueError) as exc:
            raise WorkbookUnreadable("The notes in this workbook could not be read.") from exc
    found = []
    for note_field in fields:
        if mtool:
            sheet, ref, _problem = text_block_cell(note_field, cells, occurrences)
            where = (sheet, ref) if sheet and ref else None
        else:
            where = _template_cell(note_field, cells)
        if where is None:
            continue
        typed = _cell_text(cells, *where)
        text = stored.get(where) or ("" if typed.strip() == offline_fill._TEXT_BLOCK_MARKER else typed)
        lines = text_lines(text)
        if lines:
            found.append(WorkbookNote(note_field.field_id, f"{where[0]}!{where[1]}",
                                      tuple(line for line in lines if len(line) <= HEADING_LINE_CHARS)))
    return found


# Storing ---------------------------------------------------------------------

def store(conn: sqlite3.Connection, run_id: int, found: Iterable[WorkbookNote]) -> None:
    conn.execute("DELETE FROM filled_workbook_notes WHERE run_id = ?", (run_id,))
    conn.executemany("INSERT INTO filled_workbook_notes(run_id, field_id, workbook_cell, lines_json) "
                     "VALUES (?, ?, ?, ?)",
                     [(run_id, n.field_id, n.workbook_cell, json.dumps(list(n.lines))) for n in found])


def stored(conn: sqlite3.Connection, run_id: int) -> list[WorkbookNote]:
    return [WorkbookNote(r["field_id"], r["workbook_cell"], tuple(json.loads(r["lines_json"])))
            for r in conn.execute("SELECT field_id, workbook_cell, lines_json FROM filled_workbook_notes "
                                  "WHERE run_id = ? ORDER BY rowid", (run_id,))]


def run_notes(conn: sqlite3.Connection, run_id: int) -> tuple[list[RunNote], list[tuple[str, str]]]:
    """The run's stored notes, and the (number, title) of every note confirmed at setup."""
    placed = [RunNote(r["id"], r["note_number"] or "", r["title"] or "", r["node_uuid"],
                      tuple(json.loads(r["pages_json"] or "[]")))
              for r in conn.execute("SELECT id, note_number, title, node_uuid, pages_json FROM notes "
                                    "WHERE run_id = ? ORDER BY id", (run_id,))]
    listed = [(r["number"], r["title"]) for r in conn.execute(
        "SELECT number, title FROM run_notes WHERE run_id = ? ORDER BY position", (run_id,))]
    return placed, listed


# Comparing (pure) ------------------------------------------------------------

def compare_notes(workbook: Iterable[WorkbookNote], run: Iterable[RunNote],
                  listed: Iterable[tuple[str, str]], labels: dict[str, str]) -> Optional[dict]:
    """`NotesComparison` (docs/api-contract.md, Step 2), or None when the workbook has no notes.

    `listed`: the notes confirmed at setup, so a note the run never stored
    can still be named. `labels`: {field id: label}."""
    workbook, run = list(workbook), list(run)
    if not workbook:
        return None
    known: dict[tuple, dict] = {}   # how a note is told apart -> what the run holds of it
    for number, title, note in [(n.number, n.title, n) for n in run] + [(num, t, None) for num, t in listed]:
        group = known.setdefault(notes_scoring.note_key(number, title), {
            "number": number, "title": title, "fields": set(), "ids": [], "pages": set()})
        if note is not None:
            group["ids"].append(note.id)
            group["pages"].update(note.pages)
            if note.field_id:
                group["fields"].add(note.field_id)

    def headings(group: dict) -> set[str]:
        number = notes_scoring.note_key(group["number"], "")[1]
        return {notes_scoring.words(f"{lead}{number} {group['title']}") for lead in ("", "note ")}

    numbered = [(key, headings(group)) for key, group in known.items() if key[0] == "number"]
    entries: dict[tuple, dict] = {}   # the answer key: one entry per note the workbook holds

    def entry(key: tuple, number: str, title: str) -> dict:
        return entries.setdefault(key, {"number": number, "title": title, "fields": {}})

    for filled in workbook:
        lines = {notes_scoring.words(line) for line in filled.lines}
        named = False
        for key, wanted in numbered:
            if wanted & lines:
                entry(key, known[key]["number"], known[key]["title"])["fields"][filled.field_id] = True
                named = True
        # Only when no note is named in the field's words: then a run note placed there is taken to be
        # its content. Where a heading names the note, another run note in the same field is misplaced.
        for key, group in known.items() if not named else ():
            if filled.field_id in group["fields"]:
                entry(key, group["number"], group["title"])["fields"].setdefault(filled.field_id, False)
                named = True
        if not named:
            entry(("field", filled.field_id), "", labels.get(filled.field_id, ""))["fields"][filled.field_id] = True

    key_notes = {"notes": [{"number": e["number"], "title": e["title"],
                            "fields": [{"field_id": f, "required": required} for f, required in e["fields"].items()]}
                           for e in entries.values()]}
    result = notes_scoring.score(key_notes, [Placement(n.number, n.title, n.field_id) for n in run])

    def named_fields(field_ids: Iterable[str]) -> list[dict]:
        return [{"field_id": f, "label": labels.get(f, "")} for f in field_ids]

    kinds = {notes_scoring.ELSEWHERE: "different_field", notes_scoring.NOT_PLACED: "missing"}
    differences = []
    for key, judged in zip(entries, result["notes"]):
        if judged["status"] == notes_scoring.RIGHT:
            continue
        group = known.get(key, {"ids": [], "pages": ()})
        differences.append({"kind": kinds[judged["status"]], "number": judged["number"], "title": judged["title"],
                            "run_fields": named_fields(judged["run_fields"]),
                            "workbook_fields": named_fields(judged["key_fields"]),
                            "note_id": group["ids"][0] if group["ids"] else None,
                            "pages": sorted(group["pages"])})
    counts = result["counts"]
    return {"score": result["score"], "in_workbook": len(result["notes"]),
            "same_field": counts[notes_scoring.RIGHT], "different_field": counts[notes_scoring.ELSEWHERE],
            "missing": counts[notes_scoring.NOT_PLACED], "differences": differences,
            "only_in_run": [{"number": n["number"], "title": n["title"], "run_fields": named_fields(n["run_fields"])}
                            for n in result["not_in_key"] if n["run_fields"]]}


def comparison(conn: sqlite3.Connection, run_id: int) -> Optional[dict]:
    """The stored workbook notes against the run's current notes."""
    placed, listed = run_notes(conn, run_id)
    labels = {f.field_id: f.label for f in run_note_fields(conn, run_id)}
    return compare_notes(stored(conn, run_id), placed, listed, labels)
