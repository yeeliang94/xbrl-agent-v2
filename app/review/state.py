"""What the Reviewer's tools share during one correction round.

It extends the figures agent's state, so the same field-finding, outline,
definition, page and save tools work unchanged, and carries what the notes
agent's look and preview tools read, so they work for the Reviewer too; the store records its writes
as the agent "reviewer", and its events have the source "review".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.extraction.state import FiguresDeps

NAME = "review"        # the agent's name: its events and model calls
ACTOR = "reviewer"     # who the figure store records for its writes


@dataclass
class ReviewDeps(FiguresDeps):
    round_id: int = 0
    round_number: int = 0
    comment_ids: list[int] = field(default_factory=list)       # the round's comments, in order
    scopes: dict[int, str] = field(default_factory=dict)        # comment id -> figure, run or company
    entities: dict[int, Optional[str]] = field(default_factory=dict)   # comment id -> Group, Company or None
    answered: dict[int, str] = field(default_factory=dict)      # comment id -> outcome
    checks_before: list[dict] = field(default_factory=list)     # the check results when the round was sent
    newly_failing: list[dict] = field(default_factory=list)     # at the last run_checks
    assessed: Optional[bool] = None                             # whether the last run_checks assessed anything
    numeric: bool = False                                       # comments on share capital or related-party figures
    has_notes: bool = False                                     # the run holds notes: the note tools are given
    previews: dict = field(default_factory=dict)                # note id -> previews used in this round
    previewed_at: dict = field(default_factory=dict)            # note id -> its revision at the last preview

    PREVIEWS_USED = "say in your answer what still differs, for a person to check."
    SOON_NOTE = "Answer every comment, run the checks and finish before they run out."
    LAST_NOTE = ("Answer what you can with answer_comment now; comments left unanswered go back to the "
                 "person, and the changes you made are kept.")

    def comment_entity(self, given: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        """The Reviewer's own comment is settled like its writes: named, or the run's one entity."""
        from app.review.tools import entity_for   # the tools build on this module
        return entity_for(self, (), given)

    def shown_entities(self) -> tuple[str, ...]:
        """On a Group run show_section shows both entities' saved values, each labelled."""
        return self.family.entity_scopes


NUMERIC_CHECKS = ("notes_numeric_footing", "notes_face_tieouts")
WIDE_SCOPES = ("run", "company")   # a comment to fix the same thing wherever it occurs


def round_statements(family, comments) -> tuple[str, ...]:
    """The statements the Reviewer works on: those the round's comments are on, in order; every included
    statement when a comment applies to the run or the company; for a round on the notes alone, the run's
    first statement, so the figure tools have a template. Empty when the run has no statement."""
    from app.catalog.statements import StatementType
    from app.scope.fields import ORDER

    included = tuple(s for s in ORDER if StatementType(s) in family.template_ids)
    if any(c["scope"] in WIDE_SCOPES for c in comments):
        return included
    named = {c["statement"] for c in comments if c["target_kind"] in ("figure", "line", "statement")}
    return tuple(s for s in included if s in named) or included[:1]


def check_filter(family, statements, numeric: bool):
    """Which checks the Reviewer is shown, in run_checks and in the round's report: those on its statements,
    with the checks across them and the run's other statements, and the numeric notes' checks when the round
    changes share capital or related-party figures."""
    from app.extraction.checking import relevant_to

    every = tuple(s.value for s in family.template_ids)
    return lambda name: relevant_to(statements, name, every) or (numeric and name in NUMERIC_CHECKS)
