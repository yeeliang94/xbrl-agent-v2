"""What the notes agent's tools share during one session, and its field ids.
Several sessions run at once (`app/notes/job.py`); each has its own deps, and
only `previews` is shared between them.

Note fields get short ids of their own, as the figures agent's outline does:
`CORP-<row>`, `POL-<row>` and `LIST-<row>` for the three prose templates
(the template row, so the same in every run with that template). The two
numeric notes keep the figure outline's ids for their figures (`SC-<row>`,
`RP-<row>`); their text fields, where a note's words go, are `SCT-<row>` and
`RPT-<row>`. Ids
belong only in tool arguments: `NotesOutline.readable` turns every id in
text a person reads into the field's label, and a block id into its page.

The step budget notes come from `app/extraction/state.py` (`budgeted`).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.agents.pages import PageSource
from app.catalog.lookup import RunFamily
from app.catalog.note_fields import NoteField
from app.extraction.outline import Outline
from app.runs.events import add_event

logger = logging.getLogger(__name__)

NAME = "notes"
COMPANY = "Company"
PROSE_CODES = {"CORP_INFO": "CORP", "ACC_POLICIES": "POL", "LIST_OF_NOTES": "LIST",
               "ISSUED_CAPITAL": "SCT", "RELATED_PARTY": "RPT"}   # the numeric notes' text fields
PROSE_STATEMENT = "NOTES"   # where a comment on the notes as a whole is filed
_NOTE_ID = re.compile(r"\b(?:CORP|POL|LIST|SCT|RPT)-\d+[a-z]?\b", re.I)
_BLOCK_ID = re.compile(r"\bp(\d+)b\d+\b")


@dataclass
class NotesOutline(Outline):
    """The numeric notes' figure outline, plus the prose note fields by id."""
    notes: dict[str, NoteField] = field(default_factory=dict)       # id -> note field
    note_ids: dict[str, str] = field(default_factory=dict)          # node_uuid -> id

    def note_field(self, field_id: str) -> Optional[NoteField]:
        key = "".join(str(field_id).split()).upper()
        return self.notes.get(key)

    def note_name(self, f: NoteField) -> str:
        return f.label

    def readable(self, text: str) -> str:
        def name(match: re.Match) -> str:
            f = self.note_field(match.group(0))
            return f.label if f is not None else match.group(0)
        shown = _NOTE_ID.sub(name, text or "")
        shown = _BLOCK_ID.sub(lambda m: f"page {m.group(1)}", shown)
        return super().readable(shown)


def notes_outline(numeric: Outline, fields: list[NoteField]) -> NotesOutline:
    out = NotesOutline(**{k: getattr(numeric, k) for k in Outline.__dataclass_fields__})
    out.titles.setdefault(PROSE_STATEMENT, "the notes")
    for f in fields:
        code = PROSE_CODES[f.template]
        fid, n = f"{code}-{f.row}", 1
        while fid in out.notes:
            n += 1
            fid = f"{code}-{f.row}{'abcdefgh'[n - 2]}"
        out.notes[fid] = f
        out.note_ids[f.field_id] = fid
    return out


@dataclass
class NotesDeps(PageSource):
    family: RunFamily
    outline: NotesOutline
    session: str = "placing"                               # placing, numeric or look (agent.SESSIONS)
    name: str = "placing"                                  # this session's own name, such as look-2
    label: str = ""                                        # its activity name, e.g. "Formatting the notes, 2 of 3"
    max_steps: int = 40
    job_id: Optional[int] = None
    notes_list: list[dict] = field(default_factory=list)   # the confirmed notes list, in order
    previews: dict = field(default_factory=dict)            # note id -> previews used (shared across sessions)
    previewed_at: dict = field(default_factory=dict)        # note id -> its revision at the last preview
    touched: set = field(default_factory=set)               # note ids placed or changed in this session
    looked: set = field(default_factory=set)                # note ids whose look this session set
    group: frozenset = frozenset()                          # a formatting session's note ids; empty otherwise
    writes: int = 0                                         # changes in this session (notes, figures, reports)
    coverage_open: Optional[list[str]] = None                # what the last report_coverage left open
    coverage_at: int = -1
    coverage_told: Optional[list[str]] = None                # the open points last sent back on a finish
    refused_finish: bool = False
    finish: Optional[dict] = None
    asked: Optional[int] = None
    warned: set = field(default_factory=set)
    statement: str = PROSE_STATEMENT                       # leave_comment's whole-statement target
    stage: str = "notes"                                    # ask_scope's stage
    actor_name: str = NAME
    source: str = NAME

    PREVIEWS_USED = "flag what still differs with flag_formatting."
    SOON_NOTE = "Finish placing, preview what you changed, report coverage and finish before they run out."
    LAST_NOTE = "Stop calling tools and finish now: say what you placed and list what is left in unresolved."
    ASKED = ("Your question is saved for the person. Stop now and do not call another tool: every note you "
             "placed is kept, and the notes agent starts again with their answer.")

    @property
    def periods(self) -> tuple[str, ...]:
        return self.family.periods

    @property
    def entity(self) -> str:
        return COMPANY

    @property
    def statements(self) -> tuple[str, ...]:
        """leave_comment's statement: the one this group of comments is on."""
        return (self.statement,)

    def owns(self, f: Any) -> bool:
        return f is not None and f.statement == self.statement

    def comment_entity(self, given: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        if given is not None and given != COMPANY:
            return None, "The notes agent fills the Company figures, so a comment goes on those."
        return COMPANY, None

    def event(self, kind: str, message: str, data: Optional[dict] = None, pages: Any = None) -> None:
        """A progress row a person reads: ids become names, the agent's own words kept in `data["raw"]`."""
        try:
            if self.label:
                data = {**(data or {}), "agent": self.label}
            shown = self.outline.readable(message)
            if shown != message:
                data = {**(data or {}), "raw": message}
            add_event(self.source, kind, shown, run_id=self.run_id, job_id=self.job_id, data=data, pages=pages)
        except Exception:  # noqa: BLE001
            logger.warning("Could not record a notes agent event", exc_info=True)
