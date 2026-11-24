"""Reading and answering a run's scope question (decision record 3, item 2).

An answer either confirms the setup (the confirmed value, or the person's
own words) and extraction carries on with the answer as a fact from the
person, keeping every saved figure; or it changes the setup, through the
same check as confirming it, clears the agent's figures of the statements
the change refiles (never a person's), and extraction starts again. Either
way the extract job is queued again, so the stage and the run always reach
a final state. Every answer is kept on the question and written as events.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Optional

from app.catalog.lookup import run_family
from app.catalog.note_fields import run_note_fields
from app.catalog.statements import NOT_PREPARED, StatementType, layout_label, printed_layouts
from app.db import now
from app.documents import store as documents
from app.figures import setup_change, store as figures
from app.runs import events, setup as run_setup, status as run_status
from app.scope import fields

logger = logging.getLogger(__name__)

MAX_ANSWER = 1000
MAX_PAGES = 10


class QuestionRefused(ValueError):
    def __init__(self, sentence: str, status: int = 422) -> None:
        super().__init__(sentence)
        self.status = status


def public(row: sqlite3.Row) -> dict:
    """`ScopeQuestion` (docs/api-contract.md, Step 5b)."""
    return {"id": row["id"], "run_id": row["run_id"], "stage": row["stage"], "asked_by": row["asked_by"],
            "field": row["field"], "statement": row["statement"], "question": row["question"],
            "evidence": json.loads(row["evidence_json"]), "choices": json.loads(row["choices_json"]),
            "setup_value": row["setup_value"], "status": row["status"], "asked_at": row["asked_at"],
            "answer": None if row["status"] == "open" else {
                "choice": row["answer_choice"], "text": row["answer_text"], "value": row["answer_value"],
                "setup_changed": bool(row["setup_changed"]), "cleared": row["cleared"],
                "by": row["answered_by"], "at": row["answered_at"]}}


def open_question(conn: sqlite3.Connection, run_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM scope_questions WHERE run_id = ? AND status = 'open'", (run_id,)).fetchone()


def questions(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    return [public(r) for r in conn.execute("SELECT * FROM scope_questions WHERE run_id = ? ORDER BY id", (run_id,))]


def _event(conn: sqlite3.Connection, run_id: int, kind: str, message: str, data: dict, row: sqlite3.Row) -> None:
    """An event of the question, linking its evidence pages."""
    events.insert(conn, "extraction", kind, message, run_id=run_id, data=data,
                  pages=[e["page"] for e in json.loads(row["evidence_json"])])


# The answer ---------------------------------------------------------------------

def _read_answer(row: sqlite3.Row, body: Any) -> tuple[Optional[int], Optional[str]]:
    body = body if isinstance(body, dict) else {}
    choice, text = body.get("choice"), body.get("text")
    text = " ".join(text.split()) if isinstance(text, str) else None
    if (choice is None) == (not text):
        raise QuestionRefused("Choose one of the choices or write your own answer, not both.")
    if choice is not None:
        if type(choice) is not int or not 0 <= choice < len(json.loads(row["choices_json"])):
            raise QuestionRefused("There is no such choice.")
        return choice, None
    if len(text) > MAX_ANSWER:
        raise QuestionRefused(f"Keep the answer to {MAX_ANSWER:,} characters or fewer.")
    return None, text


def _changed_body(conn: sqlite3.Connection, run_id: int, row: sqlite3.Row, value: str) -> dict:
    """The confirmed setup with the answer applied, ready for the setup check.
    Raises QuestionRefused when a statement's layout has no template under the
    new standard: the run's setup cannot be mended in place."""
    body = fields.current_setup(conn, run_id)
    field, statement = row["field"], row["statement"]
    if field in ("standard", "level", "unit", "year_end"):
        body[field] = value
    if field == "standard":
        for st in body["statements"]:
            ok = st["layout"] in (*printed_layouts(StatementType(st["statement"]), value.lower()), NOT_PREPARED)
            if ok:
                continue
            if st["included"]:
                raise QuestionRefused(
                    f"The {layout_label(StatementType(st['statement']), st['layout']).lower()} layout of the "
                    f"{fields.STATEMENT_WORDS[st['statement']]} does not exist for {value} filings, so start a "
                    "new run with the right setup.", 409)
            st["layout"] = printed_layouts(StatementType(st["statement"]), value.lower())[0]
    if field == "layout":
        st = next(s for s in body["statements"] if s["statement"] == statement)
        if value == fields.NOT_PRINTED:
            st["included"] = False
            if statement == "SOCI":
                st["layout"] = NOT_PREPARED
        else:
            st["layout"], st["included"] = value, True
            if not st["pages"]:
                st["pages"] = sorted({e["page"] for e in json.loads(row["evidence_json"])})[:MAX_PAGES]
    return body


def _apply_setup(conn: sqlite3.Connection, run_id: int, setup: run_setup.Confirmed) -> None:
    """Save the changed setup: the filing, the unit and year end, and the statements. Company and notes stay."""
    conn.execute("UPDATE runs SET year = ?, standard = ?, level = ? WHERE id = ?",
                 (int(setup.year_end[:4]), setup.standard, setup.level, run_id))
    conn.execute("UPDATE run_setup SET unit = ?, year_end = ? WHERE run_id = ?", (setup.unit, setup.year_end, run_id))
    conn.execute("DELETE FROM run_statements WHERE run_id = ?", (run_id,))
    conn.executemany("INSERT INTO run_statements(run_id, statement, variant, included, pages_json) "
                     "VALUES (?, ?, ?, ?, ?)",
                     [(run_id, s, layout, int(on), json.dumps(pages)) for s, layout, on, pages in setup.statements])


def _affected_templates(conn: sqlite3.Connection, run_id: int, row: sqlite3.Row) -> list[str]:
    """The templates whose agent figures the change refiles, read before the setup changes."""
    family = run_family(conn, run_id)
    if family is None:
        return []
    if row["field"] in fields.WHOLE_RUN:
        return [*family.template_ids.values(), *family.note_template_ids.values()]
    template = family.template_ids.get(StatementType(row["statement"]))
    return [template] if template else []


def _unplace_notes_off_the_filing(conn: sqlite3.Connection, run_id: int, email: str, reason: str) -> None:
    """A new standard or level brings other note templates. Each note placed in a field the filing no longer
    has is taken out of it, with a history row, so it shows as not placed instead of dropping out of the
    fill unseen. A notes agent that finished or failed starts again to place them; one still at work, or
    waiting for this answer, carries on with the new templates. One a person stopped stays stopped."""
    from app.notes import job as notes_job, store as notes

    kept = {f.field_id for f in run_note_fields(conn, run_id)}
    placed = conn.execute("SELECT id, node_uuid FROM notes WHERE run_id = ? AND node_uuid IS NOT NULL", (run_id,))
    off = [int(r["id"]) for r in placed if r["node_uuid"] not in kept]
    for note_id in off:
        notes.clear_note(conn, run_id, note_id, figures.Actor("person", email), reason)
    if off and notes_job.stage_status(conn, run_id) in ("done", "failed"):
        notes_job.start(conn, run_id)
    if off:
        logger.info("Run %s: %d note(s) taken out of fields the new filing does not have.", run_id, len(off))


def _change_setup(conn: sqlite3.Connection, run_id: int, row: sqlite3.Row, value: str, email: str) -> int:
    """Change the setup to the answer. Returns how many agent figures were cleared. Refused for a run with a
    starting workbook: its figures were imported for this setup, and the fill writes into that workbook."""
    if conn.execute("SELECT 1 FROM starting_workbooks WHERE run_id = ?", (run_id,)).fetchone():
        words = fields.field_words(row["field"], row["statement"])
        raise QuestionRefused(f"This run starts from a workbook made for its current setup, so {words} cannot "
                              "change here; start a new run with the right setup and a workbook that fits it.", 409)
    _, page_count = documents.pdf_path(conn, run_id)
    body = _changed_body(conn, run_id, row, value)
    try:
        confirmed = run_setup.check(body, page_count)
    except run_setup.SetupRefused as exc:
        raise QuestionRefused(f"This answer cannot be applied to the setup: {exc}", 409) from exc
    words = fields.field_words(row["field"], row["statement"])
    reason = f"Cleared when {email} changed {words} from {row['setup_value']} to {value}."
    cleared = setup_change.clear_agent_figures(conn, run_id, _affected_templates(conn, run_id, row), email, reason)
    _apply_setup(conn, run_id, confirmed)
    figures.recalculate(conn, run_id)   # the totals and checks of the new templates
    _unplace_notes_off_the_filing(conn, run_id, email, reason)
    shown = fields.label(row["field"], value, row["statement"])
    _event(conn, run_id, "setup_changed",
           f"Setup changed: {words} is now {shown}; {cleared} figure(s) the agent saved were cleared.",
           {"question_id": row["id"], "field": row["field"], "statement": row["statement"],
            "from": row["setup_value"], "to": value, "cleared": cleared, "by": email}, row)
    return cleared


def answer(conn: sqlite3.Connection, run: sqlite3.Row, body: Any, email: str) -> dict:
    """Answer the run's open question and queue extraction again. Use inside
    `db.connect(immediate=True)`. Raises QuestionRefused."""
    from app.extraction import job

    run_id = int(run["id"])
    row = open_question(conn, run_id)
    wanted = body.get("question_id") if isinstance(body, dict) else None
    if wanted is not None:
        asked = conn.execute("SELECT status FROM scope_questions WHERE run_id = ? AND id = ?",
                             (run_id, wanted)).fetchone()
        if asked is None:
            raise QuestionRefused("There is no such question in this run.", 404)
        if asked["status"] == "answered":
            raise QuestionRefused("This question is already answered.", 409)
    if row is None:
        raise QuestionRefused("This run has no open question to answer.", 409)
    choice, text = _read_answer(row, body)
    value = json.loads(row["choices_json"])[choice]["value"] if choice is not None else None
    current = fields.setup_value(conn, run_id, row["field"], row["statement"])
    changes = value is not None and value != current
    cleared = _change_setup(conn, run_id, row, value, email) if changes else 0
    stamp = now()
    conn.execute("UPDATE scope_questions SET status = 'answered', answer_choice = ?, answer_text = ?, "
                 "answer_value = ?, setup_changed = ?, cleared = ?, answered_by = ?, answered_at = ? WHERE id = ?",
                 (choice, text, value, int(changes), cleared, email, stamp, row["id"]))
    words = fields.field_words(row["field"], row["statement"])
    said = "in their own words" if text else f"with {json.loads(row['choices_json'])[choice]['label']}"
    _event(conn, run_id, "answered", f"{email} answered the question about {words} {said}.",
           {"question_id": row["id"], "choice": choice, "own_text": bool(text), "setup_changed": changes,
            "by": email}, row)
    waiting = conn.execute("SELECT id FROM jobs WHERE run_id = ? AND kind = ? AND status IN ('queued', 'retry')",
                           (run_id, job.EXTRACT_JOB)).fetchone()
    if waiting is not None:   # a job handed back after a restart is still to run: it takes the answer
        wanted = job.targets(conn, run_id)   # worked out again: the answer may have switched a statement off
        if wanted:
            job_id = int(waiting["id"])
            conn.execute("UPDATE jobs SET payload_json = ? WHERE id = ?",
                         (json.dumps({"statements": wanted}), job_id))
            conn.execute("UPDATE stages SET status = 'waiting', started_at = NULL, finished_at = NULL, error = NULL "
                         "WHERE run_id = ? AND name = ?", (run_id, job.STAGE))
        else:
            job_id = None
            conn.execute("UPDATE jobs SET status = 'done', last_error = 'Nothing is left to extract.', "
                         "finished_at = ? WHERE id = ?", (stamp, waiting["id"]))
            events.insert(conn, "extraction", "notice", job.NOTHING, run_id=run_id)
    else:
        job_id = job.start(conn, run_id)
    from app.notes import job as notes_job
    notes_job.after_answer(conn, run_id)   # the notes agent stopped too: it starts again from its notes
    if job_id is None:   # nothing left to extract (the answer switched the last statement off)
        conn.execute("UPDATE stages SET status = 'done', finished_at = ?, error = NULL WHERE run_id = ? "
                     "AND name = 'extract'", (stamp, run_id))
        run_status.extraction_done(conn, run_id)
    else:
        run_status.question_answered(conn, run_id)
    logger.info("Run %s: %s answered scope question %s (%s); setup %s, %s agent figure(s) cleared, job %s.",
                run_id, email, row["id"], "own words" if text else f"choice {choice}",
                "changed" if changes else "kept", cleared, job_id)
    return public(conn.execute("SELECT * FROM scope_questions WHERE id = ?", (row["id"],)).fetchone())
