"""What the figures agent's tools share during one run.

Its tools carry the note on the room left (`app/agents/budget.py`): tool
results say how many steps and how much time are left once 70% and 90% of
them are used, and the result before the last step says the next reply is
the last, so the agent reports what it finished instead of being cut off
(v1 lesson, owner's note "project_harness_learnings").
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.agents.budget import WARN_AT, budget_note, budgeted  # noqa: F401 - the agents import them from here
from app.agents.pages import PageSource
from app.catalog.lookup import RunFamily
from app.extraction.outline import Outline
from app.runs.events import add_event

logger = logging.getLogger(__name__)

NAME = "figures"
COMPANY = "Company"


@dataclass
class FiguresDeps(PageSource):
    family: RunFamily
    outline: Outline
    statements: tuple[str, ...] = ("SOFP",)   # the statements it fills, in order; never empty
    statement_pages: list[int] = field(default_factory=list)   # every page they are printed on
    pages_of: dict[str, list[int]] = field(default_factory=dict)   # statement -> its printed pages
    entity: str = COMPANY                 # the columns it fills: Group or Company
    filled: tuple[str, ...] = ()          # statements finished before this run, for the checks across them
    max_steps: int = 60
    job_id: Optional[int] = None
    writes: int = 0                       # save or clear calls that changed something
    checked_at: int = -1                  # `writes` when the checks last ran
    checks_open: list[str] = field(default_factory=list)   # action required at the last run_checks
    coverage: Optional[list[dict]] = None   # the last coverage report, as given
    coverage_open: Optional[list[str]] = None   # what it left unaccounted for; None until reported
    coverage_at: int = -1                 # `writes` when coverage was last reported
    covered: set = field(default_factory=set)   # the statements the last coverage report has lines for
    refused_finish: bool = False
    finish: Optional[dict] = None
    asked: Optional[int] = None           # the scope question asked; the run stops after the tool
    # (field, period) of the figures a person chose to keep through a redo: the tools leave them as they are
    kept_by_person: set = field(default_factory=set)
    warned: set = field(default_factory=set)
    advised: dict = field(default_factory=dict)   # advice point -> the field's value when it was given
    actor_name: str = NAME                # who the figure store records for this agent's writes
    source: str = NAME                    # the events' source

    # What the notes on steps and time left ask for; the Reviewer says its own.
    SOON_NOTE = "Save what is left, run the checks, report coverage and finish before they run out."
    LAST_NOTE = "Stop calling tools and finish now: say what you saved and list what is left in unresolved."

    @property
    def periods(self) -> tuple[str, ...]:
        return self.family.periods

    def owns(self, f: Any) -> bool:
        """Whether a field belongs to a statement this run fills."""
        return f is not None and f.statement in self.statements

    def comment_entity(self, given: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        """(the entity an agent's comment goes on, None) or (None, the refusal): the columns this run fills."""
        if given is not None and given != self.entity:
            return None, f"This run fills the {self.entity} figures, so a comment goes on those."
        return self.entity, None

    def shown_entities(self) -> tuple[str, ...]:
        """Whose saved values show_section shows: this run's own columns."""
        return (self.entity,)

    def event(self, kind: str, message: str, data: Optional[dict] = None, pages: Any = None) -> None:
        """A progress row for the run's activity, with the pages it concerns. Never ends the work.
        Same rule as the shared loop's `_Recorder.event`: a person reads the message, so field ids become
        names (`Outline.readable`), and the agent's own wording is kept in `data["raw"]` when it changed."""
        try:
            shown = self.outline.readable(message)
            if shown != message:
                data = {**(data or {}), "raw": message}
            add_event(self.source, kind, shown, run_id=self.run_id, job_id=self.job_id, data=data, pages=pages)
        except Exception:  # noqa: BLE001
            logger.warning("Could not record an agent event", exc_info=True)
