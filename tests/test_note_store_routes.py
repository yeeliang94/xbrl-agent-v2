"""The notes routes (docs/api-contract.md, Step 6b)."""
from __future__ import annotations

from app import db
from app.notes import store
from tests.conftest import OWNER, login
from tests.notes_helpers import notes_run
from tests.test_note_store import BORROWINGS, PPE, bolder, place


def signed_in(client):
    """The run's owner, whose account `make_run` made, signed in."""
    assert login(client, OWNER).status_code == 200
    return client


def test_every_notes_route_needs_a_session(client):
    run_id = notes_run()
    note = place(run_id)
    base = f"/api/runs/{run_id}/notes"
    for method, path, body in (("get", base, None), ("get", f"{base}/{note['id']}", None),
                               ("get", f"{base}/{note['id']}/history", None),
                               ("post", f"{base}/{note['id']}/look", {"blocks": note["blocks"]}),
                               ("post", f"{base}/{note['id']}/field", {"node_uuid": None}),
                               ("post", f"{base}/{note['id']}/confirm", None),
                               ("post", f"{base}/{note['id']}/undo", None),
                               ("post", f"{base}/{note['id']}/redo", None)):
        response = getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert response.status_code == 401, path
    with db.connect() as conn:
        assert len(store.note_history(conn, run_id, note["id"])) == 1


def test_a_person_lists_opens_restyles_moves_confirms_undoes_and_redoes_a_note(client):
    run_id = notes_run()
    signed_in(client)
    note = place(run_id)
    place(run_id, BORROWINGS)
    base = f"/api/runs/{run_id}/notes"

    listed = client.get(base).json()["notes"]
    assert [n["number"] for n in listed] == ["6", "4"]   # by template, then field
    assert client.get(f"{base}/{note['id']}").json()["note"]["blocks"] == note["blocks"]

    looked = client.post(f"{base}/{note['id']}/look", json={"blocks": bolder(note)})
    assert looked.status_code == 200 and looked.json()["note"]["blocks"][0]["look"]["bold"] is True
    assert looked.json()["note"]["updated_by"] == OWNER

    moved = client.post(f"{base}/{note['id']}/field", json={"node_uuid": "test-other"})
    assert moved.json()["note"]["field"]["label"] == "Disclosure of other notes to accounts"
    unplaced = client.post(f"{base}/{note['id']}/field", json={"node_uuid": None}).json()["note"]
    assert unplaced["field"] is None
    undone = client.post(f"{base}/{note['id']}/undo").json()["note"]
    assert undone["field"]["node_uuid"] == "test-other"

    confirmed = client.post(f"{base}/{note['id']}/confirm").json()["note"]
    assert confirmed["confirmed_by"] == OWNER
    redone = client.post(f"{base}/{note['id']}/redo", json={"reason": "Copy it again."}).json()["note"]
    assert redone["blocks"] == note["blocks"]

    history = client.get(f"{base}/{note['id']}/history").json()["history"]
    assert [h["action"] for h in history] == ["place", "look", "move", "clear", "restore", "confirm", "redo"]
    assert [h["actor_kind"] for h in history] == ["agent"] + ["person"] * 6
    assert history[-1]["reason"] == "Copy it again."
    first = client.post(f"{base}/{note['id']}/undo", json={"history_id": history[1]["id"]}).json()["note"]
    assert first["blocks"] == note["blocks"]


def test_refusals_come_back_as_one_sentence(client):
    run_id = notes_run()
    signed_in(client)
    note = place(run_id)
    base = f"/api/runs/{run_id}/notes"
    response = client.post(f"{base}/{note['id']}/field", json={"node_uuid": "test-heading"})
    assert response.status_code == 422
    assert response.json()["detail"] == "Notes to the financial statements is a heading, so place the note in a field under it."
    blocks = bolder(note)
    blocks[0] = {**blocks[0], "text": "4. Plant"}
    response = client.post(f"{base}/{note['id']}/look", json={"blocks": blocks})
    assert (response.status_code, response.json()["detail"]) == (422, store.LOOK_ONLY)
    response = client.post(f"{base}/{note['id']}/field", json={"node_uuid": "no-such-field"})
    assert (response.status_code, response.json()["detail"]) == (422, "There is no such note field.")
    assert client.get(f"{base}/999").json()["detail"] == "There is no such note in this run."
    assert client.get(f"{base}/999").status_code == 404
    assert client.get("/api/runs/999/notes").status_code == 404

    other = notes_run()
    response = client.post(f"/api/runs/{other}/notes/{note['id']}/confirm")
    assert (response.status_code, response.json()["detail"]) == (422, store.ANOTHER_RUN)
    response = client.post(f"{base}/{note['id']}/undo", json={"history_id": 999})
    assert (response.status_code, response.json()["detail"]) == (404, "There is no such change in this note's history.")
    with db.connect() as conn:
        assert len(store.note_history(conn, run_id, note["id"])) == 1


def test_a_disabled_person_cannot_open_the_run(client):
    run_id = notes_run()
    signed_in(client)
    place(run_id, PPE)
    with db.connect() as conn:
        conn.execute("UPDATE users SET disabled = 1 WHERE email = ?", (OWNER,))
    assert client.get(f"/api/runs/{run_id}/notes").status_code in (401, 403, 404)
