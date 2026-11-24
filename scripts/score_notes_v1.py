"""Score v1's notes placements against the answer keys' `notes` sections: the v1 baseline.

    venv/bin/python scripts/score_notes_v1.py            # every run the keys name
    venv/bin/python scripts/score_notes_v1.py --detail   # with each note that is not right

Reads v1's database read only and the keys in test-data/answer-keys/ (not
committed). Prints each run's score and the average per document.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.scoring import notes  # noqa: E402

V1_DB = Path("/Users/user/Desktop/xbrl-agent/output/xbrl_agent.db")
KEYS = Path(__file__).resolve().parents[1] / "test-data" / "answer-keys"
DOCUMENTS = ("Doc_1", "Doc_2", "Doc_3")   # Doc 4 is set aside (owner, 18 November 2026)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--v1-db", type=Path, default=V1_DB)
    parser.add_argument("--detail", action="store_true")
    args = parser.parse_args()
    v1 = sqlite3.connect(f"file:{args.v1_db}?mode=ro", uri=True)
    for name in DOCUMENTS:
        path = KEYS / f"{name}.json"
        if not path.is_file():
            print(f"{name}: no answer key on this machine")
            continue
        key = json.loads(path.read_text(encoding="utf-8"))["notes"]
        scores = []
        for run_id in key["v1_runs"]:
            result = notes.score(key, notes.v1_placements(v1, run_id))
            scores.append(result["score"])
            print(f"{name} run {run_id}: {result['score']:.3f}  {result['counts']}")
            if args.detail:
                for n in result["notes"]:
                    if n["status"] != notes.RIGHT:
                        print(f"    note {n['number']} {n['title']}: {n['status']} {n['run_fields']}")
                for n in result["not_in_key"]:
                    print(f"    not in key: {n['number']!r} {n['title']} {n['run_fields']}")
        print(f"{name} average over {len(scores)} runs: {sum(scores) / len(scores):.3f}\n")


if __name__ == "__main__":
    main()
