"""The checks, run from saved figures. Cases follow v1's check tests
(`test_cross_checks`, `test_group_checks`, `test_socf_articulation`,
`test_attribution_footing`, `test_cross_checks_mpers_socie`,
`test_notes_numeric_footing`, `test_notes_face_tieouts`,
`test_socf_section_placement`), rewritten against figures instead of
filled workbooks."""
from __future__ import annotations

from app import db
from app.checks.placement_checks import citation_disagreements, classify_section
from app.checks.runner import read_checks
from app.figures import store
from app.figures.store import Actor, FigureWrite, Line
from conftest import field, field_by_label, make_run

AGENT = Actor("agent", "figures agent")
PERSON = Actor("person", "ana@firm.com")
SOFP = "mfrs-company-sofp-cunoncu-v1"
SOCF = "mfrs-company-socf-indirect-v1"
SOPL = "mfrs-company-sopl-function-v1"
SOCIE = "mfrs-company-socie-v1"


def save(run_id, concept, value, period="CY", scope="Company", *, section="", dims=None, **kw):
    with db.connect() as conn:
        return store.save_figure(conn, run_id, FigureWrite(
            concept, period, scope, value, [Line("Printed", 5, value, section=section)], dims, **kw), AGENT)


def check(run_id, name, scope="Company") -> dict:
    with db.connect() as conn:
        return next(c for c in read_checks(conn, run_id) if c["name"] == name and c["entity_scope"] == scope)


def _balance_sheet(run_id, assets, equity, liabilities, period="CY", scope="Company", template=SOFP):
    save(run_id, field(template, "SOFP-CuNonCu", 11), assets, period, scope)       # right-of-use assets
    save(run_id, field(template, "SOFP-CuNonCu", 41), equity, period, scope)       # retained earnings
    return save(run_id, field(template, "SOFP-CuNonCu", 52), liabilities, period, scope)  # lease liabilities


def test_balance_check_fails_on_a_wrong_figure_and_passes_once_it_is_corrected():
    run_id = make_run()
    wrong = _balance_sheet(run_id, 1000, 600, 300)
    failed = check(run_id, "sofp_balance")
    assert failed["status"] == "failed"
    assert (failed["expected"], failed["actual"], failed["diff"]) == (1000, 900, 100)
    assert failed["target_concept_uuid"] == field(SOFP, "SOFP-CuNonCu", 75)
    with db.connect() as conn:
        store.save_figure(conn, run_id, FigureWrite(wrong["concept_uuid"], "CY", "Company", 400, None), PERSON)
    assert check(run_id, "sofp_balance")["status"] == "passed"


def test_a_check_with_nothing_to_judge_is_not_assessed_never_passed():
    run_id = make_run([("SOFP", "CuNonCu"), ("SOCF", "Indirect")])
    assert check(run_id, "sofp_balance")["status"] == "not_assessed"
    _balance_sheet(run_id, 1000, 600, 400)
    assert check(run_id, "sofp_balance")["status"] == "passed"
    assert check(run_id, "socf_to_sofp_cash")["status"] == "not_assessed"
    assert check(run_id, "sopl_to_socie_profit")["status"] == "not_assessed"
    assert check(run_id, "sore_to_sofp_retained_earnings")["status"] == "not_applicable"


def test_group_filings_are_checked_for_group_and_company_columns_separately():
    run_id = make_run(level="Group")
    group_sofp = "mfrs-group-sofp-cunoncu-v1"
    _balance_sheet(run_id, 1000, 600, 400, scope="Group", template=group_sofp)
    _balance_sheet(run_id, 800, 500, 200, scope="Company", template=group_sofp)
    assert check(run_id, "sofp_balance", "Group")["status"] == "passed"
    company = check(run_id, "sofp_balance", "Company")
    assert company["status"] == "failed" and "[company]" in company["comparands"][0]["label"]
    with db.connect() as conn:
        assert [c["entity_scope"] for c in read_checks(conn, run_id)][:1] == ["Group"]


def test_socf_articulation_fails_until_closing_cash_agrees():
    run_id = make_run([("SOCF", "Indirect")])
    save(run_id, field(SOCF, "SOCF-Indirect", 8), 50)      # profit before tax
    save(run_id, field(SOCF, "SOCF-Indirect", 131), 100)   # cash at beginning
    closing = save(run_id, field(SOCF, "SOCF-Indirect", 132), 160)
    result = check(run_id, "socf_articulation")
    assert result["status"] == "failed" and result["expected"] == 150 and result["actual"] == 160
    with db.connect() as conn:
        store.save_figure(conn, run_id, FigureWrite(closing["concept_uuid"], "CY", "Company", 150, None), PERSON)
    assert check(run_id, "socf_articulation")["status"] == "passed"


def test_a_company_profit_must_be_attributed_to_its_owners():
    run_id = make_run([("SOPL", "Function")])
    save(run_id, field(SOPL, "SOPL-Function", 11), 100)   # selling and distribution expenses
    missing = check(run_id, "sopl_attribution_footing")
    assert missing["status"] == "failed" and missing["message"].startswith(
        "Profit (loss), attributable to owners of parent is blank for the Company, this year.")
    save(run_id, field(SOPL, "SOPL-Function", 28), -100)  # attributable to owners of parent
    assert check(run_id, "sopl_attribution_footing")["status"] == "passed"


def test_equity_statement_closing_equity_and_profit_agree_with_the_other_statements():
    run_id = make_run([("SOFP", "CuNonCu"), ("SOPL", "Function"), ("SOCIE", "Default")])
    save(run_id, field_by_label(SOCIE, "Equity at beginning of period", matrix_col="C"), 500)
    save(run_id, field_by_label(SOCIE, "Profit (loss)", matrix_col="C"), 100)
    _balance_sheet(run_id, 700, 600, 100)
    assert check(run_id, "socie_to_sofp_equity")["status"] == "passed"
    save(run_id, field(SOPL, "SOPL-Function", 11), -100)  # selling expenses saved as a negative
    profit = check(run_id, "sopl_to_socie_profit")
    assert profit["status"] == "passed", profit["message"]


def test_mpers_retained_earnings_statement_is_checked_against_the_balance_sheet():
    run_id = make_run([("SOFP", "CuNonCu"), ("SOCIE", "SoRE")], standard="MPERS")
    sore = "mpers-company-sore-v1"
    save(run_id, field_by_label(sore, "Retained earnings at end of period"), 600, total="no_breakdown")
    save(run_id, field_by_label("mpers-company-sofp-cunoncu-v1", "Retained earnings"), 650)
    assert check(run_id, "sore_to_sofp_retained_earnings")["status"] == "failed"
    assert check(run_id, "socie_to_sofp_equity")["status"] == "not_applicable"


def test_a_cash_flow_line_saved_outside_its_printed_section_is_a_warning():
    run_id = make_run([("SOCF", "Indirect")])
    save(run_id, field(SOCF, "SOCF-Indirect", 69), -65345, section="Financing activities")  # operating row
    result = check(run_id, "socf_section_placement")
    assert result["status"] == "warning" and "financing" in result["message"]
    save(run_id, field(SOCF, "SOCF-Indirect", 124), -1000, section="Cash flows from financing activities")
    assert classify_section("Cash flows from investing and financing") is None


def test_share_capital_note_figures_that_do_not_add_up_are_reported():
    run_id = make_run()
    note = "mfrs-company-notes-issuedcapital-v1"
    axis = {"ifrs-full_ClassesOfShareCapitalAxis": "ifrs-full_OrdinarySharesMember"}
    opening, closing = field(note, "Notes-Issuedcapital", 11), field(note, "Notes-Issuedcapital", 18)
    save(run_id, opening, 1000)
    save(run_id, closing, 1200)
    save(run_id, closing, 1100, dims=axis)
    result = check(run_id, "notes_numeric_footing")
    assert result["status"] == "warning"
    assert "the categories add up to 1,100, but the total is 1,200" in result["message"]
    assert "opening 1,000 plus movements 0 is 1,000, but the closing balance is 1,200" in result["message"]


def test_share_capital_on_the_balance_sheet_must_agree_with_the_note():
    run_id = make_run()
    note = "mfrs-company-notes-issuedcapital-v1"
    save(run_id, field(SOFP, "SOFP-Sub-CuNonCu", 200), 2000000)   # capital from ordinary shares
    save(run_id, field(note, "Notes-Issuedcapital", 18), 2000)     # a thousands mix-up
    assert check(run_id, "notes_face_tieouts")["status"] == "failed"
    save(run_id, field(note, "Notes-Issuedcapital", 18), 2000000)
    assert check(run_id, "notes_face_tieouts")["status"] == "passed"


def test_a_printed_total_that_differs_from_its_lines_is_a_warning():
    run_id = make_run()
    _balance_sheet(run_id, 1000, 600, 400)
    with db.connect() as conn:
        store.save_figure(conn, run_id, FigureWrite(field(SOFP, "SOFP-CuNonCu", 23), "CY", "Company", 1100,
                                                     [Line("Total non-current assets", 5, 1100)],
                                                     total="printed"), AGENT)
    result = check(run_id, "printed_totals")
    assert result["status"] == "warning"
    assert result["message"] == ("For the Company, this year, the report prints Total non-current assets as "
                                 "1,100, but the saved lines add up to 1,000, a difference of 100.")


def test_policy_and_disclosure_notes_with_disjoint_pages_disagree():
    pairs = [("Description of accounting policy for leases", "Disclosure of leases")]
    assert citation_disagreements({"description of accounting policy for leases": {27}},
                                  {"disclosure of leases": {25}}, pairs)
    assert not citation_disagreements({"description of accounting policy for leases": {27, 28}},
                                      {"disclosure of leases": {28}}, pairs)


def _ppe_status(run_id):
    from app.figures import views

    with db.connect() as conn:
        rows = views.statement_view(conn, run_id, "SOFP", "template")["rows"]
    return next(r for r in rows if r["sheet"] == "SOFP-Sub-CuNonCu" and r["row"] == 39)


def test_a_total_with_no_breakdown_that_its_later_lines_disagree_with_is_flagged_in_either_order():
    other_ppe, total = field(SOFP, "SOFP-Sub-CuNonCu", 38), field(SOFP, "SOFP-Sub-CuNonCu", 39)
    sentence = ("For the Company, this year, Total property, plant and equipment is saved as 150 with no "
                "breakdown, but the lines saved under it add up to 100, a difference of 50.")
    # The total first, then a line under it.
    run_id = make_run()
    save(run_id, total, 150, total="no_breakdown")
    assert check(run_id, "printed_totals")["status"] == "passed"
    save(run_id, other_ppe, 100)
    result = check(run_id, "printed_totals")
    assert (result["status"], result["message"]) == ("warning", sentence)
    row = _ppe_status(run_id)
    assert row["status"] == "differs_from_report" and row["cells"]["Company:CY"]["lines_sum"] == 100
    assert row["cells"]["Company:CY"]["value"] == 150  # never switched to the sum of its lines
    # The lines first, then the total: it must agree when saved, and a later change to a line is flagged.
    run_id = make_run()
    save(run_id, other_ppe, 150)
    save(run_id, total, 150, total="no_breakdown")
    assert check(run_id, "printed_totals")["status"] == "passed" and _ppe_status(run_id)["status"] is None
    save(run_id, other_ppe, 100)
    result = check(run_id, "printed_totals")
    assert (result["status"], result["message"]) == ("warning", sentence)
    assert _ppe_status(run_id)["status"] == "differs_from_report"


def test_printed_totals_use_the_shared_tolerance():
    run_id = make_run()
    save(run_id, field(SOFP, "SOFP-CuNonCu", 11), 1000)
    with db.connect() as conn:
        store.save_figure(conn, run_id, FigureWrite(field(SOFP, "SOFP-CuNonCu", 23), "CY", "Company", 1000.5,
                                                     [Line("Total non-current assets", 5, 1000.5)],
                                                     total="printed"), AGENT)
    assert check(run_id, "printed_totals")["status"] == "passed"


def test_check_messages_name_a_blank_line_and_state_a_difference_in_words():
    run_id = make_run()
    save(run_id, field(SOFP, "SOFP-CuNonCu", 11), 1000)   # assets only
    result = check(run_id, "sofp_balance")
    assert result["message"].startswith("Total equity and liabilities is blank for the Company, this year.")
    assert "None" not in result["message"] and "diff=" not in result["message"]
    save(run_id, field(SOFP, "SOFP-CuNonCu", 41), 600)
    result = check(run_id, "sofp_balance")
    assert result["message"].startswith(
        "For the Company, this year, Total assets is 1,000 and Total equity and liabilities is 600, "
        "a difference of 400.")
    assert (result["expected"], result["actual"], result["diff"]) == (1000, 600, 400)
