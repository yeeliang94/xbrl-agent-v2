"""Compare a run's figures with a workbook a person filled. Pure: no database, no files.

Rebuilt from v1 `eval/human_compare.py` (`compare_figures`, `derive_totals`) with backend-plan section 4.3's scores. The rules are in
`docs/api-contract.md`, Step 2. In short:

- Only data-entry fields are scored. Calculated totals are compared on their
  own, so one wrong line is not counted again in every total above it. The
  Total column on the share-capital and related-party sheets is one of them
  whenever a category beside it is filled (owner, 18 November 2026).
- Completeness = both filled / person filled. Accuracy = agree / both filled.
  Complete and accurate = their product. None when a denominator is zero.
- Agreement uses the checks' tolerance (RM 1). v1 required exact equality.
- A person's zero against a blank run cell is listed, not scored (as v1).
- Anything that could not be read or matched is a `not_assessed` row. It
  never counts as agreeing and never enters a score.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Container, Iterable, Mapping, Optional

from app.catalog.dimensions import CATEGORY_SHEETS
from app.checks.framework import DEFAULT_TOLERANCE
from app.catalog.fields import STATEMENT_ORDER, FieldInfo
from app.scoring.workbook_read import Key, PersonCell, Unread

KINDS = ("agree", "extra", "sign_only", "scale", "different", "missing", "zero_left_blank")
_SCALES = (1_000.0, 1_000_000.0)
_ZERO = 0.005


@dataclass(frozen=True)
class RunValue:
    value: Optional[float]      # blank and "not disclosed" are both None, never zero
    figure_id: Optional[int] = None
    stands: bool = False        # a total kept as saved (no breakdown, or typed in a workbook), not re-added


def kind_of(person: Optional[float], run: Optional[float], tolerance: float = DEFAULT_TOLERANCE) -> Optional[str]:
    """The kind of one cell's comparison, or None when both are blank."""
    if person is None and run is None:
        return None
    if person is None:
        return "extra"
    if run is None:
        return "zero_left_blank" if abs(person) < _ZERO else "missing"
    if abs(person - run) <= tolerance:
        return "agree"
    if abs(person + run) <= tolerance:
        return "sign_only"
    if (person > 0) == (run > 0):
        small, big = sorted((abs(person), abs(run)))
        if small > tolerance and any(abs(big / factor - small) <= tolerance for factor in _SCALES):
            return "scale"
    return "different"


def derive_totals(values: Mapping[Key, float], edges: Mapping[str, list[tuple[str, float]]],
                  keys: Iterable[Key], unknown: frozenset = frozenset()) -> dict[Key, float]:
    """What the template calculates for each key in `keys`, from `values`
    through `edges` ({total: [(line, coefficient)]}). A value already in
    `values` (a typed total) is kept. A total with no numeric line stays out,
    and so does a key in `unknown` (a cell that could not be read)."""
    memo: dict[Key, Optional[float]] = {}

    def value(key: Key, visiting: frozenset) -> Optional[float]:
        if key in unknown:
            return None
        if key in values:
            return values[key]
        if key in memo:
            return memo[key]
        uuid, rest = key[0], key[1:]
        children = edges.get(uuid)
        if not children or uuid in visiting:
            return None
        total, found = 0.0, False
        for child, coefficient in children:
            child_value = value((child, *rest), visiting | {uuid})
            if child_value is not None:
                found, total = True, total + coefficient * child_value
        memo[key] = round(total, 2) if found else None
        return memo[key]

    return {key: v for key in keys if (v := value(key, frozenset())) is not None}


def rests_on(key: Key, edges: Mapping[str, list[tuple[str, float]]], unknown: frozenset,
             kept: Container[Key] = ()) -> bool:
    """True when `key` is in `unknown`, or is a total with a line in `unknown`
    at any depth. A key in `kept` (a typed total) is its own value."""
    def walk(k: Key, visiting: frozenset) -> bool:
        if k in unknown:
            return True
        if k in kept or k[0] in visiting:
            return False
        return any(walk((child, *k[1:]), visiting | {k[0]}) for child, _ in edges.get(k[0], ()))

    return walk(key, frozenset())


def _sum_of(values: Iterable[Optional[float]]) -> Optional[float]:
    numbers = [v for v in values if isinstance(v, (int, float))]
    return round(sum(numbers), 2) if numbers else None


def _category_totals(fields: Mapping[str, FieldInfo], person: Mapping[Key, PersonCell],
                     run: Mapping[Key, RunValue], unread: Mapping[Key, Unread], wanted) -> dict[Key, list[Key]]:
    """{Total-column key: its category keys} on the share-capital and
    related-party sheets, for each field, period and entity where either side
    filled a category. Where neither did, the Total column is the only figure
    and stays a scored cell."""
    def has_value(k: Key) -> bool:
        return k in unread and unread[k].holds_value or \
            any(side.get(k) is not None and side[k].value is not None for side in (person, run))

    categories: dict[Key, set[Key]] = {}
    for k in set(person) | set(run) | set(unread):
        if k[3] and wanted(k) and fields[k[0]].sheet in CATEGORY_SHEETS and not fields[k[0]].is_total:
            categories.setdefault((*k[:3], ""), set()).add(k)
    return {total: sorted(keys) for total, keys in categories.items() if any(has_value(k) for k in keys)}


def _counts() -> dict[str, int]:
    return {**{k: 0 for k in KINDS}, "not_assessed": 0}


def _score(counts: dict[str, int]) -> dict:
    person_filled = counts["agree"] + counts["sign_only"] + counts["scale"] + counts["different"] + counts["missing"]
    both = person_filled - counts["missing"]
    completeness = both / person_filled if person_filled else None
    accuracy = counts["agree"] / both if both else None
    return {"person_filled": person_filled, "both_filled": both, "agree": counts["agree"],
            "completeness": None if completeness is None else round(completeness, 4),
            "accuracy": None if accuracy is None else round(accuracy, 4),
            "complete_and_accurate": None if completeness is None or accuracy is None
            else round(completeness * accuracy, 4), "counts": counts}


def _row(kind: str, key: Key, info: FieldInfo, person: Optional[PersonCell], run: Optional[RunValue]) -> dict:
    return {"kind": kind, "statement": info.statement, "concept_uuid": key[0], "field_label": info.plain_label,
            "sheet": info.sheet, "row": info.row, "period": key[1], "entity_scope": key[2],
            "dimension_key": key[3], "matrix_col": info.matrix_col,
            "run_value": run.value if run else None, "person_value": person.value if person else None,
            "figure_id": run.figure_id if run else None,
            "workbook_cell": person.workbook_cell if person else None}


def _not_assessed(reason: str, sentence: str, key: Optional[Key], statement: Optional[str],
                  workbook_cell: Optional[str], run: Optional[RunValue]) -> dict:
    return {"statement": statement, "reason": reason, "sentence": sentence, "workbook_cell": workbook_cell,
            "concept_uuid": key[0] if key else None, "period": key[1] if key else None,
            "entity_scope": key[2] if key else None, "dimension_key": key[3] if key else None,
            "figure_id": run.figure_id if run else None}


def compare(fields: Mapping[str, FieldInfo], person: Mapping[Key, PersonCell], unread: Mapping[Key, Unread],
            loose: Iterable[dict], run: Mapping[Key, RunValue], edges: Mapping[str, list[tuple[str, float]]], *,
            periods: tuple[str, ...] = ("CY", "PY"), tolerance: float = DEFAULT_TOLERANCE) -> dict:
    """The scores, the differences and what could not be assessed.

    `person`: every cell the workbook holds for a field, blank ones included.
    `unread`: fields whose cell could not be read or trusted. `loose`:
    numbers no field claims. `run`: the run's current figures. Keys outside
    `fields` or `periods` are left out."""
    statement_counts: dict[str, dict[str, int]] = {}
    differences, not_assessed, total_rows = [], [], []
    total_counts = _counts()

    def counts_for(statement: Optional[str]) -> dict[str, int]:
        return statement_counts.setdefault(statement or "", _counts())

    def wanted(key: Key) -> bool:
        return key[0] in fields and key[1] in periods

    for key, problem in sorted(unread.items()):
        if key[0] not in fields:
            continue
        if key[1] not in periods and problem.reason != "prior_year_first_statements":
            continue
        if problem.holds_value or (run.get(key) and run[key].value is not None):
            statement = fields[key[0]].statement
            not_assessed.append(_not_assessed(problem.reason, problem.sentence, key, statement,
                                              problem.workbook_cell, run.get(key)))
            counts_for(statement)["not_assessed"] += 1
    sheet_statement = {f.sheet: f.statement for f in fields.values()}
    for item in loose:
        statement = sheet_statement.get(item.get("sheet"))
        not_assessed.append(_not_assessed(item["reason"], item["sentence"], None, statement,
                                          item.get("workbook_cell"), None))
        counts_for(statement)["not_assessed"] += 1

    # On the share-capital and related-party sheets, the Total column (the field with no
    # category) is a total over the category cells beside it whenever either side filled one.
    category_totals = _category_totals(fields, person, run, unread, wanted)
    entry_keys = {k for k in set(person) | set(run) if wanted(k) and not fields[k[0]].is_total
                  and k not in unread and k not in category_totals}
    for key in sorted(entry_keys):
        info, p, r = fields[key[0]], person.get(key), run.get(key)
        if p is None:
            if r is not None and r.value is not None:
                not_assessed.append(_not_assessed(
                    "no_cell", f"The workbook has no cell for {info.plain_label}.", key, info.statement, None, r))
                counts_for(info.statement)["not_assessed"] += 1
            continue
        kind = kind_of(p.value, r.value if r else None, tolerance)
        if kind is None:
            continue
        counts_for(info.statement)[kind] += 1
        if kind != "agree":
            differences.append(_row(kind, key, info, p, r))

    # Totals: each side's typed total, else what the template calculates from its own lines.
    # A total the person's side could not read, or whose lines include such a cell, is not compared.
    unknown = frozenset(k for k in unread if wanted(k))
    operands = {k: c.value for k, c in person.items()
                if wanted(k) and k not in unread and c.value is not None and not c.is_formula}
    run_operands = {k: r.value for k, r in run.items() if wanted(k) and r.value is not None
                    and (not fields[k[0]].is_total or r.stands)}
    scopes = {k[1:] for k in set(person) | set(run) if wanted(k)}
    total_keys = [(uuid, *scope) for uuid, f in fields.items() if f.is_total for scope in scopes]
    person_totals = derive_totals(operands, edges, total_keys, unknown)
    run_totals = derive_totals(run_operands, edges, total_keys)
    for key in sorted(set(person_totals) | {k for k in run_totals if k in person}):
        if key in unread:
            continue   # listed above
        info, r = fields[key[0]], run.get(key)
        run_total = RunValue(run_totals.get(key), r.figure_id if r else None)
        p = person.get(key)
        cell = PersonCell(person_totals.get(key), bool(p and p.is_formula), p.workbook_cell if p else None)
        kind = kind_of(cell.value, run_total.value, tolerance)
        if kind is None:
            continue
        if rests_on(key, edges, unknown, kept=operands):
            not_assessed.append(_not_assessed(
                "line_not_read", f"{info.plain_label} was not compared, because a line under it could not "
                "be read.", key, info.statement, cell.workbook_cell, run_total))
            counts_for(info.statement)["not_assessed"] += 1
            continue
        total_counts[kind] += 1
        if kind != "agree":
            total_rows.append(_row(kind, key, info, cell, run_total))

    for key, categories in sorted(category_totals.items()):
        info, p, r = fields[key[0]], person.get(key), run.get(key)
        if key in unread or any(c in unread and unread[c].holds_value for c in categories):
            if key not in unread:   # an unread Total cell is listed above
                not_assessed.append(_not_assessed(
                    "line_not_read", f"{info.plain_label} was not compared, because a category beside it "
                    "could not be read.", key, info.statement, p.workbook_cell if p else None, r))
                counts_for(info.statement)["not_assessed"] += 1
            continue
        person_value = p.value if p and p.value is not None and not p.is_formula else \
            _sum_of(person[c].value for c in categories if c in person)
        # The run's own categories, added up, as for any other total; its saved Total only when it has none.
        run_value = _sum_of(run[c].value for c in categories if c in run)
        if run_value is None and r is not None:
            run_value = r.value
        kind = kind_of(person_value, run_value, tolerance)
        if kind is None:
            continue
        total_counts[kind] += 1
        if kind != "agree":
            total_rows.append(_row(kind, key, info, PersonCell(person_value, bool(p and p.is_formula),
                                                               p.workbook_cell if p else None),
                                   RunValue(run_value, r.figure_id if r else None)))

    overall = _counts()
    for counts in statement_counts.values():
        for name, n in counts.items():
            overall[name] += n
    order = {name: i for i, name in enumerate(STATEMENT_ORDER)}
    return {
        "tolerance": tolerance, "overall": _score(overall),
        "statements": [{"statement": name or None, "score": _score(counts)} for name, counts in
                       sorted(statement_counts.items(), key=lambda kv: order.get(kv[0], len(order)))],
        "differences": differences, "totals": {"counts": total_counts, "differences": total_rows},
        "not_assessed": not_assessed,
    }
