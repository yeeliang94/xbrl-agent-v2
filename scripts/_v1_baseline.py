"""Score the old app's saved figures with v2's definitions, so v1 can be the baseline.

A private module of `scripts/score_runs.py`, kept beside it because it opens
paths an operator types (`operator_path`), which no app module may do.

Reads a v1 database read-only and never imports v1. A v1 run is scored
against the workbook a person attached to it in v1 (`human_files`,
`human_file_facts`, `human_files.unmatched_json`), or against a workbook
given on the command line, read with v2's reader.

v1 and v2 name fields the same way (`concept_uuid` is a UUID5 of template,
sheet, row and label), and v2's catalogue is pinned to v1's at commit
`4bb9c6bf` (`tests/test_catalogue.py`). A v1 figure on a field v2's
templates do not have, for example one saved before v1 regenerated a
template, is listed as not assessed with reason `field_not_in_templates`,
never dropped.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

from app.catalog.lookup import RunFamily
from app.catalog.parser import derive_template_id
from app.catalog.statements import NUMERIC_NOTES, StatementType, numeric_note_path, template_path
from app.figures.sums import known_value
from app.scoring.compare import RunValue, _counts, _score, compare
from app.catalog.fields import run_edges, run_fields
from app.scoring.workbook_read import PersonCell, read_filled_workbook
from app.utils.paths import operator_path


def open_v1(path: str) -> sqlite3.Connection:
    """The v1 database, opened read-only."""
    resolved = operator_path(path)
    if not resolved.is_file():
        raise SystemExit(f"There is no v1 database at {resolved}.")
    conn = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _has_table(v1: sqlite3.Connection, name: str) -> bool:
    return v1.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def runs_with_workbooks(v1: sqlite3.Connection) -> list[int]:
    if not _has_table(v1, "human_files"):
        return []
    return [r[0] for r in v1.execute("SELECT run_id FROM human_files ORDER BY run_id")]


def v1_family(v1: sqlite3.Connection, run_id: int) -> RunFamily:
    """The v1 run's standard, level, first-statements flag and layouts, as v1's
    `run_filing_shape` reads them: the requested layout, else the one layout
    its agents recorded. A statement whose layout is unknown is left out."""
    row = v1.execute("SELECT run_config_json FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise SystemExit(f"The v1 database has no run {run_id}.")
    config = json.loads(row[0] or "{}")
    family = RunFamily(run_id, str(config.get("filing_standard") or "mfrs").lower(),
                       str(config.get("filing_level") or "company").lower(),
                       config.get("first_financial_statements") is True)
    recorded: dict[str, set[str]] = {}
    if _has_table(v1, "run_agents"):
        for statement, variant in v1.execute(
                "SELECT statement_type, variant FROM run_agents WHERE run_id = ? AND variant IS NOT NULL "
                "AND status IN ('succeeded', 'completed_with_errors', 'skipped')", (run_id,)):
            recorded.setdefault(statement, set()).add(variant)
    for statement in config.get("statements") or []:
        variant = (config.get("variants") or {}).get(statement)
        if not variant and len(recorded.get(statement, ())) == 1:
            variant = next(iter(recorded[statement]))
        try:
            path = template_path(StatementType(statement), variant, family.level, family.standard)
        except (KeyError, ValueError):
            continue
        family.variants[StatementType(statement)] = variant
        family.template_ids[StatementType(statement)] = derive_template_id(path)
    for note in set(config.get("notes_to_run") or []) & set(NUMERIC_NOTES):
        family.note_template_ids[note] = derive_template_id(numeric_note_path(note, family.level, family.standard))
    return family


def _key(r: sqlite3.Row) -> tuple[str, str, str, str]:
    return (r["concept_uuid"], r["period"], r["entity_scope"], r["dimension_key"] or "")


def score_v1_run(v1: sqlite3.Connection, conn: sqlite3.Connection, run_id: int,
                 workbook: Optional[str] = None) -> dict:
    """The comparison for one v1 run. `conn` is v2's database, for the catalogue."""
    family = v1_family(v1, run_id)
    fields = run_fields(conn, family)
    run = {_key(r): RunValue(known_value(r["value"], r["value_status"]))
           for r in v1.execute("SELECT concept_uuid, period, entity_scope, dimension_key, value, value_status "
                               "FROM run_concept_facts WHERE run_id = ?", (run_id,))}
    if workbook is not None:
        read = read_filled_workbook(conn, family, str(operator_path(workbook)))
        cells, unread, loose = read.cells, read.unread, read.loose
    else:
        cells = {_key(r): PersonCell(r["value"], bool(r["calculated"]) and r["value"] is None, None)
                 for r in v1.execute("SELECT concept_uuid, period, entity_scope, dimension_key, value, calculated "
                                     "FROM human_file_facts WHERE run_id = ?", (run_id,))}
        unread = {}
        record = v1.execute("SELECT unmatched_json FROM human_files WHERE run_id = ?", (run_id,)).fetchone()
        loose = [{"reason": "no_field", "sheet": u.get("sheet"), "workbook_cell": None,
                  "sentence": f"{u.get('sheet')} row {u.get('row')} holds a number, but no field of the run's "
                              "templates sits there."}
                 for u in json.loads(record[0] if record else "[]") if u.get("kind") == "figure"]
    result = compare(fields, cells, unread, loose, run, run_edges(conn, family), periods=family.periods)
    _add_unknown_fields(conn, result, fields, run, cells, family.periods)
    return result


def _add_unknown_fields(conn: sqlite3.Connection, result: dict, fields: dict, run: dict, cells: dict,
                        periods: tuple[str, ...]) -> None:
    """v1 cells on fields outside this run's v2 templates: listed, never dropped."""
    unknown = sorted({k for k in run if run[k].value is not None} | {k for k, c in cells.items()
                                                                     if c.value is not None})
    unknown = [k for k in unknown if k[0] not in fields and k[1] in periods]
    known = {r[0]: r[1] for r in conn.execute(
        f"SELECT concept_uuid, template_id FROM concept_nodes WHERE concept_uuid IN "
        f"({','.join('?' * len(unknown))})", [k[0] for k in unknown])} if unknown else {}
    for key in unknown:
        side = "the run" if key in run and run[key].value is not None else "the workbook"
        reason, where = (("outside_run_templates", f"in {known[key[0]]}, not one of this run's layouts")
                         if key[0] in known else ("field_not_in_templates", "not in v2's templates"))
        result["not_assessed"].append({
            "statement": None, "reason": reason, "workbook_cell": None, "concept_uuid": key[0],
            "period": key[1], "entity_scope": key[2], "dimension_key": key[3], "figure_id": None,
            "sentence": f"A figure in {side} sits on field {key[0]}, {where}."})
        result["overall"]["counts"]["not_assessed"] += 1
    if unknown:   # their own row, outside the run's templates, so the rows add up to the whole run
        outside = next((s for s in result["statements"] if s["statement"] is None), None)
        if outside is None:
            outside = {"statement": None, "score": _score(_counts())}
            result["statements"].append(outside)
        outside["score"]["counts"]["not_assessed"] += len(unknown)
