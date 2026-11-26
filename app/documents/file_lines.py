"""The words and numbers of a Word or Excel file, as the file holds them.

Stored at upload, one row per heading, paragraph or table row, each with the
reading-copy page it is laid out on. The agents read and search them through
`app/agents/file_tools.py`; the review screen reads a sheet's cells here.
A run that started from a PDF has none.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Iterable, Optional

from app.documents.reading_copy import Line


def save(conn: sqlite3.Connection, document_id: int, lines: Iterable[Line], *, start: int = 0) -> None:
    conn.executemany(
        "INSERT INTO file_lines(document_id, position, page, kind, block, sheet, row, cells_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(document_id, start + i, line.page, line.kind, line.block, line.sheet, line.row,
          json.dumps(line.cells, ensure_ascii=False)) for i, line in enumerate(lines)])


def _line(row: sqlite3.Row) -> Line:
    return Line(kind=row["kind"], cells=json.loads(row["cells_json"]), block=row["block"], sheet=row["sheet"],
                row=row["row"], page=row["page"])


def run_kind(conn: sqlite3.Connection, run_id: Optional[int]) -> Optional[str]:
    """`pdf`, `word` or `excel`, or None for a run with no document."""
    if run_id is None:
        return None
    row = conn.execute("SELECT kind FROM documents WHERE run_id = ?", (run_id,)).fetchone()
    return row["kind"] if row is not None else None


def of_run(conn: sqlite3.Connection, run_id: int, *, pages: Optional[Iterable[int]] = None,
           sheet: Optional[str] = None) -> list[Line]:
    """The run's lines in file order: all of them, those on the named pages, or one sheet's."""
    sql = ("SELECT l.* FROM file_lines l JOIN documents d ON d.id = l.document_id WHERE d.run_id = ?")
    params: list = [run_id]
    if pages is not None:
        wanted = sorted(set(pages))
        sql += f" AND l.page IN ({', '.join('?' * len(wanted))})"
        params += wanted
    if sheet is not None:
        sql += " AND l.sheet = ?"
        params.append(sheet)
    return [_line(r) for r in conn.execute(sql + " ORDER BY l.position", params)]


def count(conn: sqlite3.Connection, document_id: int) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM file_lines WHERE document_id = ?", (document_id,)).fetchone()[0])
