"""The note store: place, look, move, clear, confirm, redo, undo (step 6b)."""
from __future__ import annotations

import pytest

from app import db
from app.notes import store
from app.notes.blocks import parse, words
from app.runs.events import list_events
from tests.notes_helpers import notes_run

AGENT = store.Actor("agent", "notes")
PERSON = store.Actor("person", "ana@firm.com")

PPE = store.NotePlacement("4", "Property, plant and equipment", [(23, 0), (23, 1), (23, 2)], "test-ppe")
RECEIVABLES = store.NotePlacement("5", "Trade and other receivables", [(23, 3), (23, 4), (24, 0)], "test-other")
BORROWINGS = store.NotePlacement("6", "Borrowings", [(24, 1), (24, 2), (24, 3)], "test-borrowings")


def place(run_id, placement=PPE, actor=AGENT):
    with db.connect(immediate=True) as conn:
        return store.place_note(conn, run_id, placement, actor)


def call(fn, *args, **kwargs):
    with db.connect(immediate=True) as conn:
        return fn(conn, *args, **kwargs)


def bolder(note, *, total_row=-1):
    """The note's blocks with the heading bold and the table's last row a bold total with a double line."""
    blocks = [dict(b) for b in note["blocks"]]
    for b in blocks:
        if b["kind"] == "heading":
            b["look"] = {**b["look"], "bold": True}
        if b["kind"] == "table":
            rows = [dict(r) for r in b["rows"]]
            rows[total_row] = {**rows[total_row], "role": "total", "bold": True,
                               "line_below": {"style": "double", "columns": [1, 2]}}
            b["rows"] = rows
            b["columns"] = [{**c, "align": "right"} if c["role"] == "amount" else c for c in b["columns"]]
    return blocks


def test_three_notes_placed_restyled_one_moved_and_undone_read_back_in_order():
    run_id = notes_run()
    notes = [place(run_id, p) for p in (PPE, RECEIVABLES, BORROWINGS)]
    assert [n["field"]["node_uuid"] for n in notes] == ["test-ppe", "test-other", "test-borrowings"]
    assert notes[1]["pages"] == [23, 24] and notes[1]["field"]["label"] == "Disclosure of other notes to accounts"

    styled = [call(store.set_look, run_id, n["id"], bolder(n), PERSON) for n in notes]
    for before, after in zip(notes, styled):
        assert words(parse({"blocks": after["blocks"]})) == words(parse({"blocks": before["blocks"]}))
        assert after["blocks"][0]["look"]["bold"] is True

    moved = call(store.move_note, run_id, notes[1]["id"], "test-receivables", PERSON)
    assert moved["field"]["node_uuid"] == "test-receivables"
    with db.connect() as conn:
        last = store.latest_change(conn, run_id, notes[1]["id"])
    undone = call(store.undo_change, run_id, last, PERSON)
    assert undone["field"]["node_uuid"] == "test-other"
    assert undone["blocks"] == styled[1]["blocks"]

    with db.connect() as conn:
        history = store.note_history(conn, run_id, notes[1]["id"])
        listed = store.run_notes(conn, run_id)
    assert [(h["action"], h["actor_kind"]) for h in history] == [
        ("place", "agent"), ("look", "person"), ("move", "person"), ("restore", "person")]
    assert history[0]["before"] is None
    assert history[2]["before"]["node_uuid"] == "test-other" and history[2]["after"]["node_uuid"] == "test-receivables"
    assert history[3]["after"] == history[2]["before"]
    assert {n["id"] for n in listed} == {n["id"] for n in notes}
    assert all("blocks" not in n for n in listed)


def test_every_write_adds_one_history_row_and_one_event():
    run_id = notes_run()
    note = place(run_id)
    steps = [
        lambda: call(store.set_look, run_id, note["id"], bolder(note), PERSON),
        lambda: call(store.move_note, run_id, note["id"], "test-other", PERSON),
        lambda: call(store.clear_note, run_id, note["id"], PERSON),
        lambda: call(store.move_note, run_id, note["id"], "test-ppe", PERSON),
        lambda: call(store.confirm_note, run_id, note["id"], PERSON),
        lambda: call(store.redo_from_source, run_id, note["id"], PERSON, "The table lost a line."),
    ]
    for n, step in enumerate(steps, 2):
        step()
        with db.connect() as conn:
            assert len(store.note_history(conn, run_id, note["id"])) == n
        assert len([e for e in list_events(run_id=run_id) if e["source"] == "notes"]) == n
    events = [e for e in list_events(run_id=run_id) if e["source"] == "notes"]
    assert [e["kind"] for e in events] == ["place", "look", "move", "clear", "move", "confirm", "redo"]
    assert events[2]["message"] == ("Moved note 4 Property, plant and equipment from Disclosure of property, plant "
                                    "and equipment to Disclosure of other notes to accounts.")
    assert events[0]["pages"] == [23] and events[0]["data"]["note_id"] == note["id"]
    assert all("test-" not in e["message"] for e in events)


def test_a_look_change_that_touches_the_words_or_the_blocks_is_refused_and_saves_nothing():
    run_id = notes_run()
    note = place(run_id)
    changed_word = bolder(note)
    changed_word[1] = {**changed_word[1], "text": changed_word[1]["text"] + " Extra."}
    dropped_block = bolder(note)[:2]
    table = bolder(note)
    table[2] = {**table[2], "rows": table[2]["rows"][:-1]}
    moved_cell = bolder(note)
    cells = [dict(c) for c in moved_cell[2]["rows"][2]["cells"]]
    cells[1], cells[2] = cells[2], cells[1]
    moved_cell[2]["rows"][2] = {**moved_cell[2]["rows"][2], "cells": cells}
    for blocks in (changed_word, dropped_block, table, moved_cell):
        with pytest.raises(store.Refused) as exc:
            call(store.set_look, run_id, note["id"], blocks, PERSON)
        assert str(exc.value) == store.LOOK_ONLY
    bad_line = bolder(note)
    bad_line[2]["rows"][0] = {**bad_line[2]["rows"][0], "line_below": {"style": "single", "columns": [9]}}
    with pytest.raises(store.Refused) as exc:
        call(store.set_look, run_id, note["id"], bad_line, PERSON)
    assert str(exc.value) == "Row 1's line names column 9, but the columns are 0 to 4."
    with db.connect() as conn:
        assert len(store.note_history(conn, run_id, note["id"])) == 1
        assert store.get_note(conn, run_id, note["id"])["blocks"] == note["blocks"]


def test_undo_restores_exactly_and_undoing_the_placement_keeps_the_note_unplaced():
    run_id = notes_run()
    note = place(run_id)
    with db.connect() as conn:
        placed = store.note_state(conn, run_id, note["id"])
    styled = call(store.set_look, run_id, note["id"], bolder(note), PERSON, format_state="check_formatting",
                  format_reason="The double line under the total is not clear on the scan.")
    assert styled["format_state"] == "check_formatting"
    with db.connect() as conn:
        look_change = store.latest_change(conn, run_id, note["id"])
    call(store.undo_change, run_id, look_change, PERSON)
    with db.connect() as conn:
        assert store.note_state(conn, run_id, note["id"]) == placed
        first = store.note_history(conn, run_id, note["id"])[0]["id"]
    unplaced = call(store.undo_change, run_id, first, PERSON)
    assert unplaced["field"] is None and unplaced["template_id"] is None
    assert unplaced["blocks"] == note["blocks"]
    again = call(store.restore_note, run_id, look_change, PERSON)
    assert again["blocks"] == styled["blocks"] and again["field"]["node_uuid"] == "test-ppe"


def test_a_not_sure_look_shows_the_note_as_not_sure_until_it_is_set():
    run_id = notes_run()
    note = place(run_id)
    blocks = bolder(note)
    blocks[2]["rows"][-1] = {**blocks[2]["rows"][-1], "unsure": ["line_below"]}
    unsure = call(store.set_look, run_id, note["id"], blocks, AGENT)
    assert (unsure["format_state"], unsure["has_unsure"]) == ("not_sure", True)
    blocks[2]["rows"][-1] = {**blocks[2]["rows"][-1], "unsure": []}
    assert call(store.set_look, run_id, note["id"], blocks, PERSON)["format_state"] == "fine"


def test_the_three_hard_stops_each_say_one_sentence():
    run_id = notes_run()
    with pytest.raises(store.Refused) as exc:
        place(run_id, store.NotePlacement("4", "PPE", [(23, 0)], "test-heading"))
    assert str(exc.value) == "Notes to the financial statements is a heading, so place the note in a field under it."
    with pytest.raises(store.Refused) as exc:
        place(run_id, store.NotePlacement("4", "PPE", [(23, 0), (23, 12)], "test-ppe"))
    assert str(exc.value) == "Page 23 of this run has no block 12, so place blocks shown on this run's pages."
    note = place(run_id)
    with pytest.raises(store.Refused) as exc:
        call(store.move_note, run_id, note["id"], "test-heading", PERSON)
    assert "is a heading" in str(exc.value)

    other = notes_run()
    for write in (lambda c: store.move_note(c, other, note["id"], "test-other", PERSON),
                  lambda c: store.set_look(c, other, note["id"], note["blocks"], PERSON),
                  lambda c: store.confirm_note(c, other, note["id"], PERSON),
                  lambda c: store.undo_change(c, other, store.latest_change(c, run_id, note["id"]), PERSON)):
        with pytest.raises(store.Refused) as exc:
            call(write)
        assert str(exc.value) == store.ANOTHER_RUN
    with db.connect() as conn:
        assert len(store.note_history(conn, run_id, note["id"])) == 1
        assert conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 1


def test_redo_from_source_copies_the_words_again_with_the_plain_look():
    run_id = notes_run()
    note = place(run_id)
    call(store.set_look, run_id, note["id"], bolder(note), PERSON)
    redone = call(store.redo_from_source, run_id, note["id"], PERSON)
    assert redone["blocks"] == note["blocks"] and redone["field"]["node_uuid"] == "test-ppe"


def test_round_tags_and_placed_elsewhere():
    run_id = notes_run()
    note = place(run_id)
    with db.connect(immediate=True) as conn, store.tagged(3, [7, 5]):
        store.move_note(conn, run_id, note["id"], "test-other", AGENT, reason="Comment 5 asked for the catch-all.")
    with db.connect() as conn:
        entry = store.note_history(conn, run_id, note["id"])[-1]
        assert (entry["round_id"], entry["comment_ids"], entry["reason"]) == (
            3, [5, 7], "Comment 5 asked for the catch-all.")
        assert [n["id"] for n in store.placed_elsewhere(conn, run_id, [(23, 2)])] == [note["id"]]
        assert store.placed_elsewhere(conn, run_id, [(24, 0)]) == []
