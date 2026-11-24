"""A run's notes: list, open, change look, change field, confirm, undo, redo
(`docs/api-contract.md`, Step 6b); the note fields, the notes agent's
reports and a field's prepared text (Step 6e); the review text, which is
that prepared text with marks to select by.

A person's changes go through the same note store functions agents use.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import db
from app.auth.deps import current_user
from app.auth.store import User
from app.catalog.note_fields import run_note_fields
from app.notes import field_text, render, store, store_reports
from app.notes.blocks import parse
from app.runs import store as runs

router = APIRouter(prefix="/api/runs/{run_id}/notes")


class LookBody(BaseModel):
    blocks: list[Any]
    format_state: Optional[str] = None
    reason: str = ""


class FieldBody(BaseModel):
    node_uuid: Optional[str]
    position: Optional[int] = None


class UndoBody(BaseModel):
    history_id: Optional[int] = None


class RedoBody(BaseModel):
    reason: str = ""


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def _person(user: User) -> store.Actor:
    return store.Actor("person", user.email)


def _read(run_id: int, user: User, work):
    with db.connect() as conn:
        try:
            runs.open_run(conn, run_id, user)
            return work(conn)
        except runs.RunNotFound as exc:
            return _error(404, str(exc))
        except store.NoteNotFound as exc:
            return _error(404, str(exc))
        except store.NotPlaced as exc:
            return _error(409, str(exc))
        except store.Refused as exc:
            return _error(422, str(exc))


def _change(run_id: int, user: User, work):
    """Open the run, make one change in one write transaction, or say why not."""
    try:
        with db.connect(immediate=True) as conn:
            runs.open_run(conn, run_id, user)
            result = work(conn)
            runs.touch(conn, run_id)
            return result
    except runs.RunNotFound as exc:
        return _error(404, str(exc))
    except store.NoteNotFound as exc:
        return _error(404, str(exc))
    except store.Refused as exc:
        return _error(422, str(exc))
    except store_reports.ReportRefused as exc:
        return _error(exc.status, str(exc))


def _shown(conn, run_id: int, note: dict) -> dict:
    """A changed note as a person reads it: with its field's fit and a numeric note's figures."""
    return {"note": store.get_note(conn, run_id, note["id"], fit=True)}


def _field(f) -> dict:
    return {"field_id": f.field_id, "template": f.template, "template_name": f.template_name,
            "template_id": f.template_id, "label": f.label, "path": list(f.path), "heading": f.heading,
            "mandatory": f.mandatory, "catch_all": f.catch_all}


@router.get("")
def list_notes(run_id: int, user: User = Depends(current_user)):
    return _read(run_id, user, lambda conn: {"notes": store.run_notes(conn, run_id, fit=True)})


@router.get("/fields")
def note_fields(run_id: int, user: User = Depends(current_user)):
    return _read(run_id, user, lambda conn: {"fields": [_field(f) for f in run_note_fields(conn, run_id)]})


@router.get("/reports")
def note_reports(run_id: int, user: User = Depends(current_user)):
    return _read(run_id, user, lambda conn: {"reports": store_reports.public_reports(conn, run_id)})


@router.post("/reports/{report_id}/leave-empty")
def leave_empty(run_id: int, report_id: int, user: User = Depends(current_user)):
    return _change(run_id, user, lambda conn: {"report": store_reports.leave_empty(conn, run_id, report_id,
                                                                                   user.email)})


@router.post("/reports/{report_id}/reopen")
def reopen_report(run_id: int, report_id: int, user: User = Depends(current_user)):
    return _change(run_id, user, lambda conn: {"report": store_reports.reopen(conn, run_id, report_id)})


@router.get("/{note_id}")
def get_note(run_id: int, note_id: int, user: User = Depends(current_user)):
    return _read(run_id, user, lambda conn: {"note": store.get_note(conn, run_id, note_id, fit=True)})


@router.get("/{note_id}/prepared")
def prepared_note(run_id: int, note_id: int, user: User = Depends(current_user)):
    return _read(run_id, user, lambda conn: {"prepared": store.prepared_text(conn, run_id, note_id)})


def _review(conn, run_id: int, note_id: int) -> dict:
    """`NoteReview`: the text the review page draws. A placed note's is its
    field's prepared text, as Copy and mTool get it; a note not placed is
    drawn alone through the same renderer. Either way with its marks."""
    note = store.get_note(conn, run_id, note_id)
    uuid = note["field"]["node_uuid"] if note["field"] else None
    found = field_text.field_rows(conn, run_id, uuid) if uuid else [
        conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()]
    bodies = [parse(json.loads(r["blocks_json"])) for r in found]
    house = field_text.house(conn)
    text = field_text.prepared(conn, run_id, uuid, house) if uuid else render.prepare(bodies, house)
    return {"note_id": note_id, "node_uuid": uuid, "revision": text.revision, "tier": text.tier,
            "html": render.review_html(bodies, [r["id"] for r in found], text, house),
            "double_underline": house["double_underline"]}


@router.get("/{note_id}/review")
def review_note(run_id: int, note_id: int, user: User = Depends(current_user)):
    return _read(run_id, user, lambda conn: {"review": _review(conn, run_id, note_id)})


@router.get("/{note_id}/history")
def note_history(run_id: int, note_id: int, user: User = Depends(current_user)):
    return _read(run_id, user, lambda conn: {"history": store.note_history(conn, run_id, note_id)})


@router.post("/{note_id}/look")
def change_look(run_id: int, note_id: int, body: LookBody, user: User = Depends(current_user)):
    def work(conn):
        note = store.set_look(conn, run_id, note_id, body.blocks, _person(user), format_state=body.format_state,
                              reason=body.reason)
        return {**_shown(conn, run_id, note), "history_id": note["history_id"]}   # what Undo of this change takes
    return _change(run_id, user, work)


@router.post("/{note_id}/field")
def change_field(run_id: int, note_id: int, body: FieldBody, user: User = Depends(current_user)):
    def work(conn):
        if body.node_uuid is None:
            note = store.clear_note(conn, run_id, note_id, _person(user))
        else:
            note = store.move_note(conn, run_id, note_id, body.node_uuid, _person(user), position=body.position)
        return {**_shown(conn, run_id, note), "history_id": note.get("history_id")}   # what Undo of this move takes
    return _change(run_id, user, work)


@router.post("/{note_id}/field/confirm")
def confirm_field(run_id: int, note_id: int, user: User = Depends(current_user)):
    def work(conn):
        note = store.confirm_placement(conn, run_id, note_id, _person(user))
        return {**_shown(conn, run_id, note), "history_id": note["history_id"]}
    return _change(run_id, user, work)


@router.post("/{note_id}/confirm")
def confirm_note(run_id: int, note_id: int, user: User = Depends(current_user)):
    return _change(run_id, user, lambda conn: _shown(conn, run_id, store.confirm_note(conn, run_id, note_id,
                                                                                     _person(user))))


@router.post("/{note_id}/undo")
def undo_note(run_id: int, note_id: int, body: Optional[UndoBody] = None, user: User = Depends(current_user)):
    def work(conn):
        history_id = body.history_id if body is not None and body.history_id is not None else (
            store.latest_change(conn, run_id, note_id))
        entry = conn.execute("SELECT note_id FROM note_history WHERE id = ?", (history_id,)).fetchone()
        if entry is None or entry["note_id"] != note_id:
            raise store.NoteNotFound("There is no such change in this note's history.")
        return _shown(conn, run_id, store.undo_change(conn, run_id, history_id, _person(user)))
    return _change(run_id, user, work)


@router.post("/{note_id}/redo")
def redo_note(run_id: int, note_id: int, body: Optional[RedoBody] = None, user: User = Depends(current_user)):
    return _change(run_id, user, lambda conn: _shown(conn, run_id, store.redo_from_source(
        conn, run_id, note_id, _person(user), body.reason if body is not None else "")))
