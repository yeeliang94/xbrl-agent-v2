"""Make a filled workbook from a run's own figures, to try the scoring tool.

    venv/bin/python scripts/make_filled_workbook.py RUN_ID OUT.xlsx [--seed-differences]

The workbook uses the app's own template layout (the files under
`templates/`): every sheet of the run's templates in one workbook, as v1's
merged download had them. Each data-entry figure is typed into its cell. A
total the run saved with no breakdown is typed over the template's formula;
every other total keeps its formula.

`--seed-differences` changes five cells on the run's first statement, this
year, one of each kind the comparison lists (see `SEEDED`): the workbook
then scores exactly one extra, one missing, one sign only, one scale and one
different. Attach the file to the run on the run's page, or score it with
`scripts/score_runs.py`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import openpyxl  # noqa: E402

from app import db  # noqa: E402
from app.catalog.lookup import run_family  # noqa: E402
from app.figures.sums import known_value  # noqa: E402
from app.catalog.fields import STATEMENT_ORDER, run_fields  # noqa: E402
from app.utils.paths import PROJECT_ROOT, safe_path  # noqa: E402

# The kinds seeded, in the order the cells are chosen.
SEEDED = ("extra", "missing", "sign_only", "scale", "different")


def _template_paths(conn, family) -> list[Path]:
    ids = sorted(family.template_ids.values())
    return [PROJECT_ROOT / r[0] for r in conn.execute(
        f"SELECT source_path FROM concept_templates WHERE template_id IN ({','.join('?' * len(ids))}) "
        "ORDER BY source_path", ids)]


def _copy_templates(paths: list[Path]) -> openpyxl.Workbook:
    out = openpyxl.Workbook()
    out.remove(out.active)
    for path in paths:
        source = openpyxl.load_workbook(safe_path(path), data_only=False)
        for ws in source.worksheets:
            target = out.create_sheet(ws.title)
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is not None:
                        target.cell(cell.row, cell.column, cell.value if isinstance(cell.value, (str, int, float))
                                    else str(cell.value))
        source.close()
    return out


def _cells(conn, family) -> dict:
    """{(concept, period, entity): (sheet, row, column)} for every field of the run's templates."""
    ids = sorted(family.template_ids.values())
    return {(r[0], r[2], r[1]): (r[3], r[4], r[5]) for r in conn.execute(
        "SELECT t.concept_uuid, t.entity_scope, t.period, t.target_sheet, t.target_row, t.target_col "
        "FROM concept_targets t JOIN concept_nodes n ON n.concept_uuid = t.concept_uuid "
        f"WHERE n.is_current = 1 AND n.template_id IN ({','.join('?' * len(ids))})", ids)}


def build(conn, run_id: int, out_path: Path, *, seed_differences: bool = False) -> list[dict]:
    """Write the workbook. Returns the seeded changes (empty without seeding)."""
    family = run_family(conn, run_id)
    fields = run_fields(conn, family)
    workbook = _copy_templates(_template_paths(conn, family))
    cells = _cells(conn, family)
    figures = [r for r in conn.execute(
        "SELECT concept_uuid, period, entity_scope, dimension_key, value, status, children_status "
        "FROM figures WHERE run_id = ? ORDER BY id", (run_id,))
        if r["concept_uuid"] in fields and r["dimension_key"] == "" and r["period"] in family.periods]
    typed = {}
    for f in figures:
        value = known_value(f["value"], f["status"])
        info = fields[f["concept_uuid"]]
        if value is None or (info.is_total and f["children_status"] != "aggregate_only"):
            continue
        typed[(f["concept_uuid"], f["period"], f["entity_scope"])] = value
    seeded = _seed(fields, typed, cells, family) if seed_differences else []
    for key, value in typed.items():
        sheet, row, col = cells[key]
        workbook[sheet][f"{col}{row}"] = value
    workbook.save(safe_path(out_path))
    return seeded


def _seed(fields, typed: dict, cells: dict, family) -> list[dict]:
    """One change of each kind on this year's data-entry lines of the first statement."""
    first = family.template_ids[min(family.template_ids, key=lambda s: STATEMENT_ORDER.index(s.value))]
    lines = [k for k, v in typed.items() if k[1] == "CY" and fields[k[0]].template_id == first
             and not fields[k[0]].is_total and abs(v) >= 10_000]
    blank = next(k for k in cells if k[1] == "CY" and k[2] == "Company" and k[0] in fields
                 and fields[k[0]].template_id == first and not fields[k[0]].is_total and k not in typed)
    if len(lines) < 4:
        raise SystemExit("The run needs at least four figures of 10,000 or more this year to seed differences.")
    changes = [("extra", lines[0], None), ("missing", blank, 50_000.0), ("sign_only", lines[1], -typed[lines[1]]),
               ("scale", lines[2], round(typed[lines[2]] / 1000)), ("different", lines[3], typed[lines[3]] + 10_000)]
    out = []
    for kind, key, value in changes:
        out.append({"kind": kind, "concept_uuid": key[0], "period": key[1], "entity_scope": key[2],
                    "run_value": typed.get(key), "person_value": value, "field_label": fields[key[0]].plain_label})
        if value is None:
            typed.pop(key)
        else:
            typed[key] = value
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_id", type=int)
    parser.add_argument("out", type=Path)
    parser.add_argument("--seed-differences", action="store_true", help="change one cell of each kind")
    args = parser.parse_args()
    with db.connect() as conn:
        if run_family(conn, args.run_id) is None:
            raise SystemExit(f"There is no run {args.run_id}.")
        seeded = build(conn, args.run_id, args.out, seed_differences=args.seed_differences)
    print(f"Wrote {args.out}")
    for change in seeded:
        print(f"  {change['kind']:<10} {change['field_label']}, this year: run {change['run_value']}, "
              f"workbook {change['person_value']}")


if __name__ == "__main__":
    main()
