"""`ask_scope`: an agent's one question to a person, about scope only. Shared
by the figures agent and the notes agent; the question is filed under the
asking agent's stage (`deps.stage`, `extract` unless the deps say otherwise).

It is for evidence in the document against the setup a person confirmed.
The question, its evidence and its choices are saved with the stage set to
`asking` and the run to `needs_answer`, in one transaction, and the agent
stops before its next step (`agent.run_figures` passes the stop). Every
figure saved so far is kept. A refusal is one plain sentence the agent can
act on.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from app import db
from app.reading.map_schema import STATEMENTS
from app.runs import status as run_status
from app.scope import fields

logger = logging.getLogger(__name__)

MAX_QUESTION = 300
MAX_TEXT = 500
MAX_EVIDENCE = 6
STAGE = "extract"
ASKED = ("Your question is saved for the person. Stop now and do not call another tool: every figure you saved "
         "is kept, and extraction starts again with their answer.")


class Evidence(BaseModel):
    text: str = Field(description="The words quoted from the page, or what the page shows, in one line.")
    page: Optional[int] = Field(default=None, description="The PDF page it is on.")


class Choice(BaseModel):
    label: str = Field(description="The choice as the person reads it, such as MPERS.")
    value: str = Field(description="The setup value it stands for: MFRS or MPERS; Company or Group; RM, "
                                   "RM'000 or RM'000,000; a date YYYY-MM-DD; or a layout name, or NotPrepared for a "
                                   "statement not printed.")
    effect: str = Field(description="One line on what follows if the person picks it.")
    suggested: bool = Field(default=False, description="True on the one choice the evidence supports best.")


def _text(value: str) -> str:
    return " ".join(str(value or "").split())


def _refusal(deps, field: str, statement: Optional[str], question: str, evidence: list[Evidence],
             choices: list[Choice], confirmed: str) -> Optional[str]:
    if field not in fields.FIELDS:
        return ("Ask only about the scope: the standard, the level, the year end, the unit, or a statement's "
                "layout or whether it is printed. Settle anything else yourself: mark the figure unsure or "
                "leave a comment.")
    if field == "layout" and statement not in STATEMENTS:
        return "Name the statement whose layout you ask about: SOFP, SOPL, SOCI, SOCF or SOCIE."
    if not question or len(question) > MAX_QUESTION:
        return f"Put the question in one sentence of up to {MAX_QUESTION} characters."
    if not evidence or any(e.page is None for e in evidence):
        return "Give the evidence with the PDF page of each line, so the person can check it."
    if len(evidence) > MAX_EVIDENCE or any(not _text(e.text) or len(_text(e.text)) > MAX_TEXT for e in evidence):
        return f"Give up to {MAX_EVIDENCE} lines of evidence, each one line of text with its page."
    if any(not 1 <= int(e.page) <= deps.page_count for e in evidence):
        return f"Evidence pages must be within the document's {deps.page_count} pages."
    if not 2 <= len(choices) <= 4:
        return "Give two to four choices."
    if sum(1 for c in choices if c.suggested) != 1:
        return "Mark exactly one choice as suggested: the one the evidence supports best."
    if any(not _text(c.label) or not _text(c.effect) or len(_text(c.effect)) > MAX_TEXT for c in choices):
        return "Give each choice a label and one line on what follows."
    bad = next((c.value for c in choices if not fields.valid(field, c.value, statement)), None)
    if bad is not None:
        allowed = fields.values(field, statement)
        return (f"{bad!r} is not a value for {fields.field_words(field, statement)}; use "
                + (", ".join(allowed) if allowed else "a date as YYYY-MM-DD") + ".")
    if len({c.value for c in choices}) != len(choices):
        return "Give each choice a different value."
    if confirmed not in {c.value for c in choices}:
        return (f"One choice must be the setup as confirmed ({confirmed}), so the person can keep it, with what "
                "follows if they do.")
    return None


def ask_scope(ctx: RunContext, field: str, question: str, evidence: list[Evidence], choices: list[Choice],
              statement: Optional[str] = None) -> str:
    """Ask the person one question about the run's scope, when the document itself contradicts the setup
    they confirmed: the standard, the level (Company or Group), the year end, the unit, or a statement's
    layout or whether it is printed. Give the evidence on both sides with pages, and two to four choices
    with exactly one suggested; the confirmed value is one of them. Your run stops after this tool."""
    deps = ctx.deps
    readable = deps.outline.readable   # a person reads the card: field ids become names
    stage = getattr(deps, "stage", STAGE)
    question = readable(_text(question))
    statement = statement if field == "layout" else None   # as saved, so a repeat is found whatever was passed
    with db.connect(immediate=True) as conn:
        open_row = conn.execute("SELECT id FROM scope_questions WHERE run_id = ? AND status = 'open'",
                                (deps.run_id,)).fetchone()
        if open_row is not None:
            return "A question is already waiting for the person's answer, so stop now."
        confirmed = fields.setup_value(conn, deps.run_id, field, statement) if field in fields.FIELDS else ""
        refusal = _refusal(deps, field, statement, question, evidence, choices, confirmed)
        if refusal:
            return refusal
        # A question answered earlier in this run is settled: asking it again would loop the person.
        earlier = conn.execute("SELECT answer_text, answer_value FROM scope_questions WHERE run_id = ? "
                               "AND status = 'answered' AND field = ? AND COALESCE(statement, '') = ? "
                               "ORDER BY id DESC LIMIT 1", (deps.run_id, field, statement or "")).fetchone()
        if earlier is not None:
            return (f"The person already answered a question about {fields.field_words(field, statement)}; "
                    "their answer is in your first message. Treat it as settled and carry on.")
        stamp = db.now()
        question_id = int(conn.execute(
            "INSERT INTO scope_questions(run_id, stage, asked_by, field, statement, question, evidence_json, "
            "choices_json, setup_value, asked_at, job_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (deps.run_id, stage, deps.actor_name, field, statement, question,
             json.dumps([{"text": readable(_text(e.text)), "page": int(e.page)} for e in evidence],
                        ensure_ascii=False),
             json.dumps([{"label": readable(_text(c.label)), "value": c.value, "effect": readable(_text(c.effect)),
                          "suggested": bool(c.suggested)} for c in choices], ensure_ascii=False),
             confirmed, stamp, deps.job_id)).lastrowid)
        conn.execute("UPDATE stages SET status = 'asking', finished_at = ?, error = NULL WHERE run_id = ? "
                     "AND name = ?", (stamp, deps.run_id, stage))
        run_status.extraction_asked(conn, deps.run_id)
    deps.asked = question_id
    deps.event("asked", f"Stopped to ask about {fields.field_words(field, statement)}.",
               {"question_id": question_id, "field": field, "statement": statement}, [e.page for e in evidence])
    logger.info("Run %s: the %s agent asked scope question %s about %s.", deps.run_id, deps.actor_name,
                question_id, field)
    return getattr(deps, "ASKED", ASKED)
