"""What "scope" is: the fields of a run's setup a question may be about, the
values each may take, the words a choice shows, and the setup questions the
setup screen shows for the Reader's unsure suggestions.

Scope is what setup holds: the standard, the level, the year end, the unit,
and each statement's layout or whether it is printed. Every other doubt is
settled by the agent and shown for review (decision record 3, item 1).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Mapping, Optional

from app.catalog.statements import NOT_PREPARED, StatementType, layout_choices, layout_label, printed_layouts
from app.reading.map_schema import STATEMENTS
from app.runs import units

FIELDS = ("standard", "level", "year_end", "unit", "layout")
# A run-time question's "not printed" choice: the same name setup uses for a statement not printed.
NOT_PRINTED = NOT_PREPARED
STANDARDS = ("MFRS", "MPERS")
LEVELS = ("Company", "Group")
UNITS = units.UNITS
# What the agents and the questions call each statement.
STATEMENT_WORDS = {"SOFP": "statement of financial position", "SOPL": "statement of profit or loss",
                   "SOCI": "statement of comprehensive income", "SOCF": "statement of cash flows",
                   "SOCIE": "statement of changes in equity"}
# The one layout that changes a statement's name: MPERS's statement of retained earnings files in SOCIE's place.
LAYOUT_WORDS = {("SOCIE", "SoRE"): "statement of retained earnings"}
# The order the figures agent fills them in and names them.
ORDER = ("SOFP", "SOPL", "SOCI", "SOCIE", "SOCF")
# A setup change to one of these refiles every statement; a layout change refiles one.
WHOLE_RUN = ("standard", "level", "year_end", "unit")


def statement_words(statement: str, layout: Optional[str] = None) -> str:
    """One statement as a person names it, by its layout where the layout renames it (SoRE)."""
    code = getattr(statement, "value", statement)
    return LAYOUT_WORDS.get((code, layout or ""), STATEMENT_WORDS.get(code, code))


def names_of(statements, layouts: Optional[Mapping] = None) -> str:
    """Statements as a person names them: "statement of financial position and statement of cash flows".
    `layouts` maps a statement to its layout (a run family's `variants`), so SoRE is named as printed."""
    layouts = {getattr(k, "value", k): v for k, v in (layouts or {}).items()}
    words = [statement_words(s, layouts.get(getattr(s, "value", s))) for s in statements]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def field_words(field: str, statement: Optional[str] = None) -> str:
    if field == "layout":
        return f"the layout of the {STATEMENT_WORDS.get(statement or '', 'statement')}"
    return {"standard": "the standard", "level": "the level", "year_end": "the year end",
            "unit": "the unit"}[field]


def values(field: str, statement: Optional[str] = None) -> Optional[tuple[str, ...]]:
    """The values a field may take, or None for a date (the year end)."""
    if field == "standard":
        return STANDARDS
    if field == "level":
        return LEVELS
    if field == "unit":
        return UNITS
    if field == "layout":
        return (*printed_layouts(StatementType(statement)), NOT_PRINTED)
    return None


def valid(field: str, value: str, statement: Optional[str] = None) -> bool:
    allowed = values(field, statement)
    if allowed is not None:
        return value in allowed
    try:
        return len(value) == 10 and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def label(field: str, value: str, statement: Optional[str] = None) -> str:
    if field == "unit":
        return units.unit_words(value)
    if field == "layout":
        return "Not printed" if value == NOT_PRINTED else layout_label(StatementType(statement), value)
    return value


def effect(field: str, value: str, statement: Optional[str] = None) -> str:
    """One line on what follows when this value is chosen at setup."""
    if field == "standard":
        return f"Files with the {value} templates"
    if field == "level":
        return "Files the Company figures only" if value == "Company" else "Files Group and Company figures"
    if field == "unit":
        return f"Figures are filed as printed, in {label(field, value)}"
    if value == NOT_PRINTED:
        return "Nothing is filed for this statement"
    return f"Uses the {label(field, value, statement).lower()} template"


def setup_value(conn: sqlite3.Connection, run_id: int, field: str, statement: Optional[str] = None) -> str:
    """The run's confirmed value for a field, as a question's choice holds it."""
    if field in ("standard", "level"):
        return conn.execute(f"SELECT {field} FROM runs WHERE id = ?", (run_id,)).fetchone()[0] or ""
    if field in ("unit", "year_end"):
        row = conn.execute(f"SELECT {field} FROM run_setup WHERE run_id = ?", (run_id,)).fetchone()
        return (row[0] if row else None) or ""
    row = conn.execute("SELECT variant, included FROM run_statements WHERE run_id = ? AND statement = ?",
                       (run_id, statement)).fetchone()
    if row is None or not row["included"] or row["variant"] == NOT_PREPARED:
        return NOT_PRINTED
    return row["variant"]


def setup_questions(setup: dict) -> list[dict]:
    """The setup screen's question cards: one per unsure suggestion of the
    standard, the level, the unit or a statement's layout, with the allowed
    choices and the suggested one. The year end and the company's name are
    typed, so they have no card."""
    out = []
    standard = setup["standard"]["value"] if setup["standard"]["value"] in STANDARDS else None
    questions = {"standard": "Which standard applies?", "level": "Is this a Company or a Group filing?",
                 "unit": "Are the amounts in RM, RM thousands or RM millions?"}
    for field, question in questions.items():
        finding = setup[field]
        if not finding.get("unsure"):
            continue
        out.append({"field": field, "statement": None, "question": question, "reason": finding.get("reason"),
                    "pages": finding.get("pages") or [],
                    "choices": [{"value": v, "label": label(field, v), "effect": effect(field, v),
                                 "suggested": v == finding.get("value")} for v in values(field)]})
    for st in setup["statements"]:
        if not st.get("unsure"):
            continue
        statement = st["statement"]
        out.append({"field": "layout", "statement": statement,
                    "question": f"Which layout does the {STATEMENT_WORDS[statement]} use?",
                    "reason": st.get("reason"), "pages": st.get("pages") or [],
                    "choices": layout_card_choices(statement, standard or "MFRS", st)})
    first = setup.get("first_statements") or {}
    if first.get("value") == "yes":
        # The Reader found no figures for last year. It only suggests: the person says which it is.
        out.append({"field": "period", "statement": None,
                    "question": "No figures for last year were found. Are these the company's first financial "
                                "statements?",
                    "reason": first.get("reason"), "pages": first.get("pages") or [],
                    "choices": [{"value": "only", "label": "Yes, this year only",
                                 "effect": "Files this year's figures only", "suggested": True},
                                {"value": "both", "label": "No, this year and last year",
                                 "effect": "Files this year's and last year's figures", "suggested": False}]})
    return out


def layout_card_choices(statement: str, standard: str, suggestion: dict) -> list[dict]:
    """A layout card's choices: exactly what `POST .../setup` accepts for the
    statement under the standard. Each says what it sets on the statement:
    `layout` and `included`. Where "not printed" is a layout of its own
    (comprehensive income's NotPrepared), it is one of the layouts; for any
    other statement it is `included` false, keeping the layout as it is."""
    suggested = suggestion["layout"] if suggestion.get("found") else None
    out = []
    for choice in layout_choices(StatementType(statement))[standard]:
        printed = choice["value"] != NOT_PREPARED
        out.append({"value": choice["value"], "label": choice["label"], "layout": choice["value"],
                    "included": printed, "effect": effect("layout", choice["value"], statement),
                    "suggested": choice["value"] == (suggested if suggestion.get("found") else NOT_PREPARED)})
    if not any(c["value"] == NOT_PREPARED for c in out):
        keep = suggested or (out[0]["layout"] if out else None)
        out.append({"value": None, "label": "Not printed", "layout": keep, "included": False,
                    "effect": effect("layout", NOT_PREPARED, statement), "suggested": not suggestion.get("found")})
    return out


def current_setup(conn: sqlite3.Connection, run_id: int) -> dict:
    """The confirmed setup as a `ConfirmedSetup` body, so a change can go
    through the same check as confirming the setup."""
    run = conn.execute("SELECT r.standard, r.level, c.name AS company, s.unit, s.year_end, s.notes_included, "
                       "s.first_statements "
                       "FROM runs r LEFT JOIN companies c ON c.id = r.company_id "
                       "LEFT JOIN run_setup s ON s.run_id = r.id WHERE r.id = ?", (run_id,)).fetchone()
    rows = {r["statement"]: r for r in conn.execute(
        "SELECT statement, variant, included, pages_json FROM run_statements WHERE run_id = ?", (run_id,))}
    statements = []
    for statement in STATEMENTS:
        r = rows.get(statement)
        statements.append({"statement": statement, "layout": r["variant"] if r else NOT_PREPARED,
                           "included": bool(r and r["included"]),
                           "pages": json.loads(r["pages_json"]) if r else []})
    notes = [{"number": n["number"], "title": n["title"], "first_page": n["first_page"],
              "last_page": n["last_page"]} for n in conn.execute(
        "SELECT number, title, first_page, last_page FROM run_notes WHERE run_id = ? ORDER BY position", (run_id,))]
    return {"company": run["company"], "year_end": run["year_end"], "standard": run["standard"],
            "level": run["level"], "unit": run["unit"], "statements": statements,
            "notes_included": bool(run["notes_included"]), "notes": notes,
            "first_statements": bool(run["first_statements"])}
