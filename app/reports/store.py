"""The report store: every write of a run's report fields goes through here.

The reports agent and people call the same functions. Every write adds a
`report_field_history` row (before, after, who) and an activity event. A
refused write raises `Refused` with one plain sentence; nothing is saved.

Checks, from v1 `reports/repository.py` `save_field`: the field is one of
the report's; a choice is one of its list; a date is a real date written
YYYY-MM-DD; text is at most 4,096 characters; an edit made against an older
revision is refused. A value the agent saves names the page it was read
from, and the agent never changes what a person set. A field left empty
says why, and the empty value is no value, never the word "none".

The narrative is not typed by anyone: its words are copied by code from the
run's page content, as a note's are (`app/notes/copy.py`), and drawn by the
note renderer (`narrative_text`). Identity numbers are kept exactly as
written; how one goes into mTool is the fill's question (step 10g).
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional, Sequence

from pydantic import ValidationError

from app.catalog.reports import REPORTS, ReportField, find_field, report_fields, report_name
from app.db import now
from app.figures.store import Actor, Refused
from app.notes import copy as copier
from app.notes import render
from app.notes.blocks import NoteBody, parse
from app.runs import events

__all__ = ["Actor", "Refused", "FieldNotFound", "StaleEdit", "FieldWrite", "save_field", "clear_field",
           "run_reports", "get_field", "field_history", "narrative_text", "fill_values"]

SOURCE = "reports"
STATUSES = ("filled", "not_shown", "unsure", "cleared")
EMPTY = ("not_shown", "unsure", "cleared")
MAX_TEXT = 4096
_NONE_WORDS = {"none", "nil", "null", "n/a", "na", "-", "—", "not applicable", "not disclosed", "not shown"}
_STATE = ("status", "value", "blocks", "reason", "pages", "revision", "actor_kind", "updated_by")


class FieldNotFound(Refused):
    """A run, report or field that does not exist."""


class StaleEdit(Refused):
    """An edit made against an older revision of the field."""


@dataclass
class FieldWrite:
    status: str                                    # filled, not_shown, unsure or cleared
    value: Optional[str] = None                    # filled text, date or choice fields
    sources: Sequence[tuple[int, int]] = ()        # filled narrative: (PDF page, block index) in reading order
    pages: Sequence[int] = ()                      # the PDF pages it was read from
    reason: str = ""


# Checks --------------------------------------------------------------------

def _standard(conn: sqlite3.Connection, run_id: int) -> str:
    run = conn.execute("SELECT standard FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        raise FieldNotFound("There is no such run.")
    if not run["standard"]:
        raise Refused("The run's setup is not confirmed, so it has no reports yet.")
    return run["standard"].lower()


def _field(conn: sqlite3.Connection, run_id: int, report: str, wanted: str) -> ReportField:
    if report not in REPORTS:
        raise FieldNotFound("There is no such report; the reports are DIRECTORS_REPORT, STATEMENT_BY_DIRECTORS "
                            "and AUDITORS_REPORT.")
    found = find_field(report, _standard(conn, run_id), wanted)
    if found is None:
        raise FieldNotFound(f"The {report_name(report).lower()} has no field {wanted}.")
    return found


def _page_count(conn: sqlite3.Connection, run_id: int) -> Optional[int]:
    row = conn.execute("SELECT page_count FROM documents WHERE run_id = ?", (run_id,)).fetchone()
    return int(row["page_count"]) if row is not None else None


def _pages(conn: sqlite3.Connection, run_id: int, pages: Sequence[Any]) -> list[int]:
    count = _page_count(conn, run_id)
    for p in pages:
        if type(p) is not int or p < 1 or (count is not None and p > count):
            raise Refused(f"Page {p} is not a page of this document; give PDF page numbers.")
    return sorted(set(pages))


def _one_line(text: Any) -> str:
    return " ".join(str(text or "").split())


MAX_REASON = 500


def _reason(text: Any) -> str:
    """A reason on one line, cut at 500 characters like every other reason the app keeps."""
    return _one_line(text)[:MAX_REASON]


def _scalar(f: ReportField, value: Optional[str], actor: Actor) -> str:
    text = (value or "").strip()
    if not text:
        raise Refused(f"Give a value for {f.label}, or leave it empty with a reason.")
    if actor.kind == "agent" and _one_line(text).lower() in _NONE_WORDS:
        raise Refused(f"{f.label}: leave the field empty with a reason instead of writing {text!r}.")
    if f.kind == "choice":
        match = next((c for c in f.choices if c.lower() == _one_line(text).lower()), None)
        if match is None:
            raise Refused(f"{f.label} takes one of: " + "; ".join(f.choices) + ".")
        return match
    if f.kind == "date":
        try:
            ok = date.fromisoformat(text).isoformat() == text
        except ValueError:
            ok = False
        if not ok:
            raise Refused(f"{f.label} is a date, so write it as YYYY-MM-DD, for example 2025-04-30.")
        return text
    if len(text) > MAX_TEXT:
        raise Refused(f"{f.label} is longer than {MAX_TEXT:,} characters, so shorten it to what is printed.")
    return text


def _narrative(conn: sqlite3.Connection, run_id: int, f: ReportField, sources: Sequence[tuple[int, int]]) -> NoteBody:
    if not sources:
        raise Refused(f"Give the blocks of the {f.label.lower()}, as block ids from the pages.")
    try:
        return NoteBody(blocks=copier.copy_blocks(conn, run_id, list(sources)))
    except copier.NotFromRun as exc:
        raise Refused(str(exc)) from exc
    except (ValidationError, ValueError) as exc:
        raise Refused("The blocks could not be copied as given, so give each block once, in reading order.") from exc


# Rows ----------------------------------------------------------------------

def _row(conn: sqlite3.Connection, run_id: int, report: str, element_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM report_fields WHERE run_id = ? AND report = ? AND element_id = ?",
                        (run_id, report, element_id)).fetchone()


def _state(row: Optional[sqlite3.Row]) -> Optional[dict]:
    if row is None:
        return None
    return {"status": row["status"], "value": row["value"],
            "blocks": json.loads(row["blocks_json"]) if row["blocks_json"] else None, "reason": row["reason"],
            "pages": json.loads(row["pages_json"]), "revision": row["revision"], "actor_kind": row["actor_kind"],
            "updated_by": row["updated_by"]}


def _write(conn: sqlite3.Connection, run_id: int, f: ReportField, new: dict, actor: Actor, action: str,
           expected_revision: Optional[int]) -> dict:
    old = _row(conn, run_id, f.report, f.element_id)
    revision = old["revision"] if old is not None else 0
    if expected_revision is not None and int(expected_revision) != revision:
        raise StaleEdit(f"{f.label} changed since you opened it, so reload it before saving.")
    if actor.kind == "agent" and old is not None and old["actor_kind"] == "person":
        raise Refused(f"A person set {f.label}, so it stays as they set it.")
    stamp = now()
    params = (new["status"], new.get("value"), json.dumps(new["blocks"]) if new.get("blocks") else None,
              new["reason"], json.dumps(new["pages"]), revision + 1, actor.kind, actor.name, stamp)
    if old is None:
        field_row = int(conn.execute(
            "INSERT INTO report_fields(status, value, blocks_json, reason, pages_json, revision, actor_kind, "
            "updated_by, updated_at, run_id, report, element_id, kind, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*params, run_id, f.report, f.element_id, f.kind, stamp)).lastrowid)
    else:
        field_row = int(old["id"])
        conn.execute("UPDATE report_fields SET status = ?, value = ?, blocks_json = ?, reason = ?, pages_json = ?, "
                     "revision = ?, actor_kind = ?, updated_by = ?, updated_at = ? WHERE id = ?", (*params, field_row))
    after = _state(conn.execute("SELECT * FROM report_fields WHERE id = ?", (field_row,)).fetchone())
    history_id = int(conn.execute(
        "INSERT INTO report_field_history(run_id, field_id, action, actor_kind, actor_name, before_json, after_json, "
        "changed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, field_row, action, actor.kind, actor.name, json.dumps(_state(old)) if old is not None else None,
         json.dumps(after), stamp)).lastrowid)
    where = report_name(f.report).lower()
    if new["status"] == "filled":
        message = f"Saved {f.label} in the {where}."
    elif new["status"] == "cleared":
        message = f"Cleared {f.label} in the {where}."
    else:
        message = f"Left {f.label} in the {where} empty: {new['reason']}"
    events.insert(conn, SOURCE, action, message, run_id=run_id,
                  data={"report": f.report, "field_id": f.field_id, "element_id": f.element_id,
                        "status": new["status"], "history_id": history_id, "by": actor.kind},
                  pages=new["pages"])
    return {**get_field(conn, run_id, f.report, f.element_id), "history_id": history_id}


# Writes --------------------------------------------------------------------

def save_field(conn: sqlite3.Connection, run_id: int, report: str, field: str, write: FieldWrite, actor: Actor, *,
               expected_revision: Optional[int] = None) -> dict:
    """Save one field (by taxonomy element or short id). Returns the field as `get_field`, with `history_id`.
    Raises `Refused` (FieldNotFound, StaleEdit) with one plain sentence."""
    f = _field(conn, run_id, report, field)
    if write.status not in STATUSES:
        raise Refused("A field is filled, not_shown or unsure.")
    if write.status == "cleared":
        if actor.kind != "person":
            raise Refused("Only a person clears a field; leave it empty with a reason instead.")
        return clear_field(conn, run_id, report, field, actor, expected_revision=expected_revision,
                           reason=write.reason)
    pages = _pages(conn, run_id, list(write.pages))
    reason = _reason(write.reason)
    new: dict[str, Any] = {"status": write.status, "value": None, "blocks": None, "reason": reason, "pages": pages}
    if write.status == "filled":
        if f.kind == "html":
            body = _narrative(conn, run_id, f, write.sources)
            new["blocks"] = body.model_dump(mode="json")
            new["pages"] = sorted({b.source.page for b in body.blocks})
        else:
            new["value"] = _scalar(f, write.value, actor)
            if actor.kind == "agent" and not pages:
                raise Refused(f"{f.label}: give the PDF page the value was read from.")
    elif not reason:
        raise Refused(f"{f.label}: say in the reason why the field is left empty.")
    return _write(conn, run_id, f, new, actor, "save" if actor.kind == "agent" else "edit", expected_revision)


def clear_field(conn: sqlite3.Connection, run_id: int, report: str, field: str, actor: Actor, *,
                expected_revision: Optional[int] = None, reason: str = "") -> dict:
    """A person empties a field on purpose: the fill leaves its cell blank."""
    f = _field(conn, run_id, report, field)
    if actor.kind != "person":
        raise Refused("Only a person clears a field; leave it empty with a reason instead.")
    new = {"status": "cleared", "value": None, "blocks": None, "reason": _reason(reason), "pages": []}
    return _write(conn, run_id, f, new, actor, "clear", expected_revision)


# Reads ---------------------------------------------------------------------

def _house(conn: sqlite3.Connection) -> dict:
    from app.notes.field_text import house
    return house(conn)


def _shown(f: ReportField, row: Optional[sqlite3.Row], house: Optional[dict]) -> dict:
    """`ReportField` (docs/api-contract.md, Step 10)."""
    state = _state(row) or {}
    out = {"report": f.report, "field_id": f.field_id, "element_id": f.element_id, "label": f.label, "kind": f.kind,
           "choices": list(f.choices), "row": f.row, "status": state.get("status", "not_assessed"),
           "value": state.get("value"), "reason": state.get("reason", ""), "pages": state.get("pages", []),
           "revision": state.get("revision", 0), "updated_by": state.get("updated_by"),
           "actor_kind": state.get("actor_kind"), "updated_at": row["updated_at"] if row is not None else None}
    if f.kind == "html":
        text = render.prepare([parse(state["blocks"])], house) if state.get("blocks") else None
        out["html"] = text.html if text else None
        out["fit"] = {"tier": text.tier, "chars": text.chars, "limit": text.limit} if text else None
    return out


def get_field(conn: sqlite3.Connection, run_id: int, report: str, field: str) -> dict:
    f = _field(conn, run_id, report, field)
    row = _row(conn, run_id, report, f.element_id)
    return _shown(f, row, _house(conn) if f.kind == "html" else None)


def run_reports(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    """`Report` for each of the three reports, every field in template order, assessed or not."""
    standard = _standard(conn, run_id)
    stored = {(r["report"], r["element_id"]): r for r in conn.execute(
        "SELECT * FROM report_fields WHERE run_id = ?", (run_id,))}
    house = _house(conn)
    out = []
    for report, (name, _role, sheet, _code) in REPORTS.items():
        fields = [_shown(f, stored.get((report, f.element_id)), house) for f in report_fields(report, standard)]
        out.append({"report": report, "name": name, "sheet": sheet, "fields": fields,
                    "assessed": sum(1 for f in fields if f["status"] != "not_assessed"), "total": len(fields)})
    return out


def field_history(conn: sqlite3.Connection, run_id: int, report: str, field: str) -> list[dict]:
    f = _field(conn, run_id, report, field)
    row = _row(conn, run_id, report, f.element_id)
    if row is None:
        return []
    return [{"id": h["id"], "action": h["action"], "actor_kind": h["actor_kind"], "actor_name": h["actor_name"],
             "changed_at": h["changed_at"], "before": json.loads(h["before_json"]) if h["before_json"] else None,
             "after": json.loads(h["after_json"])}
            for h in conn.execute("SELECT * FROM report_field_history WHERE field_id = ? ORDER BY id", (row["id"],))]


def not_assessed(conn: sqlite3.Connection, run_id: int) -> list[ReportField]:
    """The fields of the three reports with no assessment yet."""
    standard = _standard(conn, run_id)
    done = {(r["report"], r["element_id"]) for r in conn.execute(
        "SELECT report, element_id FROM report_fields WHERE run_id = ?", (run_id,))}
    return [f for report in REPORTS for f in report_fields(report, standard) if (report, f.element_id) not in done]


# For the fill (step 10g) ------------------------------------------------------

def narrative_text(conn: sqlite3.Connection, run_id: int, report: str,
                   house: Optional[dict] = None) -> Optional[render.Prepared]:
    """The report's narrative as mTool gets it, through the note renderer, or None when it is not filled."""
    f = next(f for f in report_fields(report, _standard(conn, run_id)) if f.kind == "html")
    row = _row(conn, run_id, report, f.element_id)
    if row is None or row["status"] != "filled" or not row["blocks_json"]:
        return None
    return render.prepare([parse(json.loads(row["blocks_json"]))], house if house is not None else _house(conn))


def narrative_statuses(conn: sqlite3.Connection, run_id: int) -> dict[str, str]:
    """{report: its narrative's status} (filled, not_shown, unsure, cleared or not_assessed)."""
    return {report["report"]: next(f["status"] for f in report["fields"] if f["kind"] == "html")
            for report in run_reports(conn, run_id)}


def fill_values(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    """Every non-narrative field of the three reports with what the fill should do: `value` for a filled field,
    `None` with status `cleared` to blank the cell, and `not_shown`, `unsure` or `not_assessed` to leave it
    and list it. Each carries report, sheet, element_id, label, kind, row and pages."""
    out = []
    for report in run_reports(conn, run_id):
        for f in report["fields"]:
            if f["kind"] != "html":
                out.append({"report": report["report"], "sheet": report["sheet"], "element_id": f["element_id"],
                            "label": f["label"], "kind": f["kind"], "row": f["row"], "status": f["status"],
                            "value": f["value"], "pages": f["pages"]})
    return out
