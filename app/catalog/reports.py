"""The three reports SSM files beside the statements, and their fields.

Copied from v1 `reports/registry.py`. Each report's fields come from its
taxonomy presentation role (directors' report 120000, statement by
directors 120100, auditors' report 130000): every reportable concept, in
role order, with its kind from its data type. A text block is the report's
rich-text narrative ("html"), a date item a date, a type with an
enumeration in the foundation schema a choice from that list, anything else
plain text. Identity numbers are text: they are copied as printed.

The narrative row of each report template joins the notes catalogue
(`notes_nodes`), as the prose notes do, so the note renderer and the note
fill handle it (`report_note_fields`). The report's other fields live only
here and in `report_fields` (`app/reports/store.py`).

Changes from v1: the taxonomy walk is `app.catalog.taxonomy_walk`, the row
of each field is checked against the template's label column instead of
assumed, and each field has a short id for the agent (`DIR-7`: the report's
code and the template row).
"""
from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import openpyxl

from app.catalog.note_fields import NoteField
from app.catalog.notes_parser import NotesNode
from app.catalog.parser import derive_template_id, mint_uuid
from app.catalog.statements import LEVELS, STANDARDS, TAXONOMY_DIR, TEMPLATE_DIRS
from app.catalog.taxonomy import taxonomy_registry
from app.catalog.taxonomy_walk import walk_role_for_taxonomy
from app.utils.paths import safe_path

# report: (name, taxonomy role, template file and sheet name, short code)
REPORTS: dict[str, tuple[str, str, str, str]] = {
    "DIRECTORS_REPORT": ("Directors' report", "120000", "Report-Directors", "DIR"),
    "STATEMENT_BY_DIRECTORS": ("Statement by directors", "120100", "Report-StatementByDirectors", "SBD"),
    "AUDITORS_REPORT": ("Auditors' report", "130000", "Report-Auditors", "AUD"),
}
# The Reader's section kinds (`app/reading/map_schema.SectionKind`) for each report.
SECTION_KINDS: dict[str, str] = {
    "directors_report": "DIRECTORS_REPORT",
    "statement_by_directors": "STATEMENT_BY_DIRECTORS",
    "auditors_report": "AUDITORS_REPORT",
}
KINDS = ("html", "date", "choice", "text")
FIRST_ROW = 3   # the template's rows 1-2 are its column headings
_FDN_SCHEMA = TAXONOMY_DIR / "def" / "fdn" / "ssmt-fdn_2022-12-31.xsd"
_XS = "{http://www.w3.org/2001/XMLSchema}"


@dataclass(frozen=True)
class ReportField:
    report: str
    field_id: str                 # DIR-7: the report's code and the template row
    element_id: str               # the taxonomy element, e.g. ssmt_NameOfAuditFirm
    label: str
    row: int
    kind: str                     # html, date, choice or text
    choices: tuple[str, ...] = ()


def report_name(report: str) -> str:
    return REPORTS[report][0]


def report_template_path(report: str, level: str = "company", standard: str = "mfrs") -> Path:
    if report not in REPORTS or standard not in STANDARDS or level not in LEVELS:
        raise ValueError(f"No report template for {report!r} on {standard!r} {level!r}.")
    return TEMPLATE_DIRS[standard] / level.capitalize() / f"{REPORTS[report][2]}.xlsx"


def report_template_paths() -> list[Path]:
    return [report_template_path(r, level, standard) for standard in STANDARDS for level in LEVELS for r in REPORTS]


def report_for_path(path: Path) -> str | None:
    return next((r for r, entry in REPORTS.items() if path.name == f"{entry[2]}.xlsx"), None)


@lru_cache(maxsize=1)
def _choice_lists() -> dict[str, tuple[str, ...]]:
    root = ET.parse(safe_path(_FDN_SCHEMA)).getroot()
    out = {}
    for t in root.iter(_XS + "complexType"):
        values = tuple(e.get("value") for e in t.iter(_XS + "enumeration"))
        if values:
            out[t.get("name")] = values
    return out


@lru_cache(maxsize=1)
def _template_labels() -> dict[tuple[str, str], dict[int, str]]:
    """Column A of each report template on the Company level, by (report, standard). Group is the same."""
    out = {}
    for standard in STANDARDS:
        for report in REPORTS:
            wb = openpyxl.load_workbook(safe_path(report_template_path(report, "company", standard)), read_only=True)
            try:
                ws = wb.worksheets[0]
                out[(report, standard)] = {row: str(v).strip() for row, (v,) in enumerate(
                    ws.iter_rows(min_col=1, max_col=1, values_only=True), start=1) if v not in (None, "")}
            finally:
                wb.close()
    return out


@lru_cache(maxsize=8)
def report_fields(report: str, standard: str = "mfrs") -> tuple[ReportField, ...]:
    """The report's fields in template order. Raises ValueError for an unknown report or standard, or a
    template whose rows no longer follow the taxonomy role."""
    if report not in REPORTS or standard not in STANDARDS:
        raise ValueError(f"No report {report!r} on {standard!r}.")
    registry = taxonomy_registry()
    labels = _template_labels()[(report, standard)]
    rows = walk_role_for_taxonomy(standard, REPORTS[report][1])
    if sorted(labels) != list(range(FIRST_ROW, FIRST_ROW + len(rows))):
        raise ValueError(f"The {REPORTS[report][2]} template no longer follows its taxonomy role.")
    out = []
    for row, (_depth, element_id, _label, _abstract) in enumerate(rows, FIRST_ROW):
        concept = registry.get(element_id)
        if concept is None or not concept.reportable:
            continue
        data_type = (concept.data_type or "").split(":")[-1]
        choices = _choice_lists().get(data_type, ())
        kind = ("html" if data_type == "textBlockItemType" else "date" if data_type == "dateItemType"
                else "choice" if choices else "text")
        out.append(ReportField(report, f"{REPORTS[report][3]}-{row}", element_id, labels[row], row, kind, choices))
    return tuple(out)


def find_field(report: str, standard: str, element_or_id: str) -> ReportField | None:
    """A report's field by its taxonomy element or its short id."""
    wanted = "".join(str(element_or_id).split())
    return next((f for f in report_fields(report, standard)
                 if f.element_id == wanted or f.field_id == wanted.upper()), None)


def narrative_field(report: str, standard: str) -> ReportField:
    return next(f for f in report_fields(report, standard) if f.kind == "html")


# The notes catalogue ---------------------------------------------------------

def narrative_node(path: Path) -> NotesNode:
    """The report template's rich-text row as a `notes_nodes` field (IDs as the notes parser mints them)."""
    report = report_for_path(path)
    standard = "mpers" if "MPERS" in path.parent.parent.name.upper() else "mfrs"
    f = narrative_field(report, standard)
    template_id = derive_template_id(path)
    sheet = REPORTS[report][2]
    return NotesNode(node_uuid=mint_uuid(template_id, sheet, f.row, f.label), template_id=template_id, sheet=sheet,
                     row=f.row, label=f.label, kind="LEAF", slot_role="INPUT", taxonomy_element_id=f.element_id,
                     depth=2)


def report_note_fields(conn: sqlite3.Connection, level: str, standard: str) -> list[NoteField]:
    """The three narrative fields of a standard and level, as note fields for the note fill
    (`app/filing/notes.plan_notes`). Empty when the catalogue has not loaded them."""
    out = []
    for report in REPORTS:
        template_id = derive_template_id(report_template_path(report, level, standard))
        row = conn.execute("SELECT node_uuid, sheet, row, label, taxonomy_element_id FROM notes_nodes "
                           "WHERE template_id = ? AND kind = 'LEAF'", (template_id,)).fetchone()
        if row is not None:
            out.append(NoteField(row["node_uuid"], report, report_name(report), template_id, row["sheet"], row["row"],
                                 row["label"], (), False, False, False, row["taxonomy_element_id"]))
    return out
