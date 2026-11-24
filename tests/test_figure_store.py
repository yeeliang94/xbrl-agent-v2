"""The figure store: the eight hard stops, history, restore, moves and totals."""
from __future__ import annotations

import pytest

from app import db
from app.figures import store
from app.figures.store import Actor, FigureWrite, Line, Refused
from conftest import field, make_run

SOFP = "mfrs-company-sofp-cunoncu-v1"
AGENT = Actor("agent", "figures agent")
PERSON = Actor("person", "ana@firm.com")
FACE, SUB = "SOFP-CuNonCu", "SOFP-Sub-CuNonCu"


def _line(amount, label="Printed line", page=7, **kw):
    return [Line(label, page, amount, **kw)]


def _save(run_id, concept, value, *, period="CY", lines="auto", actor=AGENT, **kw):
    if lines == "auto":
        lines = _line(value)
    with db.connect() as conn:
        return store.save_figure(conn, run_id, FigureWrite(concept, period, "Company", value, lines, **kw), actor)


def _refusal(run_id, concept, value, **kw) -> str:
    with pytest.raises(Refused) as caught:
        _save(run_id, concept, value, **kw)
    return str(caught.value)


def _value(run_id, concept, period="CY"):
    with db.connect() as conn:
        found = [f for f in store.run_figures(conn, run_id)
                 if f["concept_uuid"] == concept and f["period"] == period]
    return found[0]["value"] if found else None


def test_a_value_in_a_heading_row_is_refused_with_a_plain_sentence():
    run_id = make_run()
    assert _refusal(run_id, field(SOFP, FACE, 7), 100) == (
        "Non-current assets is a heading and cannot hold a value, so save the figure on a line under it.")
    with db.connect() as conn:
        assert store.run_figures(conn, run_id) == []


def test_a_typed_value_on_a_calculated_total_is_refused():
    run_id = make_run()
    assert _refusal(run_id, field(SOFP, FACE, 23), 500) == (
        "Total non-current assets is added up from the lines under it, so save those lines, "
        "or save this total as printed or as a total with no breakdown.")


def test_a_total_with_no_breakdown_is_refused_when_its_lines_disagree():
    run_id = make_run()
    _save(run_id, field(SOFP, SUB, 38), 100)  # Other property, plant and equipment
    assert _refusal(run_id, field(SOFP, SUB, 39), 150, total="no_breakdown") == (
        "The lines under Total property, plant and equipment already add up to 100, "
        "so correct or clear them before saving this total with no breakdown.")
    # When the lines agree it is accepted.
    assert _save(run_id, field(SOFP, SUB, 39), 100, total="no_breakdown")["value"] == 100


def test_a_zero_needs_a_printed_amount_and_lines_that_add_to_zero_are_accepted():
    run_id = make_run()
    rou = field(SOFP, FACE, 11)
    assert _refusal(run_id, rou, 0, lines=_line(None)) == (
        "Give the printed amount of the line that shows this zero, such as 0 or a dash, "
        "because a zero needs a printed source like any other figure.")
    saved = _save(run_id, rou, 0, lines=_line(0))
    assert (saved["value"], saved["status"]) == (0, "explicit_zero")
    # A true zero made of printed lines that cancel out is a correct figure.
    netted = _save(run_id, field(SOFP, FACE, 20), 0, lines=[
        Line("Deferred tax assets", 7, 500), Line("Set off against liabilities", 7, 500, coefficient=-1)])
    assert (netted["value"], netted["status"]) == (0, "explicit_zero")


def test_a_value_that_is_not_the_sum_of_its_printed_lines_is_refused_with_its_cause():
    run_id = make_run()
    rou = field(SOFP, FACE, 11)
    assert _refusal(run_id, rou, 900, lines=_line(1000)) == (
        "The printed lines given add up to 1,000 but the value given is 900, so check the sign of each line "
        "and whether a line is missing, because a value must be the sum of its printed lines and not a "
        "number found by subtraction.")
    assert _refusal(run_id, rou, 900, lines=[Line("Buildings", 7, 1000), Line("Vehicles", 7, None)]) == (
        "Give the printed amount of each line given for this figure, so the value can be checked against them.")
    # Adding printed lines is not plugging.
    saved = _save(run_id, rou, 1500, lines=[Line("Buildings", 7, 1000), Line("Vehicles", 7, 500)])
    assert saved["value"] == 1500 and len(saved["lines"]) == 2


def test_a_figure_with_no_source_page_is_refused():
    run_id = make_run()
    sentence = "Give the page and the line as printed for this figure, because every figure needs its source."
    assert _refusal(run_id, field(SOFP, FACE, 11), 100, lines=[]) == sentence
    assert _refusal(run_id, field(SOFP, FACE, 11), 100, lines=_line(100, page=0)) == sentence
    assert _refusal(run_id, field(SOFP, FACE, 11), 100, lines=_line(100, label=" ")) == sentence


def test_prior_year_figures_are_refused_on_first_financial_statements():
    run_id = make_run(first_statements=True)
    assert _refusal(run_id, field(SOFP, FACE, 11), 100, period="PY") == (
        "These are the company's first financial statements, so there is no prior year to save.")
    assert _save(run_id, field(SOFP, FACE, 11), 100)["value"] == 100


def test_a_figure_kept_from_last_years_workbook_is_refused_for_everyone():
    run_id = make_run()
    rou = field(SOFP, FACE, 11)
    with db.connect() as conn:
        imported = store.import_figure(conn, run_id, FigureWrite(rou, "PY", "Company", 100, []), "last.xlsx!D11")
    assert (imported["locked"], imported["origin"], imported["value"]) == (True, "prior_workbook", 100)
    sentence = ("This prior-year figure is kept as filed in last year's workbook, so leave a comment "
                "if the report shows a different amount.")
    assert _refusal(run_id, rou, 120, period="PY") == sentence
    assert _refusal(run_id, rou, 120, period="PY", actor=PERSON) == sentence


def test_only_a_person_settles_a_sign_only_difference():
    run_id = make_run()
    figure = _save(run_id, field(SOFP, FACE, 11), 100)
    with db.connect() as conn:
        store.mark_sign_question(conn, run_id, figure["id"], "Last year's workbook shows -100.")
    sentence = ("Only a person can settle a sign-only difference with last year's workbook, "
                "so leave a comment for the reviewer.")
    with db.connect() as conn, pytest.raises(Refused) as caught:
        store.confirm_figure(conn, run_id, figure["id"], AGENT)
    assert str(caught.value) == sentence
    assert _refusal(run_id, field(SOFP, FACE, 11), -100, lines=_line(-100)) == sentence
    with db.connect() as conn:
        settled = store.confirm_figure(conn, run_id, figure["id"], PERSON)
    assert settled["sign_question"] is False and settled["certainty"] == "sure"


def test_requests_that_do_not_fit_the_run_are_refused():
    run_id = make_run()
    with db.connect() as conn, pytest.raises(Refused) as caught:
        store.save_figure(conn, run_id, FigureWrite(field(SOFP, FACE, 11), "CY", "Group", 1, _line(1)), AGENT)
    assert str(caught.value) == "This run saves figures for the Company only."
    group_run = make_run([("SOFP", "CuNonCu")], level="Group")
    with db.connect() as conn, pytest.raises(Refused) as caught:
        store.save_figure(conn, group_run, FigureWrite(field("mfrs-group-sofp-cunoncu-v1", FACE, 11), "CY",
                                                       "Branch", 1, _line(1)), AGENT)
    assert str(caught.value) == "This run saves figures for Group and Company."
    other = field("mfrs-company-sopl-function-v1", "SOPL-Function", 11)
    assert _refusal(run_id, other, 1) == "That field is not in this run's templates."


def test_every_write_adds_history_and_a_restore_puts_the_value_back():
    run_id = make_run()
    rou = field(SOFP, FACE, 11)
    first = _save(run_id, rou, 100, reason="Face page.")
    _save(run_id, rou, 120, lines=_line(120, label="Right-of-use assets"))
    with db.connect() as conn:
        history = store.figure_history(conn, run_id, first["id"])
    assert [h["action"] for h in history] == ["save", "save"]
    assert history[0]["before"] is None and history[0]["after"]["value"] == 100
    assert history[1]["before"]["value"] == 100 and history[1]["after"]["value"] == 120
    with db.connect() as conn:
        restored = store.restore_figure(conn, run_id, history[0]["id"], PERSON)
        assert [h["action"] for h in store.figure_history(conn, run_id, first["id"])][-1] == "restore"
    assert restored["value"] == 100 and restored["reason"] == "Face page."
    assert restored["lines"][0]["printed_label"] == "Printed line"


def test_totals_are_added_up_and_recorded_in_history_but_a_missing_line_is_not_zero():
    run_id = make_run()
    rou, dta, total = field(SOFP, FACE, 11), field(SOFP, FACE, 20), field(SOFP, FACE, 23)
    assert _value(run_id, total) is None
    _save(run_id, rou, 100)
    _save(run_id, dta, 50)
    assert _value(run_id, total) == 150
    assert _value(run_id, total, "PY") is None  # nothing saved last year: blank, not zero
    with db.connect() as conn:
        figure = next(f for f in store.run_figures(conn, run_id) if f["concept_uuid"] == total)
        assert {h["action"] for h in store.figure_history(conn, run_id, figure["id"])} == {"calculate"}
        store.clear_figure(conn, run_id, next(f["id"] for f in store.run_figures(conn, run_id)
                                               if f["concept_uuid"] == rou), PERSON)
        store.clear_figure(conn, run_id, next(f["id"] for f in store.run_figures(conn, run_id)
                                               if f["concept_uuid"] == dta), PERSON)
    assert _value(run_id, total) is None  # every line cleared: the total is blank again


def test_a_printed_total_is_kept_beside_the_sum_and_never_forced():
    run_id = make_run()
    _save(run_id, field(SOFP, FACE, 11), 100)
    total = field(SOFP, FACE, 23)
    printed = _save(run_id, total, 130, total="printed", lines=_line(130, label="Total non-current assets"))
    assert (printed["value"], printed["stated_value"], printed["origin"]) == (100, 130, "calculated")


def test_a_person_edit_keeps_the_page_and_is_not_judged_on_arithmetic():
    run_id = make_run()
    rou = field(SOFP, FACE, 11)
    _save(run_id, rou, 100, certainty="unsure", reason="Hard to read.")
    edited = _save(run_id, rou, 0, lines=None, actor=PERSON)
    assert edited["value"] == 0 and edited["person_edited"] is True
    assert edited["lines"][0]["page"] == 7 and edited["lines"][0]["amount"] == 0
    # A brand-new figure from a person still needs its page.
    assert _refusal(run_id, field(SOFP, FACE, 20), 5, lines=None, actor=PERSON).startswith("Give the page")


def test_a_batch_saves_each_figure_on_its_own():
    run_id = make_run()
    with db.connect() as conn:
        results = store.save_figures(conn, run_id, [
            FigureWrite(field(SOFP, FACE, 11), "CY", "Company", 100, _line(100)),
            FigureWrite(field(SOFP, FACE, 7), "CY", "Company", 5, _line(5)),
            FigureWrite(field(SOFP, FACE, 20), "CY", "Company", 50, _line(50)),
        ], AGENT)
    assert [r["ok"] for r in results] == [True, False, True]
    assert results[1]["refused"].startswith("Non-current assets is a heading")
    assert _value(run_id, field(SOFP, FACE, 23)) == 150


def test_moving_a_figure_adds_it_to_the_target_and_clears_the_source():
    run_id = make_run()
    rou, dta, other = field(SOFP, FACE, 11), field(SOFP, FACE, 20), field(SOFP, FACE, 19)
    first = _save(run_id, rou, 100, lines=_line(100, label="Right-of-use"))
    _save(run_id, rou, 90, period="PY")
    _save(run_id, dta, 50, lines=_line(50, label="Deferred tax"))
    with db.connect() as conn:
        moved = store.move_figure(conn, run_id, first["id"], dta, PERSON)
    assert moved[0]["value"] == 150 and len(moved[0]["lines"]) == 2
    assert _value(run_id, rou) is None and _value(run_id, rou, "PY") == 90
    with db.connect() as conn:
        py = next(f for f in store.run_figures(conn, run_id) if f["concept_uuid"] == rou and f["period"] == "PY")
        store.move_figure(conn, run_id, py["id"], other, PERSON, whole_row=True)
        with pytest.raises(Refused, match="heading"):
            store.move_figure(conn, run_id, moved[0]["id"], field(SOFP, FACE, 7), AGENT)
    assert _value(run_id, other, "PY") == 90 and _value(run_id, rou, "PY") is None


def test_values_that_are_not_ordinary_numbers_are_refused():
    run_id = make_run()
    rou = field(SOFP, FACE, 11)
    for bad in (float("inf"), float("-inf"), float("nan")):
        assert _refusal(run_id, rou, bad, lines=_line(100)) == "The value must be an ordinary number."
        assert _refusal(run_id, rou, 100, lines=_line(bad)) == (
            "The amount of each printed line must be an ordinary number.")
    with db.connect() as conn:
        assert store.run_figures(conn, run_id) == []


def test_restore_brings_back_how_a_total_is_added_up():
    run_id = make_run()
    other_ppe, total = field(SOFP, SUB, 38), field(SOFP, SUB, 39)
    label = "Property, plant and equipment"
    # Itemised, then given with no breakdown, then restored to the itemised entry.
    line = _save(run_id, other_ppe, 100)
    printed = _save(run_id, total, 100, total="printed", lines=_line(100, label=label))
    with db.connect() as conn:
        itemised_entry = store.figure_history(conn, run_id, printed["id"])[-1]["id"]
        store.clear_figure(conn, run_id, line["id"], PERSON)
    assert _save(run_id, total, 150, total="no_breakdown", lines=_line(150, label=label))["value"] == 150
    with db.connect() as conn:
        restored = store.restore_figure(conn, run_id, itemised_entry, PERSON)
    assert (restored["children_status"], restored["stated_value"], restored["value"]) == ("itemised", 100, None)
    _save(run_id, other_ppe, 70)
    assert _value(run_id, total) == 70  # added up from its lines again, not kept at 150


def test_restore_brings_back_a_total_given_with_no_breakdown():
    run_id = make_run()
    other_ppe, total = field(SOFP, SUB, 38), field(SOFP, SUB, 39)
    label = "Property, plant and equipment"
    typed = _save(run_id, total, 150, total="no_breakdown", lines=_line(150, label=label))
    with db.connect() as conn:
        typed_entry = store.figure_history(conn, run_id, typed["id"])[-1]["id"]
        store.clear_figure(conn, run_id, typed["id"], PERSON)
    line = _save(run_id, other_ppe, 100)
    _save(run_id, total, 120, total="printed", lines=_line(120, label=label))
    with db.connect() as conn:
        store.clear_figure(conn, run_id, line["id"], PERSON)
        restored = store.restore_figure(conn, run_id, typed_entry, PERSON)
    assert (restored["children_status"], restored["stated_value"], restored["value"]) == ("aggregate_only", None, 150)


def test_a_figure_typed_into_the_workbook_is_kept_fixed_against_agents():
    from app.figures import views

    run_id = make_run()
    rou, dta = field(SOFP, FACE, 11), field(SOFP, FACE, 20)
    with db.connect() as conn:
        typed = store.import_figure(conn, run_id, FigureWrite(rou, "CY", "Company", 100, []), "last.xlsx!C11",
                                    origin="typed_in_workbook")
    assert (typed["origin"], typed["locked"]) == ("typed_in_workbook", False)
    sentence = ("A person typed this figure into the workbook, so leave a comment for the reviewer "
                "rather than changing it.")
    assert _refusal(run_id, rou, 120) == sentence
    other = _save(run_id, dta, 50)
    with db.connect() as conn:
        for attempt in (lambda: store.clear_figure(conn, run_id, typed["id"], AGENT),
                        lambda: store.move_figure(conn, run_id, typed["id"], dta, AGENT),
                        lambda: store.move_figure(conn, run_id, other["id"], rou, AGENT)):
            with pytest.raises(Refused) as caught:
                attempt()
            assert str(caught.value) == sentence
        cell = next(r for r in views.statement_view(conn, run_id, "SOFP", "template")["rows"]
                    if r.get("concept_uuid") == rou)["cells"]["Company:CY"]
    assert cell["writable"] and not cell["agent_writable"]
    assert _value(run_id, rou) == 100 and _value(run_id, dta) == 50
    with db.connect() as conn:
        edited = store.edit_by_person(conn, run_id, PERSON, concept_uuid=rou, period="CY", entity_scope="Company",
                                      value=120, page=7, printed_label="Right-of-use assets")
    assert edited["value"] == 120


def test_moving_a_blank_figure_is_refused():
    run_id = make_run()
    rou = field(SOFP, FACE, 11)
    figure = _save(run_id, rou, 100)
    with db.connect() as conn:
        store.clear_figure(conn, run_id, figure["id"], PERSON)
        with pytest.raises(Refused) as caught:
            store.move_figure(conn, run_id, figure["id"], field(SOFP, FACE, 20), PERSON)
    assert str(caught.value) == "This figure is blank, so there is nothing to move."


def test_a_printed_label_has_a_length_limit():
    run_id = make_run()
    assert _refusal(run_id, field(SOFP, FACE, 11), 100, lines=_line(100, label="x" * 301)) == (
        "Keep each printed label to 300 characters or fewer, as the line is printed.")
    assert _save(run_id, field(SOFP, FACE, 11), 100, lines=_line(100, label="x" * 300))["value"] == 100


def test_a_person_edit_keeps_printed_lines_and_corrects_only_what_was_sent():
    run_id = make_run()
    rou, dta = field(SOFP, FACE, 11), field(SOFP, FACE, 20)
    _save(run_id, rou, 100, lines=_line(100, label="Right-of-use assets", print_order=4, section="Non-current"))
    with db.connect() as conn:
        edited = store.edit_by_person(conn, run_id, PERSON, concept_uuid=rou, period="CY", entity_scope="Company",
                                      value=110, page=9)
    assert [(l["printed_label"], l["page"], l["amount"], l["print_order"], l["section"]) for l in edited["lines"]] == [
        ("Right-of-use assets", 9, 110, 4, "Non-current")]
    _save(run_id, dta, 150, lines=[Line("Deferred tax on leases", 7, 100), Line("Deferred tax on tax losses", 8, 50)])
    with db.connect() as conn:
        edited = store.edit_by_person(conn, run_id, PERSON, concept_uuid=dta, period="CY", entity_scope="Company",
                                      value=160, page=9, printed_label="ignored on a two-line figure")
    assert edited["value"] == 160
    assert [(l["printed_label"], l["page"]) for l in edited["lines"]] == [
        ("Deferred tax on leases", 7), ("Deferred tax on tax losses", 8)]
