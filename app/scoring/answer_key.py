"""Score a run against an answer key (docs/answer-keys.md). Pure: no database, no files.

An answer key gives, for each printed line of a statement, the data-entry
cells where its amounts belong (`entry`, with `concept_uuid`, `cy`, `py`).
Those become the person's side of the step 2 comparison. Every other
data-entry field of the same statement is a blank person cell, so a figure
the run saved where the key has nothing is counted as extra, not ignored.
Two entries on one cell are added together. A line may list
`alternatives`: other sets of entry cells the owner also accepts. The set
the run's figures match is used; otherwise the line's own `entry`. Calculated totals are compared
on their own, as for a filled workbook (`compare.compare`).

The key's entity is the Company (step 4: MFRS Company filings). v1 stores
`entity_scope = 'Company'` and so does v2.
"""
from __future__ import annotations

from typing import Mapping

from app.scoring.compare import RunValue, compare
from app.catalog.fields import FieldInfo
from app.scoring.workbook_read import Key, PersonCell

ENTITY = "Company"


class KeyDoesNotFit(ValueError):
    """The key names fields the run's templates do not have. `str()` is one sentence."""


def _matches(entries: list[dict], run: Mapping[Key, RunValue], periods: tuple[str, ...]) -> bool:
    for entry in entries:
        for period in periods:
            want, got = entry.get(period.lower()), run.get((entry["concept_uuid"], period, ENTITY, ""))
            have = got.value if got else None
            if want is None:
                continue
            if have is None or abs(have - float(want)) > 1:
                return False
    return bool(entries)


def _chosen(line: dict, run: Mapping[Key, RunValue], periods: tuple[str, ...]) -> list[dict]:
    """The line's own entry cells, or the accepted alternative the run's figures match."""
    own = line.get("entry") or []
    if _matches(own, run, periods):
        return own
    return next((alt for alt in line.get("alternatives") or [] if _matches(alt, run, periods)), own)


def person_cells(key: dict, statement: str, fields: Mapping[str, FieldInfo],
                 periods: tuple[str, ...] = ("CY", "PY"), run: Mapping[Key, RunValue] = {}) -> dict[Key, PersonCell]:
    """The key's cells for one statement, and a blank cell for every other data-entry field of it."""
    lines = ((key.get("statements") or {}).get(statement) or {}).get("lines") or []
    cells: dict[Key, PersonCell] = {}
    for line in lines:
        for entry in _chosen(line, run, periods):
            for period in periods:
                value = entry.get(period.lower())
                if value is None:
                    continue
                k = (entry["concept_uuid"], period, ENTITY, "")
                before = cells[k].value if k in cells else 0.0
                cells[k] = PersonCell(round(before + float(value), 2), False, f"key: {line.get('label', '')}")
    outside = sorted({k[0] for k in cells if k[0] not in fields or fields[k[0]].statement != statement})
    if outside:
        raise KeyDoesNotFit(f"The answer key names {len(outside)} field(s) that are not data-entry fields of this "
                            f"run's {statement} template, so it was made for another layout.")
    for uuid, info in fields.items():
        if info.statement == statement and not info.is_total:
            for period in periods:
                cells.setdefault((uuid, period, ENTITY, ""), PersonCell(None, False, "key: blank"))
    return cells


def score(key: dict, statement: str, fields: Mapping[str, FieldInfo], run: Mapping[Key, RunValue],
          edges: Mapping[str, list[tuple[str, float]]], periods: tuple[str, ...] = ("CY", "PY")) -> dict:
    """The step 2 comparison of the run's figures for one statement with the key."""
    own = {uuid: info for uuid, info in fields.items() if info.statement == statement}
    figures = {k: v for k, v in run.items() if k[0] in own and k[2] == ENTITY}
    person = person_cells(key, statement, own, periods, figures)
    return compare(own, person, {}, [], figures, edges, periods=periods)
