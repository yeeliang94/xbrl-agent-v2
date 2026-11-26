"""One zip of everything recorded for a run (docs/api-contract.md, "Traces").

Safety: no path from the database or the request becomes a file path. The
two folders read come from the run's number alone. Every file inside them is
resolved and must still sit inside its folder; symbolic links are skipped.
The uploaded files are only told apart, by comparing resolved paths, and are
added only when asked for. The zip is written to a temporary file, never held
in memory whole.

Every text in the zip (records, transcripts, the log lines) goes through
`app/utils/masking.mask`, so no key or gateway address leaves in it. Only
the uploaded files, added when asked for, go in as they are.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable, Optional

from app.db import now
from app.guidance import framing
from app.reading import store as reading
from app.records import server_log
from app.scope import answer as scope_answer
from app.utils.masking import mask
from app.utils.paths import output_dir, safe_path
from app.utils.version import VERSION, deployed_commit, version_text

NOT_RECORDED_YET: list[str] = []
_UPLOAD_NAME = re.compile(r"^(document-[0-9a-f]+\.pdf|source-[0-9a-f]+\.(docx|xlsx)|filled-workbook-[0-9a-f]+\.xlsx"
                          r"|starting-workbook-[0-9a-f]+\.xls[xm]"
                          r"|fills/(template|filled)-[0-9]+\.xls[xm])$")
MODEL_CALL_COLUMNS = ("id", "run_id", "source", "page", "model", "input_tokens", "cached_tokens", "output_tokens",
                      "cost_usd", "duration_ms", "error", "created_at")


def _rows(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, tuple(params))]


def _parsed(row: dict, *names: str) -> dict:
    """The row with its JSON text columns turned back into values."""
    for name in names:
        text = row.pop(name, None)
        row[name.removesuffix("_json")] = json.loads(text) if text else None
    return row


def csv_cell(value: Any) -> Any:
    """A spreadsheet must not run a cell as a formula."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def csv_text(columns: Iterable[str], rows: Iterable[dict]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    columns = list(columns)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([csv_cell(row.get(c)) for c in columns])
    return out.getvalue()


def _run_record(conn: sqlite3.Connection, run_id: int) -> dict:
    run = dict(conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone())
    company = conn.execute("SELECT * FROM companies WHERE id = ?", (run["company_id"],)).fetchone()
    setup = conn.execute("SELECT * FROM run_setup WHERE run_id = ?", (run_id,)).fetchone()
    return {
        "run": run, "company": dict(company) if company else None, "setup": dict(setup) if setup else None,
        "statements": [_parsed(r, "pages_json") for r in _rows(
            conn, "SELECT statement, variant, included, pages_json FROM run_statements WHERE run_id = ? "
                  "ORDER BY statement", (run_id,))],
        "notes": _rows(conn, "SELECT number, title, first_page, last_page FROM run_notes WHERE run_id = ? "
                             "ORDER BY position", (run_id,)),
        "stages": _rows(conn, "SELECT * FROM stages WHERE run_id = ? ORDER BY id", (run_id,)),
        "jobs": [_parsed(j, "payload_json") for j in _rows(conn, "SELECT * FROM jobs WHERE run_id = ? ORDER BY id",
                                                          (run_id,))],
    }


def _pages(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    return [_parsed(p, "content_json") for p in _rows(
        conn, "SELECT p.page, p.width, p.height, p.rotation, p.has_text_layer, p.read_at, p.read_error, p.content_json "
              "FROM pages p JOIN documents d ON d.id = p.document_id WHERE d.run_id = ? ORDER BY p.page", (run_id,))]


def _figures(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    figures = _rows(conn, "SELECT * FROM figures WHERE run_id = ? ORDER BY id", (run_id,))
    lines: dict[int, list] = {}
    for line in _rows(conn, "SELECT l.* FROM figure_lines l JOIN figures f ON f.id = l.figure_id "
                            "WHERE f.run_id = ? ORDER BY l.id", (run_id,)):
        lines.setdefault(line["figure_id"], []).append(line)
    history: dict[int, list] = {}
    for row in _rows(conn, "SELECT * FROM figure_history WHERE run_id = ? ORDER BY id", (run_id,)):
        history.setdefault(row["figure_id"], []).append(_parsed(row, "before_json", "after_json"))
    return [{**f, "lines": lines.get(f["id"], []), "history": history.get(f["id"], [])} for f in figures]


def _notes(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    """Every note with its blocks and its history, oldest change first."""
    history: dict[int, list] = {}
    for row in _rows(conn, "SELECT * FROM note_history WHERE run_id = ? ORDER BY id", (run_id,)):
        history.setdefault(row["note_id"], []).append(_parsed(row, "before_json", "after_json", "comment_ids_json"))
    return [{**_parsed(n, "pages_json", "blocks_json"), "history": history.get(n["id"], [])}
            for n in _rows(conn, "SELECT * FROM notes WHERE run_id = ? ORDER BY id", (run_id,))]


def _review(conn: sqlite3.Connection, run_id: int) -> tuple[list[dict], list[dict]]:
    """Every comment with its thread, and every round with the comments it carried and its change report."""
    from app.review import changes

    comment_rows = [_parsed(c, "thread_json") for c in _rows(
        conn, "SELECT * FROM comments WHERE run_id = ? ORDER BY id", (run_id,))]
    round_rows = []
    for r in _rows(conn, "SELECT * FROM rounds WHERE run_id = ? ORDER BY id", (run_id,)):
        r = _parsed(r, "checks_before_json")
        r["comments"] = _rows(conn, "SELECT * FROM round_comments WHERE round_id = ? ORDER BY comment_id", (r["id"],))
        r["report"] = changes.report(conn, run_id, r["id"])
        round_rows.append(r)
    return comment_rows, round_rows


def _scoring(conn: sqlite3.Connection, run_id: int) -> Optional[dict]:
    workbook = conn.execute("SELECT * FROM filled_workbooks WHERE run_id = ?", (run_id,)).fetchone()
    if workbook is None:
        return None
    return {"workbook": _parsed(dict(workbook), "loose_json"),
            "cells": _rows(conn, "SELECT * FROM filled_workbook_cells WHERE run_id = ?", (run_id,)),
            "notes": _rows(conn, "SELECT * FROM filled_workbook_notes WHERE run_id = ?", (run_id,))}


def _starting(conn: sqlite3.Connection, run_id: int) -> Optional[dict]:
    """The starting workbook's record and the comparatives read against its last-year figures (step 10d)."""
    row = conn.execute("SELECT * FROM starting_workbooks WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return {"workbook": _parsed(dict(row), "facts_json", "import_json"),
            "comparisons": _rows(conn, "SELECT * FROM prior_year_comparisons WHERE run_id = ? ORDER BY figure_id",
                                 (run_id,))}


def _fills(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    """Every mTool fill with its full report, file paths relative to the output folder."""
    return [_parsed(f, "report_json") for f in _rows(conn, "SELECT * FROM fills WHERE run_id = ? ORDER BY id",
                                                      (run_id,))]


def _reports(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    """Every assessed report field with its history, oldest change first (step 10)."""
    history: dict[int, list] = {}
    for row in _rows(conn, "SELECT * FROM report_field_history WHERE run_id = ? ORDER BY id", (run_id,)):
        history.setdefault(row["field_id"], []).append(_parsed(row, "before_json", "after_json"))
    return [{**_parsed(f, "pages_json", "blocks_json"), "history": history.get(f["id"], [])}
            for f in _rows(conn, "SELECT * FROM report_fields WHERE run_id = ? ORDER BY report, id", (run_id,))]


def _uploaded(conn: sqlite3.Connection, run_id: int, run_folder: Path) -> list[tuple[Path, str]]:
    """The run's uploaded files, as (resolved path, name in the zip). A stored
    path that does not resolve inside the run's own folder is ignored. The
    mTool fills' templates and filled files are named by fill number."""
    out = []
    rows = [conn.execute(sql, (run_id,)).fetchone() for sql in (
        # A Word or Excel run keeps two files: the file as uploaded, and the reading copy made from it.
        "SELECT stored_path, CASE WHEN kind = 'pdf' THEN filename ELSE 'reading copy of ' || filename || '.pdf' END "
        "AS filename FROM documents WHERE run_id = ?",
        "SELECT source_path AS stored_path, filename FROM documents WHERE run_id = ?",
        "SELECT stored_path, filename FROM filled_workbooks WHERE run_id = ?",
        "SELECT stored_path, 'starting ' || filename AS filename FROM starting_workbooks WHERE run_id = ?")]
    for fill in conn.execute("SELECT id, template_path, template_filename, output_path FROM fills "
                             "WHERE run_id = ? ORDER BY id", (run_id,)):
        rows.append({"stored_path": fill["template_path"], "filename": f"fill-{fill['id']} {fill['template_filename']}"})
        if fill["output_path"]:
            rows.append({"stored_path": fill["output_path"],
                         "filename": f"fill-{fill['id']} filled{Path(fill['output_path']).suffix}"})
    for row in rows:
        if row is None or not row["stored_path"]:
            continue
        try:
            path = safe_path(output_dir() / row["stored_path"])
        except PermissionError:
            continue
        if path.is_relative_to(run_folder) and path.is_file():
            name = re.sub(r"[^\w.\- ]", "_", Path(str(row["filename"])).name).strip(". ") or "upload"
            out.append((path, name))
    return out



def _files_in(folder: Path) -> Iterable[tuple[Path, str]]:
    """Regular files under `folder`, as (resolved path, relative name), never
    following a symbolic link out of it."""
    if not folder.is_dir():
        return
    for directory, subfolders, names in os.walk(folder, followlinks=False):
        subfolders[:] = sorted(d for d in subfolders if not (Path(directory) / d).is_symlink())
        for name in sorted(names):
            candidate = Path(directory) / name
            if candidate.is_symlink() or not candidate.is_file():
                continue
            resolved = safe_path(candidate)
            if resolved.is_relative_to(folder):
                yield resolved, resolved.relative_to(folder).as_posix()


def build(conn: sqlite3.Connection, run_id: int, *, include_pdf: bool) -> Path:
    """Write the run's traces zip to a temporary file and return its path.
    The caller removes the file once it is sent."""
    run_id = int(run_id)
    run_folder = safe_path(output_dir() / "runs" / f"run-{run_id}")
    transcripts = safe_path(output_dir() / "transcripts" / f"run-{run_id}")
    temp_folder = safe_path(output_dir() / "tmp")
    temp_folder.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=f"traces-{run_id}-", suffix=".zip", dir=temp_folder)
    os.close(handle)
    path = safe_path(name)
    written: list[str] = []
    try:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            def put(arcname: str, payload: Any) -> None:
                text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2,
                                                                           default=str)
                zf.writestr(arcname, mask(text))
                written.append(arcname)

            def put_file(source: Path, arcname: str) -> None:
                data = source.read_bytes()
                try:
                    zf.writestr(arcname, mask(data.decode("utf-8")))
                except UnicodeDecodeError:
                    zf.writestr(arcname, data)   # not text, so no key can be written in it as text
                written.append(arcname)

            put("version.txt", version_text())   # which build made these records
            put("run.json", _run_record(conn, run_id))
            put("events.json", [_parsed(e, "data_json") for e in _rows(
                conn, "SELECT * FROM events WHERE run_id = ? ORDER BY id", (run_id,))])
            calls = _rows(conn, "SELECT * FROM model_calls WHERE run_id = ? ORDER BY id", (run_id,))
            put("model_calls.json", calls)
            put("model_calls.csv", csv_text(MODEL_CALL_COLUMNS, calls))
            document = conn.execute("SELECT * FROM documents WHERE run_id = ?", (run_id,)).fetchone()
            put("document.json", dict(document) if document else None)
            put("pages.json", _pages(conn, run_id))
            if document is not None and document["kind"] != "pdf":   # the file's own words and numbers
                put("file_lines.json", [_parsed(r, "cells_json") for r in _rows(
                    conn, "SELECT position, page, kind, block, sheet, row, cells_json FROM file_lines "
                          "WHERE document_id = ? ORDER BY position", (document["id"],))])
            put("document_map.json", reading.saved_map(conn, run_id))
            put("figures.json", _figures(conn, run_id))
            put("checks.json", [_parsed(c, "comparands_json") for c in _rows(
                conn, "SELECT * FROM check_results WHERE run_id = ? ORDER BY check_name, entity_scope", (run_id,))])
            put("notes.json", _notes(conn, run_id))
            put("note_reports.json", [_parsed(r, "pages_json") for r in _rows(
                conn, "SELECT * FROM note_reports WHERE run_id = ? ORDER BY id", (run_id,))])
            comment_rows, round_rows = _review(conn, run_id)
            put("comments.json", comment_rows)
            put("rounds.json", round_rows)
            put("scope_questions.json", scope_answer.questions(conn, run_id))
            put("guidance_used.json", framing.used(conn, run_id))
            put("fills.json", _fills(conn, run_id))
            put("starting_workbook.json", _starting(conn, run_id))
            put("reports.json", _reports(conn, run_id))
            scoring = _scoring(conn, run_id)
            if scoring is not None:
                put("scoring.json", scoring)
            with zf.open("server-log.txt", "w") as log:
                for line in server_log.lines_for_run(run_id):
                    log.write(mask(line).encode("utf-8"))
            written.append("server-log.txt")

            uploaded = _uploaded(conn, run_id, run_folder)
            skip = {p for p, _ in uploaded}
            for source, relative in _files_in(transcripts):
                put_file(source, f"transcripts/{relative}")
            for source, relative in _files_in(run_folder):
                if source in skip or _UPLOAD_NAME.match(relative):
                    continue   # an uploaded file, even an earlier copy, goes in only when asked for
                put_file(source, f"records/{relative}")
            if include_pdf:
                for source, arcname in uploaded:
                    zf.write(source, f"uploaded/{arcname}")
                    written.append(f"uploaded/{arcname}")
            put("manifest.json", {"run_id": run_id, "made_at": now(), "include_pdf": include_pdf,
                                  "app_version": VERSION, "commit": deployed_commit(),
                                  "files": sorted(written), "not_recorded_yet": NOT_RECORDED_YET})
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path
