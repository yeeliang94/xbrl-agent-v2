"""Statements, their layouts (variants) and which template file serves each.

Copied from v1 `statement_types.py` (the registry and `template_path`) and
v1 `notes_types.py` (the five note templates and their file numbers). The scout's detection signals are left
out: v2's Reader chooses layouts in step 3.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from app.utils.paths import PROJECT_ROOT

TEMPLATES_ROOT = PROJECT_ROOT / "templates"
TEMPLATE_DIRS: dict[str, Path] = {
    "mfrs": TEMPLATES_ROOT / "XBRL-template-MFRS",
    "mpers": TEMPLATES_ROOT / "XBRL-template-MPERS",
}
TAXONOMY_DIR = TEMPLATES_ROOT / "SSMxT_2022v1.0"

STANDARDS = ("mfrs", "mpers")
LEVELS = ("company", "group")


class StatementType(str, Enum):
    """The five primary statements."""
    SOFP = "SOFP"    # financial position
    SOPL = "SOPL"    # profit or loss
    SOCI = "SOCI"    # comprehensive income
    SOCF = "SOCF"    # cash flows
    SOCIE = "SOCIE"  # changes in equity (or retained earnings, MPERS SoRE)


@dataclass(frozen=True)
class Variant:
    statement: StatementType
    name: str
    template_filename: str
    applies_to_standard: frozenset[str] = field(
        default_factory=lambda: frozenset({"mfrs", "mpers"})
    )
    # What the setup screen calls the layout.
    label: str = ""


NOT_PREPARED = "NotPrepared"

VARIANTS: dict[tuple[StatementType, str], Variant] = {
    (StatementType.SOFP, "CuNonCu"): Variant(
        StatementType.SOFP, "CuNonCu", "01-SOFP-CuNonCu.xlsx", label="Current and non-current"),
    (StatementType.SOFP, "OrderOfLiquidity"): Variant(
        StatementType.SOFP, "OrderOfLiquidity", "02-SOFP-OrderOfLiquidity.xlsx", label="Order of liquidity"),
    (StatementType.SOPL, "Function"): Variant(
        StatementType.SOPL, "Function", "03-SOPL-Function.xlsx", label="By function"),
    (StatementType.SOPL, "Nature"): Variant(StatementType.SOPL, "Nature", "04-SOPL-Nature.xlsx", label="By nature"),
    (StatementType.SOCI, "BeforeTax"): Variant(
        StatementType.SOCI, "BeforeTax", "05-SOCI-BeforeTax.xlsx", label="Before tax"),
    (StatementType.SOCI, "NetOfTax"): Variant(
        StatementType.SOCI, "NetOfTax", "06-SOCI-NetOfTax.xlsx", label="Net of tax"),
    # No standalone SOCI page: no template, nothing is extracted.
    (StatementType.SOCI, NOT_PREPARED): Variant(StatementType.SOCI, NOT_PREPARED, "", label="Not printed"),
    (StatementType.SOCF, "Indirect"): Variant(StatementType.SOCF, "Indirect", "07-SOCF-Indirect.xlsx", label="Indirect"),
    (StatementType.SOCF, "Direct"): Variant(StatementType.SOCF, "Direct", "08-SOCF-Direct.xlsx", label="Direct"),
    (StatementType.SOCIE, "Default"): Variant(
        StatementType.SOCIE, "Default", "09-SOCIE.xlsx", label="Changes in equity"),
    # MPERS only: the statement of retained earnings replaces SOCIE.
    (StatementType.SOCIE, "SoRE"): Variant(
        StatementType.SOCIE, "SoRE", "10-SoRE.xlsx", frozenset({"mpers"}), label="Retained earnings"),
}

# The two numeric notes. They are read into the catalogue exactly like a
# statement. The file number differs by standard (MFRS 13/14, MPERS 14/15).
NUMERIC_NOTES: dict[str, dict[str, str]] = {
    "ISSUED_CAPITAL": {"mfrs": "13-Notes-IssuedCapital.xlsx", "mpers": "14-Notes-IssuedCapital.xlsx"},
    "RELATED_PARTY": {"mfrs": "14-Notes-RelatedParty.xlsx", "mpers": "15-Notes-RelatedParty.xlsx"},
}


# The three prose-note templates, read into `notes_nodes`. MFRS files 10-12,
# MPERS 11-13 (MPERS slot 10 is SoRE).
PROSE_NOTES: dict[str, dict[str, str]] = {
    "CORP_INFO": {"mfrs": "10-Notes-CorporateInfo.xlsx", "mpers": "11-Notes-CorporateInfo.xlsx"},
    "ACC_POLICIES": {"mfrs": "11-Notes-AccountingPolicies.xlsx", "mpers": "12-Notes-AccountingPolicies.xlsx"},
    "LIST_OF_NOTES": {"mfrs": "12-Notes-ListOfNotes.xlsx", "mpers": "13-Notes-ListOfNotes.xlsx"},
}

# Every note template in the order a person reads them, with its name.
NOTE_TEMPLATES: dict[str, str] = {
    "CORP_INFO": "Corporate information",
    "ACC_POLICIES": "Accounting policies",
    "LIST_OF_NOTES": "List of notes",
    "ISSUED_CAPITAL": "Issued capital",
    "RELATED_PARTY": "Related parties",
}

# The one catch-all field of each prose template: where a note goes when no
# other field fits the whole of it. Named by taxonomy element, the part after
# the prefix, which is the same on both standards. v1 found these by searching
# labels in four files (agent-lessons section 7); here it is data, and the
# loader refuses a template that does not have exactly one.
# Corporate information has no "other" field: its general field is the
# catch-all; the other three take one specific explanation each.
CATCH_ALL_ELEMENTS: dict[str, str] = {
    "CORP_INFO": "DisclosureOfCorporateInformationExplanatory",
    "ACC_POLICIES": ("DescriptionOfAccountingPolicyForOtherSignificantAccountingPolicies"
                     "RelevantToUnderstandingOfFinancialStatementsExplanatory"),
    "LIST_OF_NOTES": "DisclosureOfOtherNotesToAccountsExplanatory",
}


def _check_family(level: str, standard: str) -> None:
    if level not in LEVELS:
        raise ValueError(f"Invalid filing level {level!r}; must be one of {LEVELS}")
    if standard not in TEMPLATE_DIRS:
        raise ValueError(f"Invalid filing standard {standard!r}; must be one of {STANDARDS}")


def get_variant(statement: StatementType, variant_name: str) -> Variant:
    try:
        return VARIANTS[(StatementType(statement), variant_name)]
    except KeyError as exc:
        raise KeyError(f"No layout {variant_name!r} for {StatementType(statement).value}.") from exc


def template_path(statement: StatementType, variant_name: str,
                  level: str = "company", standard: str = "mfrs") -> Path:
    """The template file for one statement layout, level and standard.

    Raises ValueError for NotPrepared (no template), an unknown level or
    standard, or a layout that does not exist on that standard (SoRE on MFRS).
    """
    _check_family(level, standard)
    variant = get_variant(statement, variant_name)
    if not variant.template_filename:
        raise ValueError(f"{variant.statement.value}/{variant_name} has no template.")
    if standard not in variant.applies_to_standard:
        raise ValueError(f"{variant.statement.value}/{variant_name} is not available on {standard.upper()}.")
    return TEMPLATE_DIRS[standard] / level.capitalize() / variant.template_filename


def numeric_note_path(note: str, level: str = "company", standard: str = "mfrs") -> Path:
    _check_family(level, standard)
    return TEMPLATE_DIRS[standard] / level.capitalize() / NUMERIC_NOTES[note][standard]


def prose_note_path(note: str, level: str = "company", standard: str = "mfrs") -> Path:
    _check_family(level, standard)
    return TEMPLATE_DIRS[standard] / level.capitalize() / PROSE_NOTES[note][standard]


def variants_for(statement: StatementType, standard: str) -> list[Variant]:
    return [v for (s, _), v in VARIANTS.items()
            if s == StatementType(statement) and standard.lower() in v.applies_to_standard]


def printed_layouts(statement: StatementType, standard: str | None = None) -> list[str]:
    """The layouts a printed statement can have: every standard's when
    `standard` is None, else that standard's. Never NotPrepared."""
    standards = STANDARDS if standard is None else (standard.lower(),)
    return [name for (s, name), v in VARIANTS.items() if s == StatementType(statement) and name != NOT_PREPARED
            and any(std in v.applies_to_standard for std in standards)]


def layout_label(statement: StatementType, name: str) -> str:
    """The layout's label; a layout of another statement keeps its own label."""
    variant = VARIANTS.get((StatementType(statement), name))
    if variant is None:
        variant = next((v for v in VARIANTS.values() if v.name == name), None)
    return variant.label if variant is not None else name


def layout_choices(statement: StatementType) -> dict[str, list[dict]]:
    """The setup screen's choices for one statement, by standard:
    {"MFRS": [{"value", "label"}], "MPERS": [...]}. The one list the browser shows."""
    return {standard.upper(): [{"value": v.name, "label": v.label} for v in variants_for(statement, standard)]
            for standard in STANDARDS}


def statement_template_paths() -> list[Path]:
    """Every statement template: 9 per level on MFRS, 10 on MPERS, 38 in all."""
    paths = []
    for (statement, name), variant in VARIANTS.items():
        for standard in STANDARDS:
            for level in LEVELS:
                try:
                    paths.append(template_path(statement, name, level, standard))
                except ValueError:
                    continue
    return paths


def numeric_note_paths() -> list[Path]:
    return [numeric_note_path(note, level, standard)
            for note in NUMERIC_NOTES for standard in STANDARDS for level in LEVELS]


def prose_note_paths() -> list[Path]:
    """The 12 prose-note templates: three per standard and level."""
    return [prose_note_path(note, level, standard)
            for note in PROSE_NOTES for standard in STANDARDS for level in LEVELS]
