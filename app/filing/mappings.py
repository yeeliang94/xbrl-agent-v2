"""Placements a person confirmed for a template (step 12), kept by the template's fingerprint. A saved
mapping makes the template known (`identify`) and gives the fill the cells it could not find itself
(`plan_figures`, `confirmed`). Only a person's Use on the placements screen writes one: the investigating
agent never does."""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

from app import db

KEY = ("concept_uuid", "period", "entity_scope", "dimension_key")


def key(line: dict) -> tuple:
    return tuple(line.get(k) or "" for k in KEY)


def confirmed_for(conn: sqlite3.Connection, fingerprint: str) -> Optional[dict]:
    """`{"name", "cells": {key: (sheet, row, col)}, "labels": {key: the row's words when confirmed}}` for
    `fill_workbook`, or None."""
    row = conn.execute("SELECT name, cells_json FROM template_mappings WHERE fingerprint = ?",
                       (fingerprint,)).fetchone()
    if row is None:
        return None
    saved = json.loads(row["cells_json"])
    return {"name": row["name"], "cells": {key(c): (c["sheet"], int(c["row"]), c["col"]) for c in saved},
            "labels": {key(c): c.get("label", "") for c in saved}}


def still_fits(mapping: dict, label_of) -> dict:
    """The mapping with only the cells whose row still holds the words it held when a person confirmed it.
    The template's fingerprint ignores rows, so a row moved since then would put a figure on another line;
    such a cell is dropped and the figure is placed by meaning, or listed, as if nothing were saved."""
    cells = {k: cell for k, cell in mapping["cells"].items()
             if " ".join((mapping["labels"].get(k) or "").split()).lower()
             == " ".join(label_of(cell[0], cell[1]).split()).lower()}
    return {**mapping, "cells": cells}


def save(conn: sqlite3.Connection, fingerprint: str, name: str, cells: list[dict], email: str) -> None:
    """Add these confirmed cells to the template's mapping; a figure confirmed again takes its new cell."""
    row = conn.execute("SELECT cells_json FROM template_mappings WHERE fingerprint = ?", (fingerprint,)).fetchone()
    merged = {key(c): c for c in (json.loads(row["cells_json"]) if row else [])}
    merged.update({key(c): {**{k: c[k] for k in KEY}, "sheet": c["sheet"], "row": int(c["row"]), "col": c["col"],
                            "label": c.get("label", "")} for c in cells})
    stamp = db.now()
    conn.execute("INSERT INTO template_mappings(fingerprint, name, cells_json, confirmed_by, confirmed_at) "
                 "VALUES (?, ?, ?, ?, ?) ON CONFLICT(fingerprint) DO UPDATE SET cells_json = excluded.cells_json, "
                 "confirmed_by = excluded.confirmed_by, confirmed_at = excluded.confirmed_at",
                 (fingerprint, name, json.dumps(list(merged.values())), email, stamp))
