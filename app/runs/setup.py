"""Confirm a run's setup (docs/api-contract.md, "Confirming the setup").

The person checks what the Reader suggested and changes what is wrong. This
module checks the confirmed values, refusing with one plain sentence, then
saves them in one transaction: the company (matched or created), the
filing, each statement's layout and whether it is included, and the notes
list. Extraction then starts from `extraction.start_extraction`.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.catalog.statements import NOT_PREPARED, VARIANTS, StatementType, layout_label
from app.db import now
from app.reading import store as reading
from app.reading.map_schema import STATEMENT_NAMES, STATEMENTS
from app.runs import extraction, status as run_status, units

logger = logging.getLogger(__name__)

MAX_NAME = 200
MAX_NOTES = 500
MAX_STATEMENT_PAGES = 10
UNITS = units.UNITS


class SetupRefused(ValueError):
    """`str()` is one plain sentence. `status` is the HTTP status to answer with."""

    def __init__(self, sentence: str, status: int = 422) -> None:
        super().__init__(sentence)
        self.status = status


@dataclass
class Confirmed:
    company: str
    year_end: str
    standard: str
    level: str
    unit: str
    statements: list[tuple[str, str, bool, list[int]]]   # (statement, layout, included, PDF pages)
    notes_included: bool
    notes: list[tuple[str, str, int, int]]    # (number, title, first page, last page)
    first_statements: bool = False            # "This year only": the company's first financial statements


def _text(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _statement_pages(raw: Any, name: str, page_count: int) -> list[int]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(type(p) is int for p in raw) or len(raw) > MAX_STATEMENT_PAGES:
        raise SetupRefused(f"Give the pages of {name.lower()} as up to {MAX_STATEMENT_PAGES} page numbers.")
    if not all(1 <= p <= page_count for p in raw):
        raise SetupRefused(f"The pages of {name.lower()} must be within the document's {page_count} pages.")
    return sorted(set(raw))


def _statements(raw: Any, standard: str, page_count: int) -> list[tuple[str, str, bool, list[int]]]:
    if not isinstance(raw, list) or not all(isinstance(s, dict) for s in raw):
        raise SetupRefused("Give each of the five statements once.")
    names = [s.get("statement") for s in raw]
    if sorted(map(str, names)) != sorted(STATEMENTS):
        raise SetupRefused("Give each of the five statements once.")
    out = []
    for item in sorted(raw, key=lambda s: STATEMENTS.index(s["statement"])):
        statement, layout, included = item["statement"], item.get("layout"), item.get("included")
        name = STATEMENT_NAMES[statement]
        if not isinstance(included, bool):
            raise SetupRefused(f"Say whether {name.lower()} is included.")
        variant = VARIANTS.get((StatementType(statement), layout)) if isinstance(layout, str) else None
        if variant is None or standard.lower() not in variant.applies_to_standard:
            label = layout_label(statement, layout) if isinstance(layout, str) else "chosen"
            raise SetupRefused(f"The {label} layout of {name.lower()} does not exist for {standard} filings, "
                               "so choose another layout.")
        if layout == NOT_PREPARED and included:
            raise SetupRefused(f"{name} is marked not printed, so switch it off or choose a layout.")
        pages = _statement_pages(item.get("pages"), name, page_count)
        if included and not pages:
            raise SetupRefused(f"Give the page {name.lower()} is printed on, or switch it off.")
        out.append((statement, layout, included, pages))
    if not any(included for _, _, included, _ in out):
        raise SetupRefused("Switch on at least one statement.")
    return out


def _page(value: Any) -> int | None:
    return value if type(value) is int else None


def _notes(raw: Any, page_count: int) -> list[tuple[str, str, int, int]]:
    if not isinstance(raw, list) or not all(isinstance(n, dict) for n in raw):
        raise SetupRefused("Give the notes as a list.")
    if len(raw) > MAX_NOTES:
        raise SetupRefused(f"The notes list holds more than {MAX_NOTES} notes.")
    out, seen = [], set()
    for item in raw:
        number, title = _text(item.get("number")), _text(item.get("title"))
        first, last = _page(item.get("first_page")), _page(item.get("last_page"))
        if not title:
            raise SetupRefused("Each note needs a title.")
        if len(title) > MAX_NAME:
            raise SetupRefused(f"Keep each note title to {MAX_NAME} characters or fewer.")
        if number and number in seen:
            raise SetupRefused(f"Note {number} is listed twice.")
        seen.add(number)
        if first is None or last is None or not 1 <= first <= last <= page_count:
            raise SetupRefused(f"Note {number or title}'s pages must be within the document's {page_count} pages, "
                               "first page first.")
        out.append((number, title, first, last))
    return out


def check(body: Any, page_count: int) -> Confirmed:
    """The confirmed setup from a request body, or SetupRefused."""
    if not isinstance(body, dict):
        raise SetupRefused("Send the setup as a set of fields.")
    company = _text(body.get("company"))
    if not company:
        raise SetupRefused("Enter the company's name.")
    if len(company) > MAX_NAME:
        raise SetupRefused("The company's name is too long.")
    year_end = body.get("year_end")
    try:
        parsed = date.fromisoformat(year_end) if isinstance(year_end, str) and len(year_end) == 10 else None
    except ValueError:
        parsed = None
    if parsed is None:
        raise SetupRefused("Enter the year end as a date.")
    standard, level, unit = body.get("standard"), body.get("level"), body.get("unit")
    if standard not in ("MFRS", "MPERS"):
        raise SetupRefused("Choose MFRS or MPERS.")
    if level not in ("Company", "Group"):
        raise SetupRefused("Choose Company or Group.")
    if unit not in UNITS:
        raise SetupRefused(units.CHOOSE)
    notes_included = body.get("notes_included", True)
    if not isinstance(notes_included, bool):
        raise SetupRefused("Say whether the notes are included.")
    first_statements = body.get("first_statements", False)
    if not isinstance(first_statements, bool):
        raise SetupRefused("Say whether the report covers this year and last year, or this year only.")
    return Confirmed(company, parsed.isoformat(), standard, level, unit, _statements(body.get("statements"), standard, page_count),
                     notes_included, _notes(body.get("notes", []), page_count), first_statements)


# Companies -----------------------------------------------------------------

def company_key(name: str) -> str:
    """The same company whatever its case, spacing or the punctuation . , ( )."""
    return " ".join(re.sub(r"[.,()]", " ", name).lower().split())


def find_company(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    """The existing company with the same name apart from case, spacing and punctuation, or None. Never creates one."""
    key = company_key(name or "")
    if not key:
        return None
    for row in conn.execute("SELECT id, name FROM companies ORDER BY id"):
        if company_key(row["name"]) == key:
            return row
    return None


def match_company(conn: sqlite3.Connection, name: str) -> tuple[int, str, bool]:
    """(id, stored name, existing) for the company, creating it when no
    company has the same name apart from case, spacing and punctuation."""
    found = find_company(conn, name)
    if found is not None:
        return int(found["id"]), found["name"], True
    company_id = int(conn.execute("INSERT INTO companies(name, created_at) VALUES (?, ?)", (name, now())).lastrowid)
    return company_id, name, False


# Saving --------------------------------------------------------------------

def _ready_to_confirm(conn: sqlite3.Connection, run: sqlite3.Row) -> None:
    status = run["status"]
    if status == "reading":
        raise SetupRefused("Reading is not finished, so the setup cannot be confirmed yet.", 409)
    if status == "failed" and (reading.stage(conn, run["id"]) or {"status": ""})["status"] == "failed":
        raise SetupRefused("Reading failed, so try again before confirming the setup.", 409)
    if status != "setup":
        raise SetupRefused("This run's setup is already confirmed.", 409)


def confirm(conn: sqlite3.Connection, run: sqlite3.Row, body: Any, page_count: int, actor_email: str) -> dict:
    """Check and save the setup of a run waiting at setup. Use inside
    `db.connect(immediate=True)`. Returns the matched company."""
    _ready_to_confirm(conn, run)
    setup = check(body, page_count)
    run_id = int(run["id"])
    conn.execute("SAVEPOINT confirm_setup")   # undone whole if the starting workbook does not fit
    company_id, company_name, existing = match_company(conn, setup.company)
    stamp = now()
    conn.execute("UPDATE runs SET company_id = ?, year = ?, standard = ?, level = ? WHERE id = ?",
                 (company_id, int(setup.year_end[:4]), setup.standard, setup.level, run_id))
    run_status.setup_confirmed(conn, run_id)
    conn.execute("INSERT INTO run_setup(run_id, unit, year_end, notes_included, first_statements) "
                 "VALUES (?, ?, ?, ?, ?) "
                 "ON CONFLICT(run_id) DO UPDATE SET unit = excluded.unit, year_end = excluded.year_end, "
                 "notes_included = excluded.notes_included, first_statements = excluded.first_statements",
                 (run_id, setup.unit, setup.year_end, int(setup.notes_included), int(setup.first_statements)))
    conn.execute("DELETE FROM run_statements WHERE run_id = ?", (run_id,))
    conn.executemany("INSERT INTO run_statements(run_id, statement, variant, included, pages_json) "
                     "VALUES (?, ?, ?, ?, ?)",
                     [(run_id, s, layout, int(on), json.dumps(pages)) for s, layout, on, pages in setup.statements])
    conn.execute("DELETE FROM run_notes WHERE run_id = ?", (run_id,))
    conn.executemany("INSERT INTO run_notes(run_id, position, number, title, first_page, last_page) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     [(run_id, i, *note) for i, note in enumerate(setup.notes)])
    conn.execute("INSERT INTO stages(run_id, name, status, started_at, finished_at) VALUES (?, 'setup', 'done', ?, ?) "
                 "ON CONFLICT(run_id, name) DO UPDATE SET status = 'done', finished_at = excluded.finished_at, "
                 "error = NULL", (run_id, stamp, stamp))
    included = [s for s, _, on, _ in setup.statements if on]
    conn.execute(
        "INSERT INTO events(run_id, source, kind, message, data_json, created_at) VALUES (?, 'setup', 'finished', ?, ?, ?)",
        (run_id, "Setup confirmed.", _event_data(setup, actor_email, existing), stamp))

    from app.catalog.lookup import run_family
    from app.checks.runner import run_checks

    from app.starting import store as starting
    from app.starting.workbook import Refused as WorkbookRefused
    from app.workbook.xlsx_cells import WorkbookUnreadable

    try:
        starting.import_at_confirm(conn, run_id)   # a starting workbook's figures, before extraction starts
    except (WorkbookRefused, WorkbookUnreadable) as exc:
        conn.execute("ROLLBACK TO confirm_setup")
        conn.execute("RELEASE confirm_setup")
        raise SetupRefused(str(exc)) from exc
    conn.execute("RELEASE confirm_setup")
    run_checks(conn, run_family(conn, run_id))   # "not assessed" until figures arrive
    extraction.start_extraction(conn, run_id)
    extraction.start_notes(conn, run_id)
    extraction.start_reports(conn, run_id)
    logger.info("Run %s: setup confirmed by a person: %s, %s, %d statement(s), %d note(s), company %s.", run_id,
                setup.standard, setup.level, len(included), len(setup.notes), "matched" if existing else "new")
    return {"id": company_id, "name": company_name, "existing": existing}


def _event_data(setup: Confirmed, actor_email: str, existing: bool) -> str:
    return json.dumps({
        "by": actor_email, "company": setup.company, "company_existing": existing, "year_end": setup.year_end,
        "standard": setup.standard, "level": setup.level, "unit": setup.unit, "notes_included": setup.notes_included,
        "first_statements": setup.first_statements,
        "statements": [{"statement": s, "layout": layout, "included": on, "pages": pages}
                       for s, layout, on, pages in setup.statements],
        "notes": len(setup.notes),
    }, ensure_ascii=False)
