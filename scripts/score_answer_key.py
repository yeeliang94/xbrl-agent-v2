"""Score a run's figures for one statement against an answer key, and print the score.

    venv/bin/python scripts/score_answer_key.py --key test-data/answer-keys/Doc_1.json --run 7
    venv/bin/python scripts/score_answer_key.py --key test-data/answer-keys/Doc_1.json \\
        --v1-database /Users/user/Desktop/xbrl-agent/output/xbrl_agent.db --v1-run 393
    ... --statement SOFP (the default)   --detail (list each difference, with field names and amounts)

Without --detail it prints counts and percentages only. The answer keys are
described in docs/answer-keys.md; the scores in docs/api-contract.md, Step 2.
The run's database is v2's (XBRL_OUTPUT_DIR, as the app uses it); a v1
database is opened read-only. Nothing is written.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _v1_baseline as v1_baseline  # noqa: E402
import score_runs  # noqa: E402
from app import db  # noqa: E402
from app.catalog import loader  # noqa: E402
from app.catalog.lookup import run_family  # noqa: E402
from app.figures.sums import known_value  # noqa: E402
from app.scoring import answer_key, attached  # noqa: E402
from app.scoring.compare import RunValue  # noqa: E402
from app.catalog.fields import run_edges, run_fields  # noqa: E402
from app.utils.paths import operator_path  # noqa: E402


def score_v2(conn, run_id: int, key: dict, statement: str) -> dict:
    family = run_family(conn, run_id)
    if family is None:
        raise SystemExit(f"There is no run {run_id}.")
    return answer_key.score(key, statement, run_fields(conn, family), attached.run_values(conn, run_id),
                            run_edges(conn, family), family.periods)


def score_v1(conn, v1, run_id: int, key: dict, statement: str) -> dict:
    family = v1_baseline.v1_family(v1, run_id)
    run = {v1_baseline._key(r): RunValue(known_value(r["value"], r["value_status"])) for r in v1.execute(
        "SELECT concept_uuid, period, entity_scope, dimension_key, value, value_status FROM run_concept_facts "
        "WHERE run_id = ?", (run_id,))}
    return answer_key.score(key, statement, run_fields(conn, family), run, run_edges(conn, family), family.periods)


def summary(label: str, result: dict, statement: str) -> str:
    score = next((s["score"] for s in result["statements"] if s["statement"] == statement), None)
    if score is None:
        return f"{label}: nothing to compare for {statement}."
    totals = {k: n for k, n in result["totals"]["counts"].items() if n}
    return (f"{label} {statement}: completeness {score['completeness']}, accuracy {score['accuracy']}, "
            f"complete and accurate {score['complete_and_accurate']}; "
            + ", ".join(f"{k} {n}" for k, n in score["counts"].items() if n)
            + f"; totals {', '.join(f'{k} {n}' for k, n in totals.items()) or 'none compared'}.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--key", required=True, help="the answer key JSON")
    parser.add_argument("--statement", default="SOFP")
    parser.add_argument("--run", type=int, help="the v2 run to score")
    parser.add_argument("--v1-database", help="score a run of the old app instead (opened read-only)")
    parser.add_argument("--v1-run", type=int, help="with --v1-database: the v1 run")
    parser.add_argument("--detail", action="store_true", help="list the differences")
    args = parser.parse_args(argv)
    if bool(args.v1_database) != bool(args.v1_run) or bool(args.run) == bool(args.v1_run):
        parser.error("give --run, or --v1-database with --v1-run")
    key = json.loads(operator_path(args.key).read_text(encoding="utf-8"))
    db.init_db()
    loader.load_catalogue()
    with db.connect() as conn:
        try:
            if args.v1_database:
                v1 = v1_baseline.open_v1(args.v1_database)
                try:
                    label, result = f"v1-{args.v1_run}", score_v1(conn, v1, args.v1_run, key, args.statement)
                finally:
                    v1.close()
            else:
                label, result = str(args.run), score_v2(conn, args.run, key, args.statement)
        except answer_key.KeyDoesNotFit as exc:
            print(exc)
            return 1
    print(summary(label, result, args.statement))
    if args.detail:
        print(score_runs.detail(label, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
