"""Judge where a run placed its notes against an answer key's `notes` section.

"Same field" only: the words are not compared (owner, 18 November 2026).
Each note in the key lists the fields it may go in (`fields`); some are
marked `required`. A note is:

- **right** when every placement of it is in one of its fields and every
  required field holds part of it (a split at a first-level sub-section, or
  the allowed share-capital double, gives several placements);
- **elsewhere** when it is placed, but at least one placement is in a field
  the key does not list, or a required field is missing;
- **not placed** when the run has no placement for it.

A run's note that matches no note in the key is "placed but not in the key".
The single number is right / notes in the key. Unnumbered entries of the key
(an opening paragraph without a number) are judged and reported, but are not
in the number.

A run note is matched to the key by its printed number; one without a number
is matched by its title. Pure, except the two readers at the end: one for a v2
run's `notes` table, one for a v1 run in v1's database (read only).
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Optional

RIGHT, ELSEWHERE, NOT_PLACED = "right", "elsewhere", "not_placed"


@dataclass(frozen=True)
class Placement:
    """One placed note (or part of one). `field_id` is None for a note the run did not place."""
    number: str
    title: str
    field_id: Optional[str]


def _number(text: str) -> str:
    text = re.sub(r"^\s*note\s+", "", (text or "").strip(), flags=re.I)
    return text.rstrip(".").strip().lower()


def _title(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _judge(entry: dict, fields: set[str]) -> str:
    if not fields:
        return NOT_PLACED
    allowed = {f["field_id"] for f in entry.get("fields") or []}
    required = {f["field_id"] for f in entry.get("fields") or [] if f.get("required")}
    return RIGHT if fields <= allowed and required <= fields else ELSEWHERE


def _row(entry: dict, fields: set[str]) -> dict:
    return {"number": entry.get("number", ""), "title": entry.get("title", ""),
            "status": _judge(entry, fields), "run_fields": sorted(fields),
            "key_fields": [f["field_id"] for f in entry.get("fields") or []],
            "confidence": entry.get("confidence", "")}


def score(key_notes: dict, placements: Iterable[Placement]) -> dict:
    """Score a run's placements against a key's `notes` section."""
    numbered = key_notes.get("notes") or []
    unnumbered = key_notes.get("unnumbered") or []
    by_number = {_number(e["number"]): e for e in numbered if _number(e.get("number", ""))}
    by_title = {_title(e["title"]): e for e in [*numbered, *unnumbered]}

    found: dict[int, set[str]] = defaultdict(set)    # id(key entry) -> run fields
    seen: set[int] = set()
    outside: dict[tuple[str, str], set[str]] = {}
    for p in placements:
        entry = by_number.get(_number(p.number)) if _number(p.number) else by_title.get(_title(p.title))
        if entry is None:
            outside.setdefault((p.number, p.title), set())
            if p.field_id:
                outside[(p.number, p.title)].add(p.field_id)
            continue
        seen.add(id(entry))
        if p.field_id:
            found[id(entry)].add(p.field_id)

    notes = [_row(e, found.get(id(e), set())) for e in numbered]
    counts = {s: sum(n["status"] == s for n in notes) for s in (RIGHT, ELSEWHERE, NOT_PLACED)}
    counts["not_in_key"] = len(outside)
    return {
        "score": round(counts[RIGHT] / len(notes), 4) if notes else None,
        "counts": counts,
        "notes": notes,
        "unnumbered": [_row(e, found.get(id(e), set())) for e in unnumbered],
        "not_in_key": [{"number": num, "title": title, "run_fields": sorted(fields)}
                       for (num, title), fields in outside.items()],
    }


# Readers ---------------------------------------------------------------------

def v2_placements(conn: sqlite3.Connection, run_id: int) -> list[Placement]:
    """A v2 run's notes, one placement per stored note or part (`notes` table)."""
    return [Placement(r[0] or "", r[1] or "", r[2]) for r in conn.execute(
        "SELECT note_number, title, node_uuid FROM notes WHERE run_id = ? ORDER BY id", (run_id,))]


def v1_placements(v1: sqlite3.Connection, run_id: int) -> list[Placement]:
    """A v1 run's note placements, from v1's database (open it read only).

    v1 kept one text per field (`notes_cells`, whose `concept_uuid` is v2's
    field id). Which note a field holds comes from three records, joined:
    the source blocks each field used (`notes_block_usages`, with the note
    each block belongs to), the coverage rows' placements, and, for the two
    numeric notes' text fields, the "Note N" in the cell's evidence. Only
    fields still filled at the end of the run count. A filled field none of
    these attributes to a note is not counted.
    """
    cells = {(r[0], r[1]): r[2] for r in v1.execute(
        "SELECT sheet, row, concept_uuid FROM notes_cells WHERE run_id = ?", (run_id,))}
    placed: dict[tuple[str, str], set[tuple[str, int]]] = defaultdict(set)
    generation = v1.execute("SELECT id FROM notes_source_generations WHERE run_id = ? AND status = 'active' "
                            "ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()
    if generation:
        for number, title, sheet, row in v1.execute(
                "SELECT n.top_note_num, n.title, u.sheet, u.row FROM notes_block_usages u "
                "JOIN notes_source_blocks b ON b.generation_id = u.generation_id AND b.block_id = u.block_id "
                "JOIN notes_source_notes n ON n.generation_id = b.generation_id AND n.source_note_id = b.source_note_id "
                "WHERE u.run_id = ? AND u.generation_id = ? AND u.disposition = 'included'", (run_id, generation[0])):
            placed[(number or "", title or "")].add((sheet, row))
    titles = {str(r[0]): r[1] or "" for r in v1.execute(
        "SELECT note_num, title FROM run_notes_inventory WHERE run_id = ?", (run_id,))}
    numbered = {num: title for (num, title) in placed if num}
    for number, raw in v1.execute("SELECT note_num, placements_json FROM notes_coverage_rows "
                                  "WHERE run_id = ? AND subnote_ref IS NULL AND note_num > 0", (run_id,)):
        number = str(number)
        for p in json.loads(raw or "[]"):
            placed[(number, numbered.get(number, titles.get(number, "")))].add((p["sheet"], p["row"]))
    for sheet, row, evidence in v1.execute(
            "SELECT sheet, row, evidence FROM notes_cells WHERE run_id = ? "
            "AND sheet IN ('Notes-Issuedcapital', 'Notes-RelatedPartytran')", (run_id,)):
        match = re.search(r"\bNote (\d+)", evidence or "")
        if match:
            number = match.group(1)
            placed[(number, numbered.get(number, titles.get(number, "")))].add((sheet, row))
    out = []
    for (number, title), where in placed.items():
        for cell in sorted(where):
            if cells.get(cell):
                out.append(Placement(number, title, cells[cell]))
    return out
