"""The Reviewer's tools for share capital and related-party figures: the
notes agent's save and clear (`app/notes/figure_tools.py`), each write naming
the comments it answers.

Those figures go through the figure store like any other figure, so every
hard stop and history row is the same; each write is tagged with the round
and its comments, and its result ends with the server's own count of what
the round changed so far. Given only when a round's comments are on these
figures.
"""
from __future__ import annotations

from typing import Optional

from pydantic import Field
from pydantic_ai import RunContext

from app.figures import store
from app.notes import figure_tools
from app.review.state import ReviewDeps
from app.review.tools import _bad_ids, _grouped, _report_text


class ReviewNoteFigure(figure_tools.NoteFigure):
    comment_ids: list[int] = Field(default_factory=list, description=(
        "The comments this figure answers. Leave it empty only for a change no comment asked for."))


class ReviewNoteFigureClear(figure_tools.NoteFigureClear):
    comment_ids: list[int] = Field(default_factory=list, description="The comments this clear answers.")


def save_note_figures(ctx: RunContext[ReviewDeps], figures: list[ReviewNoteFigure], note: Optional[str] = None
                      ) -> str:
    """Save share capital and related-party figures by field id (SC- and RP- ids) and category, both years in
    one entry, naming the comments each answers. Saving the same field and category again replaces it. The
    result ends with what the round has changed so far.
    `note`: one plain sentence for the person following the round: what you are doing and why."""
    deps = ctx.deps
    if not figures:
        return "Give at least one figure."
    out = []
    for (ids, _), group in _grouped(figures).items():   # the numeric notes are the Company's
        problem = _bad_ids(deps, list(ids))
        if problem:
            out.append(problem)
            continue
        with store.tagged(deps.round_id, ids):
            out.append(figure_tools.save_figures(ctx, group, note))
        note = None
    return "\n".join(out + ["", _report_text(deps)])


def clear_note_figures(ctx: RunContext[ReviewDeps], figures: list[ReviewNoteFigureClear]) -> str:
    """Clear saved share capital or related-party figures, naming the comments each clear answers. A cleared
    figure is blank again, never zero. The result ends with what the round has changed so far."""
    deps = ctx.deps
    if not figures:
        return "Name at least one field."
    out = []
    for (ids, _), group in _grouped(figures).items():   # the numeric notes are the Company's
        problem = _bad_ids(deps, list(ids))
        if problem:
            out.append(problem)
            continue
        with store.tagged(deps.round_id, ids):
            out.append(figure_tools.clear_figures(ctx, group))
    return "\n".join(out + ["", _report_text(deps)])


TOOLS = (save_note_figures, clear_note_figures)
