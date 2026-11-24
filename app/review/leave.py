"""`leave_comment`: an agent asks a person to look at something it did not
change (backend-plan 4.6, `raise_flag`). Shared by the figures agent and the
Reviewer. The comment lands in the run's comments, author kind agent, and in
the "Needs you" list.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from app import db
from app.review import comments as comment_store

MAX_COMMENTS = 10
MAX_TEXT = 1000
PERIOD_WORDS = {"CY": "this year", "PY": "last year"}


class AgentComment(BaseModel):
    field: Optional[str] = Field(default=None, description="The field id, such as FP-s141. Leave it out for a "
                                                           "point about the whole statement.")
    period: Optional[Literal["CY", "PY"]] = Field(default=None, description="The year, for one figure. Leave it "
                                                                            "out for every year of the field.")
    statement: Optional[str] = Field(default=None, description="For a point about a whole statement when you work "
                                                               "on several: its code, such as SOPL.")
    entity: Optional[Literal["Group", "Company"]] = Field(default=None, description=(
        "Group or Company: whose figures. Leave it out for the columns you work on."))
    text: str = Field(description="What a person should look at and why, in one or two plain sentences.")


def _target(deps, entry: AgentComment) -> tuple[Optional[dict], str, str]:
    """(target, where for the agent by id, where for a person by name), or (None, the refusal, '')."""
    if entry.field is None:
        statement = entry.statement or deps.statements[0]
        if statement not in deps.statements:
            return None, f"{statement} is not a statement you work on ({', '.join(deps.statements)}).", ""
        return ({"kind": "statement", "statement": statement, "concept_uuid": None, "period": None,
                 "entity_scope": None, "dimension_key": ""}, statement,
                deps.outline.titles.get(statement, "the statement"))
    f = deps.outline.get(entry.field)
    if not deps.owns(f):
        return None, f"{entry.field} is not a field id in the outline; find the field with find_fields.", ""
    kind = "figure" if entry.period else "line"
    if entry.period and entry.period not in deps.periods:
        return None, f"{f.id}: this run has no prior year.", ""
    entity, refused = deps.comment_entity(entry.entity)
    if refused:
        return None, f"{f.id}: {refused}", ""
    name = deps.outline.person_name(f)
    return ({"kind": kind, "statement": f.statement, "concept_uuid": f.concept_uuid, "period": entry.period,
             "entity_scope": entity, "dimension_key": ""}, f"{f.id}{' ' + entry.period if entry.period else ''}",
            f"{name}, {PERIOD_WORDS[entry.period]}" if entry.period else name)


def leave_comment(ctx: RunContext, comments: list[AgentComment]) -> str:
    """Leave a comment for a person on a figure, a line (every year of a field) or the statement:
    something they should look at that you did not change, such as a figure the report does not settle or
    one a person typed that looks wrong. Up to 10 at a time."""
    deps = ctx.deps
    if not comments:
        return "Give at least one comment."
    if len(comments) > MAX_COMMENTS:
        return f"Leave at most {MAX_COMMENTS} comments at a time."
    out, left = [], []
    with db.connect(immediate=True) as conn:
        for entry in comments:
            text = deps.outline.readable(" ".join(entry.text.split()))   # a person reads it: names, not ids
            if not text:
                out.append("- A comment needs its text.")
                continue
            if len(text) > MAX_TEXT:
                out.append(f"- Keep each comment to {MAX_TEXT} characters or fewer.")
                continue
            target, where, person = _target(deps, entry)
            if target is None:
                out.append(f"- {where}")
                continue
            same = conn.execute(
                "SELECT id FROM comments WHERE run_id = ? AND author_kind = 'agent' AND status = 'open' AND text = ? "
                "AND target_kind = ? AND COALESCE(concept_uuid, '') = ? AND COALESCE(period, '') = ? "
                "AND COALESCE(entity_scope, '') = ?",
                (deps.run_id, text, target["kind"], target["concept_uuid"] or "", target["period"] or "",
                 target["entity_scope"] or "")).fetchone()
            if same is not None:
                out.append(f"- {where}: the same comment is already open (comment {same[0]}).")
                continue
            comment_id = comment_store.add_agent_comment(conn, deps.run_id, deps.actor_name, target, text,
                                                         getattr(deps, "round_id", None))
            out.append(f"- {where}: comment {comment_id} left.")
            left.append((comment_id, person))
    for comment_id, person in left:   # after the write transaction, which holds the database's write lock
        deps.event("comment", f"Left a comment on {person}.", {"comment_id": comment_id})
    return "\n".join(out)
