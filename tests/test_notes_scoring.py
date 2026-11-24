"""The notes placement score (step 6g): "same field" only, on synthetic keys and runs."""
from __future__ import annotations

import json
import sqlite3

from app import db
from app.notes import store
from app.scoring import notes
from app.scoring.notes import Placement
from tests.notes_helpers import notes_run

PPE, PPE_POLICY, RECEIVABLES, OTHER = "f-ppe", "f-ppe-policy", "f-receivables", "f-other"
SHARES_LIST, SHARES_TEXT = "f-shares-list", "f-shares-text"
INTRO = "f-corporate"


def _field(field_id: str, required: bool = False) -> dict:
    return {"field_id": field_id, "label": field_id, "required": required}


KEY = {
    "notes": [
        {"number": "1", "title": "Property, plant and equipment",
         "fields": [_field(PPE, True), _field(PPE_POLICY)], "confidence": "high"},
        {"number": "2", "title": "Trade and other receivables", "fields": [_field(RECEIVABLES, True)],
         "confidence": "high"},
        {"number": "3", "title": "Share capital", "fields": [_field(SHARES_LIST), _field(SHARES_TEXT)],
         "confidence": "high"},
        {"number": "4", "title": "Capital management", "fields": [_field(OTHER, True)], "confidence": "medium"},
    ],
    "unnumbered": [{"number": "", "title": "Notes to the financial statements", "fields": [_field(INTRO, True)]}],
}


def _status(result: dict) -> dict:
    return {n["number"]: n["status"] for n in result["notes"]}


def test_a_note_in_its_field_is_right_and_the_number_is_right_over_notes_in_the_key():
    result = notes.score(KEY, [Placement("1", "Property, plant and equipment", PPE),
                               Placement("2", "Trade and other receivables", RECEIVABLES)])
    assert _status(result) == {"1": "right", "2": "right", "3": "not_placed", "4": "not_placed"}
    assert result["score"] == 0.5
    assert result["counts"] == {"right": 2, "elsewhere": 0, "not_placed": 2, "not_in_key": 0}


def test_an_allowed_split_is_right_but_a_part_outside_the_key_or_a_missing_required_field_is_elsewhere():
    split = [Placement("1", "PPE", PPE), Placement("1", "PPE", PPE_POLICY)]
    assert _status(notes.score(KEY, split))["1"] == "right"
    assert _status(notes.score(KEY, [*split, Placement("1", "PPE", OTHER)]))["1"] == "elsewhere"
    assert _status(notes.score(KEY, [Placement("1", "PPE", PPE_POLICY)]))["1"] == "elsewhere"


def test_share_capital_may_sit_in_either_field_or_both():
    for fields in ([SHARES_LIST], [SHARES_TEXT], [SHARES_LIST, SHARES_TEXT]):
        result = notes.score(KEY, [Placement("3", "Share capital", f) for f in fields])
        assert _status(result)["3"] == "right", fields


def test_a_note_the_run_left_unplaced_counts_as_not_placed():
    result = notes.score(KEY, [Placement("2", "Trade and other receivables", None)])
    assert _status(result)["2"] == "not_placed"


def test_numbers_match_however_they_are_printed_and_wording_is_not_compared():
    result = notes.score(KEY, [Placement("Note 2.", "Receivables from customers", RECEIVABLES)])
    assert _status(result)["2"] == "right"


def test_a_run_note_the_key_does_not_have_is_reported_and_does_not_change_the_number():
    result = notes.score(KEY, [Placement("1", "PPE", PPE), Placement("9", "Dividends", OTHER)])
    assert result["not_in_key"] == [{"number": "9", "title": "Dividends", "run_fields": [OTHER]}]
    assert result["counts"]["not_in_key"] == 1 and result["score"] == 0.25


def test_an_unnumbered_section_is_matched_by_title_and_left_out_of_the_number():
    result = notes.score(KEY, [Placement("", "Notes to the Financial Statements", INTRO)])
    assert result["unnumbered"][0]["status"] == "right"
    assert result["score"] == 0.0 and result["counts"]["not_in_key"] == 0


def test_a_key_without_notes_has_no_number():
    assert notes.score({"notes": []}, [Placement("1", "PPE", PPE)])["score"] is None


def test_a_v2_run_is_scored_from_its_notes_table_with_split_parts_and_cleared_notes():
    run_id = notes_run()
    actor = store.Actor("agent", "notes")
    key = {"notes": [
        {"number": "4", "title": "Property, plant and equipment", "fields": [_field("test-ppe", True)]},
        {"number": "5", "title": "Trade and other receivables", "fields": [_field("test-receivables", True)]},
        {"number": "6", "title": "Borrowings", "fields": [_field("test-borrowings", True)]},
    ]}
    with db.connect(immediate=True) as conn:
        store.place_note(conn, run_id, store.NotePlacement("4", "PPE", [(23, 0), (23, 1)], "test-ppe",
                                                           part=1, parts=2), actor)
        store.place_note(conn, run_id, store.NotePlacement("4", "PPE", [(23, 2)], "test-ppe", part=2, parts=2), actor)
        store.place_note(conn, run_id, store.NotePlacement("5", "Receivables", [(23, 3), (23, 4)], "test-other"),
                         actor)
        borrowings = store.place_note(conn, run_id, store.NotePlacement("6", "Borrowings", [(24, 1)],
                                                                        "test-borrowings"), actor)
        store.clear_note(conn, run_id, borrowings["id"], actor)
        result = notes.score(key, notes.v2_placements(conn, run_id))
    assert _status(result) == {"4": "right", "5": "elsewhere", "6": "not_placed"}


def _v1_database() -> sqlite3.Connection:
    """The few v1 tables the adapter reads, with one run: note 1 by its blocks, note 2 by the coverage rows,
    note 3 by the issued-capital cell's evidence, and one field no record ties to a note."""
    v1 = sqlite3.connect(":memory:")
    v1.executescript("""
        CREATE TABLE notes_cells (run_id, sheet, row, concept_uuid, evidence);
        CREATE TABLE notes_source_generations (id, run_id, status);
        CREATE TABLE notes_source_notes (generation_id, source_note_id, top_note_num, title);
        CREATE TABLE notes_source_blocks (generation_id, block_id, source_note_id);
        CREATE TABLE notes_block_usages (run_id, generation_id, block_id, sheet, row, disposition);
        CREATE TABLE run_notes_inventory (run_id, note_num, title);
        CREATE TABLE notes_coverage_rows (run_id, note_num, subnote_ref, placements_json);
    """)
    v1.executemany("INSERT INTO notes_cells VALUES (7, ?, ?, ?, ?)", [
        ("Notes-Listofnotes", 125, PPE, None), ("Notes-SummaryofAccPol", 48, PPE_POLICY, None),
        ("Notes-Listofnotes", 140, RECEIVABLES, None), ("Notes-Issuedcapital", 4, SHARES_TEXT, "PDF page 21 Note 3."),
        ("Notes-Listofnotes", 112, OTHER, None)])
    v1.execute("INSERT INTO notes_source_generations VALUES (1, 7, 'active')")
    v1.execute("INSERT INTO notes_source_notes VALUES (1, 'n1', '1', 'Property, plant and equipment')")
    v1.executemany("INSERT INTO notes_source_blocks VALUES (1, ?, 'n1')", [("b1",), ("b2",), ("b3",)])
    v1.executemany("INSERT INTO notes_block_usages VALUES (7, 1, ?, ?, ?, ?)", [
        ("b1", "Notes-Listofnotes", 125, "included"), ("b2", "Notes-SummaryofAccPol", 48, "included"),
        ("b3", "Notes-Listofnotes", 112, "excluded")])
    v1.execute("INSERT INTO run_notes_inventory VALUES (7, 2, 'Trade and other receivables')")
    v1.execute("INSERT INTO notes_coverage_rows VALUES (7, 2, NULL, ?)",
               (json.dumps([{"sheet": "Notes-Listofnotes", "row": 140}, {"sheet": "Notes-Listofnotes", "row": 99}]),))
    return v1


def test_a_v1_run_is_read_from_its_blocks_coverage_rows_and_numeric_note_evidence():
    placements = notes.v1_placements(_v1_database(), 7)
    assert sorted((p.number, p.field_id) for p in placements) == [
        ("1", PPE), ("1", PPE_POLICY), ("2", RECEIVABLES), ("3", SHARES_TEXT)]
    result = notes.score(KEY, placements)
    assert _status(result) == {"1": "right", "2": "right", "3": "right", "4": "not_placed"}
