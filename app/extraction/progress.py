"""Which statements of a run the figures agent has finished: the one owner of
"finished".

A statement is finished for an entity when the agent's accepted finish
covers it: the run completed, its checks ran after the last change, and its
last coverage report, made after the last change, has lines for that
statement (`covered`). The job then writes one `finished` event per agent
run whose data holds the `statements` it finished and the `entity` (step 4's
events hold `statement` alone, for the Company). A failed agent run marks
nothing; a partly filled one (its step or time limit) leaves its statements
unfinished.

A `setup_changed` event (`app/scope/answer.py`) clears the agents' figures of
the statements it refiles, so it drops their marks: every statement for a
whole-run field (`fields.WHOLE_RUN`), else the one whose layout changed.
A `redo` event (`app/runs/redo.py`: a person asked for one statement to be
filled again) drops that statement's marks the same way, and stays open
until the statement is finished again or answered "not printed"
(`open_redo`).
Events were chosen over a new column because every finish already writes
one and it is in the run's export.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Optional, Sequence

from app.catalog.statements import NOT_PREPARED
from app.extraction.state import COMPANY, FiguresDeps
from app.runs.events import insert
from app.scope.fields import ORDER, WHOLE_RUN, names_of

SOURCE = "extraction"


def _finished_pairs(data: dict) -> set[tuple[str, str]]:
    """The (statement, entity) pairs a `finished` event marks."""
    return {(s, data.get("entity") or COMPANY) for s in data.get("statements") or [data.get("statement")] if s}


def finished(conn: sqlite3.Connection, run_id: int) -> set[tuple[str, str]]:
    """(statement, entity) pairs finished and not refiled since."""
    out: set[tuple[str, str]] = set()
    for row in conn.execute("SELECT kind, data_json FROM events WHERE run_id = ? AND ((source = ? AND kind IN "
                            "('finished', 'redo')) OR kind = 'setup_changed') ORDER BY id", (run_id, SOURCE)):
        data = json.loads(row["data_json"] or "{}")
        if row["kind"] == "redo":
            out = {(s, e) for s, e in out if s != data.get("statement")}
            continue
        if row["kind"] == "setup_changed":
            refiled = set(ORDER) if data.get("field") in WHOLE_RUN else {data.get("statement")}
            out = {(s, e) for s, e in out if s not in refiled}
            continue
        out |= _finished_pairs(data)
    return out


def finished_for(conn: sqlite3.Connection, run_id: int, entity: str) -> tuple[str, ...]:
    """The statements finished for one entity, in order."""
    done = finished(conn, run_id)
    return tuple(s for s in ORDER if (s, entity) in done)


def covered(deps: FiguresDeps, completed: bool) -> tuple[str, ...]:
    """The statements an agent run's accepted finish covers (see the module's first paragraph)."""
    if not completed or deps.checked_at != deps.writes or deps.coverage_at != deps.writes:
        return ()
    return tuple(s for s in deps.statements if s in deps.covered)


def mark(conn: sqlite3.Connection, run_id: int, job_id: Optional[int], statements: Sequence[str], entity: str,
         message: str, data: dict) -> None:
    """The finished mark of an agent run: one event naming the statements it finished."""
    insert(conn, SOURCE, "finished", message, run_id=run_id, job_id=job_id,
           data={**data, "statement": statements[0], "statements": list(statements), "entity": entity})


def mark_redo(conn: sqlite3.Connection, run_id: int, statement: str, message: str, keep_mine: bool,
              kept: Sequence[int], cleared: int, email: str) -> None:
    """A person asked for one statement to be filled again: its finished marks are dropped. `keep_mine` says
    whether what a person edited or confirmed is kept (worked out again each time the agent starts, so an edit
    made after a stopped redo is kept too); `kept` records the ids kept when the redo started."""
    insert(conn, SOURCE, "redo", message, run_id=run_id,
           data={"statement": statement, "keep_mine": keep_mine, "kept": list(kept), "cleared": cleared,
                 "by": email})


def open_redo(conn: sqlite3.Connection, run_id: int, entities: Sequence[str] = (COMPANY,)) -> Optional[dict]:
    """The run's latest redo while it is still open: `{"statement", "keep_mine"}`, else None. It stays open
    through a stop, a retry and a setup change that refiles its statement, so a person's figures stay kept
    (`app/figures/redo.held`). It ends for good at the first later event that finishes its statement for
    every entity, or that answers its statement "not printed": the statement has then left the filing, and a
    redo left open would block every other redo."""
    row = conn.execute("SELECT id, data_json FROM events WHERE run_id = ? AND source = ? AND kind = 'redo' "
                       "ORDER BY id DESC LIMIT 1", (run_id, SOURCE)).fetchone()
    if row is None:
        return None
    data = json.loads(row["data_json"] or "{}")
    statement, done = data.get("statement"), set()
    for later in conn.execute("SELECT kind, data_json FROM events WHERE run_id = ? AND id > ? AND ((source = ? "
                              "AND kind = 'finished') OR kind = 'setup_changed') ORDER BY id",
                              (run_id, row["id"], SOURCE)):
        event = json.loads(later["data_json"] or "{}")
        if later["kind"] == "setup_changed":
            if (event.get("field"), event.get("statement"), event.get("to")) == ("layout", statement, NOT_PREPARED):
                return None
            continue
        done |= {entity for s, entity in _finished_pairs(event) if s == statement}
        if all(entity in done for entity in entities):
            return None
    return {"statement": statement, "keep_mine": bool(data.get("keep_mine", data.get("kept")))}


def todo(statements: Sequence[str], entities: Sequence[str], done: set[tuple[str, str]]
         ) -> list[tuple[tuple[str, ...], str]]:
    """The agent runs still to do: one per entity (Group, then Company), with every statement it has not
    finished."""
    out = []
    for entity in entities:
        left = tuple(s for s in statements if (s, entity) not in done)
        if left:
            out.append((left, entity))
    return out


def what(statements: Sequence[str], entity: str, entities: Sequence[str], layouts=None) -> str:
    """Statements as a person names them, with "(Group figures)" or "(Company figures)" on a Group run.
    `layouts` is the run family's `variants`, so a retained earnings statement is named as one."""
    return names_of(statements, layouts) + (f" ({entity} figures)" if len(entities) > 1 else "")


def queued(statements: Sequence[str], entities: Sequence[str], layouts=None) -> str:
    columns = " for the Group and the Company columns" if len(entities) > 1 else ""
    return f"Extraction is queued: the {names_of(statements, layouts)}{columns}."
