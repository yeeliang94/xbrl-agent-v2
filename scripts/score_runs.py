"""Score runs against the workbooks people filled, and print the scores.

    venv/bin/python scripts/score_runs.py                      every run with a workbook attached
    venv/bin/python scripts/score_runs.py --run 7              one run
    venv/bin/python scripts/score_runs.py --run 7 --workbook filled.xlsx
                                                               one run against a workbook not attached
    venv/bin/python scripts/score_runs.py --detail 7           the differences of one run
    venv/bin/python scripts/score_runs.py --v1-database C:\\path\\to\\xbrl.db [--run N] [--workbook F] [--detail N]
                                                               the old app's runs, scored the same way

The default output names no company, no figure and no document text: one
row per run and statement, with run numbers, percentages and counts only.
`--detail` lists the differences of one run, with field names and amounts.

Nothing is written, except that an attached workbook is read again when its
run's templates changed since it was attached. Runs on the app's own Python with no extra packages.
The scores are defined in docs/api-contract.md, Step 2.
"""
from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _v1_baseline as v1_baseline  # noqa: E402
from app import db  # noqa: E402
from app.catalog import loader  # noqa: E402
from app.catalog.lookup import run_family  # noqa: E402
from app.scoring import attached  # noqa: E402
from app.scoring.workbook_read import NothingMatches, read_filled_workbook  # noqa: E402
from app.workbook.xlsx_cells import WorkbookUnreadable  # noqa: E402
from app.utils.paths import operator_path  # noqa: E402

_COLUMNS = (("Run", 5), ("Statement", 16), ("Complete", 9), ("Accurate", 9), ("C x A", 7), ("Filled", 7),
            ("Agree", 6), ("Extra", 6), ("Sign", 5), ("Scale", 6), ("Diff", 5), ("Miss", 5), ("Zero", 5),
            ("Unread", 7), ("Totals off", 11))
LEGEND = ("Complete = of the cells the person filled, the share the run also filled. Accurate = of the cells "
          "both filled, the share that agree within RM 1. C x A = complete times accurate. Filled = cells the person "
          "filled. Sign = opposite sign only. Scale = same digits at x1,000 or x1,000,000. Miss = the run left "
          "it blank. Zero = the person's zero, the run blank (not scored). Unread = could not be read or "
          "matched (not scored). Outside = cells outside the run's templates. Totals off = calculated totals that differ (not scored).")


def _pct(value) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def _line(cells: list) -> str:
    return "".join(str(c).rjust(w) if i not in (1,) else f"  {str(c):<{w - 2}}"
                   for i, (c, (_, w)) in enumerate(zip(cells, _COLUMNS)))


def _row(run_label, statement: str, score: dict, totals_off="") -> str:
    c = score["counts"]
    return _line([run_label, statement, _pct(score["completeness"]), _pct(score["accuracy"]),
                  _pct(score["complete_and_accurate"]), score["person_filled"], c["agree"], c["extra"],
                  c["sign_only"], c["scale"], c["different"], c["missing"], c["zero_left_blank"],
                  c["not_assessed"], totals_off])


def table(results: list[tuple[str, dict]]) -> str:
    out = [_line([name for name, _ in _COLUMNS]), "-" * sum(w for _, w in _COLUMNS)]
    for label, result in results:
        if "error" in result:
            out.append(f"{label:>5}  {result['error']}")
            continue
        off = sum(n for kind, n in result["totals"]["counts"].items() if kind != "agree")
        out.append(_row(label, "All", result["overall"], off))
        for item in result["statements"]:
            out.append(_row("", item["statement"] or "Outside", item["score"]))
    return "\n".join(out + [""] + textwrap.wrap(LEGEND, 100))


def _amount(value) -> str:
    return "blank" if value is None else f"{value:,.2f}".rstrip("0").rstrip(".")


def detail(label: str, result: dict) -> str:
    lines = [f"Run {label}: {len(result['differences'])} difference(s), "
             f"{len(result['totals']['differences'])} total(s) off, {len(result['not_assessed'])} not assessed."]
    for title, rows in (("Differences (scored)", result["differences"]),
                        ("Totals (not scored)", result["totals"]["differences"])):
        lines.append(f"\n{title}")
        for d in sorted(rows, key=lambda d: (d["statement"], d["sheet"], d["row"], d["period"])):
            where = d["entity_scope"] + (f", {d['dimension_key']}" if d["dimension_key"] else "")
            lines.append(f"  {d['kind']:<16}{d['statement']:<6}{d['field_label'][:60]:<61}{d['period']} {where:<9}"
                         f" run {_amount(d['run_value']):>14}  workbook {_amount(d['person_value']):>14}")
    lines.append("\nNot assessed")
    for n in result["not_assessed"]:
        lines.append(f"  {n['reason']:<28}{n['sentence']}")
    return "\n".join(lines)


def _v2_scores(conn, run_ids: list[int], workbook) -> list[tuple[str, dict]]:
    results = []
    for run_id in run_ids:
        family = run_family(conn, run_id)
        if family is None:
            results.append((str(run_id), {"error": "There is no such run."}))
            continue
        try:
            if workbook is not None:
                read = read_filled_workbook(conn, family, str(operator_path(workbook)))
                result = attached.score(conn, family, read)
            else:
                result = attached.comparison(run_id)
        except attached.NoWorkbook as exc:
            result = {"error": str(exc)}
        except (WorkbookUnreadable, NothingMatches) as exc:
            result = {"error": str(exc)}
        results.append((str(run_id), result))
    return results


def _v1_scores(conn, v1, run_ids: list[int], workbook) -> list[tuple[str, dict]]:
    results = []
    for run_id in run_ids:
        try:
            results.append((f"v1-{run_id}", v1_baseline.score_v1_run(v1, conn, run_id, workbook)))
        except (WorkbookUnreadable, NothingMatches) as exc:
            results.append((f"v1-{run_id}", {"error": str(exc)}))
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", type=int, help="score one run")
    parser.add_argument("--workbook", help="with --run: score against this workbook instead of the attached one")
    parser.add_argument("--detail", type=int, metavar="RUN", help="list the differences of one run")
    parser.add_argument("--v1-database", help="score the old app's runs from its database (opened read-only)")
    args = parser.parse_args(argv)
    if args.workbook and not (args.run or args.detail):
        parser.error("--workbook needs --run or --detail")
    db.init_db()
    loader.load_catalogue()
    one = args.detail or args.run
    with db.connect() as conn:
        if args.v1_database:
            v1 = v1_baseline.open_v1(args.v1_database)
            try:
                ids = [one] if one else v1_baseline.runs_with_workbooks(v1)
                results = _v1_scores(conn, v1, ids, args.workbook)
            finally:
                v1.close()
        else:
            ids = [one] if one else [r[0] for r in conn.execute("SELECT run_id FROM filled_workbooks ORDER BY run_id")]
            results = _v2_scores(conn, ids, args.workbook)
    if not results:
        print("No run has a filled workbook attached.")
        return 0
    if args.detail:
        label, result = results[0]
        print(result["error"] if "error" in result else detail(label, result))
    else:
        print(table(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
