"""Scoring a run against an answer key (app/scoring/answer_key.py), with a small made-up key."""
from __future__ import annotations

import json

import pytest

from app import db
from app.catalog.lookup import run_family
from app.scoring import answer_key
from app.scoring.compare import RunValue
from app.catalog.fields import run_edges, run_fields
from tests.conftest import field, make_run

SOFP = "mfrs-company-sofp-cunoncu-v1"
SUB = "SOFP-Sub-CuNonCu"


def _key(plant: str, office: str, payables: str) -> dict:
    return {"statements": {"SOFP": {"lines": [
        {"label": "Assets", "kind": "heading", "entry": []},
        {"label": "Equipment", "kind": "line", "entry": [
            {"concept_uuid": plant, "cy": 1000, "py": 900},
            {"concept_uuid": office, "cy": 200, "py": None}]},
        {"label": "Trade and other payables", "kind": "line", "entry": [
            {"concept_uuid": payables, "cy": 300, "py": 250},
            {"concept_uuid": payables, "cy": 50, "py": 0}]},
    ]}}}


@pytest.fixture
def setup():
    run_id = make_run()
    plant, office, payables = field(SOFP, SUB, 28), field(SOFP, SUB, 29), field(SOFP, SUB, 404)
    other = field(SOFP, SUB, 38)
    with db.connect() as conn:
        family = run_family(conn, run_id)
        fields, edges = run_fields(conn, family), run_edges(conn, family)
    return _key(plant, office, payables), fields, edges, (plant, office, payables, other)


def test_the_key_is_the_person_side_and_every_other_entry_field_is_a_blank_cell(setup):
    key, fields, edges, (plant, office, payables, other) = setup
    cells = answer_key.person_cells(key, "SOFP", fields)
    assert cells[(plant, "CY", "Company", "")].value == 1000
    assert cells[(payables, "CY", "Company", "")].value == 350          # two entries on one cell are added
    assert cells[(payables, "PY", "Company", "")].value == 250
    assert cells[(office, "PY", "Company", "")].value is None           # a blank in the key stays blank
    assert cells[(other, "CY", "Company", "")].value is None
    assert all(not fields[k[0]].is_total for k in cells)


def test_a_run_is_scored_with_extras_counted(setup):
    key, fields, edges, (plant, office, payables, other) = setup
    run = {(plant, "CY", "Company", ""): RunValue(1000.0), (plant, "PY", "Company", ""): RunValue(900.0),
           (payables, "CY", "Company", ""): RunValue(300.0), (payables, "PY", "Company", ""): RunValue(250.0),
           (other, "CY", "Company", ""): RunValue(200.0)}
    result = answer_key.score(key, "SOFP", fields, run, edges)
    score = next(s["score"] for s in result["statements"] if s["statement"] == "SOFP")
    counts = {k: n for k, n in score["counts"].items() if n}
    # Filled by the key: plant CY, PY; office CY; payables CY, PY (the zero adds to 250). Office is missing.
    assert counts == {"agree": 3, "different": 1, "missing": 1, "extra": 1}
    assert score["completeness"] == 0.8 and score["accuracy"] == 0.75 and score["complete_and_accurate"] == 0.6
    assert any(d["kind"] == "extra" and d["concept_uuid"] == other for d in result["differences"])
    # Totals are compared apart: total property, plant and equipment agrees this year (1,200 either way).
    assert result["totals"]["counts"]["agree"] > 0


def test_a_key_for_another_layout_is_refused(setup):
    key, fields, edges, _ = setup
    key["statements"]["SOFP"]["lines"][1]["entry"][0]["concept_uuid"] = "not-a-field"
    with pytest.raises(answer_key.KeyDoesNotFit, match="1 field"):
        answer_key.person_cells(key, "SOFP", fields)


def test_the_command_line_scores_a_run(setup, tmp_path, capsys):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import score_answer_key

    key, *_ = setup
    path = tmp_path / "key.json"
    path.write_text(json.dumps(key))
    assert score_answer_key.main(["--key", str(path), "--run", "1"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("1 SOFP: completeness 0.0, accuracy None") and "missing 5" in out


def test_an_accepted_alternative_counts_when_the_run_chose_it(setup):
    key, fields, edges, (plant, office, payables, other) = setup
    equipment = key["statements"]["SOFP"]["lines"][1]
    equipment["alternatives"] = [[{"concept_uuid": other, "cy": 1200, "py": 900}]]
    chose_other = {(other, "CY", "Company", ""): RunValue(1200.0), (other, "PY", "Company", ""): RunValue(900.0)}
    cells = answer_key.person_cells(key, "SOFP", fields, run=chose_other)
    assert cells[(other, "CY", "Company", "")].value == 1200 and cells[(plant, "CY", "Company", "")].value is None
    # A run that matches neither is held to the line's own entry.
    cells = answer_key.person_cells(key, "SOFP", fields, run={})
    assert cells[(plant, "CY", "Company", "")].value == 1000 and cells[(other, "CY", "Company", "")].value is None
