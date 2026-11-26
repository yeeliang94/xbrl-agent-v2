"""The one SQLite database. `schema.sql` is applied on start-up.

Use `with db.connect() as conn:` for a block of work: it commits on success,
rolls back on error and always closes.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from app.db import location
from app.utils.paths import safe_path

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def db_path() -> Path:
    """`<output folder>/xbrl.db`, or the container's own disk on Azure (`location.py`)."""
    return safe_path(location.live_path())


def now() -> str:
    """Current UTC time as ISO 8601 text with a Z, the format every table uses."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _open() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def connect(*, immediate: bool = False) -> Iterator[sqlite3.Connection]:
    """A connection inside one transaction. `immediate=True` takes the write
    lock at the start, for read-then-write steps that must not interleave."""
    conn = _open()
    try:
        conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create every table that does not exist yet, then bring an older
    database's tables up to date."""
    schema = SCHEMA_FILE.read_text(encoding="utf-8")
    conn = _open()
    try:
        conn.executescript(schema)
        _rebuild_runs_if_stale(conn, schema)
        _add_missing_columns(conn)
    finally:
        conn.close()


# Columns added to a table after it first shipped: (table, column, definition).
_ADDED_COLUMNS = (
    ("pages", "read_error", "TEXT"),
    ("run_setup", "year_end", "TEXT"),
    ("run_setup", "notes_included", "INTEGER NOT NULL DEFAULT 1"),
    ("run_statements", "included", "INTEGER NOT NULL DEFAULT 1"),
    ("run_statements", "pages_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("figure_history", "comment_ids_json", "TEXT"),
    ("comments", "guidance_status", "TEXT CHECK (guidance_status IN ('added', 'dismissed'))"),
    ("comments", "guidance_version", "INTEGER"),
    ("events", "pages_json", "TEXT"),
    ("stages", "working_on", "TEXT"),
    ("stages", "stop_requested", "INTEGER NOT NULL DEFAULT 0"),
    ("comments", "note_id", "INTEGER"),
    ("comments", "note_part_json", "TEXT"),
    ("note_reports", "after_block", "TEXT"),
    ("note_reports", "status", "TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'settled'))"),
    ("note_reports", "settled_by", "TEXT"),
    ("note_reports", "settled_at", "TEXT"),
    ("note_history", "settled_reports_json", "TEXT"),
    ("comments", "report_id", "INTEGER"),
    ("fills", "investigation", "TEXT CHECK (investigation IN ('queued', 'working', 'done', 'failed'))"),
    ("fills", "investigation_error", "TEXT"),
    ("model_calls", "agent", "TEXT"),
    ("documents", "kind", "TEXT NOT NULL DEFAULT 'pdf' CHECK (kind IN ('pdf', 'word', 'excel'))"),
    ("documents", "source_path", "TEXT"),
    ("documents", "source_json", "TEXT"),
)


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    for table, column, definition in _ADDED_COLUMNS:
        present = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in present:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _rebuild_runs_if_stale(conn: sqlite3.Connection, schema: str) -> None:
    """Bring an older `runs` or `stages` table up to schema.sql. SQLite cannot
    change a column's NOT NULL or CHECK in place, so the table is rebuilt from
    schema.sql's own definition.

    Step 3a: a run made from an upload has no company, standard or level until
    setup, so those are no longer NOT NULL. Step 3c: the status `ready` is
    added and `reviewed` is dropped (no run could have reached it; one that
    somehow did is copied as `in_review`). Step 5b: the run status
    `needs_answer` and the stage status `asking` are added."""
    columns = {row["name"]: row["notnull"] for row in conn.execute("PRAGMA table_info(runs)")}
    stored = _stored_sql(conn, "runs")
    current = "'needs_answer'" in stored and "'reviewed'" not in stored
    if columns.get("company_id") or not current:
        _rebuild(conn, schema, "runs", list(columns), r"CREATE INDEX IF NOT EXISTS ix_runs_updated[^;]*;",
                 {"status": "CASE status WHEN 'reviewed' THEN 'in_review' ELSE status END"})
    if "'asking'" not in _stored_sql(conn, "stages"):
        names = [row["name"] for row in conn.execute("PRAGMA table_info(stages)")]
        _rebuild(conn, schema, "stages", names, None, {})


def _stored_sql(conn: sqlite3.Connection, table: str) -> str:
    stored = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    return stored["sql"] if stored is not None else ""


def _rebuild(conn: sqlite3.Connection, schema: str, table: str, columns: list[str], index_pattern, picks: dict
             ) -> None:
    """SQLite's documented procedure: new table, copy, drop, rename, with
    foreign keys off so the drop cascades nothing and other tables keep
    pointing at the table."""
    definition = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \(.*?\n\);", schema, re.S).group(0)
    index = re.search(index_pattern, schema).group(0) if index_pattern else None
    names = ", ".join(columns)
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(definition.replace(f"IF NOT EXISTS {table} (", f"{table}_new (", 1))
        chosen = ", ".join(picks.get(c, c) for c in columns)
        conn.execute(f"INSERT INTO {table}_new ({names}) SELECT {chosen} FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
        if index:
            conn.execute(index)
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeError(f"Rebuilding the {table} table broke a link between tables.")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
