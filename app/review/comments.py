"""Comments on a run: a person's, and an agent's (`leave_comment`).

A person's comment: open -> sent (in a round) -> answered -> accepted or
undone. A reply puts it back to open for the next round, keeping the earlier
answer and the reply in its thread. An agent's comment is open until a
person marks it done. Every refusal is `CommentRefused` with one plain
sentence and the HTTP status the routes answer with.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable, Optional

from app.catalog import lookup
from app.catalog.statements import StatementType
from app.db import now
from app.notes import note_figures, store_reports
from app.notes.state import PROSE_STATEMENT
from app.review import note_parts

TARGET_KINDS = ("figure", "line", "statement", "note")
SCOPES = ("figure", "run", "company")
STATUSES = ("open", "sent", "answered", "accepted", "undone", "done")
OUTCOMES = ("changed", "not_changed", "question")
MAX_TEXT = 2000
NOT_COMMENTABLE = "That figure is in no statement or numeric note of this run."


class CommentRefused(ValueError):
    def __init__(self, sentence: str, status: int = 422) -> None:
        super().__init__(sentence)
        self.status = status


def _text(value: Any) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        raise CommentRefused("Write what the comment should say.")
    if len(text) > MAX_TEXT:
        raise CommentRefused("Keep a comment to 2,000 characters or fewer.")
    return text


def _family(conn: sqlite3.Connection, run_id: int) -> lookup.RunFamily:
    family = lookup.run_family(conn, run_id)
    if family is None:
        raise CommentRefused("There is no such run.", 404)
    return family


def _statement(family: lookup.RunFamily, statement: Any) -> str:
    try:
        kind = StatementType(str(statement))
    except ValueError:
        kind = None
    if kind is None or kind not in family.template_ids:
        raise CommentRefused("That statement is not part of this run.")
    return kind.value


def _notes_target(conn: sqlite3.Connection, run_id: int, target: dict) -> dict:
    """A comment on the notes as a whole, or, with `report_id`, on one of the notes agent's reports (such as a
    required field no note fills)."""
    setup = conn.execute("SELECT notes_included FROM run_setup WHERE run_id = ?", (run_id,)).fetchone()
    if setup is None or not setup["notes_included"]:
        raise CommentRefused("This run leaves the notes out, so there are no notes to comment on.")
    report_id = target.get("report_id")
    if report_id is not None:
        found = conn.execute("SELECT 1 FROM note_reports WHERE run_id = ? AND id = ?",
                             (run_id, report_id if type(report_id) is int else -1)).fetchone()
        if found is None:
            raise CommentRefused("There is no such report in this run.", 404)
    return {"kind": "statement", "statement": PROSE_STATEMENT, "concept_uuid": None, "period": None,
            "entity_scope": None, "dimension_key": "", "note_id": None, "note_part": None, "report_id": report_id}


def _report_name(conn: sqlite3.Connection, run_id: int, report_id: int) -> str:
    """A report as a person finds it: its field's label, else its note, never an id."""
    found = next((r for r in store_reports.public_reports(conn, run_id) if r["id"] == report_id), None)
    if found is None:
        return "The notes"
    return found["field_label"] or (f"Note {found['note_number']}" if found["note_number"] else "The notes")


def resolve_target(conn: sqlite3.Connection, run_id: int, target: Any) -> dict:
    """A target as stored: kind, statement and, as needed, the figure's key.
    Raises CommentRefused."""
    if not isinstance(target, dict):
        raise CommentRefused("A comment points at a figure, a line or a statement.")
    kind = target.get("kind")
    if kind == "note":
        return note_parts.resolve(conn, run_id, target)
    if kind not in TARGET_KINDS:
        raise CommentRefused("A comment points at a figure, a line or a statement.")
    family = _family(conn, run_id)
    if kind == "figure" and target.get("figure_id") is not None:
        row = conn.execute("SELECT * FROM figures WHERE run_id = ? AND id = ?",
                           (run_id, target.get("figure_id"))).fetchone()
        if row is None:
            raise CommentRefused("There is no such figure in this run.", 404)
        concept = lookup.concept(conn, row["concept_uuid"])
        statement = family.statement_of(concept.template_id) if concept else None
        # A share capital or related-party figure is filed under its numeric note.
        code = statement.value if statement else note_figures.numeric_code(family, concept.template_id if concept
                                                                           else None)
        if code is None:
            raise CommentRefused(NOT_COMMENTABLE)
        return {"kind": "figure", "statement": code, "concept_uuid": row["concept_uuid"],
                "period": row["period"], "entity_scope": row["entity_scope"], "dimension_key": row["dimension_key"],
                "note_id": None, "note_part": None}
    if kind == "statement" and target.get("statement") == PROSE_STATEMENT:
        return _notes_target(conn, run_id, target)
    statement = _statement(family, target.get("statement"))
    out: dict = {"kind": kind, "statement": statement, "concept_uuid": None, "period": None,
                 "entity_scope": None, "dimension_key": "", "note_id": None, "note_part": None}
    if kind == "statement":
        return out
    concept = lookup.concept(conn, str(target.get("concept_uuid") or ""))
    if concept is None or concept.template_id != family.template_ids[StatementType(statement)]:
        raise CommentRefused("That field is not in this statement's template.")
    entity = target.get("entity_scope") or "Company"
    if entity not in family.entity_scopes:
        raise CommentRefused("This run saves figures for Group and Company." if family.level == "group"
                             else "This run saves figures for the Company only.")
    out.update(concept_uuid=concept.concept_uuid, entity_scope=entity,
               dimension_key=str(target.get("dimension_key") or ""))
    if kind == "figure":
        period = target.get("period")
        if period not in ("CY", "PY"):
            raise CommentRefused("The period is CY (this year) or PY (last year).")
        if period not in family.periods:
            raise CommentRefused("This run has no prior year.")
        out["period"] = period
    return out


def _insert(conn: sqlite3.Connection, run_id: int, author_kind: str, author_name: str, target: dict, text: str,
            scope: str, round_id: Optional[int] = None) -> int:
    stamp = now()
    return int(conn.execute(
        "INSERT INTO comments(run_id, author_kind, author_name, target_kind, statement, concept_uuid, period, "
        "entity_scope, dimension_key, note_id, note_part_json, report_id, text, scope, status, round_id, created_at, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)",
        (run_id, author_kind, author_name, target["kind"], target["statement"], target["concept_uuid"],
         target["period"], target["entity_scope"], target["dimension_key"] or "", target.get("note_id"),
         json.dumps(target["note_part"]) if target.get("note_part") else None, target.get("report_id"), text, scope,
         round_id, stamp, stamp)).lastrowid)


def add_person_comment(conn: sqlite3.Connection, run: sqlite3.Row, body: Any, email: str) -> dict:
    if run["status"] not in ("in_review", "correcting"):
        raise CommentRefused("Comments can be added once extraction has finished.", 409)
    body = body if isinstance(body, dict) else {}
    target = resolve_target(conn, run["id"], body.get("target"))
    text = _text(body.get("text"))
    scope = body.get("scope") or "figure"
    if scope not in SCOPES:
        raise CommentRefused("A comment applies to the figure, the run or the company.")
    if scope != "figure" and target["kind"] not in ("figure", "line"):
        raise CommentRefused("Only a comment on a figure or a line can apply to the run or the company.")
    return get(conn, run["id"], _insert(conn, run["id"], "person", email, target, text, scope))


def add_agent_comment(conn: sqlite3.Connection, run_id: int, agent: str, target: dict, text: str,
                      round_id: Optional[int] = None) -> int:
    """An agent's comment for a person to look at. `target` is already resolved."""
    return _insert(conn, run_id, "agent", agent, target, _text(text), "figure", round_id)


# Reads ------------------------------------------------------------------------

def _figure_id(conn: sqlite3.Connection, row: sqlite3.Row) -> Optional[int]:
    if row["target_kind"] != "figure":
        return None
    found = conn.execute("SELECT id FROM figures WHERE run_id = ? AND concept_uuid = ? AND period = ? "
                         "AND entity_scope = ? AND dimension_key = ?",
                         (row["run_id"], row["concept_uuid"], row["period"], row["entity_scope"],
                          row["dimension_key"])).fetchone()
    return int(found[0]) if found else None


def public(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """`Comment` (docs/api-contract.md, Step 5a)."""
    concept = lookup.concept(conn, row["concept_uuid"]) if row["concept_uuid"] else None
    target = {"kind": row["target_kind"], "statement": row["statement"], "concept_uuid": row["concept_uuid"],
              "period": row["period"], "entity_scope": row["entity_scope"], "dimension_key": row["dimension_key"],
              "field_label": concept.plain_label if concept else None, "figure_id": _figure_id(conn, row),
              "report_id": row["report_id"]}
    if row["target_kind"] == "statement" and row["statement"] == PROSE_STATEMENT:   # the notes, or one report
        target["field_label"] = (_report_name(conn, row["run_id"], row["report_id"]) if row["report_id"]
                                 else "The notes")
    if concept is not None and row["target_kind"] in ("figure", "line"):
        family = lookup.run_family(conn, row["run_id"])
        if note_figures.numeric_code(family, concept.template_id):   # opens on the note that shows its figures
            target["note_id"] = note_figures.holding_note(conn, row["run_id"], concept.template_id)
    if row["target_kind"] == "note":
        part = json.loads(row["note_part_json"]) if row["note_part_json"] else None
        target.update(note_id=row["note_id"], note_part=part,
                      field_label=note_parts.name(conn, row["run_id"], row["note_id"], part))
    return {"id": row["id"], "run_id": row["run_id"], "author_kind": row["author_kind"],
            "author_name": row["author_name"], "target": target, "text": row["text"], "scope": row["scope"],
            "status": row["status"], "outcome": row["outcome"], "answer": row["answer"],
            "proposed_guidance": row["proposed_guidance"], "guidance_status": row["guidance_status"],
            "guidance_version": row["guidance_version"], "round_id": row["round_id"],
            "thread": json.loads(row["thread_json"] or "[]"), "created_at": row["created_at"],
            "updated_at": row["updated_at"]}


def row(conn: sqlite3.Connection, run_id: int, comment_id: int) -> sqlite3.Row:
    found = conn.execute("SELECT * FROM comments WHERE run_id = ? AND id = ?", (run_id, comment_id)).fetchone()
    if found is None:
        raise CommentRefused("There is no such comment in this run.", 404)
    return found


def get(conn: sqlite3.Connection, run_id: int, comment_id: int) -> dict:
    return public(conn, row(conn, run_id, comment_id))


def list_comments(conn: sqlite3.Connection, run_id: int, statuses: Iterable[str] = ()) -> list[dict]:
    wanted = [s for s in statuses if s in STATUSES]
    sql, params = "SELECT * FROM comments WHERE run_id = ?", [run_id]
    if wanted:
        sql += f" AND status IN ({','.join('?' * len(wanted))})"
        params += wanted
    return [public(conn, r) for r in conn.execute(sql + " ORDER BY id", params)]


# Changes a person makes -------------------------------------------------------

def _set(conn: sqlite3.Connection, comment_id: int, **fields: Any) -> None:
    fields["updated_at"] = now()
    conn.execute(f"UPDATE comments SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                 [*fields.values(), comment_id])


def remove(conn: sqlite3.Connection, run_id: int, comment_id: int) -> None:
    found = row(conn, run_id, comment_id)
    if found["author_kind"] == "agent":
        raise CommentRefused("An agent's comment is marked done, not removed.", 409)
    if found["status"] != "open":
        raise CommentRefused("Only an open comment can be removed.", 409)
    conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))


def reply(conn: sqlite3.Connection, run_id: int, comment_id: int, text: Any, email: str) -> dict:
    found = row(conn, run_id, comment_id)
    if found["author_kind"] == "agent":
        raise CommentRefused("Reply to an agent's comment by adding a comment of your own.", 409)
    if found["status"] == "sent":
        raise CommentRefused("This comment is being worked on, so reply when the round ends.", 409)
    if found["status"] not in ("answered", "accepted", "undone"):
        raise CommentRefused("Only an answered comment can be replied to.", 409)
    text = _text(text)
    thread = json.loads(found["thread_json"] or "[]")
    if found["outcome"]:
        thread.append({"kind": "answer", "round_id": found["round_id"], "outcome": found["outcome"],
                       "answer": found["answer"], "at": found["updated_at"]})
    thread.append({"kind": "reply", "author_name": email, "text": text, "at": now()})
    _set(conn, comment_id, status="open", outcome=None, answer=None, proposed_guidance=None, guidance_status=None,
         guidance_version=None, thread_json=json.dumps(thread, ensure_ascii=False), closed_by=None)
    return get(conn, run_id, comment_id)


def accept(conn: sqlite3.Connection, run_id: int, comment_id: int, email: str) -> dict:
    if row(conn, run_id, comment_id)["status"] != "answered":
        raise CommentRefused("Only an answered comment can be accepted.", 409)
    _set(conn, comment_id, status="accepted", closed_by=email)
    return get(conn, run_id, comment_id)


def acceptable(conn: sqlite3.Connection, run_id: int) -> dict:
    """What Accept all would accept now: the answered comments of the latest round, except questions, which
    wait for a reply. `{"round_id", "comment_ids"}`, the round id null before any round."""
    latest = conn.execute("SELECT MAX(id) FROM rounds WHERE run_id = ?", (run_id,)).fetchone()[0]
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM comments WHERE run_id = ? AND round_id = ? AND status = 'answered' "
        "AND outcome IN ('changed', 'not_changed') ORDER BY id", (run_id, latest))] if latest else []
    return {"round_id": latest, "comment_ids": ids}


def accept_all(conn: sqlite3.Connection, run_id: int, email: str) -> list[dict]:
    """The answered comments of the latest round, except questions, which wait for a reply."""
    ids = acceptable(conn, run_id)["comment_ids"]
    for comment_id in ids:
        _set(conn, comment_id, status="accepted", closed_by=email)
    return [get(conn, run_id, c) for c in ids]


def mark_done(conn: sqlite3.Connection, run_id: int, comment_id: int, email: str) -> dict:
    found = row(conn, run_id, comment_id)
    if found["author_kind"] != "agent":
        raise CommentRefused("Only an agent's comment is marked done.", 409)
    _set(conn, comment_id, status="done", closed_by=email)
    return get(conn, run_id, comment_id)


def mark_undone(conn: sqlite3.Connection, comment_ids: Iterable[int], email: str) -> None:
    for comment_id in comment_ids:
        _set(conn, comment_id, status="undone", closed_by=email)


def record_answer(conn: sqlite3.Connection, round_id: int, comment_id: int, outcome: str, answer: str,
                  proposed_guidance: Optional[str]) -> None:
    """The Reviewer's answer: on the comment, and kept for the round."""
    stamp = now()
    _set(conn, comment_id, status="answered", outcome=outcome, answer=answer, proposed_guidance=proposed_guidance)
    conn.execute("UPDATE round_comments SET outcome = ?, answer = ?, answered_at = ? "
                 "WHERE round_id = ? AND comment_id = ?", (outcome, answer, stamp, round_id, comment_id))
