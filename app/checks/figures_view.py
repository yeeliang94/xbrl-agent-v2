"""What a check reads: a run's template lines and saved figures, in memory.

Copied from v1 `cross_checks/facts_util.py` and `concept_model/label_resolver.py`.
v1 read these with SQL per lookup; v2 loads the run's lines and figures
once into `CheckContext`, so every check runs from a list.

Lines are found by label as in v1: case-insensitive, a leading `*` ignored,
exact matches before partial ones, top row first, a value line preferred
over a heading of the same name.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from app.catalog.statements import StatementType


@dataclass(frozen=True)
class Line:
    concept_uuid: str
    kind: str
    label: str
    sheet: str
    row: int
    matrix_col: Optional[str]
    primary_concept: Optional[str] = None


@dataclass
class LabelledValue:
    value: Optional[float]
    sheet: Optional[str]
    row: Optional[int]


@dataclass
class CheckContext:
    run_id: int
    filing_level: str                 # company | group
    filing_standard: str              # mfrs | mpers
    entity_scope: str                 # the entity this pass checks
    periods: tuple[str, ...]          # ("CY", "PY"), or ("CY",) for first statements
    template_ids: dict[StatementType, str]
    variants: dict[StatementType, str]
    note_template_ids: dict[str, str]
    lines: dict[str, list[Line]]      # template id -> lines, top to bottom
    # (concept, period, entity, category) -> value; blank and not-disclosed are absent
    values: dict[tuple[str, str, str, str], float]
    # (concept, period, entity, '') -> the figure's printed lines (label, section)
    printed: dict[tuple[str, str, str], list[tuple[str, str]]] = field(default_factory=dict)
    # (concept, period, entity) -> a total as the report prints it
    stated: dict[tuple[str, str, str], float] = field(default_factory=dict)
    # (concept, period, entity) of totals saved with no breakdown (dimension '')
    no_breakdown: set[tuple[str, str, str]] = field(default_factory=set)
    # total -> [(line, coefficient)], for the run's templates
    edges: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    prior_year_imported: bool = False
    # each last-year figure kept from the starting workbook, with the report's comparative as read
    comparisons: list[dict] = field(default_factory=list)


def norm(label) -> str:
    return str(label).strip().lstrip("*").strip().lower()


def _lines(ctx: CheckContext, stmt: StatementType) -> list[Line]:
    template_id = ctx.template_ids.get(stmt)
    return ctx.lines.get(template_id, []) if template_id else []


def value_of(ctx: CheckContext, uuid: str, period: str, entity_scope: str, dims: str = "") -> Optional[float]:
    return ctx.values.get((uuid, period, entity_scope, dims))


def label_candidates(lines: Iterable[Line], label, *, prefer_leaf: bool = True) -> list[Line]:
    target = norm(label)
    exact, partial = [], []
    for line in lines:
        if line.matrix_col is not None:
            continue
        n = norm(line.label)
        if n == target:
            exact.append(line)
        elif target in n or n in target:
            partial.append(line)
    found = exact + partial
    if prefer_leaf and any(c.kind != "ABSTRACT" for c in found):
        found = [c for c in found if c.kind != "ABSTRACT"]
    return found


def read_labelled_value(ctx: CheckContext, stmt: StatementType, label: str | Sequence[str],
                        period: str, entity_scope: str) -> LabelledValue:
    """The first line matching `label` (or any of several labels) that holds a value."""
    for cand in ([label] if isinstance(label, str) else list(label)):
        for line in label_candidates(_lines(ctx, stmt), cand):
            value = value_of(ctx, line.concept_uuid, period, entity_scope)
            if value is not None:
                return LabelledValue(value, line.sheet, line.row)
    return LabelledValue(None, None, None)


def read_labelled_value_last(ctx: CheckContext, stmt: StatementType, label: str, period: str,
                             entity_scope: str) -> LabelledValue:
    """The bottom-most line whose label matches exactly (SOCI repeats one label)."""
    last = None
    for line in _lines(ctx, stmt):
        if line.matrix_col is None and norm(line.label) == norm(label):
            last = line
    if last is None:
        return LabelledValue(None, None, None)
    return LabelledValue(value_of(ctx, last.concept_uuid, period, entity_scope), last.sheet, last.row)


def read_socf_net_change(ctx: CheckContext, period: str, entity_scope: str) -> LabelledValue:
    """The final net change in cash, found by its shape: the bottom-most
    "net increase/change ... cash" line that is not the before-exchange subtotal."""
    matches = [line for line in _lines(ctx, StatementType.SOCF)
               if line.matrix_col is None
               and ("net increase" in norm(line.label) or "net change" in norm(line.label))
               and "cash" in norm(line.label) and "before" not in norm(line.label)]
    for line in reversed(matches):
        value = value_of(ctx, line.concept_uuid, period, entity_scope)
        if value is not None:
            return LabelledValue(value, line.sheet, line.row)
    return LabelledValue(None, None, None)


# SOCIE grid columns. MFRS: Total = X, retained earnings = C, NCI = W.
# MPERS: Total = O, retained earnings = C, NCI = N.
_MFRS_SOCIE_COMPONENT_COLS = ["B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L",
                              "N", "O", "P", "Q", "R", "V", "W"]


def socie_total_col(filing_standard: str) -> str:
    return "O" if filing_standard == "mpers" else "X"


def socie_component_cols(filing_standard: str) -> list[str]:
    return list("BCDEFGHJMN") if filing_standard == "mpers" else list(_MFRS_SOCIE_COMPONENT_COLS)


def socie_retained_col(filing_standard: str) -> str:
    return "C"


def socie_has_nci(ctx: CheckContext, period: str, entity_scope: str) -> bool:
    nci = "N" if ctx.filing_standard == "mpers" else "W"
    return any(line.matrix_col == nci and value_of(ctx, line.concept_uuid, period, entity_scope) not in (None, 0.0)
               for line in _lines(ctx, StatementType.SOCIE))


def read_matrix_value(ctx: CheckContext, stmt: StatementType, row_label: str, matrix_col: str,
                      period: str, entity_scope: str) -> LabelledValue:
    target = norm(row_label)
    cells = [line for line in _lines(ctx, stmt) if line.matrix_col == matrix_col]
    ordered = [c for c in cells if norm(c.label) == target] + [
        c for c in cells if norm(c.label) != target and (target in norm(c.label) or norm(c.label) in target)]
    for cell in ordered:
        value = value_of(ctx, cell.concept_uuid, period, entity_scope)
        if value is not None:
            return LabelledValue(value, cell.sheet, cell.row)
    return LabelledValue(None, None, None)


def read_matrix_row_sum(ctx: CheckContext, stmt: StatementType, row_label: str, cols: Sequence[str],
                        period: str, entity_scope: str) -> LabelledValue:
    """A SOCIE row added across columns. All columns blank reads as not found."""
    total, sheet, row = None, None, None
    for col in cols:
        lv = read_matrix_value(ctx, stmt, row_label, col, period, entity_scope)
        if lv.value is not None:
            total = lv.value if total is None else total + lv.value
            if sheet is None:
                sheet, row = lv.sheet, lv.row
    return LabelledValue(total, sheet, row)


def is_sore_run(ctx: CheckContext) -> bool:
    return ctx.variants.get(StatementType.SOCIE) == "SoRE"
