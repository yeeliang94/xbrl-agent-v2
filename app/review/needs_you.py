"""The "Needs you" list: everything that waits for a person, in one list
(decision record 3, item 4; document-agent-lessons 5.2).

Order: failed checks, Unsure figures, open agent comments, notes (too long,
to check, not placed, source gaps, missing required fields), then one group of alike lines answered at once. It ends with `passed`, the
figures holding a value that no item names. Each item carries what the
browser needs to open it.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Optional

from app.catalog import lookup
from app.checks.runner import read_checks
from app.figures import store
from app.notes import field_text, note_figures, store_reports
from app.notes import store_rows as note_rows
from app.notes.state import PROSE_STATEMENT
from app.review import comments, note_parts

PERIOD_WORDS = {"CY": "this year", "PY": "last year"}


class _Fields:
    """Field labels and statements, each read once."""

    def __init__(self, conn: sqlite3.Connection, run_id: int):
        self.conn, self.family, self.cache = conn, lookup.run_family(conn, run_id), {}

    def concept(self, uuid: Optional[str]) -> Optional[lookup.Concept]:
        if not uuid:
            return None
        if uuid not in self.cache:
            self.cache[uuid] = lookup.concept(self.conn, uuid)
        return self.cache[uuid]

    def where(self, uuid: Optional[str], period: Optional[str], entity: Optional[str], figure_id: Optional[int]
              ) -> dict:
        concept = self.concept(uuid)
        statement = self.family.statement_of(concept.template_id) if concept and self.family else None
        out = {"statement": statement.value if statement else None, "concept_uuid": uuid, "period": period,
               "entity_scope": entity, "figure_id": figure_id}
        code = None if statement or concept is None else note_figures.numeric_code(self.family, concept.template_id)
        if code:   # a share capital or related-party figure: opened on the note that shows it
            out.update(statement=code, note_id=note_figures.holding_note(self.conn, self.family.run_id,
                                                                         concept.template_id))
        return out

    def title(self, uuid: Optional[str], period: Optional[str]) -> str:
        concept = self.concept(uuid)
        label = concept.plain_label if concept else "The statement"
        return f"{label}, {PERIOD_WORDS[period]}" if period in PERIOD_WORDS else label


def _figure_id(conn: sqlite3.Connection, run_id: int, uuid, period, entity) -> Optional[int]:
    if not uuid or not period:
        return None
    row = conn.execute("SELECT id FROM figures WHERE run_id = ? AND concept_uuid = ? AND period = ? "
                       "AND entity_scope = ? AND dimension_key = ''", (run_id, uuid, period, entity)).fetchone()
    return int(row[0]) if row else None


def _plain(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def alike_lines(conn: sqlite3.Connection, run_id: int, fields: _Fields) -> list[dict]:
    """Figures saved from a printed line whose label is not the field's, that no person confirmed since
    their last change."""
    out = []
    for r in conn.execute(
            # An Unsure figure or one with a sign question stays its own item: accepting a name never settles it.
            "SELECT f.id, f.concept_uuid, f.period, f.entity_scope, l.printed_label FROM figures f "
            "JOIN figure_lines l ON l.figure_id = f.id WHERE f.run_id = ? AND f.value IS NOT NULL "
            "AND f.status != 'not_disclosed' AND f.origin = 'agent' AND f.certainty = 'sure' "
            "AND f.sign_question = 0 ORDER BY f.id, l.id", (run_id,)):
        concept = fields.concept(r["concept_uuid"])
        if concept is None or _plain(r["printed_label"]) == _plain(concept.plain_label):
            continue
        last = conn.execute("SELECT action, actor_kind FROM figure_history WHERE figure_id = ? "
                            "AND action != 'calculate' ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
        if last is not None and last["action"] == "confirm" and last["actor_kind"] == "person":
            continue
        if out and out[-1]["figure_id"] == r["id"]:
            continue   # one entry per figure, from its first differing line
        out.append({"figure_id": r["id"], "printed_label": r["printed_label"], "field_label": concept.plain_label,
                    **{k: v for k, v in fields.where(r["concept_uuid"], r["period"], r["entity_scope"],
                                                     r["id"]).items() if k != "figure_id"}})
    return out


_NO_FIGURE = {"statement": None, "concept_uuid": None, "period": None, "entity_scope": None, "figure_id": None}


def _note_item(kind: str, title: str, message: str, **where) -> dict:
    return {"kind": kind, "title": title, "message": message, **_NO_FIGURE, **where}


def notes_items(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    """What the notes need from a person, in order: fields too long for mTool, notes to check, notes in no
    field, open source gaps, and required fields no note fills that nobody left empty."""
    notes = conn.execute("SELECT * FROM notes WHERE run_id = ? ORDER BY node_uuid IS NULL, template_id, node_uuid, "
                         "position, id", (run_id,)).fetchall()
    if not notes and conn.execute("SELECT 1 FROM note_reports WHERE run_id = ? LIMIT 1", (run_id,)).fetchone() is None:
        return []
    long, check, loose = [], [], []
    seen: set[str] = set()
    house = field_text.house(conn)
    for n in notes:
        title = note_parts.note_title(n)
        uuid = n["node_uuid"]
        if uuid is None:
            loose.append(_note_item("unplaced_note", title, "This note is in no field, so mTool will not get it.",
                                    note_id=n["id"]))
            continue
        if uuid not in seen:
            seen.add(uuid)
            text = field_text.prepared(conn, run_id, uuid, house)
            if text is not None and text.too_long:
                long.append(_note_item(
                    "note_too_long", note_rows.field_label(conn, uuid) or title,
                    f"{text.chars:,} of {text.limit:,} characters with all styling dropped. Nothing was cut; "
                    "split the field's notes or move one.", note_id=n["id"], node_uuid=uuid))
        if n["format_state"] != "fine" or n["certainty"] == "unsure":
            why = n["format_reason"] if n["format_state"] == "check_formatting" else (
                "A look on this note could not be told from the page." if n["format_state"] == "not_sure" else "")
            why = " ".join(x for x in (why, n["certainty_reason"] if n["certainty"] == "unsure" else "") if x)
            check.append(_note_item("note_to_check", title, why or "The notes agent was not sure of this note.",
                                    note_id=n["id"]))
    gaps, missing = [], []
    for r in store_reports.public_reports(conn, run_id):
        if r["status"] != "open":
            continue
        if r["kind"] == "source_gap":
            note = next((n for n in notes if n["id"] == r["note_id"]), None)
            gaps.append(_note_item("note_gap", note_parts.note_title(note) if note else
                                   (f"Note {r['note_number']}" if r["note_number"] else "The notes"),
                                   r["reason"], note_id=r["note_id"], report_id=r["id"]))
        elif r["kind"] == "missing_mandatory_field" and not any(n["node_uuid"] == r["node_uuid"] for n in notes):
            missing.append(_note_item("missing_field", r["field_label"] or "A required field", r["reason"],
                                      report_id=r["id"]))
    return long + check + loose + gaps + missing


def needs_you(conn: sqlite3.Connection, run_id: int) -> dict:
    fields = _Fields(conn, run_id)
    items: list[dict] = []
    for c in read_checks(conn, run_id):
        if c["status"] != "failed":
            continue
        uuid = c["target_concept_uuid"]
        items.append({"kind": "failed_check", "title": c["title"], "message": c["message"], "check": c["name"],
                      **fields.where(uuid, c["period"], c["entity_scope"],
                                     _figure_id(conn, run_id, uuid, c["period"], c["entity_scope"]))})
    for r in conn.execute("SELECT * FROM figures WHERE run_id = ? AND certainty = 'unsure' ORDER BY id", (run_id,)):
        items.append({"kind": "unsure", "title": fields.title(r["concept_uuid"], r["period"]), "message": r["reason"],
                      **fields.where(r["concept_uuid"], r["period"], r["entity_scope"], r["id"])})
    for c in comments.list_comments(conn, run_id, ["open"]):
        if c["author_kind"] != "agent":
            continue
        t = c["target"]
        if t["statement"] == PROSE_STATEMENT:   # the notes agent's comment on the notes as a whole
            items.append({"kind": "agent_comment", "title": "The notes", "message": c["text"],
                          "comment_id": c["id"], **_NO_FIGURE, "statement": PROSE_STATEMENT, "target_kind": "notes"})
            continue
        items.append({"kind": "agent_comment", "title": fields.title(t["concept_uuid"], t["period"]),
                      "message": c["text"], "comment_id": c["id"],
                      **fields.where(t["concept_uuid"], t["period"], t["entity_scope"], t["figure_id"]),
                      **({"statement": t["statement"]} if t["statement"] else {})})
    items += notes_items(conn, run_id)
    alike = alike_lines(conn, run_id, fields)
    if alike:
        example = alike[0]
        # A printed line filed in a field counts once, however many years it holds a figure for.
        count = len({(a["concept_uuid"], a["entity_scope"], _plain(a["printed_label"])) for a in alike})
        items.append({"kind": "alike", "title": f"{count} line{'s' if count != 1 else ''} filed under a "
                                                f"different name",
                      "message": f"For example “{example['printed_label']}” filed as {example['field_label']}.",
                      "count": count, "lines": alike})
    named = {i["figure_id"] for i in items if i.get("figure_id")} | {line["figure_id"] for line in alike}
    filled = [r[0] for r in conn.execute("SELECT id FROM figures WHERE run_id = ? AND value IS NOT NULL "
                                         "AND status != 'not_disclosed'", (run_id,))]
    return {"items": items, "passed": sum(1 for f in filled if f not in named)}


def accept_alike(conn: sqlite3.Connection, run_id: int, email: str) -> dict:
    """Confirm every alike line at once: a "confirm" history row each, so they leave the list."""
    actor = store.Actor("person", email)
    for line in alike_lines(conn, run_id, _Fields(conn, run_id)):
        store.confirm_figure(conn, run_id, line["figure_id"], actor, settle=False)
    return needs_you(conn, run_id)
