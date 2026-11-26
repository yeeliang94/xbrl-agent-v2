"""The document map the Reader saves (docs/api-contract.md, "Reading").

The shapes here are what the save tool accepts. Checks that need the
document itself (pages that exist, layouts the standard allows) live in
`map_checks.py`, so each refusal is one plain sentence about this document.
The layouts themselves come from `app/catalog/statements.VARIANTS`.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.reading.content import clean_text

STATEMENTS = ("SOFP", "SOPL", "SOCI", "SOCF", "SOCIE")
STATEMENT_NAMES = {"SOFP": "Financial position", "SOPL": "Profit or loss", "SOCI": "Comprehensive income",
                   "SOCF": "Cash flows", "SOCIE": "Changes in equity"}


def statement_name(statement: str, layout: Optional[str] = None) -> str:
    """The short name, by layout where the layout renames it: MPERS's SoRE files in SOCIE's place."""
    return "Retained earnings" if (statement, layout) == ("SOCIE", "SoRE") else STATEMENT_NAMES[statement]
SectionKind = Literal["directors_report", "statement_by_directors", "statutory_declaration", "auditors_report"]


def _text(v: Optional[str]) -> Optional[str]:
    return clean_text(v) if isinstance(v, str) else v


class Finding(BaseModel):
    value: Optional[str] = Field(description="The answer, or null when the document does not show it.")
    pages: list[int] = Field(default_factory=list, description="PDF page numbers it was read from, never folios.")
    reason: str = Field(description="One sentence: what on the page shows it.")
    unsure: bool = Field(default=False, description="True when the page does not settle it; the reason says why.")

    _clean = field_validator("value", "reason")(_text)


class StatementFinding(BaseModel):
    statement: Literal["SOFP", "SOPL", "SOCI", "SOCF", "SOCIE"]
    found: bool = Field(description="False when the statement is not printed in the document.")
    pages: list[int] = Field(default_factory=list, description="PDF page numbers of the statement, never folios.")
    title: str = Field(default="", description="The statement's title as printed.")
    layout: Optional[str] = Field(default=None, description="The layout, from the statement's own list; null when not printed.")
    reason: str = Field(description="One sentence: what on the page decides the layout, or why it is not printed.")
    unsure: bool = Field(default=False, description="True when the page does not show enough to decide; the reason says what is missing.")

    _clean = field_validator("title", "reason")(_text)


class SubNote(BaseModel):
    number: str = ""
    title: str
    page: int

    _clean = field_validator("number", "title")(_text)


class Note(BaseModel):
    number: str = Field(description="As printed, or empty when it cannot be read on the scan.")
    title: str
    first_page: int = Field(description="PDF page of the note's heading.")
    last_page: int = Field(description="PDF page of the note's last line.")
    sub_notes: list[SubNote] = Field(default_factory=list)

    _clean = field_validator("number", "title")(_text)


class Section(BaseModel):
    kind: SectionKind
    title: str = ""
    first_page: int
    last_page: int

    _clean = field_validator("title")(_text)


class NoteGap(BaseModel):
    note: str = Field(description="The note number that is not in the list.")
    reason: str = Field(description="Why it is absent, for example the document skips the number.")

    _clean = field_validator("note", "reason")(_text)


class DocumentMap(BaseModel):
    company: Finding
    year_end: Finding = Field(description="value as YYYY-MM-DD.")
    standard: Finding = Field(description="value MFRS, MPERS or unknown.")
    level: Finding = Field(description="value Company or Group.")
    unit: Finding = Field(description="value RM, RM'000 or RM'000,000 (millions), as the statements' column "
                                      "headings print it.")
    first_statements: Optional[Finding] = Field(
        default=None, description="value yes when no statement prints figures for a prior year, so these look "
                                  "like the company's first financial statements; otherwise no. The reason says "
                                  "what on the pages shows it.")
    statements: list[StatementFinding] = Field(description="All five statements, each once.")
    notes: list[Note] = Field(default_factory=list)
    other_sections: list[Section] = Field(default_factory=list)
    note_gaps: list[NoteGap] = Field(default_factory=list,
                                     description="Note numbers missing from the list, each with the reason.")
