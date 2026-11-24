"""Where notes sit, as the placement map changes it (owner, 24 November 2026): a person's move confirms the
field, "Field is right" confirms only the field, a split part is named by its own heading, and a split note's
short opening paragraph may start each of its parts."""
from __future__ import annotations

from types import SimpleNamespace

from app import db
from app.notes import agent, store, tools
from tests.conftest import OWNER, login
from app.notes import job as notes_job
from tests.notes_agent_helpers import NOTES_LIST, field_ids
from tests.notes_helpers import PAGES, notes_run
from tests.test_note_store import AGENT, BORROWINGS, PPE, call, place

PERSON = store.Actor("person", OWNER)


def flagged(run_id, note):
    """The note as the agent left it: placed unsure, with its formatting to check."""
    call(store.set_look, run_id, note["id"], note["blocks"], AGENT, format_state="check_formatting",
         format_reason="The rule under the total is unclear.")
    with db.connect() as conn:
        conn.execute("UPDATE notes SET certainty = 'unsure', certainty_reason = 'Maybe leases.' WHERE id = ?",
                     (note["id"],))


def test_a_person_moving_a_note_confirms_its_field_but_not_its_formatting():
    run_id = notes_run()
    note = place(run_id, BORROWINGS)
    flagged(run_id, note)

    moved = call(store.move_note, run_id, note["id"], "test-other", PERSON)
    assert (moved["certainty"], moved["confirmed_by"]) == ("sure", OWNER)
    assert moved["format_state"] == "check_formatting"

    by_agent = call(store.move_note, run_id, place(run_id, PPE)["id"], "test-other", AGENT)
    assert by_agent["confirmed_by"] is None


def test_field_is_right_confirms_only_the_field_and_undo_takes_it_back(client):
    run_id = notes_run()
    assert login(client, OWNER).status_code == 200
    note = place(run_id, BORROWINGS)
    flagged(run_id, note)
    base = f"/api/runs/{run_id}/notes/{note['id']}"

    right = client.post(f"{base}/field/confirm").json()
    assert (right["note"]["certainty"], right["note"]["confirmed_by"]) == ("sure", OWNER)
    assert right["note"]["format_state"] == "check_formatting"
    back = client.post(f"{base}/undo", json={"history_id": right["history_id"]}).json()["note"]
    assert (back["certainty"], back["confirmed_by"]) == ("unsure", None)

    moved = client.post(f"{base}/field", json={"node_uuid": "test-other"}).json()
    assert moved["note"]["confirmed_by"] == OWNER and moved["history_id"]
    assert client.post(f"{base}/undo", json={"history_id": moved["history_id"]}).json()["note"]["field"][
        "node_uuid"] == "test-borrowings"

    client.post(f"{base}/field", json={"node_uuid": None})
    refused = client.post(f"{base}/field/confirm")
    assert refused.status_code == 422 and refused.json()["detail"] == (
        "The note is in no field, so there is no field to confirm.")


def test_a_split_part_is_named_by_its_own_heading():
    run_id = notes_run()
    whole = place(run_id, BORROWINGS)
    assert whole["part_title"] == ""
    part = place(run_id, store.NotePlacement("4", "Property, plant and equipment", [(24, 1), (24, 2)],
                                             "test-borrowings", part=2, parts=2))
    assert part["part_title"] == "Borrowings"   # "6. Borrowings", its numbering dropped


def _place(run_id, *placements):
    deps, _ = agent.build_deps(run_id, "placing")
    return tools.place_note(SimpleNamespace(deps=deps), list(placements))


POLICIES = {30: {"folio": "28", "rotation": 0, "kind": "notes", "title": "", "blocks": [
    {"type": "heading", "level": 2, "text": "7. Accounting policies"},
    {"type": "paragraph", "text": "These policies have been applied consistently to all years presented."},
    {"type": "heading", "level": 3, "text": "(a) Leases"},
    {"type": "paragraph", "text": "Leases are recognised as right-of-use assets."},
    {"type": "heading", "level": 3, "text": "(b) Inventories"},
    {"type": "paragraph", "text": "Inventories are stated at the lower of cost and net realisable value."},
]}}


def policies_run() -> int:
    run_id = notes_run({**PAGES, **POLICIES})
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE runs SET status = 'ready' WHERE id = ?", (run_id,))
        conn.execute("UPDATE run_setup SET year_end = '2025-12-31', notes_included = 1 WHERE run_id = ?", (run_id,))
        conn.executemany("INSERT INTO run_notes(run_id, position, number, title, first_page, last_page) "
                         "VALUES (?, ?, ?, ?, ?, ?)", [(run_id, i, *n) for i, n in enumerate(
                             NOTES_LIST + [("7", "Accounting policies", 30, 30)])])
        notes_job.start(conn, run_id)
    return run_id


def test_split_parts_may_start_with_the_same_opening_and_nothing_else_twice():
    run_id = policies_run()
    ids = field_ids(run_id)
    first, second = ids["Disclosure of borrowings"], ids["catch-all"]
    part = lambda n, blocks, field, parts=2: tools.Placement(note="7", field=field, blocks=blocks, part=n, parts=parts)

    # The note's heading and its opening start part 1; part 2 repeats the opening only.
    assert "placed in" in _place(run_id, part(1, ["p30b0-p30b3"], first))
    assert "placed in" in _place(run_id, part(2, ["p30b1", "p30b4", "p30b5"], second))

    # A sub-section is not the opening: placing (a) again in a third part is refused, and says which blocks.
    again = _place(run_id, part(3, ["p30b1-p30b3"], ids["Disclosure of trade and other receivables"], 3))
    assert "p30b2, p30b3 are already in another part of this note and not part of its opening" in again
    other_note = _place(run_id, tools.Placement(note="5", field=second, blocks=["p30b1"]))
    assert "already placed" in other_note
    with db.connect() as conn:
        assert len(store.run_notes(conn, run_id)) == 2


def test_an_agent_moving_a_note_a_person_confirmed_asks_for_a_check_again():
    run_id = notes_run()
    note = place(run_id, BORROWINGS)
    call(store.confirm_placement, run_id, note["id"], PERSON)
    moved = call(store.move_note, run_id, note["id"], "test-other", AGENT)
    assert (moved["confirmed_by"], moved["confirmed_at"]) == (None, None)
