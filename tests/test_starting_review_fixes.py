"""Review fixes for the starting workbook (steps 10d, 10e and 10g): a typed figure a person edited stays
fixed against agents and the fill never keeps a differing one silently (C5), the setup cannot change under
an imported workbook (C1), the comparison is recorded before the checks run (C2), the comparatives check
reaches the figures agent on its own face fields only (C9), kept-only saves count as work (C22), last year's
figures added where the workbook was blank are listed (C6), a different reading during a sign question is
an ordinary difference (C7), and the year end is read from a date cell or refused (C8). No model."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import db
from app.checks.comparatives_check import comparisons
from app.catalog.lookup import run_family
from app.extraction import checking, tools
from app.extraction.tools import FigureSave, PrintedLine
from app.figures import store
from app.filing import receipts
from app.filing.fill import FillError, fill_workbook
from app.scope import ask
from app.starting import workbook
from tests.conftest import make_run
from tests.mtool_fill_helpers import AGENT
from tests.test_fill_starting import PERSON, _last_year, _save, _set_cell, _value
from tests.test_scope_questions import _ask
from tests.test_starting_workbook import (  # noqa: F401 - the fixtures
    COMPANY_RM, OTHER_PPE, ROU, _comparative, _f, _figure, _import, _save_py, imported, signed_in,
)


def _agent_save(run_id, where, period, value):
    with db.connect() as conn:
        return store.save_figures(conn, run_id, [
            store.FigureWrite(_f(where), period, "Company", value, [store.Line("A line", 3, value)])], AGENT)[0]


# C5 ---------------------------------------------------------------------------------------------------------

def test_a_typed_figure_a_person_edited_stays_fixed_against_agents_and_is_written(tmp_path):
    path, cell = _last_year(tmp_path, [(OTHER_PPE, "PY", 900), (OTHER_PPE, "CY", 1100)])
    run = make_run([("SOFP", "CuNonCu")])
    _import(run, path)
    _save(run, [(OTHER_PPE, "CY", 1200)], PERSON)
    assert _figure(run, OTHER_PPE, "CY")["origin"] == "person"
    refused = _agent_save(run, OTHER_PPE, "CY", 5)
    assert refused["refused"] == ("A person typed this figure into the workbook, so leave a comment for the "
                                  "reviewer rather than changing it.")
    assert _figure(run, OTHER_PPE, "CY")["value"] == 1200
    report = fill_workbook(run, None, tmp_path / "filled.xlsx")
    assert _value(tmp_path / "filled.xlsx", cell[(OTHER_PPE, "CY")]) == ("N", "1200")
    assert [x["code"] for x in report["starting"]["replaced"]] == ["person_edit"]


def test_a_run_value_that_differs_from_its_typed_cell_is_never_kept_silently(tmp_path):
    path, cell = _last_year(tmp_path, [(OTHER_PPE, "PY", 900), (OTHER_PPE, "CY", 1100)])
    run = make_run([("SOFP", "CuNonCu")])
    _import(run, path)
    with db.connect() as conn:   # any route that is not a person's edit: the app shows another amount
        conn.execute("UPDATE figures SET value = 999 WHERE run_id = ? AND concept_uuid = ? AND period = 'CY'",
                     (run, _f(OTHER_PPE)))
    out = tmp_path / "filled.xlsx"
    report = fill_workbook(run, None, out)
    assert _value(out, cell[(OTHER_PPE, "CY")]) == ("N", "1100")      # the workbook's is kept, not overwritten
    line = next(x for x in report["unresolved"] if x["code"] == "run_differs")
    assert line["period"] == "CY" and "sheet" not in line
    assert report["status"] == "needs review"
    assert not [x for x in report["starting"]["kept_in_workbook"] if x["period"] == "CY"]


# C1 ---------------------------------------------------------------------------------------------------------

def test_a_scope_answer_cannot_change_the_setup_under_a_starting_workbook(imported):
    run_id, client = imported.run_id, imported.client
    assert _ask(run_id) == ask.ASKED
    response = client.post(f"/api/runs/{run_id}/question/answer", json={"choice": 0})
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This run starts from a workbook made for its current setup, so the standard cannot change here; start a "
        "new run with the right setup and a workbook that fits it.")
    with db.connect() as conn:
        assert conn.execute("SELECT standard FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "MFRS"


def test_the_fill_checks_the_workbook_still_fits_the_setup(tmp_path):
    path, _cell = _last_year(tmp_path, [(OTHER_PPE, "PY", 900)])
    run = make_run([("SOFP", "CuNonCu")])
    _import(run, path)
    with db.connect() as conn:
        conn.execute("UPDATE run_setup SET unit = ? WHERE run_id = ?", ("RM'000", run))
    out = tmp_path / "filled.xlsx"
    with pytest.raises(FillError) as refused:
        fill_workbook(run, None, out)
    assert str(refused.value) == ("The workbook is in RM but the report is in RM'000 (thousands), so this run's "
                                  "setup no longer fits the starting workbook and no file was made; start a new "
                                  "run with it.")
    assert not out.exists()


# C2 and C22 -------------------------------------------------------------------------------------------------

def test_a_save_with_a_kept_comparative_records_it_before_the_checks_run(imported):
    deps = imported.deps
    other, rou = (deps.outline.for_uuid(_f(w)).id for w in (OTHER_PPE, ROU))
    out = tools.save_figures(SimpleNamespace(deps=deps, run_step=1), [
        FigureSave(field=other, lines=[PrintedLine(label="Other PPE", page=2, cy=5, py=900)]),
        FigureSave(field=rou, lines=[PrintedLine(label="Right-of-use", page=2, py=70)])])
    assert out.splitlines()[0] == ("Saved 1 of 1 figure(s) by year; compared 2 of last year's figures kept from "
                                   "the workbook with the report.")
    assert _comparative(imported.run_id)["status"] == "passed"     # both readings are in the checks


def test_a_save_that_only_compares_counts_as_work_and_says_so(imported):
    deps = imported.deps
    before = deps.writes
    out = _save_py(deps, OTHER_PPE, 900)
    assert out.splitlines()[0] == "Compared 1 of last year's figures kept from the workbook with the report."
    assert "Saved 0 of 0" not in out
    assert deps.writes == before + 1


# C9 ---------------------------------------------------------------------------------------------------------

def test_the_figures_agent_sees_its_uncompared_kept_figures_and_differences_only_as_information(imported):
    run_id, deps = imported.run_id, imported.deps
    assert checking.relevant_to("SOFP", "prior_year_comparatives")   # the Reviewer's filter includes it
    out = checking.run_checks(SimpleNamespace(deps=deps))
    assert "Last year's figures kept from the workbook: 2 of 2 are not compared with the report yet" in out
    assert any("not compared" in c for c in deps.checks_open)
    _save_py(deps, OTHER_PPE, 950)
    _save_py(deps, ROU, 70)
    out = checking.run_checks(SimpleNamespace(deps=deps))
    assert "not compared" not in out                               # a difference never holds up the finish
    assert not [c for c in deps.checks_open if "kept from the workbook" in c or "950" in c]
    other = deps.outline.for_uuid(_f(OTHER_PPE))
    assert f"- {other.id} {other.name}: the workbook holds 900, you read 950." in out
    assert _comparative(run_id)["status"] == "warning"


def test_only_face_figures_with_no_category_are_compared(imported):
    run_id = imported.run_id
    with db.connect() as conn:
        family = run_family(conn, run_id)
        before = len(comparisons(conn, family, "Company"))
        conn.execute(
            "INSERT INTO figures(run_id, concept_uuid, period, entity_scope, dimension_key, value, status, origin, "
            "locked, source_ref, updated_by, updated_at) VALUES (?, ?, 'PY', 'Company', ?, 5, 'observed', "
            "'prior_workbook', 1, '{}', 'import', '')", (run_id, _f(OTHER_PPE), '{"x": "y_ZMember"}'))
        assert len(comparisons(conn, family, "Company")) == before == 2


# C6 ---------------------------------------------------------------------------------------------------------

def test_a_last_year_figure_where_the_workbook_was_blank_is_written_and_listed(tmp_path):
    path, _cell = _last_year(tmp_path, [(OTHER_PPE, "PY", 900)])
    run = make_run([("SOFP", "CuNonCu")])
    _import(run, path)
    _save(run, [(ROU, "PY", 40)])
    out = tmp_path / "filled.xlsx"
    report = fill_workbook(run, None, out)
    written = next(x for x in report["written"] if (x["concept_uuid"], x["period"]) == (_f(ROU), "PY"))
    assert _value(out, written["cell"]) == ("N", "40")
    added = report["starting"]["prior_year_added"]
    assert [(x["concept_uuid"], x["code"]) for x in added] == [(_f(ROU), "prior_year_added")]
    assert report["status"] == "needs review"
    line = next(x for x in receipts.receipt(report)["lines"] if x["kind"] == "prior_year_added")
    assert "Last year's filing had no figure here" in line["reason"]


# C7 ---------------------------------------------------------------------------------------------------------

def test_another_amount_read_during_a_sign_question_is_an_ordinary_difference(imported):
    run_id, deps = imported.run_id, imported.deps
    assert "the same amount with the opposite sign" in _save_py(deps, ROU, -70)
    out = _save_py(deps, ROU, 75)
    assert "Last year's workbook holds 70 but you read 75, a difference of 5." in out
    assert "opposite sign" not in out
    check = _comparative(run_id)["message"]
    assert "the report shows 75, a difference of 5" in check and "opposite sign" not in check
    assert "the same amount with the opposite sign" in _save_py(deps, ROU, -70)
    assert "shows -70: the same amount with the opposite sign" in _comparative(run_id)["message"]


# C8 ---------------------------------------------------------------------------------------------------------

def test_a_year_end_held_as_a_date_is_read_and_a_missing_one_is_refused(tmp_path):
    assert workbook._iso("44561") == "2021-12-31" and workbook._iso("31/12/2021") == "2021-12-31"
    path, _cell = _last_year(tmp_path, [(OTHER_PPE, "PY", 900)])
    _set_cell(path, "FilingInfo!E24", "<v>44561</v>")
    assert workbook.facts(workbook.read_cells(str(path)))["year_end"] == "2021-12-31"
    _set_cell(path, "FilingInfo!E24", "<is><t>sometime</t></is>")
    _set_cell(path, "StartUp!L13", "<is><t>sometime</t></is>")
    with pytest.raises(workbook.Refused) as refused:
        _import(make_run([("SOFP", "CuNonCu")]), path)
    assert str(refused.value) == ("The workbook does not say its year end, so it cannot be checked against the "
                                  "report; set it in the workbook's filing information.")
