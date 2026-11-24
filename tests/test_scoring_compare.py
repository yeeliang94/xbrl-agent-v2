"""The comparison and its scores (app/scoring/compare.py). Pure: no database.

The first test is v1's `test_found_same_value_and_ai_only_follow_the_agreed_formulas`
restated with v2's three numbers.
"""
from __future__ import annotations

import pytest

from app.scoring.compare import RunValue, compare, derive_totals, kind_of
from app.catalog.fields import FieldInfo
from app.scoring.workbook_read import PersonCell, Unread


def _field(uuid, statement="SOFP", total=False):
    return FieldInfo(uuid, "t", statement, "COMPUTED" if total else "LEAF", uuid, "Sheet", 1, None, None,
                     total, "")


def _key(uuid, period="CY", entity="Company"):
    return (uuid, period, entity, "")


def _person(value, formula=False):
    return PersonCell(value, formula, "Sheet!B1")


def test_the_three_numbers_follow_their_definitions():
    # The person filled 50 cells. The run filled 45 of them (40 agree, 5 not),
    # left 5 blank, and filled 3 cells the person left blank.
    fields = {f"u{i}": _field(f"u{i}") for i in range(50)} | {f"x{i}": _field(f"x{i}") for i in range(3)}
    person = {_key(f"u{i}"): _person(1000.0 * (i + 1)) for i in range(50)}
    person |= {_key(f"x{i}"): _person(None) for i in range(3)}
    run = {_key(f"u{i}"): RunValue(1000.0 * (i + 1)) for i in range(40)}
    run |= {_key(f"u{i}"): RunValue(1000.0 * (i + 1) + 7) for i in range(40, 45)}
    run |= {_key(f"x{i}"): RunValue(5.0) for i in range(3)}

    result = compare(fields, person, {}, [], run, {})

    score = result["overall"]
    assert (score["person_filled"], score["both_filled"], score["agree"]) == (50, 45, 40)
    assert score["completeness"] == 0.9
    assert score["accuracy"] == round(40 / 45, 4)
    assert score["complete_and_accurate"] == 0.8
    assert score["counts"] | {} == {"agree": 40, "extra": 3, "sign_only": 0, "scale": 0, "different": 5,
                                    "missing": 5, "zero_left_blank": 0, "not_assessed": 0}
    assert len(result["differences"]) == 13


@pytest.mark.parametrize("person,run,kind", [
    (100.0, 100.0, "agree"), (100.0, 101.0, "agree"), (100.0, 101.5, "different"),
    (-1628400.0, 1628400.0, "sign_only"), (1265.0, 1264900.0, "scale"), (1264900.0, 1265.0, "scale"),
    (1.3, 1264900.0, "scale"), (-1265.0, 1264900.0, "different"), (1.0, 600.0, "different"),
    (None, 5.0, "extra"), (5.0, None, "missing"), (0.0, None, "zero_left_blank"), (None, None, None),
    (0.0, 0.0, "agree"),
])
def test_each_kind_of_difference(person, run, kind):
    assert kind_of(person, run) == kind


def test_a_score_with_nothing_to_divide_by_is_none_not_zero():
    result = compare({"a": _field("a")}, {_key("a"): _person(None)}, {}, [], {_key("a"): RunValue(3.0)}, {})
    score = result["overall"]
    assert score["completeness"] is None and score["accuracy"] is None and score["complete_and_accurate"] is None
    assert score["counts"]["extra"] == 1


def test_a_persons_zero_against_a_blank_run_is_listed_but_not_scored():
    fields = {"a": _field("a"), "b": _field("b")}
    result = compare(fields, {_key("a"): _person(0.0), _key("b"): _person(5.0)}, {}, [],
                     {_key("b"): RunValue(5.0)}, {})
    assert result["overall"]["person_filled"] == 1
    assert result["overall"]["counts"]["zero_left_blank"] == 1
    assert [d["kind"] for d in result["differences"]] == ["zero_left_blank"]


def test_not_disclosed_is_blank_not_zero():
    result = compare({"a": _field("a")}, {_key("a"): _person(0.0)}, {}, [], {_key("a"): RunValue(None)}, {})
    assert result["overall"]["counts"]["agree"] == 0
    assert result["overall"]["counts"]["zero_left_blank"] == 1


def test_one_wrong_line_is_scored_once_and_its_totals_are_listed_apart():
    fields = {"a": _field("a"), "b": _field("b"), "sub": _field("sub", total=True),
              "grand": _field("grand", total=True)}
    edges = {"sub": [("a", 1.0), ("b", 1.0)], "grand": [("sub", 1.0)]}
    person = {_key("a"): _person(10.0), _key("b"): _person(20.0), _key("sub"): _person(None, True),
              _key("grand"): _person(None, True)}
    run = {_key("a"): RunValue(10.0), _key("b"): RunValue(25.0), _key("sub"): RunValue(35.0),
           _key("grand"): RunValue(35.0)}

    result = compare(fields, person, {}, [], run, edges)

    assert result["overall"]["counts"]["different"] == 1
    assert result["overall"]["person_filled"] == 2
    assert {(d["concept_uuid"], d["person_value"], d["run_value"]) for d in result["totals"]["differences"]} == {
        ("sub", 30.0, 35.0), ("grand", 30.0, 35.0)}


def test_a_typed_total_is_kept_and_compared_with_the_runs_total():
    fields = {"a": _field("a"), "sub": _field("sub", total=True)}
    person = {_key("a"): _person(None), _key("sub"): _person(500.0)}
    run = {_key("sub"): RunValue(500.0, stands=True)}   # saved with no breakdown
    result = compare(fields, person, {}, [], run, {"sub": [("a", 1.0)]})
    assert result["totals"]["counts"]["agree"] == 1 and result["totals"]["differences"] == []


def test_cells_that_could_not_be_assessed_are_listed_and_never_agree():
    fields = {"a": _field("a"), "b": _field("b"), "c": _field("c", "SOPL")}
    unread = {_key("a"): Unread("not_a_number", "Sheet!B1 holds text, not a number.", "Sheet!B1", True)}
    run = {_key("a"): RunValue(5.0), _key("b"): RunValue(7.0, figure_id=9)}
    loose = [{"reason": "no_field", "sentence": "x", "workbook_cell": "Sheet!B9", "sheet": "Sheet"}]

    result = compare(fields, {}, unread, loose, run, {})

    assert [(n["reason"], n["figure_id"]) for n in result["not_assessed"]] == [
        ("not_a_number", None), ("no_field", None), ("no_cell", 9)]
    assert result["overall"]["counts"]["not_assessed"] == 3
    assert result["overall"]["person_filled"] == 0 and result["overall"]["counts"]["agree"] == 0


def test_prior_year_is_left_out_when_the_run_has_none():
    fields = {"a": _field("a")}
    person = {_key("a"): _person(1.0), _key("a", "PY"): _person(2.0)}
    result = compare(fields, person, {}, [], {_key("a"): RunValue(1.0)}, {}, periods=("CY",))
    assert result["overall"]["person_filled"] == 1 and result["overall"]["counts"]["agree"] == 1


def test_scores_are_given_per_statement_and_for_the_whole_run():
    fields = {"a": _field("a", "SOFP"), "b": _field("b", "SOPL")}
    person = {_key("a"): _person(1.0), _key("b"): _person(2.0)}
    result = compare(fields, person, {}, [], {_key("a"): RunValue(1.0)}, {})
    assert [(s["statement"], s["score"]["completeness"]) for s in result["statements"]] == [
        ("SOFP", 1.0), ("SOPL", 0.0)]
    assert result["overall"]["completeness"] == 0.5


def test_totals_are_derived_from_the_persons_own_lines():
    # v1 tests/test_human_compare.py::test_human_totals_are_derived_from_the_human_inputs
    edges = {"total": [("a", 1.0), ("b", -1.0)], "grand": [("total", 1.0), ("c", 1.0)], "empty": [("x", 1.0)]}
    values = {("a", "CY", "Company", ""): 10.0, ("b", "CY", "Company", ""): 3.0,
              ("c", "CY", "Company", ""): 1.0, ("a", "PY", "Company", ""): 4.0,
              ("grand", "PY", "Company", ""): 50.0}
    keys = [(u, p, "Company", "") for u in ("total", "grand", "empty") for p in ("CY", "PY")]
    assert derive_totals(values, edges, keys) == {
        ("total", "CY", "Company", ""): 7.0, ("grand", "CY", "Company", ""): 8.0,
        ("total", "PY", "Company", ""): 4.0, ("grand", "PY", "Company", ""): 50.0}


def test_an_unreadable_total_is_listed_once_and_never_agrees():
    fields = {"a": _field("a"), "b": _field("b"), "sub": _field("sub", total=True)}
    person = {_key("a"): _person(10.0), _key("b"): _person(20.0)}
    unread = {_key("sub"): Unread("not_a_number", "Sheet!B3 holds text, not a number.", "Sheet!B3", True)}
    run = {_key("a"): RunValue(10.0), _key("b"): RunValue(20.0)}

    result = compare(fields, person, unread, [], run, {"sub": [("a", 1.0), ("b", 1.0)]})

    assert result["totals"]["counts"]["agree"] == 0 and result["totals"]["differences"] == []
    assert [(n["reason"], n["concept_uuid"]) for n in result["not_assessed"]] == [("not_a_number", "sub")]


def test_a_total_over_an_unread_line_is_not_assessed_not_agreeing():
    fields = {"a": _field("a"), "b": _field("b"), "sub": _field("sub", total=True)}
    person = {_key("a"): _person(10.0), _key("sub"): _person(None, True)}
    unread = {_key("b"): Unread("not_a_number", "Sheet!B2 holds text, not a number.", "Sheet!B2", True)}
    run = {_key("a"): RunValue(10.0)}   # the run left b blank, so both sides add up to 10

    result = compare(fields, person, unread, [], run, {"sub": [("a", 1.0), ("b", 1.0)]})

    assert result["totals"]["counts"]["agree"] == 0
    assert [(n["reason"], n["concept_uuid"]) for n in result["not_assessed"]] == [
        ("not_a_number", "b"), ("line_not_read", "sub")]
    assert "a line under it could not be read" in result["not_assessed"][1]["sentence"]
    assert result["overall"]["counts"]["not_assessed"] == 2


def test_the_runs_totals_are_worked_out_from_its_own_lines():
    fields = {"a": _field("a"), "b": _field("b"), "sub": _field("sub", total=True)}
    edges = {"sub": [("a", 1.0), ("b", 1.0)]}
    person = {_key("a"): _person(None), _key("b"): _person(None), _key("sub"): _person(30.0)}

    result = compare(fields, person, {}, [], {_key("a"): RunValue(10.0), _key("b"): RunValue(20.0)}, edges)
    assert result["totals"]["counts"]["agree"] == 1 and result["totals"]["differences"] == []

    # A stored sum is not trusted over the lines; a total saved with no breakdown stands.
    stale = {_key("a"): RunValue(10.0), _key("b"): RunValue(20.0), _key("sub"): RunValue(99.0)}
    assert compare(fields, person, {}, [], stale, edges)["totals"]["counts"]["agree"] == 1
    kept = {_key("sub"): RunValue(30.0, stands=True), _key("a"): RunValue(1.0)}
    assert compare(fields, person, {}, [], kept, edges)["totals"]["counts"]["agree"] == 1


def _capital(uuid):
    return FieldInfo(uuid, "t", "Share capital", "LEAF", uuid, "Notes-Issuedcapital", 1, None, None, False, "")


def _class(uuid, member, period="CY"):
    return (uuid, period, "Company", f"ClassesOfShareCapitalAxis={member}")


def test_one_wrong_share_class_is_scored_once_and_its_total_is_listed_apart():
    fields = {"shares": _capital("shares")}
    person = {_class("shares", "Ordinary"): _person(100.0), _class("shares", "Preference"): _person(50.0),
              _key("shares"): _person(None, True)}
    run = {_class("shares", "Ordinary"): RunValue(100.0), _class("shares", "Preference"): RunValue(40.0),
           _key("shares"): RunValue(140.0)}

    result = compare(fields, person, {}, [], run, {})

    assert result["overall"]["person_filled"] == 2
    assert result["overall"]["counts"]["different"] == 1
    assert [(d["concept_uuid"], d["dimension_key"], d["person_value"], d["run_value"])
            for d in result["totals"]["differences"]] == [("shares", "", 150.0, 140.0)]


def test_a_share_total_with_no_classes_on_either_side_is_still_scored():
    fields = {"shares": _capital("shares")}
    result = compare(fields, {_key("shares"): _person(150.0)}, {}, [], {_key("shares"): RunValue(150.0)}, {})
    assert result["overall"]["person_filled"] == 1 and result["overall"]["agree"] == 1
    assert result["totals"]["counts"]["agree"] == 0


def test_a_typed_share_total_is_compared_with_the_runs_classes():
    fields = {"shares": _capital("shares")}
    person = {_key("shares"): _person(150.0), _class("shares", "Ordinary"): _person(None),
              _class("shares", "Preference"): _person(None)}   # the person typed only the Total column
    run = {_class("shares", "Ordinary"): RunValue(100.0), _class("shares", "Preference"): RunValue(50.0)}

    result = compare(fields, person, {}, [], run, {})

    assert result["overall"]["counts"]["extra"] == 2 and result["overall"]["person_filled"] == 0
    assert result["totals"]["counts"]["agree"] == 1


def test_a_share_total_beside_an_unread_class_is_not_assessed():
    fields = {"shares": _capital("shares")}
    person = {_class("shares", "Ordinary"): _person(100.0), _key("shares"): _person(None, True)}
    unread = {_class("shares", "Preference"): Unread("not_a_number", "C5 holds text.", "C5", True)}
    run = {_class("shares", "Ordinary"): RunValue(100.0), _key("shares"): RunValue(100.0)}

    result = compare(fields, person, unread, [], run, {})

    assert result["totals"]["counts"]["agree"] == 0
    assert ("line_not_read", "shares", "") in {(n["reason"], n["concept_uuid"], n["dimension_key"])
                                               for n in result["not_assessed"]}


def test_a_blank_unread_class_does_not_hold_back_the_share_total():
    fields = {"shares": _capital("shares")}
    person = {_class("shares", "Ordinary"): _person(100.0), _key("shares"): _person(None, True)}
    unread = {_class("shares", "Preference"): Unread("ambiguous", "Two cells carry this name.", None, False)}
    run = {_class("shares", "Ordinary"): RunValue(100.0)}

    result = compare(fields, person, unread, [], run, {})

    assert result["totals"]["counts"]["agree"] == 1 and result["not_assessed"] == []
