"""A comment on a note, or on part of it: a block, or a table's row, column
or cell (docs/api-contract.md, Step 6e).

`resolve` checks a note target against the note's own blocks, and `name`
words the part as the review screen names a selection, so a person reads
"Note 5 Trade and other receivables › Row: Total", never a block id. Rows
and columns are 0-based here, as the browser sends them.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

SCOPES = ("block", "table", "row", "column", "cell")
_WORD = {"heading": "Heading", "paragraph": "Paragraph", "list": "List", "table": "Table"}


def _refused(sentence: str, status: int = 422):
    from app.review.comments import CommentRefused   # comments imports this module
    return CommentRefused(sentence, status)


def _note(conn: sqlite3.Connection, run_id: int, note_id: Any) -> sqlite3.Row:
    if type(note_id) is not int:
        raise _refused("A note comment names the note by its id.")
    row = conn.execute("SELECT * FROM notes WHERE run_id = ? AND id = ?", (run_id, note_id)).fetchone()
    if row is None:
        raise _refused("There is no such note in this run.", 404)
    return row


def note_title(row) -> str:
    number, title = row["note_number"], row["title"]
    return (f"Note {number} {title}" if number else title or "The note").strip()


def _blocks(row: sqlite3.Row) -> list[dict]:
    return json.loads(row["blocks_json"]).get("blocks", [])


def _index(value: Any) -> Optional[int]:
    return value if type(value) is int else None


def resolve(conn: sqlite3.Connection, run_id: int, target: dict) -> dict:
    """A note target as stored. Raises CommentRefused."""
    row = _note(conn, run_id, target.get("note_id"))
    out = {"kind": "note", "statement": None, "concept_uuid": None, "period": None, "entity_scope": None,
           "dimension_key": "", "note_id": row["id"], "note_part": None}
    part = target.get("note_part")
    if part is None:
        return out
    if not isinstance(part, dict):
        raise _refused("A comment on part of a note is on a block, a table, a row, a column or a cell.")
    block_id = str(part.get("block") or "").strip().lower()
    block = next((b for b in _blocks(row) if b["id"] == block_id), None)
    if block is None:
        raise _refused(f"{note_title(row)} has no block {part.get('block') or '(none)'}.")
    scope = part.get("scope") or "block"
    if scope not in SCOPES:
        raise _refused("A comment on part of a note is on a block, a table, a row, a column or a cell.")
    if block["kind"] != "table":
        if scope != "block":
            raise _refused(f"A {block['kind']} has no rows or columns, so comment on the whole block.")
        out["note_part"] = {"block": block_id, "scope": "block", "row": None, "column": None}
        return out
    scope = "table" if scope == "block" else scope
    row_no = _index(part.get("row")) if scope in ("row", "cell") else None
    col_no = _index(part.get("column")) if scope in ("column", "cell") else None
    if scope in ("row", "cell") and row_no is None:
        raise _refused("Name the row for a row or cell comment.")
    if scope in ("column", "cell") and col_no is None:
        raise _refused("Name the column for a column or cell comment.")
    height, width = len(block["rows"]), len(block["columns"])
    if row_no is not None and not 0 <= row_no < height:
        raise _refused(f"The table has {height} rows, so row {row_no + 1} does not exist.")
    if col_no is not None and not 0 <= col_no < width:
        raise _refused(f"The table has {width} columns, so column {col_no + 1} does not exist.")
    out["note_part"] = {"block": block_id, "scope": scope, "row": row_no, "column": col_no}
    return out


def _column_name(table: dict, c: int) -> str:
    for r in table["rows"]:
        if r["role"] == "heading" and c < len(r["cells"]) and r["cells"][c]["text"].strip():
            return " ".join(r["cells"][c]["text"].split())
    return ""


def _row_name(table: dict, r: int) -> str:
    row = table["rows"][r]
    first = " ".join(row["cells"][0]["text"].split()) if row["cells"] else ""
    return first or ("Total" if row["role"] in ("total", "subtotal") else f"Row {r + 1}")


def part_name(blocks: list[dict], part: Optional[dict]) -> str:
    """The part as the review screen names a selection, or "" for the whole note."""
    if not part:
        return ""
    block = next((b for b in blocks if b["id"] == part["block"]), None)
    if block is None:
        return ""
    if block["kind"] != "table" or part["scope"] in ("block", "table"):
        return _WORD.get(block["kind"], "Block")
    try:
        if part["scope"] == "column":
            c = part["column"]
            return f"Column: {_column_name(block, c) or ('Labels' if c == 0 else str(c + 1))}"
        if part["scope"] == "row":
            return f"Row: {_row_name(block, part['row'])}"
        col = _column_name(block, part["column"]) if part["column"] else ""
        row = _row_name(block, part["row"])
        return f"{row}, {col}" if col else row
    except (IndexError, TypeError):   # the table changed shape after the comment (a redo from source)
        return "Table"


def name(conn: sqlite3.Connection, run_id: int, note_id: Optional[int], part: Optional[dict]) -> str:
    """"Note 5 Trade and other receivables", with " › " and the part when the comment is on one."""
    row = conn.execute("SELECT * FROM notes WHERE run_id = ? AND id = ?", (run_id, note_id)).fetchone()
    if row is None:
        return "A note"
    shown = part_name(_blocks(row), part)
    return f"{note_title(row)} › {shown}" if shown else note_title(row)
