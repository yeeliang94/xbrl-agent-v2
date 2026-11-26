"""Go-live plan A3: "This year only" at setup, and amounts in RM, RM thousands
or RM millions carried through setup, the agents' opening messages, the
checks, scoring, the starting workbook and the mTool fill. Figures are never
rescaled: the third unit must change nothing but its name."""
from __future__ import annotations

import copy
import io
import zipfile

import pytest

from app import db
from app.catalog import lookup
from app.catalog.fields import run_fields
from app.checks.runner import read_checks
from app.extraction import instructions as figures_instructions
from app.figures import store
from app.filing.fill import fill_workbook
from app.notes import instructions as notes_instructions
from app.reading import map_checks, store as reading
from app.reading.map_schema import DocumentMap
from app.review import instructions as review_instructions
from app.runs import units
from app.scope import fields as scope
from app.scoring.compare import kind_of
from app.scoring.workbook_read import read_filled_workbook
from app.starting import workbook as starting_workbook
from app.workbook.xlsx_cells import read_workbook
from tests import reading_fakes as fakes
from tests.conftest import OWNER, field, login, make_run, make_user
from tests.mtool_fill_helpers import AGENT, GENUINE, TEMPLATES, matching_run, seed_input_figures
from tests.test_setup_confirm import GOOD, mapped_run

SOFP = "mfrs-company-sofp-cunoncu-v1"
FIRST_TIME = TEMPLATES / "mTool_MFRS_Group_FirstTime_SOFP-CuNonCu_SOPL-Function_SOCI-NetOfTax_SOCF-Indirect_SOCIE_RM.xlsx"
THOUSANDS = TEMPLATES / "mTool_MFRS_Company_SOFP-CuNonCu_SOPL-Function_SOCI-NetOfTax_SOCF-Indirect_SOCIE_RM000.xlsx"
ACTUALS = TEMPLATES / "mTool_MFRS_Company_SOFP-CuNonCu_SOPL-Function_SOCI-NetOfTax_SOCF-Indirect_SOCIE_RM.xlsx"
UNITS = ["RM", "RM'000", "RM'000,000"]


@pytest.fixture
def signed_in(client):
    make_user(OWNER)
    assert login(client, OWNER).status_code == 200
    return client


def body(**changes) -> dict:
    out = copy.deepcopy(GOOD)
    out.update(changes)
    return out


def set_unit(run_id: int, unit: str) -> None:
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE run_setup SET unit = ? WHERE run_id = ?", (unit, run_id))


def millions_template(tmp_path):
    """The genuine thousands template with its level of rounding set to SSM's millions value, as mTool
    writes it. No genuine millions template is in the repository."""
    with zipfile.ZipFile(THOUSANDS) as zf:
        data = {name: zf.read(name) for name in zf.namelist()}
    strings = data["xl/sharedStrings.xml"]
    assert strings.count(b"In thousands ('000')") == 1
    data["xl/sharedStrings.xml"] = strings.replace(b"In thousands ('000')", b"In millions ('000,000')")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in data.items():
            zf.writestr(name, payload)
    path = tmp_path / "millions-template.xlsx"
    path.write_bytes(buffer.getvalue())
    return path


# Reporting period ---------------------------------------------------------------

def test_setup_saves_this_year_only_and_the_run_then_refuses_a_prior_year_figure(signed_in):
    run_id = mapped_run(signed_in)
    response = signed_in.post(f"/api/runs/{run_id}/setup", json=body(first_statements=True))
    assert response.status_code == 200, response.text
    concept = field(SOFP, "SOFP-CuNonCu", 11)
    with db.connect(immediate=True) as conn:
        assert conn.execute("SELECT first_statements FROM run_setup WHERE run_id = ?", (run_id,)).fetchone()[0] == 1
        family = lookup.run_family(conn, run_id)
        results = store.save_figures(conn, run_id, [
            store.FigureWrite(concept, "PY", "Company", 100.0, [store.Line("A line", 2, 100.0)]),
            store.FigureWrite(concept, "CY", "Company", 120.0, [store.Line("A line", 2, 120.0)])], AGENT)
        event = conn.execute("SELECT data_json FROM events WHERE run_id = ? AND source = 'setup'", (run_id,)).fetchone()
    assert family.first_statements and family.periods == ("CY",)
    assert results[0]["refused"] == "These are the company's first financial statements, so there is no prior year to save."
    assert results[1]["ok"]
    assert '"first_statements": true' in event["data_json"]


def test_setup_keeps_both_years_unless_told_and_refuses_anything_but_yes_or_no(signed_in):
    run_id = mapped_run(signed_in)
    refused = signed_in.post(f"/api/runs/{run_id}/setup", json=body(first_statements="yes"))
    assert refused.status_code == 422
    assert refused.json() == {"detail": "Say whether the report covers this year and last year, or this year only."}
    assert signed_in.post(f"/api/runs/{run_id}/setup", json=GOOD).status_code == 200   # no first_statements sent
    with db.connect() as conn:
        assert conn.execute("SELECT first_statements FROM run_setup WHERE run_id = ?", (run_id,)).fetchone()[0] == 0
        assert lookup.run_family(conn, run_id).periods == ("CY", "PY")
        assert scope.current_setup(conn, run_id)["first_statements"] is False


def test_a_this_year_only_run_fills_the_first_time_template_with_no_prior_year(tmp_path):
    run_id = matching_run(FIRST_TIME)
    writes = seed_input_figures(run_id, every=3)
    assert writes and {w.period for w in writes} == {"CY"}

    report = fill_workbook(run_id, FIRST_TIME, tmp_path / "filled.xlsx")

    assert report["status"] == "ok" and report["template"]["compatibility"] == "known"
    assert report["mismatched"] == [] and len(report["written"]) > 50
    assert {line["period"] for line in report["written"]} == {"CY"}
    # The first-time template has no column for last year at all: nothing is placed there.
    with db.connect() as conn:
        read = read_filled_workbook(conn, lookup.run_family(conn, run_id), str(tmp_path / "filled.xlsx"))
    assert read.cells and {key[1] for key in read.cells} == {"CY"}


def test_the_reader_may_suggest_first_statements_and_setup_asks_the_person(signed_in):
    run_id = mapped_run(signed_in)
    first = fakes.finding("yes", (2, 3), "Every statement has one column of amounts.")
    with db.connect(immediate=True) as conn:
        reading.save_map(conn, run_id, fakes.good_map(first_statements=first), [])
    setup = signed_in.get(f"/api/runs/{run_id}/setup").json()["setup"]
    assert setup["first_statements"]["value"] == "yes"
    card = next(q for q in setup["questions"] if q["field"] == "period")
    assert card["question"] == "No figures for last year were found. Are these the company's first financial statements?"
    assert (card["reason"], card["pages"]) == ("Every statement has one column of amounts.", [2, 3])
    assert [(c["value"], c["label"], c["suggested"]) for c in card["choices"]] == [
        ("only", "Yes, this year only", True), ("both", "No, this year and last year", False)]
    # The suggestion is never saved by itself: the run stays at both years until a person confirms.
    with db.connect() as conn:
        assert conn.execute("SELECT first_statements FROM run_setup WHERE run_id = ?", (run_id,)).fetchone()[0] == 0


@pytest.mark.parametrize("first", [None, "no"])
def test_setup_does_not_ask_when_the_reader_saw_last_year_or_never_looked(signed_in, first):
    run_id = mapped_run(signed_in)
    if first:
        with db.connect(immediate=True) as conn:
            reading.save_map(conn, run_id, fakes.good_map(
                first_statements=fakes.finding(first, (2,), "Two columns of amounts.")), [])
    setup = signed_in.get(f"/api/runs/{run_id}/setup").json()["setup"]
    assert [q for q in setup["questions"] if q["field"] == "period"] == []


def test_the_readers_first_statements_finding_is_checked_like_the_rest_of_the_map():
    good = DocumentMap.model_validate(fakes.good_map(first_statements=fakes.finding(" Yes ", (2,), "One column.")))
    assert map_checks.problems(good, 4) == [] and good.first_statements.value == "yes"
    bad = DocumentMap.model_validate(fakes.good_map(first_statements=fakes.finding("maybe", (9,), "")))
    assert map_checks.problems(bad, 4) == [
        "Say yes or no for first statements: yes when no statement prints figures for a prior year.",
        "Give a one-sentence reason for first statements.",
        "Page 9 for first statements is outside the document, which has 4 pages, so cite the PDF page number, "
        "not the printed folio."]
    assert map_checks.problems(DocumentMap.model_validate(fakes.good_map()), 4) == []   # a map without it still saves


# Three units ----------------------------------------------------------------------

@pytest.mark.parametrize("unit", UNITS)
def test_setup_takes_each_unit_and_refuses_any_other(signed_in, unit):
    run_id = mapped_run(signed_in)
    refused = signed_in.post(f"/api/runs/{run_id}/setup", json=body(unit="RM billions"))
    assert refused.status_code == 422
    assert refused.json() == {"detail": "Choose whether amounts are in RM, RM thousands or RM millions."}
    assert signed_in.post(f"/api/runs/{run_id}/setup", json=body(unit=unit)).status_code == 200
    with db.connect() as conn:
        assert conn.execute("SELECT unit FROM run_setup WHERE run_id = ?", (run_id,)).fetchone()[0] == unit
        assert scope.valid("unit", unit)


@pytest.mark.parametrize("printed, unit", [
    ("RM", "RM"), ("RM '000", "RM'000"), ("RM’000", "RM'000"), ("RM million", "RM'000,000"),
    ("RM'm", "RM'000,000"), ("RM mil", "RM'000,000"), ("RM'000,000", "RM'000,000"), ("RM’000,000", "RM'000,000"),
])
def test_the_reader_s_unit_is_read_in_the_forms_a_report_prints(printed, unit):
    doc_map = DocumentMap.model_validate(fakes.good_map(unit=fakes.finding(printed, (2, 3))))
    assert map_checks.problems(doc_map, 4) == [] and doc_map.unit.value == unit


@pytest.mark.parametrize("unit, words", [("RM", "RM"), ("RM'000", "RM thousands"), ("RM'000,000", "RM millions")])
def test_every_agent_is_told_the_unit_in_words_and_never_to_rescale(unit, words):
    figures = figures_instructions.first_message(
        statement_name="statement of financial position", company="Contoh Sdn. Bhd.", year_end="2025-12-31",
        standard="MFRS", level="Company", unit=unit, page_count=10, statement_pages=[4], other_statements=[],
        notes=[], outline_text="")
    notes = notes_instructions.first_message(
        session=next(iter(notes_instructions.SESSIONS)), company="Contoh Sdn. Bhd.", year_end="2025-12-31",
        standard="MFRS", level="Company", unit=unit, page_count=10, notes=[], standing=[], sections=[])
    review = review_instructions.first_message(
        round_number=1, company="Contoh Sdn. Bhd.", year_end="2025-12-31", standard="MFRS", unit=unit,
        page_count=10, statement_name="statement of financial position", statement_pages=[4], notes=[],
        comments=[], failing=[], outline_text="")
    assert f"Amounts are in {words} as printed ({unit}); never rescale them." in figures
    assert f"Amounts are in {words} as printed ({unit})." in notes
    assert f"Amounts are in {words} as printed ({unit})." in review
    assert scope.label("unit", unit) == words == units.unit_words(unit)


def _balance(run_id: int, assets: float, equity: float, liabilities: float) -> str:
    with db.connect(immediate=True) as conn:
        for row, value in ((11, assets), (41, equity), (52, liabilities)):
            saved = store.save_figure(conn, run_id, store.FigureWrite(
                field(SOFP, "SOFP-CuNonCu", row), "CY", "Company", value, [store.Line("Printed", 5, value)]), AGENT)
            assert saved["value"] == value                     # stored as printed, decimals and all
        return next(c for c in read_checks(conn, run_id) if c["name"] == "sofp_balance")["status"]


@pytest.mark.parametrize("unit", UNITS)
def test_the_checks_judge_the_printed_amounts_the_same_in_every_unit(unit):
    balanced, wrong = make_run(), make_run()
    set_unit(balanced, unit)
    set_unit(wrong, unit)
    # A report in millions prints decimals: 1,234.5 = 734.2 + 500.3.
    assert _balance(balanced, 1234.5, 734.2, 500.3) == "passed"
    assert _balance(wrong, 1234.5, 734.2, 497.8) == "failed"


@pytest.mark.parametrize("person, run, kind", [
    (12.5, 12.5, "agree"), (12.5, -12.5, "sign_only"), (12.5, 12500.0, "scale"), (12.5, 12_500_000.0, "scale"),
    (12_500.0, 12_500_000.0, "scale"), (12.5, 40.0, "different"), (12.5, None, "missing"),
])
def test_scoring_compares_amounts_as_printed_and_names_a_thousand_or_a_million_times_gap(person, run, kind):
    assert kind_of(person, run) == kind


def test_a_workbook_in_millions_says_so_and_a_starting_workbook_must_match_the_run(tmp_path):
    millions = read_workbook(str(millions_template(tmp_path)))[1]
    assert starting_workbook.facts(millions)["unit"] == "RM'000,000"
    assert starting_workbook.facts(read_workbook(str(THOUSANDS))[1])["unit"] == "RM'000"
    assert starting_workbook.facts(read_workbook(str(ACTUALS))[1])["unit"] == "RM"
    assert [units.from_rounding(t) for t in ("Actuals", "In thousands ('000')", "In millions ('000,000')", "", None)] == [
        "RM", "RM'000", "RM'000,000", None, None]
    with db.connect() as conn:
        family = lookup.run_family(conn, matching_run(THOUSANDS))
        with pytest.raises(starting_workbook.Refused) as caught:
            starting_workbook.check_fit(conn, family, str(millions_template(tmp_path)),
                                        {"unit": "RM'000", "year_end": None})
    assert str(caught.value) == ("The workbook is in RM'000,000 (millions) but the report is in RM'000 (thousands), "
                                 "so attach a workbook in the same unit.")


def test_a_millions_run_fills_a_millions_template_as_printed_and_scoring_reads_it_back(tmp_path):
    template = millions_template(tmp_path)
    run_id = matching_run(THOUSANDS)
    set_unit(run_id, "RM'000,000")
    with db.connect(immediate=True) as conn:
        family = lookup.run_family(conn, run_id)
        leaves = [f for f in run_fields(conn, family).values() if f.sheet == "SOFP-Sub-CuNonCu" and not f.is_total
                  and lookup.concept(conn, f.concept_uuid).writable][:3]
        amounts = [1234.5, -0.75, 12.34]                       # as a report in millions prints them
        saved = store.save_figures(conn, run_id, [
            store.FigureWrite(f.concept_uuid, "CY", "Company", value, [store.Line(f.plain_label, 4, value)])
            for f, value in zip(leaves, amounts)], AGENT)
        assert all(r["ok"] for r in saved), saved
    out = tmp_path / "filled.xlsx"

    report = fill_workbook(run_id, template, out)

    assert report["status"] == "ok", (report["template"], report["unresolved"][:2], report["mismatched"][:2])
    assert report["template"]["compatibility"] == "known" and report["template"]["reasons"] == []
    written = {line["concept_uuid"]: line["value"] for line in report["written"]}
    assert [written[f.concept_uuid] for f in leaves] == amounts
    with db.connect() as conn:
        read = read_filled_workbook(conn, family, str(out))
    assert [read.cells[(f.concept_uuid, "CY", "Company", "")].value for f in leaves] == amounts
    assert starting_workbook.facts(read_workbook(str(out))[1])["unit"] == "RM'000,000"   # the template's own unit stays


@pytest.mark.parametrize("unit, template, differs", [
    ("RM", ACTUALS, None), ("RM'000", THOUSANDS, None),
    ("RM'000,000", THOUSANDS, "The template is in RM thousands but the report is in RM millions"),
    ("RM'000", ACTUALS, "The template is in RM but the report is in RM thousands"),
    ("RM", THOUSANDS, "The template is in RM thousands but the report is in RM"),
])
def test_a_template_in_another_unit_than_the_run_is_flagged_for_a_check(tmp_path, unit, template, differs):
    run_id = matching_run(template)
    set_unit(run_id, unit)
    seed_input_figures(run_id, every=40)

    report = fill_workbook(run_id, template, tmp_path / "filled.xlsx")

    if differs is None:
        assert report["template"]["reasons"] == [] and report["status"] == "ok"
    else:
        assert report["status"] == "needs review"
        assert report["template"]["reasons"] == [
            f"{differs}, so mTool would read every amount in the wrong unit; make the template in mTool with "
            "the same level of rounding and fill it again."]
    assert GENUINE   # the genuine templates are what these tests fill
