"""Redo one statement of a run in review, without a new run (backend-plan: "One statement can be redone
without a new run").

The statement's figures are cleared and the figures agent fills that one
statement again. The other statements are not touched: the agent's tools
write only to the statement it fills. A figure a person edited or confirmed
is kept unless the person asking says otherwise, and the agent's tools then
leave it as it is (`app/extraction/tools.py`). Every cleared figure keeps its
history, so any of them can be restored. A stopped redo is tried again with
the ordinary extraction retry; the kept figures stay kept until the
statement is finished again (`progress.open_redo`).
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from app.catalog.lookup import run_family
from app.catalog.statements import StatementType
from app.db import now
from app.extraction import job, progress
from app.figures import redo as figures_redo
from app.runs import status
from app.scope.fields import ORDER, statement_words


class NoSuchStatement(LookupError):
    def __init__(self) -> None:
        super().__init__("That statement is not part of this run.")


class RedoRefused(ValueError):
    """The statement cannot be redone now. `str()` is one plain sentence."""


NOT_IN_REVIEW = "A statement can be redone once the run is in review and no agent is working on it."
BUSY = "This run still has work in progress, so wait for it to finish before redoing a statement."
UNFINISHED = "The redo of the {name} was stopped before it finished, so try it again before redoing another statement."


def _template(conn: sqlite3.Connection, run_id: int, statement: str) -> tuple[str, str]:
    """(the statement's template id, its name as a person says it), or NoSuchStatement."""
    family = run_family(conn, run_id)
    if statement not in ORDER or family is None or StatementType(statement) not in family.template_ids:
        raise NoSuchStatement()
    kind = StatementType(statement)
    return family.template_ids[kind], statement_words(statement, family.variants.get(kind))


def _refusal(conn: sqlite3.Connection, run: sqlite3.Row, statement: str) -> Optional[str]:
    if run["status"] != status.IN_REVIEW:
        return NOT_IN_REVIEW
    busy = conn.execute("SELECT 1 FROM jobs WHERE run_id = ? AND status IN ('queued', 'working', 'retry')",
                        (run["id"],)).fetchone()
    if busy is not None:
        return BUSY
    # A stopped redo of another statement is still open: a second one would leave that statement half filled
    # and drop what it keeps, so the person finishes it first (Try again).
    family = run_family(conn, run["id"])
    open_redo = progress.open_redo(conn, run["id"], family.entity_scopes) if family else None
    if open_redo and open_redo["statement"] != statement:
        return UNFINISHED.format(name=_template(conn, run["id"], open_redo["statement"])[1])
    return None


def _lines(kept: list[dict], group: bool) -> list[dict]:
    """The kept figures as lines of the statement: one per field (and entity on a Group run), "edited" when any
    of its figures was edited."""
    lines: dict[tuple[str, str], dict] = {}
    for k in kept:
        line = lines.setdefault((k["concept_uuid"], k["entity_scope"]), {
            "concept_uuid": k["concept_uuid"], "entity_scope": k["entity_scope"],
            "label": k["label"] + (f" ({k['entity_scope']})" if group else ""), "how": k["how"]})
        if k["how"] == "edited":
            line["how"] = "edited"
    return list(lines.values())


def preview(conn: sqlite3.Connection, run: sqlite3.Row, statement: str) -> dict:
    """`RedoPreview`: whether the statement can be redone now, and the lines a person edited or confirmed."""
    template_id, name = _template(conn, run["id"], statement)
    kept = figures_redo.kept_by_person(conn, run["id"], template_id)
    return {"statement": statement, "name": name, "refusal": _refusal(conn, run, statement),
            "kept": _lines(kept, (run["level"] or "").lower() == "group")}


def start(conn: sqlite3.Connection, run: sqlite3.Row, statement: str, keep_mine: bool, email: str) -> dict:
    """Clear the statement and queue the figures agent for it alone. Use inside `db.connect(immediate=True)`.
    Returns `{"cleared", "kept"}` (figures cleared, lines kept). Raises NoSuchStatement or RedoRefused."""
    run_id = int(run["id"])
    template_id, name = _template(conn, run_id, statement)
    refusal = _refusal(conn, run, statement)
    if refusal:
        raise RedoRefused(refusal)
    kept = figures_redo.kept_by_person(conn, run_id, template_id) if keep_mine else []
    lines = len(_lines(kept, False))
    keep = frozenset(k["figure_id"] for k in kept)
    cleared = figures_redo.clear_statement(conn, run_id, template_id, email,
                                           f"Cleared when {email} redid the {name}.", keep=keep)
    progress.mark_redo(conn, run_id, statement, f"Started redoing the {name}.", keep_mine, sorted(keep), cleared,
                       email)
    if lines:
        conn.execute("INSERT INTO events(run_id, source, kind, message, created_at) VALUES (?, ?, 'notice', ?, ?)",
                     (run_id, job.SOURCE, f"Kept {lines} line{'s' if lines != 1 else ''} a person edited or "
                      "confirmed.", now()))
    job.start(conn, run_id, only=(statement,))
    status.extraction_retried(conn, run_id)
    return {"cleared": cleared, "kept": lines}
