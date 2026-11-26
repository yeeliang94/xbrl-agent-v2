"""Runs: create one, read one, and the rule for who may open it.

Runs are shared, as in v1: anyone signed in may open any run. The run list
marks a person's own runs as "Mine". `open_run` is the one place that rule
lives, so it can be narrowed later without touching the routes.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from app.auth.store import User
from app.catalog.statements import StatementType, get_variant
from app.db import now
from app.runs import status as run_status
from app.utils.paths import output_dir, safe_entry_path, safe_path

logger = logging.getLogger(__name__)


class RunNotFound(LookupError):
    """No run with that number, or not one this person may open."""


class RunRefused(ValueError):
    """A run that cannot be created as asked. `str()` is one plain sentence."""


def create_run(conn: sqlite3.Connection, *, company: str, year: Optional[int], standard: str, level: str,
               owner_email: str, statements: Iterable[tuple[str, str]], first_statements: bool = False,
               unit: str = "RM", status: str = "setup") -> int:
    """Create a run with its confirmed layouts, e.g. [("SOFP", "CuNonCu")].
    Raises RunRefused for a layout the run's standard does not have."""
    statements = list(statements)
    for statement, variant in statements:
        layout = get_variant(StatementType(statement), variant)  # an unknown layout raises here
        if standard.lower() not in layout.applies_to_standard:
            raise RunRefused(f"The {variant} layout of {statement} does not exist for {standard.upper()} "
                             "filings, so choose another layout.")
    stamp = now()
    conn.execute("INSERT INTO companies(name, created_at) VALUES (?, ?) ON CONFLICT(name) DO NOTHING",
                 (company, stamp))
    company_id = conn.execute("SELECT id FROM companies WHERE name = ?", (company,)).fetchone()[0]
    run_id = int(conn.execute(
        "INSERT INTO runs(company_id, year, standard, level, status, owner_email, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (company_id, year, standard, level, status, owner_email, stamp, stamp)).lastrowid)
    conn.execute("INSERT INTO run_setup(run_id, first_statements, unit) VALUES (?, ?, ?)",
                 (run_id, int(first_statements), unit))
    for statement, variant in statements:
        conn.execute("INSERT INTO run_statements(run_id, statement, variant) VALUES (?, ?, ?)",
                     (run_id, statement, variant))
    # The first check results: "not assessed" until figures arrive.
    from app.catalog.lookup import run_family
    from app.checks.runner import run_checks

    run_checks(conn, run_family(conn, run_id))
    return run_id


def create_reading_run(conn: sqlite3.Connection, *, owner_email: str) -> int:
    """A run made from an upload. Company, year, standard and level stay blank
    until the Reader suggests them and the person confirms setup."""
    stamp = now()
    run_id = int(conn.execute(
        "INSERT INTO runs(status, owner_email, created_at, updated_at) VALUES ('reading', ?, ?, ?)",
        (owner_email, stamp, stamp)).lastrowid)
    conn.execute("INSERT INTO run_setup(run_id) VALUES (?)", (run_id,))
    return run_id


def open_run(conn: sqlite3.Connection, run_id: int, user: User) -> sqlite3.Row:
    """The run, if this person may open it. Raises RunNotFound otherwise."""
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None or user is None or user.disabled:
        raise RunNotFound("There is no such run.")
    return row


class CompanyNotFound(LookupError):
    """No company with that number, or none of its runs is one this person may open."""


def open_company(conn: sqlite3.Connection, company_id: int, user: User) -> sqlite3.Row:
    """The company, if this person may open one of its runs (its guidance
    follows its runs: backend-plan section 9). Raises CompanyNotFound."""
    company = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    if company is not None:
        for row in conn.execute("SELECT id FROM runs WHERE company_id = ? ORDER BY id", (company_id,)).fetchall():
            try:
                open_run(conn, row["id"], user)
                return company
            except RunNotFound:
                continue
    raise CompanyNotFound("There is no such company.")


def touch(conn: sqlite3.Connection, run_id: int) -> None:
    conn.execute("UPDATE runs SET updated_at = ? WHERE id = ?", (now(), run_id))


_RUN_SQL = (
    "SELECT r.id, c.name AS company, r.year, r.standard, r.level, r.status, r.updated_at, r.owner_email, "
    "d.filename, CASE WHEN r.status = 'failed' THEN (SELECT s.name FROM stages s WHERE s.run_id = r.id "
    "AND s.status = 'failed' AND s.name IN ('read', 'extract', 'notes') ORDER BY s.name = 'notes', s.id DESC "
    "LIMIT 1) WHEN r.status = 'stopped' AND EXISTS (SELECT 1 FROM stages s WHERE s.run_id = r.id "
    "AND s.name = 'read' AND s.status = 'stopped') THEN 'read' END AS failed_stage "
    "FROM runs r LEFT JOIN companies c ON c.id = r.company_id "
    "LEFT JOIN documents d ON d.run_id = r.id")


def run_row(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    """One run's run-list row."""
    return conn.execute(_RUN_SQL + " WHERE r.id = ?", (run_id,)).fetchone()


def run_detail(conn: sqlite3.Connection, run_id: int) -> dict:
    """What one run's screen needs beyond its run-list row (`RunDetail`, Step 5c)."""
    import json

    from app.catalog.statements import layout_label
    from app.scope.fields import statement_words

    statements = [{"statement": r["statement"], "name": statement_words(r["statement"], r["variant"]),
                   "layout": r["variant"], "layout_label": layout_label(StatementType(r["statement"]), r["variant"]),
                   "pages": json.loads(r["pages_json"])}
                  for r in conn.execute("SELECT statement, variant, pages_json FROM run_statements WHERE run_id = ? "
                                        "AND included = 1", (run_id,))]
    order = ("SOFP", "SOPL", "SOCI", "SOCF", "SOCIE")
    statements.sort(key=lambda s: order.index(s["statement"]))
    stages = [dict(r) for r in conn.execute("SELECT name, status, started_at, finished_at, error, working_on "
                                            "FROM stages WHERE run_id = ? ORDER BY id", (run_id,))]
    run = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
    failed = next((s for s in reversed(sorted(stages, key=lambda s: s["name"] != "notes")) if s["status"] == "failed"),
                  None)   # the run fails on its extract (or read) stage; a failed notes stage only when alone
    extract = next((s for s in stages if s["name"] == "extract"), None)
    question = conn.execute("SELECT id FROM scope_questions WHERE run_id = ? AND status = 'open'",
                            (run_id,)).fetchone()
    return {"statements": statements,
            "failure": {"stage": failed["name"], "sentence": failed["error"]}
            if run["status"] == run_status.FAILED and failed else None,
            "working_on": extract["working_on"] if extract and extract["status"] == "working" else None,
            "open_question_id": question["id"] if question else None,
            "redo": _open_redo(conn, run_id),
            "stages": [{k: s[k] for k in ("name", "status", "started_at", "finished_at", "error")} for s in stages]}


def _open_redo(conn: sqlite3.Connection, run_id: int) -> Optional[dict]:
    """The statement being redone and the figures kept through it, until it is finished again (`RunDetail.redo`)."""
    from app.catalog.lookup import run_family
    from app.extraction import progress
    from app.figures.redo import held

    family = run_family(conn, run_id)
    redo = progress.open_redo(conn, run_id, family.entity_scopes) if family else None
    return {"statement": redo["statement"], "kept": held(conn, run_id, redo)} if redo else None


# Deleting a run --------------------------------------------------------------

# The rules for who may delete a run, and when, are in `deleting.py`.

def run_folders(run_id: int) -> list[Path]:
    """The run's own folders, named from its number alone."""
    run_id = int(run_id)
    return [safe_path(output_dir() / "runs" / f"run-{run_id}"),
            safe_path(output_dir() / "transcripts" / f"run-{run_id}")]


def remove_run_files(run_id: int) -> None:
    """Remove the run's folders: its upload, page records and transcripts. A
    symbolic link is removed itself, never followed. What cannot be removed
    (a file open on Windows, say) is logged and left."""
    for folder in run_folders(run_id):
        if not folder.is_dir() or Path(folder).is_symlink():
            continue
        for directory, subfolders, names in os.walk(folder, topdown=False, followlinks=False):
            for name in names + [d for d in subfolders if (Path(directory) / d).is_symlink()]:
                try:
                    safe_entry_path(Path(directory) / name).unlink()
                except OSError:
                    logger.warning("Run %s: could not remove a file of the deleted run.", run_id, exc_info=True)
            for name in subfolders:
                try:
                    entry = safe_entry_path(Path(directory) / name)
                    if not entry.is_symlink():
                        entry.rmdir()
                except OSError:
                    logger.warning("Run %s: could not remove a folder of the deleted run.", run_id, exc_info=True)
        try:
            safe_entry_path(folder).rmdir()
        except OSError:
            logger.warning("Run %s: could not remove the deleted run's folder.", run_id, exc_info=True)
