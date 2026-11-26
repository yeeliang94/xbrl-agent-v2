"""The Reader agent: looks at the pages and their transcriptions and saves
the document map. Runs through the shared agent loop.

Tools: the shared page tools (`app/agents/pages.py`) and save_map, each with
the note on the steps and time left (`app/agents/budget.py`). Every
tool answers a bad request with plain sentences as its result, so a refusal
costs none of the tool's retries. save_map holds the hard rules: a refusal
lists every problem at once and saves nothing; a saved map may come back
with points to check. An answer in words before a map is saved is sent
back: the run ends only once the map is saved.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pydantic_ai import ModelRetry, RunContext

from app import db
from app.agents import budget, history, loop, pages as page_tools
from app.documents import sheets
from app.reading import map_checks, store
from app.reading.instructions import INSTRUCTIONS, page_index
from app.reading.map_schema import DocumentMap

logger = logging.getLogger(__name__)

NAME = "reader"
MAX_STEPS = 40
MAX_SECONDS = 20 * 60
THINKING = "medium"


@dataclass
class ReaderDeps(page_tools.PageSource):
    pages: list[dict] = field(default_factory=list)   # MapPage rows, for folios and turns
    saved: Optional[dict] = None              # the last map saved
    open_points: list[str] = field(default_factory=list)
    max_steps: int = MAX_STEPS
    warned: set = field(default_factory=set)  # the notes on steps and time left already given

    # What the notes on the room left ask for (`app/agents/budget.py`): a map saved late is still a map.
    SOON_NOTE = "Save the map with what you have settled before they run out; you can save it again to correct it."
    LAST_NOTE = ("Save the map now with save_map, as far as you have it, and give what you could not settle in "
                 "note_gaps.")


NOT_SAVED = "Not saved. Fix each of these and save again:"
SAVE_FIRST = "Save the map with save_map before finishing."


def save_map(ctx: RunContext[ReaderDeps], document_map: DocumentMap) -> str:
    """Save the document map. It may be saved again to correct it; the last save counts."""
    deps = ctx.deps
    problems = map_checks.problems(document_map, deps.page_count)
    if problems:
        return NOT_SAVED + "\n" + "\n".join(f"- {p}" for p in problems)
    points = map_checks.points_to_check(document_map, deps.contents)
    doc_map = document_map.model_dump()
    with db.connect(immediate=True) as conn:
        store.save_map(conn, deps.run_id, doc_map, points)
    deps.saved, deps.open_points = doc_map, points
    if not points:
        return "Saved. The code sees no gaps in the notes list or the unit."
    listed = "\n".join(f"- {p}" for p in points)
    return (f"Saved, with points to check:\n{listed}\nLook into each. Correct the map and save again, or give the "
            "reason in note_gaps and save again.")


def saved_first(ctx: RunContext[ReaderDeps], answer: str) -> str:
    """The run may end only once a map is saved."""
    if ctx.deps.saved is None:
        raise ModelRetry(SAVE_FIRST)
    return answer


DROPPED_PICTURE = "[A picture shown before the map was saved was dropped to save space; view the page again if needed.]"


def map_saved(messages: list) -> bool:
    """True once save_map saved a map: older page pictures may then be dropped."""
    return any(part.tool_name == "save_map" and isinstance(part.content, str) and part.content.startswith("Saved")
               for part in history.tool_returns(messages))


def trimmer() -> history.Trimmer:
    return history.Trimmer(text_tools=history.PAGE_TEXT_TOOLS, saved=map_saved, dropped_note=DROPPED_PICTURE)


def spec(model_id: str) -> loop.AgentSpec:
    """A fresh spec per run: its history trimmer remembers what it cut."""
    return loop.AgentSpec(name=NAME, model_id=model_id, instructions=INSTRUCTIONS,
                          tools=[budget.budgeted(t) for t in (*page_tools.PAGE_TOOLS, save_map)],
                          max_steps=MAX_STEPS, max_seconds=MAX_SECONDS, retries=4, thinking=THINKING,
                          history_processor=trimmer(), output_validator=saved_first)


async def run_reader(deps: ReaderDeps, model_id: str, *, job_id: Optional[int] = None,
                     model: Any = None, should_stop: Callable[[], bool] = lambda: False) -> loop.AgentOutcome:
    prompt = page_index(deps.pages) + sheets.index_note(deps.run_id)
    return await loop.run_agent(spec(model_id), prompt, deps=deps, run_id=deps.run_id, job_id=job_id, model=model,
                                should_stop=should_stop)
