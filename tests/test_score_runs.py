"""The command-line scoring tool (scripts/score_runs.py), on v2 runs and on a v1 database."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from app import db
from app.scoring import attached
from tests.conftest import OWNER, field, make_user

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import make_filled_workbook  # noqa: E402
import score_runs  # noqa: E402
import seed_demo_run  # noqa: E402

SOFP = "mfrs-company-sofp-cunoncu-v1"


@pytest.fixture
def demo_with_workbook(tmp_path):
    make_user(OWNER)
    run_id = seed_demo_run.seed(OWNER)
    path = tmp_path / "seeded.xlsx"
    with db.connect() as conn:
        make_filled_workbook.build(conn, run_id, path, seed_differences=True)
    attached.attach(run_id, path.read_bytes(), filename=path.name, uploaded_by=OWNER)
    return run_id, path


def test_the_table_has_scores_and_counts_and_no_company_or_figures(demo_with_workbook, capsys):
    run_id, _ = demo_with_workbook
    assert score_runs.main([]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0].split()[:4] == ["Run", "Statement", "Complete", "Accurate"]
    all_row = next(line for line in lines if line.split()[:2] == [str(run_id), "All"])
    assert all_row.split()[2:5] == ["98.6%", "95.7%", "94.3%"]
    # Extra, sign only, scale, different, missing: one each; no zero left blank.
    assert next(line for line in lines if line.split()[:1] == ["SOFP"]).split()[6:12] == [
        "1", "1", "1", "1", "1", "0"]
    assert seed_demo_run.COMPANY.split()[0] not in out
    assert "386,400" not in out and "386400" not in out
    assert max(len(line) for line in lines) <= 110


def test_detail_lists_the_differences_of_one_run(demo_with_workbook, capsys):
    run_id, _ = demo_with_workbook
    score_runs.main(["--detail", str(run_id)])
    out = capsys.readouterr().out
    assert out.startswith(f"Run {run_id}: 5 difference(s)")
    for kind in make_filled_workbook.SEEDED:
        assert f"  {kind} " in out
    assert "Right-of-use assets" in out


def test_a_workbook_can_be_scored_without_attaching_it(demo_with_workbook, tmp_path, capsys):
    run_id, _ = demo_with_workbook
    same = tmp_path / "same.xlsx"
    with db.connect() as conn:
        make_filled_workbook.build(conn, run_id, same)
    score_runs.main(["--run", str(run_id), "--workbook", str(same)])
    all_row = next(line for line in capsys.readouterr().out.splitlines() if line.split()[:2] == [str(run_id), "All"])
    assert all_row.split()[2:5] == ["100.0%", "100.0%", "100.0%"]


def _v1_database(path: Path) -> dict[str, str]:
    """The v1 tables the baseline reads, with v1's columns (v1 db/schema.py)."""
    fields = {name: field(SOFP, sheet, row) for name, sheet, row in (
        ("dta", "SOFP-CuNonCu", 20), ("rou", "SOFP-CuNonCu", 11), ("bio", "SOFP-CuNonCu", 10),
        ("receivables", "SOFP-Sub-CuNonCu", 139), ("total_assets", "SOFP-CuNonCu", 37))}
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE runs (id INTEGER PRIMARY KEY, created_at TEXT, pdf_filename TEXT, status TEXT,
                           run_config_json TEXT);
        CREATE TABLE run_agents (run_id INTEGER, statement_type TEXT, variant TEXT, status TEXT);
        CREATE TABLE run_concept_facts (run_id INTEGER, concept_uuid TEXT, period TEXT, entity_scope TEXT,
                                        dimension_key TEXT NOT NULL DEFAULT '', value REAL, value_status TEXT);
        CREATE TABLE human_files (run_id INTEGER PRIMARY KEY, filename TEXT, sha256 TEXT, unit TEXT,
                                  uploaded_by TEXT, uploaded_at TEXT, summary_json TEXT DEFAULT '{}',
                                  unmatched_json TEXT DEFAULT '[]', not_compared_json TEXT DEFAULT '[]');
        CREATE TABLE human_file_facts (run_id INTEGER, concept_uuid TEXT, period TEXT, entity_scope TEXT,
                                       dimension_key TEXT NOT NULL DEFAULT '', value REAL,
                                       calculated INTEGER NOT NULL DEFAULT 0);
    """)
    # The layout was chosen automatically, so only the agents' row records it.
    conn.execute("INSERT INTO runs VALUES (3, 't', 'doc.pdf', 'completed', ?)", (json.dumps(
        {"filing_standard": "mfrs", "filing_level": "company", "statements": ["SOFP"], "variants": {}}),))
    conn.execute("INSERT INTO run_agents VALUES (3, 'SOFP', 'CuNonCu', 'succeeded')")
    facts = [("dta", 64200, "observed"), ("rou", 386400, "observed"), ("receivables", -2385600, "observed"),
             ("bio", None, "not_disclosed"), ("total_assets", 2836200, "observed")]
    conn.executemany("INSERT INTO run_concept_facts VALUES (3, ?, 'CY', 'Company', '', ?, ?)",
                     [(fields[n], v, s) for n, v, s in facts])
    conn.execute("INSERT INTO run_concept_facts VALUES (3, 'retired-0000', 'CY', 'Company', '', 5, 'observed')")
    conn.execute("INSERT INTO human_files(run_id, filename, sha256, unit, uploaded_at, unmatched_json) "
                 "VALUES (3, 'f.xlsx', 'x', 'units', 't', ?)",
                 (json.dumps([{"kind": "figure", "sheet": "SOFP-CuNonCu", "row": 5, "values": {"B": 1}}]),))
    human = [("dta", 64200, 0), ("rou", None, 0), ("receivables", 2385600, 0), ("bio", 0, 0),
             ("total_assets", None, 1)]
    conn.executemany("INSERT INTO human_file_facts VALUES (3, ?, 'CY', 'Company', '', ?, ?)",
                     [(fields[n], v, c) for n, v, c in human])
    conn.commit()
    conn.close()
    return fields


def test_the_old_apps_runs_are_scored_with_the_same_definitions(tmp_path, capsys):
    v1_path = tmp_path / "v1.db"
    _v1_database(v1_path)
    before = v1_path.read_bytes()

    assert score_runs.main(["--v1-database", str(v1_path)]) == 0
    lines = capsys.readouterr().out.splitlines()

    all_row = next(line for line in lines if line.split()[:2] == ["v1-3", "All"]).split()
    # The person filled deferred tax (agrees) and receivables (sign only); their zero on biological
    # assets, which v1 marked not disclosed, is not scored. Right-of-use assets is extra. Unread: the
    # unmatched row and the figure on a field v2 does not have. Totals off: total assets differs and
    # five totals the person's lines add up to have no v1 figure.
    assert all_row[2:5] == ["100.0%", "50.0%", "50.0%"]
    assert all_row[5:15] == ["2", "1", "1", "1", "0", "0", "0", "1", "2", "6"]
    # The rows add up to the whole run: the field v2 does not have has its own row, outside the templates.
    rows = {line.split()[0]: line.split() for line in lines if line.split()[:1] in (["SOFP"], ["Outside"])}
    assert rows["Outside"][-1] == "1" and sum(int(r[-1]) for r in rows.values()) == int(all_row[13])
    assert v1_path.read_bytes() == before, "the v1 database is opened read-only"

    score_runs.main(["--v1-database", str(v1_path), "--detail", "3"])
    out = capsys.readouterr().out
    assert "field_not_in_templates" in out and "retired-0000" in out
    assert "no_field" in out
