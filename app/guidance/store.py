"""Guidance versions: the firm's (company_id NULL) and each company's.

Every save is a whole new version: the full list of lines, who saved it,
when and how (`typed`, `proposed` when a Reviewer's proposed line was added,
`restored` when an older version was copied forward). Nothing is changed in
place, so any version can be read and restored. A save names the version
it was based on, and a stale one is refused, so two people never overwrite
each other unseen. Refusals are `GuidanceRefused` with one plain sentence
and the HTTP status the routes answer with.

Guidance is added only by a person (decision record 3, item 6): nothing here
is called by an agent.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from app.db import now

MAX_LINES = 100
MAX_LINE = 500
STALE = "Someone else changed this guidance. Reload it and try again."


class GuidanceRefused(ValueError):
    def __init__(self, sentence: str, status: int = 422) -> None:
        super().__init__(sentence)
        self.status = status


def _scope(company_id: Optional[int]) -> tuple[str, list]:
    return ("company_id = ?", [company_id]) if company_id is not None else ("company_id IS NULL", [])


def latest_row(conn: sqlite3.Connection, company_id: Optional[int]) -> Optional[sqlite3.Row]:
    where, params = _scope(company_id)
    return conn.execute(f"SELECT * FROM guidance_versions WHERE {where} ORDER BY version DESC LIMIT 1",
                        params).fetchone()


def _public(row: Optional[sqlite3.Row], company_id: Optional[int]) -> dict:
    if row is None:
        return {"company_id": company_id, "version": 0, "lines": [], "saved_by": None, "saved_at": None,
                "source": None, "comment_id": None, "restored_from": None}
    return {"company_id": row["company_id"], "version": row["version"], "lines": json.loads(row["lines_json"]),
            "saved_by": row["saved_by"], "saved_at": row["saved_at"], "source": row["source"],
            "comment_id": row["comment_id"], "restored_from": row["restored_from"]}


def latest(conn: sqlite3.Connection, company_id: Optional[int]) -> dict:
    """The guidance now: version 0 with no lines when none was ever saved."""
    return _public(latest_row(conn, company_id), company_id)


def versions(conn: sqlite3.Connection, company_id: Optional[int]) -> list[dict]:
    """Every version, newest first, without its lines."""
    where, params = _scope(company_id)
    return [{"version": r["version"], "saved_by": r["saved_by"], "saved_at": r["saved_at"], "source": r["source"],
             "comment_id": r["comment_id"], "restored_from": r["restored_from"],
             "line_count": len(json.loads(r["lines_json"]))}
            for r in conn.execute(f"SELECT * FROM guidance_versions WHERE {where} ORDER BY version DESC", params)]


def version(conn: sqlite3.Connection, company_id: Optional[int], number: Any) -> dict:
    """One version. Version 0 is the empty guidance before the first save, so
    the first line ever added can be undone by restoring it."""
    if number == 0 and type(number) is int:
        return _public(None, company_id)
    where, params = _scope(company_id)
    row = conn.execute(f"SELECT * FROM guidance_versions WHERE {where} AND version = ?",
                       [*params, number]).fetchone() if type(number) is int else None
    if row is None:
        raise GuidanceRefused("There is no such version of this guidance.", 404)
    return _public(row, company_id)


def clean_lines(raw: Any) -> list[str]:
    """The lines as saved: spacing tidied, blank lines left out."""
    if not isinstance(raw, list) or not all(isinstance(line, str) for line in raw):
        raise GuidanceRefused("Give the guidance as a list of lines of text.")
    lines = [" ".join(line.split()) for line in raw]
    lines = [line for line in lines if line]
    if len(lines) > MAX_LINES:
        raise GuidanceRefused(f"Keep guidance to {MAX_LINES} lines or fewer.")
    if any(len(line) > MAX_LINE for line in lines):
        raise GuidanceRefused(f"Keep each guidance line to {MAX_LINE} characters or fewer.")
    if len(set(lines)) != len(lines):
        raise GuidanceRefused("Each guidance line appears once.")
    return lines


def _based_on(conn: sqlite3.Connection, company_id: Optional[int], based_on: Any) -> int:
    if type(based_on) is not int or based_on < 0:
        raise GuidanceRefused("Say which version of the guidance this change was based on.")
    current = latest(conn, company_id)["version"]
    if based_on != current:
        raise GuidanceRefused(STALE, 409)
    return current


def _insert(conn: sqlite3.Connection, company_id: Optional[int], number: int, lines: list[str], email: str,
            source: str, comment_id: Optional[int] = None, restored_from: Optional[int] = None) -> dict:
    try:
        conn.execute("INSERT INTO guidance_versions(company_id, version, lines_json, saved_by, saved_at, source, "
                     "comment_id, restored_from) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (company_id, number, json.dumps(lines, ensure_ascii=False), email, now(), source, comment_id,
                      restored_from))
    except sqlite3.IntegrityError as exc:   # another save took this version number first
        raise GuidanceRefused(STALE, 409) from exc
    return latest(conn, company_id)


def save(conn: sqlite3.Connection, company_id: Optional[int], body: Any, email: str) -> dict:
    """Save typed guidance as a new version. Use inside `db.connect(immediate=True)`."""
    body = body if isinstance(body, dict) else {}
    current = _based_on(conn, company_id, body.get("based_on"))
    lines = clean_lines(body.get("lines"))
    if lines == latest(conn, company_id)["lines"]:
        raise GuidanceRefused("This is the guidance as it is now, so there is nothing to save.")
    return _insert(conn, company_id, current + 1, lines, email, "typed")


def restore(conn: sqlite3.Connection, company_id: Optional[int], body: Any, email: str) -> dict:
    """Copy an older version forward as a new version, so nothing is lost."""
    body = body if isinstance(body, dict) else {}
    current = _based_on(conn, company_id, body.get("based_on"))
    older = version(conn, company_id, body.get("version"))
    if older["version"] == current:
        raise GuidanceRefused("This version is the guidance now, so there is nothing to restore.")
    saved = _insert(conn, company_id, current + 1, older["lines"], email, "restored", restored_from=older["version"])
    if company_id is not None:
        _reopen_proposals(conn, company_id, older["version"], set(older["lines"]))
    return saved


def _reopen_proposals(conn: sqlite3.Connection, company_id: int, restored: int, lines: set[str]) -> None:
    """A proposed line taken out again by a restore (the Undo of "Add to guidance") can be added again."""
    for c in conn.execute("SELECT c.id, c.proposed_guidance FROM comments c JOIN runs r ON r.id = c.run_id "
                          "WHERE r.company_id = ? AND c.guidance_status = 'added' AND c.guidance_version > ?",
                          (company_id, restored)).fetchall():
        if c["proposed_guidance"] not in lines:
            conn.execute("UPDATE comments SET guidance_status = NULL, guidance_version = NULL, updated_at = ? "
                         "WHERE id = ?", (now(), c["id"]))


def add_proposed(conn: sqlite3.Connection, company_id: int, comment: sqlite3.Row, based_on: Any, email: str
                 ) -> dict:
    """Add a comment's proposed line to the company's guidance, as a new version."""
    line = " ".join((comment["proposed_guidance"] or "").split())
    if not line or comment["scope"] != "company":
        raise GuidanceRefused("This comment has no proposed guidance line.", 409)
    if comment["status"] not in ("answered", "accepted"):
        raise GuidanceRefused("This change was undone, so its guidance line cannot be added.", 409)
    if comment["guidance_status"] == "added":
        raise GuidanceRefused("This proposed line is already in the company's guidance.", 409)
    if comment["guidance_status"] == "dismissed":
        raise GuidanceRefused("This proposed line was dismissed.", 409)
    current = latest(conn, company_id)
    if based_on is not None:
        _based_on(conn, company_id, based_on)
    lines = current["lines"]
    if line in lines:
        raise GuidanceRefused("This line is already in the company's guidance.", 409)
    lines = clean_lines([*lines, line])
    saved = _insert(conn, company_id, current["version"] + 1, lines, email, "proposed", comment_id=comment["id"])
    conn.execute("UPDATE comments SET guidance_status = 'added', guidance_version = ?, updated_at = ? WHERE id = ?",
                 (saved["version"], now(), comment["id"]))
    return saved


def dismiss_proposed(conn: sqlite3.Connection, comment: sqlite3.Row) -> None:
    if not comment["proposed_guidance"]:
        raise GuidanceRefused("This comment has no proposed guidance line.", 409)
    if comment["guidance_status"] == "added":
        raise GuidanceRefused("This proposed line is already in the company's guidance, so restore the version "
                              "before it instead.", 409)
    conn.execute("UPDATE comments SET guidance_status = 'dismissed', updated_at = ? WHERE id = ?",
                 (now(), comment["id"]))
