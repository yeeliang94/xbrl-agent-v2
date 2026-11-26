"""The run list, one page at a time: search, filters and paging, all in SQL.

Rebuilt from v1 `api/runs.py` (115-180), which filtered and paged on the
server too. A filter the route does not know is refused with one plain
sentence (`ListRefused`), never ignored, so a mistyped filter cannot show a
longer list than was asked for.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.runs import status as run_status
from app.runs.store import _RUN_SQL

PER_PAGE = 25
MAX_PER_PAGE = 100
MAX_SEARCH = 200
# "Working": a job is running for the run, so it cannot be deleted yet.
WORKING = (run_status.READING, run_status.EXTRACTING, run_status.CORRECTING)
STATUSES = ("reading", "setup", "ready", "extracting", "needs_answer", "in_review", "correcting", "filed",
            "failed", "stopped")
STANDARDS = ("MFRS", "MPERS")


class ListRefused(ValueError):
    """A filter the list does not have. `str()` is one plain sentence."""


@dataclass
class Filters:
    q: str = ""                           # in the company's name or the file's name, any case
    status: str = ""                      # one status, or "working"
    standard: str = ""
    updated_since: str = ""               # an ISO time; runs updated at or after it
    owner_email: str = ""                 # "Mine"


def _since(text: str) -> str:
    """The time in the database's own form (UTC, as `db.now`), so text compares as time."""
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        raise ListRefused("Give the earliest update time as a date and time.") from None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _where(filters: Filters) -> tuple[str, list]:
    clauses, params = [], []
    q = " ".join(filters.q.split())[:MAX_SEARCH]
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        clauses.append("(c.name LIKE ? ESCAPE '\\' OR d.filename LIKE ? ESCAPE '\\')")
        params += [like, like]
    if filters.status == "working":
        clauses.append(f"r.status IN ({', '.join('?' * len(WORKING))})")
        params += WORKING
    elif filters.status:
        if filters.status not in STATUSES:
            raise ListRefused("Choose a status from the list.")
        clauses.append("r.status = ?")
        params.append(filters.status)
    if filters.standard:
        if filters.standard not in STANDARDS:
            raise ListRefused("Choose MFRS or MPERS.")
        clauses.append("r.standard = ?")
        params.append(filters.standard)
    if filters.updated_since:
        clauses.append("r.updated_at >= ?")
        params.append(_since(filters.updated_since))
    if filters.owner_email:
        clauses.append("r.owner_email = ?")
        params.append(filters.owner_email)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params


def page_of_runs(conn: sqlite3.Connection, filters: Filters, page: int = 0,
                 per_page: int = PER_PAGE) -> tuple[list[sqlite3.Row], int, int]:
    """(rows, total, page): the runs that match, newest first. A page past the
    end gives the last page, so a list that shrank still shows something."""
    where, params = _where(filters)
    total = conn.execute(
        "SELECT COUNT(*) FROM runs r LEFT JOIN companies c ON c.id = r.company_id "
        "LEFT JOIN documents d ON d.run_id = r.id" + where, params).fetchone()[0]
    page = max(0, min(page, (total - 1) // per_page if total else 0))
    rows = conn.execute(_RUN_SQL + where + " ORDER BY r.updated_at DESC, r.id DESC LIMIT ? OFFSET ?",
                        [*params, per_page, page * per_page]).fetchall()
    return rows, int(total), page


def filters_from(q: Optional[str], status: Optional[str], standard: Optional[str], updated_since: Optional[str],
                 owner_email: str) -> Filters:
    return Filters(q or "", status or "", standard or "", updated_since or "", owner_email)
