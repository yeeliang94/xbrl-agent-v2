"""A field's whole text as mTool gets it, and how it fits mTool's limit.

mTool holds one text per field, so the size is the field's, not one note's:
every note placed there, in order, through the one renderer
(`app/notes/render.prepare`) with the Settings house style. The review list
shows the fit, the Copy button copies the text, and Needs you names a field
that is too long. Prepared texts are kept by the notes' blocks and the
house style, so the list does not draw each field again on every read.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections import OrderedDict
from typing import Optional

from app.notes import render
from app.notes.blocks import parse

_KEPT: "OrderedDict[tuple, render.Prepared]" = OrderedDict()
_KEEP = 256
_LOCK = threading.Lock()   # routes read from several worker threads


def field_rows(conn: sqlite3.Connection, run_id: int, node_uuid: str) -> list[sqlite3.Row]:
    """The notes placed in a field, in their order there."""
    return conn.execute("SELECT * FROM notes WHERE run_id = ? AND node_uuid = ? ORDER BY position, id",
                        (run_id, node_uuid)).fetchall()


def house(conn: sqlite3.Connection) -> dict:
    from app.settings import store as settings
    return settings._read(conn)["house_style"]


def prepared(conn: sqlite3.Connection, run_id: int, node_uuid: str, house_style: Optional[dict] = None
             ) -> Optional[render.Prepared]:
    """The field's prepared text, or None when no note is placed there."""
    found = field_rows(conn, run_id, node_uuid)
    if not found:
        return None
    style = house_style if house_style is not None else house(conn)
    blocks = "\n".join(r["blocks_json"] for r in found)
    key = (hashlib.sha256(blocks.encode("utf-8")).hexdigest(), json.dumps(style, sort_keys=True))
    with _LOCK:
        if key in _KEPT:
            _KEPT.move_to_end(key)
            return _KEPT[key]
    text = render.prepare([parse(json.loads(r["blocks_json"])) for r in found], style)
    with _LOCK:
        _KEPT[key] = text
        while len(_KEPT) > _KEEP:
            _KEPT.popitem(last=False)
    return text


def fit(text: Optional[render.Prepared]) -> Optional[dict]:
    """`NoteFit` (docs/api-contract.md, Step 6e)."""
    return None if text is None else {"tier": text.tier, "chars": text.chars, "limit": text.limit}


def public(node_uuid: str, text: render.Prepared) -> dict:
    """`PreparedNote` (docs/api-contract.md, Step 6e)."""
    return {"node_uuid": node_uuid, "revision": text.revision, "html": text.html, "tier": text.tier,
            "chars": text.chars, "limit": text.limit}
