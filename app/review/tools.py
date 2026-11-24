"""The Reviewer's own tools: save, clear and move figures for named comments,
run the checks, answer comments, and the finish.

Writes go through the figures agent's save and clear tools and the figure
store's move, so every hard stop and every history row is the same as for
the figures agent. Each write is tagged with the round and the comments it
served, and its result ends with the server's own count of what the round
changed so far (`changes.report_text`). A tool that refuses says why in one
plain sentence, as its result.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext

from app import db
from app.checks.runner import read_checks
from app.extraction import tools as figure_tools
from app.extraction.checking import ACTION, check_pages
from app.figures import store
from app.review import changes, comments
from app.review.state import WIDE_SCOPES, ReviewDeps, check_filter
from app.runs.events import clean_note

MAX_ANSWER = 500
MAX_GUIDANCE = 300


def _relevant(deps: ReviewDeps, name: str) -> bool:
    """The Reviewer's checks (`state.check_filter`), the same filter the round's report uses."""
    return check_filter(deps.family, deps.statements, deps.numeric)(name)


def _entity_title(deps: ReviewDeps, check: dict) -> dict:
    """A check as the Reviewer reads it: on a Group run its title says whose figures it is on."""
    if len(deps.family.entity_scopes) < 2:
        return check
    return {**check, "title": f"{check['title']} ({check['entity_scope']})"}


def _bad_ids(deps: ReviewDeps, ids: list[int]) -> Optional[str]:
    outside = [i for i in ids if i not in deps.comment_ids]
    if outside:
        return (f"Comment {outside[0]} is not part of this round; the round's comments are "
                f"{', '.join(map(str, deps.comment_ids))}.")
    return None


def _report(deps: ReviewDeps) -> dict:
    with db.connect() as conn:
        return changes.report(conn, deps.run_id, deps.round_id)


def _report_text(deps: ReviewDeps) -> str:
    return changes.report_text(_report(deps), field_id=lambda uuid: deps.outline.by_uuid.get(uuid))


def _grouped(entries: list) -> dict[tuple[tuple[int, ...], Optional[str]], list]:
    """The entries by the comments they answer and the entity they name."""
    out: dict[tuple[tuple[int, ...], Optional[str]], list] = {}
    for entry in entries:
        out.setdefault((tuple(sorted(set(entry.comment_ids))), getattr(entry, "entity", None)), []).append(entry)
    return out


def entity_for(deps: ReviewDeps, ids, given: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """(the entity a write changes, None) or (None, the refusal). A write goes to the columns of the comments
    it answers (step 7c); a write no figure comment settles names its entity, unless the run has one."""
    scopes = deps.family.entity_scopes
    named = sorted({deps.entities[i] for i in ids if deps.entities.get(i)})
    # A comment to fix the same thing wherever it occurs may be answered in either entity's columns.
    held = sorted({deps.entities[i] for i in ids if deps.entities.get(i) and deps.scopes.get(i) not in WIDE_SCOPES})
    if given is not None and given not in scopes:
        return None, f"This run has no {given} figures; it saves figures for {' and '.join(scopes)}."
    if given is not None and held and held != [given]:
        return None, (f"Comment {', '.join(map(str, ids))} is on the {' and '.join(held)} figures, so this write "
                      f"changes those columns; leave entity out or give {held[0]}.")
    if given is not None:
        return given, None
    if len(named) > 1:
        return None, (f"Comments {', '.join(map(str, ids))} are on both the Group and the Company figures; give each "
                      "entity its own entry.")
    if named:
        return named[0], None
    if len(scopes) == 1:
        return scopes[0], None
    return None, "Say which columns this changes: give entity Group or Company."


ENTITY = Field(default=None, description="Group or Company: the columns this changes. Leave it out to use the "
                                         "columns of the comments named.")


class ReviewSave(figure_tools.FigureSave):
    comment_ids: list[int] = Field(default_factory=list, description=(
        "The comments this figure answers. Leave it empty only for a change no comment asked for."))
    entity: Optional[Literal["Group", "Company"]] = ENTITY


class ReviewClear(figure_tools.FigureClear):
    comment_ids: list[int] = Field(default_factory=list, description="The comments this clear answers.")
    entity: Optional[Literal["Group", "Company"]] = ENTITY


def save_figures(ctx: RunContext[ReviewDeps], figures: list[ReviewSave], note: Optional[str] = None) -> str:
    """Save figures by field id, both years in one entry, as the figures agent does, naming the comments each
    answers. Saving a field again replaces it. Each figure is judged on its own. The result ends with what the
    round has changed so far.
    `note`: one plain sentence for the person following the round: what you are doing and why.
    """
    deps = ctx.deps
    if not figures:
        return "Give at least one figure."
    out = []
    for (ids, given), group in _grouped(figures).items():
        problem = _bad_ids(deps, list(ids))
        entity, refused = entity_for(deps, ids, given)
        if problem or refused:
            out.append(problem or refused)
            continue
        with store.tagged(deps.round_id, ids):
            out.append(figure_tools.save_for(deps, group, note, entity))
        note = None   # the note describes the call once
    return "\n".join(out + ["", _report_text(deps)])


def clear_figures(ctx: RunContext[ReviewDeps], figures: list[ReviewClear], note: Optional[str] = None) -> str:
    """Clear saved figures, naming the comments each clear answers. A cleared figure is blank again, never
    zero. The result ends with what the round has changed so far.
    `note`: one plain sentence for the person following the round: what you are doing and why.
    """
    deps = ctx.deps
    if not figures:
        return "Name at least one field."
    out = []
    for (ids, given), group in _grouped(figures).items():
        problem = _bad_ids(deps, list(ids))
        entity, refused = entity_for(deps, ids, given)
        if problem or refused:
            out.append(problem or refused)
            continue
        with store.tagged(deps.round_id, ids):
            out.append(figure_tools.clear_for(deps, group, note, entity))
        note = None
    return "\n".join(out + ["", _report_text(deps)])


class Move(BaseModel):
    field: str = Field(description="The field id the figure is in now.")
    to_field: str = Field(description="The field id it belongs in.")
    period: Literal["CY", "PY", "both"] = "both"
    comment_ids: list[int] = Field(default_factory=list, description="The comments this move answers.")
    entity: Optional[Literal["Group", "Company"]] = ENTITY


def move_figures(ctx: RunContext[ReviewDeps], moves: list[Move], note: Optional[str] = None) -> str:
    """Move saved figures to another field with their printed lines, for a right amount in the wrong field.
    A field that already holds a figure gets the two added together. The result ends with what the round has
    changed so far.
    `note`: one plain sentence for the person following the round: what you are doing and why.
    """
    deps = ctx.deps
    if not moves:
        return "Give at least one move."
    saved = {e: figure_tools._saved(deps, e) for e in deps.family.entity_scopes}
    out, moved = [], 0
    with db.connect(immediate=True) as conn:
        for m in moves:
            source, target = deps.outline.get(m.field), deps.outline.get(m.to_field)
            problem = _bad_ids(deps, m.comment_ids)
            entity, refused = entity_for(deps, m.comment_ids, m.entity)
            problem = problem or refused
            if not deps.owns(source):
                problem = problem or figure_tools._unknown(deps, m.field)
            if not deps.owns(target):
                problem = problem or figure_tools._unknown(deps, m.to_field)
            if problem:
                out.append(f"- {problem}")
                continue
            periods = deps.periods if m.period == "both" else (m.period,)
            rows = [saved[entity].get((source.concept_uuid, p)) for p in periods]
            rows = [r for r in rows if r is not None and r["value"] is not None]
            if not rows:
                out.append(f"- {source.id} {source.name}: nothing is saved there to move.")
                continue
            # One move is all or nothing: a year refused after another was written takes every write of the
            # move back, history rows included.
            conn.execute("SAVEPOINT one_move")
            try:
                with store.tagged(deps.round_id, m.comment_ids):
                    store.move_figure(conn, deps.run_id, rows[0]["id"], target.concept_uuid,
                                      figure_tools._actor(deps), whole_row=m.period == "both")
                conn.execute("RELEASE one_move")
                moved += 1
                out.append(f"- {source.id} {source.name} moved to {target.id} {target.name} ({m.period}).")
            except store.Refused as exc:
                conn.execute("ROLLBACK TO one_move")
                conn.execute("RELEASE one_move")
                out.append(f"- {source.id} {source.name}: not moved, and nothing of this move was saved. {exc}")
    if moved:
        deps.writes += 1
        deps.event("moved", clean_note(note) or f"Moved {moved} figure(s).",
                   {"moves": [f"{m.field}>{m.to_field} {m.period}" for m in moves]})
    return "\n".join([f"Moved {moved} of {len(moves)}."] + out + ["", _report_text(deps)])


def run_checks(ctx: RunContext[ReviewDeps]) -> str:
    """Run the checks on what is saved now. The result names every check that passed when the round began
    and does not pass now."""
    deps = ctx.deps
    with db.connect() as conn:
        everything = read_checks(conn, deps.run_id)
    # Every entity of the run: a round may hold comments on the Group and on the Company figures.
    mine = [_entity_title(deps, c) for c in everything if _relevant(deps, c["name"])
            and c["status"] != "not_applicable"]
    summary = changes.check_summary(deps.checks_before, everything, lambda name: _relevant(deps, name))
    newly = [_entity_title(deps, c) for c in summary["newly_failing"]]
    action = [c for c in mine if c["status"] in ACTION]
    passed = [c for c in mine if c["status"] == "passed"]
    assessed = bool(action or passed)
    deps.checked_at, deps.checks_open = deps.writes, [f"{c['title']}: {c['message']}" for c in action]
    deps.newly_failing, deps.assessed = newly, assessed
    out = []
    if not assessed:
        out.append("No check could be assessed on what is saved now, so none is shown as passed.")
    if newly:
        out += ["Passed when the round began and do not pass now. Each is a lead to trace: either a change of "
                "yours was wrong (fix or undo it) or it exposed another wrong figure (fix that), or explain it:",
                *[f"- {c['title']}: {c['message']}" for c in newly]]
    out += (["Action required:", *[f"- {c['title']}: {c['message']}" for c in action]] if action
            else ["Nothing needs action."] if assessed else [])
    waiting = [c for c in mine if c["status"] == "not_assessed"]
    if waiting:
        out += ["Not assessed:", *[f"- {c['title']}: {c['message']}" for c in waiting]]
    if passed:
        out += ["Passed:", *[f"- {c['title']}: {c['message']}" for c in passed]]
    deps.event("checked", f"Checks: {len(action)} need action, {len(passed)} passed.",
               {"action": len(action), "passed": len(passed), "assessed": assessed, "newly_failing": len(newly)},
               check_pages(deps.run_id, action))
    return "\n".join(out)


class Answer(BaseModel):
    comment_id: int
    outcome: Literal["changed", "not_changed", "question"] = Field(
        description="changed: you corrected it. not_changed: the figures already follow the report, and the answer "
                    "says why. question: the report does not settle it and you need the person's answer.")
    answer: str = Field(description="One plain sentence for the person: what you changed and why, why nothing "
                                    "needed to change, or your question.")
    proposed_guidance: Optional[str] = Field(
        default=None, description="Only for a comment that applies to the company and that you changed: one line of "
                                  "company guidance that would have avoided the mistake. A person decides whether "
                                  "to add it.")


def answer_comment(ctx: RunContext[ReviewDeps], answers: list[Answer], note: Optional[str] = None) -> str:
    """Answer the round's comments, each with changed, not_changed or question and one sentence. A comment
    can be answered again; the last answer counts.
    `note`: one plain sentence for the person following the round: what you are doing and why.
    """
    deps = ctx.deps
    if not answers:
        return "Give at least one answer."
    rep = {c["comment_id"]: c for c in _report(deps)["comments"]}
    out, recorded = [], []
    with db.connect(immediate=True) as conn:
        for a in answers:
            # A person reads both: field ids become names.
            text = deps.outline.readable(" ".join(a.answer.split()))
            guidance = deps.outline.readable(" ".join((a.proposed_guidance or "").split())) or None
            problem = _bad_ids(deps, [a.comment_id])
            if problem is None and not text:
                problem = f"Comment {a.comment_id}: give the answer as one plain sentence."
            elif problem is None and len(text) > MAX_ANSWER:
                problem = f"Comment {a.comment_id}: keep the answer to {MAX_ANSWER} characters or fewer."
            elif problem is None and a.outcome == "changed" and not rep[a.comment_id]["changed"]:
                problem = (f"Nothing has changed for comment {a.comment_id} yet, so save the correction first, "
                           "naming this comment in comment_ids on the write that corrects it, or answer "
                           "not_changed or question.")
            elif problem is None and guidance and (deps.scopes.get(a.comment_id) != "company"
                                                   or a.outcome != "changed"):
                problem = (f"Comment {a.comment_id}: a guidance line is proposed only for a comment that applies "
                           "to the company and that you changed.")
            elif problem is None and guidance and len(guidance) > MAX_GUIDANCE:
                problem = f"Comment {a.comment_id}: keep the guidance line to {MAX_GUIDANCE} characters or fewer."
            if problem:
                out.append(f"- {problem}")
                continue
            comments.record_answer(conn, deps.round_id, a.comment_id, a.outcome, text, guidance)
            deps.answered[a.comment_id] = a.outcome
            recorded.append(a)
            out.append(f"- Comment {a.comment_id}: answered {a.outcome.replace('_', ' ')}.")
    note = clean_note(note)
    for a in recorded:   # the note, when given, is the first answer's row
        deps.event("answered", note or f"Answered comment {a.comment_id}: {a.outcome.replace('_', ' ')}.",
                   {"comment_id": a.comment_id, "outcome": a.outcome})
        note = None
    left = [c for c in deps.comment_ids if c not in deps.answered]
    out.append(f"Still to answer: comment {', '.join(map(str, left))}." if left else "Every comment is answered.")
    return "\n".join(out)


# The finish ----------------------------------------------------------------------

class Explanation(BaseModel):
    check: str = Field(description="The check's name or title, as run_checks gives it.")
    reason: str = Field(description="What you traced and why you leave it failing, in one sentence: for example "
                                    "your change follows the page and it exposed a figure the report does not "
                                    "settle.")


class ReviewFinish(BaseModel):
    summary: str = Field(description="One sentence for the person: what this round changed and what it did not.")
    explained: list[Explanation] = Field(
        default_factory=list, description="Only for a check that passed when the round began and fails now, "
                                          "which you traced and leave failing, each with its reason.")


def _covered(check: dict, notes: list[Explanation]) -> bool:
    names = {" ".join(n.check.lower().split()) for n in notes if n.reason.strip()}
    return check["name"].lower() in names or " ".join(check["title"].lower().split()) in names


def finish_reasons(deps: ReviewDeps, report: ReviewFinish) -> list[str]:
    out = []
    left = [c for c in deps.comment_ids if c not in deps.answered]
    if left:
        out.append(f"Answer comment {', '.join(map(str, left))} with answer_comment: changed, not_changed or "
                   "question, each with one sentence.")
    if deps.writes > 0 and deps.checked_at != deps.writes:
        out.append("Run the checks with run_checks after your last change.")
    elif deps.writes > 0:
        for check in deps.newly_failing:
            if not _covered(check, report.explained):
                out.append(f"{check['title']} passed when the round began and does not pass now. Trace it: "
                           "either a change of yours was wrong (fix or undo it) or it exposed another wrong "
                           "figure (fix that). If you leave it failing, finish again and explain it in explained "
                           "with the reason.")
    if not report.summary.strip():
        out.append("Give a one-sentence summary for the person.")
    return out


def finish(ctx: RunContext[ReviewDeps], report: ReviewFinish) -> ReviewFinish:
    """The round ends only with every comment answered, the checks run after the last change, and no check
    broken by the round left unexplained."""
    deps = ctx.deps
    reasons = finish_reasons(deps, report)
    if reasons:
        deps.event("notice", "The finish was sent back: " + reasons[0])
        raise ModelRetry("Not finished yet:\n" + "\n".join(f"- {r}" for r in reasons))
    deps.finish = {**report.model_dump(), "checks_assessed": deps.assessed}
    return report
