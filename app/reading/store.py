"""Reading's rows: page contents, the read stage, the document map and the
suggested setup (docs/api-contract.md, "Reading")."""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

from app.db import now
from app.catalog.statements import NOT_PREPARED, layout_choices
from app.documents import store as documents
from app.reading.map_schema import STATEMENTS
from app.runs import status as run_status

STAGE = "read"


class NoMap(LookupError):
    def __init__(self) -> None:
        super().__init__("The document has not been mapped yet.")


class NothingToRetry(ValueError):
    def __init__(self) -> None:
        super().__init__("Reading has not failed, so there is nothing to try again.")


class NothingToStop(ValueError):
    def __init__(self) -> None:
        super().__init__("Reading is not running, so there is nothing to stop.")


STOPPED_SENTENCE = "Stopped on request; the pages read so far are kept."


def _document_id(conn: sqlite3.Connection, run_id: int) -> int:
    return int(documents.document_row(conn, run_id)["id"])


# Pages ---------------------------------------------------------------------

def pages_to_read(conn: sqlite3.Connection, run_id: int) -> list[int]:
    """Pages with no stored content yet: never read, or failed last time."""
    return [r["page"] for r in conn.execute(
        "SELECT page FROM pages WHERE document_id = ? AND content_json IS NULL ORDER BY page",
        (_document_id(conn, run_id),))]


def save_page(conn: sqlite3.Connection, run_id: int, page: int, content: Optional[dict],
              error: Optional[str]) -> None:
    conn.execute(
        "UPDATE pages SET content_json = ?, read_at = ?, read_error = ? WHERE document_id = ? AND page = ?",
        (json.dumps(content, ensure_ascii=False) if content is not None else None, now(),
         None if content is not None else error, _document_id(conn, run_id), page))


def page_contents(conn: sqlite3.Connection, run_id: int) -> dict[int, dict]:
    """{PDF page: content} for every page read (blank pages included)."""
    return {r["page"]: json.loads(r["content_json"]) for r in conn.execute(
        "SELECT page, content_json FROM pages WHERE document_id = ? AND content_json IS NOT NULL ORDER BY page",
        (_document_id(conn, run_id),))}


def map_pages(conn: sqlite3.Connection, run_id: int) -> list[dict]:
    """`MapPage` rows."""
    out = []
    for r in conn.execute("SELECT page, content_json, read_error FROM pages WHERE document_id = ? ORDER BY page",
                          (_document_id(conn, run_id),)):
        content = json.loads(r["content_json"]) if r["content_json"] else None
        if content is None:
            out.append({"page": r["page"], "folio": None, "rotation": 0, "kind": None, "title": "",
                        "status": "failed" if r["read_error"] else "waiting", "reason": r["read_error"]})
            continue
        out.append({"page": r["page"], "folio": content.get("folio"), "rotation": content.get("rotation", 0),
                    "kind": content.get("kind"), "title": content.get("title", ""),
                    "status": "blank" if content.get("blank") else "read", "reason": None})
    return out


# The stage -----------------------------------------------------------------

def stage(conn: sqlite3.Connection, run_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM stages WHERE run_id = ? AND name = ?", (run_id, STAGE)).fetchone()


def stage_working(conn: sqlite3.Connection, run_id: int) -> None:
    conn.execute("UPDATE stages SET status = 'working', started_at = ?, finished_at = NULL, error = NULL "
                 "WHERE run_id = ? AND name = ?", (now(), run_id, STAGE))
    run_status.reading_started(conn, run_id)


def stage_done(conn: sqlite3.Connection, run_id: int) -> None:
    conn.execute("UPDATE stages SET status = 'done', finished_at = ?, error = NULL WHERE run_id = ? AND name = ?",
                 (now(), run_id, STAGE))
    run_status.reading_done(conn, run_id)


def stage_failed(conn: sqlite3.Connection, run_id: int, sentence: str) -> None:
    conn.execute("UPDATE stages SET status = 'failed', finished_at = ?, error = ? WHERE run_id = ? AND name = ?",
                 (now(), sentence, run_id, STAGE))
    run_status.reading_failed(conn, run_id)


def stage_stopped(conn: sqlite3.Connection, run_id: int) -> None:
    """A person stopped the reading: the stage ends `stopped`, keeping every page read."""
    conn.execute("UPDATE stages SET status = 'stopped', finished_at = ?, error = ? WHERE run_id = ? AND name = ?",
                 (now(), STOPPED_SENTENCE, run_id, STAGE))
    run_status.reading_stopped(conn, run_id)


def stop_requested(conn: sqlite3.Connection, run_id: int) -> bool:
    row = stage(conn, run_id)
    return bool(row and row["stop_requested"])


def request_stop(conn: sqlite3.Connection, run_id: int) -> bool:
    """Ask the reading to stop. Use inside `db.connect(immediate=True)`. A job still waiting to start is
    stopped at once; a working one starts no new page and no new step of the Reader, so it stops within the
    model calls already under way. Returns True when it stopped at once. Raises NothingToStop."""
    _document_id(conn, run_id)
    row = stage(conn, run_id)
    if row is None or row["status"] not in ("waiting", "working"):
        raise NothingToStop()
    conn.execute("UPDATE stages SET stop_requested = 1 WHERE id = ?", (row["id"],))
    if row["status"] == "working":
        return False
    waiting = conn.execute("UPDATE jobs SET status = 'done', last_error = 'Stopped before it started.', "
                           "finished_at = ? WHERE run_id = ? AND kind = ? AND status IN ('queued', 'retry')",
                           (now(), run_id, documents.READ_JOB)).rowcount
    if not waiting:
        return False   # the worker has just taken it: it sees the request when it starts
    stage_stopped(conn, run_id)
    conn.execute("INSERT INTO events(run_id, source, kind, message, created_at) VALUES (?, 'reading', 'stopped', ?, ?)",
                 (run_id, "Reading stopped on request before it started.", now()))
    return True


def retry(conn: sqlite3.Connection, run_id: int) -> None:
    """Start a failed or stopped reading again, in the same stage row. Use inside
    `db.connect(immediate=True)`. Pages that failed last time count as
    waiting again, since they are read again; pages already read are kept."""
    document_id = _document_id(conn, run_id)
    row = stage(conn, run_id)
    if row is None or row["status"] not in ("failed", "stopped"):
        raise NothingToRetry()
    conn.execute("UPDATE pages SET read_error = NULL WHERE document_id = ? AND content_json IS NULL", (document_id,))
    documents.start_reading(conn, run_id)


def progress(conn: sqlite3.Connection, run_id: int) -> dict:
    """`ReadProgress`."""
    document_id = _document_id(conn, run_id)
    counts = conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(content_json IS NOT NULL AND json_extract(content_json, '$.blank') IS NULL) AS read, "
        "SUM(json_extract(content_json, '$.blank') = 1) AS blank, "
        "SUM(content_json IS NULL AND read_error IS NOT NULL) AS failed "
        "FROM pages WHERE document_id = ?", (document_id,)).fetchone()
    total, read, blank, failed = (int(counts[k] or 0) for k in ("total", "read", "blank", "failed"))
    row = stage(conn, run_id)
    saved = conn.execute("SELECT 1 FROM document_maps WHERE run_id = ?", (run_id,)).fetchone() is not None
    return {"status": row["status"] if row else "waiting", "started_at": row["started_at"] if row else None,
            "finished_at": row["finished_at"] if row else None, "error": row["error"] if row else None,
            "stop_requested": bool(row and row["stop_requested"]),
            "pages": {"total": total, "read": read, "blank": blank, "failed": failed,
                      "waiting": total - read - blank - failed},
            "map_saved": saved}


# The map -------------------------------------------------------------------

def save_map(conn: sqlite3.Connection, run_id: int, doc_map: dict, open_points: list[str]) -> None:
    conn.execute(
        "INSERT INTO document_maps(run_id, map_json, open_points_json, saved_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(run_id) DO UPDATE SET map_json = excluded.map_json, "
        "open_points_json = excluded.open_points_json, saved_at = excluded.saved_at",
        (run_id, json.dumps(doc_map, ensure_ascii=False), json.dumps(open_points, ensure_ascii=False), now()))


def saved_map(conn: sqlite3.Connection, run_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM document_maps WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    doc_map = json.loads(row["map_json"])
    order = {s: i for i, s in enumerate(STATEMENTS)}
    doc_map["statements"].sort(key=lambda st: order[st["statement"]])
    return {"saved_at": row["saved_at"], **doc_map, "open_points": json.loads(row["open_points_json"])}


def document_map(conn: sqlite3.Connection, run_id: int) -> dict:
    """`DocumentMap`, or NoDocument / NoMap."""
    documents.document_row(conn, run_id)
    doc_map = saved_map(conn, run_id)
    if doc_map is None:
        raise NoMap()
    return {**doc_map, "pages": map_pages(conn, run_id)}


def suggested_setup(conn: sqlite3.Connection, run_id: int) -> dict:
    """`SuggestedSetup`, or NoDocument / NoMap."""
    doc_map = document_map(conn, run_id)
    year_end = doc_map["year_end"]["value"]
    statements = []
    for st in doc_map["statements"]:
        layout = st["layout"] if st["found"] else (NOT_PREPARED if st["statement"] == "SOCI" else None)
        statements.append({"statement": st["statement"], "found": st["found"], "pages": st["pages"], "layout": layout,
                           "layouts": layout_choices(st["statement"]), "reason": st["reason"],
                           "unsure": st["unsure"]})
    from app.scope.fields import setup_questions

    setup = {"company": doc_map["company"], "year_end": doc_map["year_end"],
             "year": int(year_end[:4]) if year_end else None, "standard": doc_map["standard"],
             "level": doc_map["level"], "unit": doc_map["unit"], "statements": statements,
             # None for a map saved before the Reader looked for a prior year.
             "first_statements": doc_map.get("first_statements")}
    setup["questions"] = setup_questions(setup)   # a question card for each unsure suggestion (step 5b)
    return setup
