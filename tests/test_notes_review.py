"""Notes in the review loop with a scripted Reviewer (docs/step-6-plan.md 6e):
a round fixes a seeded wrong field and a seeded wrong border, the server
counts both, and Undo restores each; "Redo from source" rebuilds a note and
Undo restores it. No network."""
from __future__ import annotations

import pytest

from app import db
from app.jobs import worker
from app.models import factory
from app.notes import store
from tests.conftest import OWNER, login
from tests.notes_agent_helpers import field_ids
from tests.notes_helpers import notes_run
from tests.test_extraction_job import FINAL, returns, script

AGENT = store.Actor("agent", "notes")
RECEIVABLES = ("5", "Trade and other receivables", [(23, 3), (23, 4), (24, 0)])
BORROWINGS = ("6", "Borrowings", [(24, 1), (24, 2), (24, 3)])


@pytest.fixture
def scripted(monkeypatch):
    def use(steps):
        seen: list = []
        monkeypatch.setattr(factory, "build_model", lambda model_id: script(steps, seen))
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
        return seen
    return use


def _field(run_id: int, words: str) -> tuple[str, str]:
    """(the Reviewer's field id, its node_uuid) of the list of notes' field whose label holds these words."""
    from app.notes import agent

    deps, _ = agent.build_deps(run_id, "placing")
    fid = next(fid for label, fid in field_ids(run_id).items() if words in label.lower())
    return fid, deps.outline.note_field(fid).field_id


def _place(run_id: int, note: tuple, node_uuid: str) -> dict:
    number, title, sources = note
    with db.connect(immediate=True) as conn:
        return store.place_note(conn, run_id, store.NotePlacement(number, title, sources, node_uuid), AGENT)


def _table(note: dict) -> dict:
    return next(b for b in note["blocks"] if b["kind"] == "table")


def _in_review(client) -> tuple[int, dict, dict, str, str]:
    """A run in review: note 5 seeded in the borrowings field (wrong), note 6 in its own field with a rule
    under its first item (wrong: the source rules off the last item before the total)."""
    run_id = notes_run()
    assert login(client, OWNER).status_code == 200
    recv_id, recv_uuid = _field(run_id, "receivable")
    borrow_id, borrow_uuid = _field(run_id, "borrowing")
    receivables = _place(run_id, RECEIVABLES, borrow_uuid)
    borrowings = _place(run_id, BORROWINGS, borrow_uuid)
    blocks = [dict(b) for b in borrowings["blocks"]]
    table = next(b for b in blocks if b["kind"] == "table")
    table["rows"] = [dict(r) for r in table["rows"]]
    table["rows"][1]["line_below"] = {"style": "single", "columns": []}
    with db.connect(immediate=True) as conn:
        borrowings = store.set_look(conn, run_id, borrowings["id"], blocks, AGENT)
        conn.execute("UPDATE runs SET status = 'in_review' WHERE id = ?", (run_id,))
    return run_id, receivables, borrowings, recv_id, recv_uuid


def _comment(client, run_id: int, target: dict, text: str) -> dict:
    response = client.post(f"/api/runs/{run_id}/comments", json={"target": target, "text": text})
    assert response.status_code == 201, response.json()
    return response.json()["comment"]


def _send(client, run_id: int) -> dict:
    response = client.post(f"/api/runs/{run_id}/rounds")
    assert response.status_code == 202, response.json()
    return response.json()["round"]


def _note(run_id: int, note_id: int) -> dict:
    with db.connect() as conn:
        return store.get_note(conn, run_id, note_id)


async def test_a_round_fixes_a_wrong_field_and_a_wrong_border_counts_both_and_undo_restores_each(client, scripted):
    run_id, receivables, borrowings, recv_id, recv_uuid = _in_review(client)
    table = _table(borrowings)["id"]
    wrong_field = _comment(client, run_id, {"kind": "note", "note_id": receivables["id"], "note_part": None},
                           "This is the receivables note, not borrowings.")
    wrong_rule = _comment(client, run_id, {"kind": "note", "note_id": borrowings["id"], "note_part": {
        "block": table, "scope": "row", "row": 1, "column": None}},
        "The rule sits under bank overdraft, across the two amount columns, not under the term loan.")
    assert wrong_rule["target"]["field_label"] == "Note 6 Borrowings › Row: Term loan"
    c1, c2 = wrong_field["id"], wrong_rule["id"]
    seen = scripted([
        ("show_notes", {"note_ids": [receivables["id"], borrowings["id"]]}),
        ("find_note_fields", {"queries": ["trade and other receivables"]}),
        ("move_notes", {"moves": [{"note_id": receivables["id"], "to_field": recv_id, "comment_ids": [c1]}],
                        "note": f"Moving the receivables note to {recv_id}."}),
        ("set_note_look", {"changes": [
            {"note_id": borrowings["id"], "block": table, "target": "row", "rows": [2], "line_below": "none",
             "comment_ids": [c2]},
            {"note_id": borrowings["id"], "block": table, "target": "row", "rows": [4], "line_below": "single",
             "line_columns": [3, 4], "comment_ids": [c2]}]}),
        ("preview_notes", {"note_ids": [borrowings["id"]]}),
        ("answer_comment", {"answers": [
            {"comment_id": c1, "outcome": "changed", "answer": f"Moved the note to {recv_id}."},
            {"comment_id": c2, "outcome": "changed", "answer": "Put the rule under bank overdraft."}]}),
        (FINAL, {"summary": "Moved the receivables note and fixed the borrowings rule."}),   # sent back: no checks yet
        ("run_checks", {}),
        (FINAL, {"summary": "Moved the receivables note and fixed the borrowings rule."}),
    ])
    sent = _send(client, run_id)

    assert await worker.run_once()

    body = client.get(f"/api/runs/{run_id}/rounds/{sent['id']}").json()
    assert body["round"]["status"] == "done", body["round"]
    report = body["report"]
    assert report["counts"]["notes"] == 2 and report["counts"]["changed"] == 2
    by_comment = {c["comment_id"]: c for c in report["comments"]}
    moved = by_comment[c1]["notes"][0]
    assert by_comment[c1]["verified"] and moved["field_now"]["node_uuid"] == recv_uuid
    assert moved["differences"][0].startswith("field Disclosure of borrowings")
    assert by_comment[c2]["verified"] and by_comment[c2]["notes"][0]["differences"] == ["look changed"]
    assert report["notes_other"] == []
    rows = _table(_note(run_id, borrowings["id"]))["rows"]
    assert rows[1]["line_below"] is None and rows[3]["line_below"] == {"style": "single", "columns": [2, 3]}
    # The Reviewer saw the server's count after its writes; a person reads names, never field ids.
    said = returns(seen[-1], "set_note_look")[0]
    assert "counted by the server" in said and "look changed" in said
    with db.connect() as conn:   # a round that changed only notes still runs the checks before it finishes
        notices = [r[0] for r in conn.execute("SELECT message FROM events WHERE run_id = ? AND source = 'review' "
                                              "AND kind = 'notice'", (run_id,))]
    assert any("Run the checks with run_checks" in m for m in notices)
    comments = {c["id"]: c for c in client.get(f"/api/runs/{run_id}/comments").json()["comments"]}
    assert recv_id not in comments[c1]["answer"] and "receivables" in comments[c1]["answer"].lower()
    with db.connect() as conn:
        tagged = conn.execute("SELECT COUNT(*) FROM note_history WHERE run_id = ? AND round_id = ? "
                              "AND actor_name = 'reviewer'", (run_id, sent["id"])).fetchone()[0]
        moved_events = [r[0] for r in conn.execute("SELECT message FROM events WHERE run_id = ? AND source = 'review' "
                                                   "AND kind = 'moved'", (run_id,))]
        reasons = [r[0] for r in conn.execute("SELECT reason FROM note_history WHERE round_id = ?", (sent["id"],))]
    assert tagged == 2
    assert moved_events and not any(recv_id in m for m in moved_events + reasons)

    undone = client.post(f"/api/runs/{run_id}/comments/{c1}/undo")
    assert undone.status_code == 200, undone.json()
    assert [c["id"] for c in undone.json()["comments"]] == [c1]
    assert _note(run_id, receivables["id"])["field"]["node_uuid"] == receivables["field"]["node_uuid"]
    assert _table(_note(run_id, borrowings["id"]))["rows"][3]["line_below"] is not None   # c2 untouched

    assert client.post(f"/api/runs/{run_id}/comments/{c2}/undo").status_code == 200
    assert _note(run_id, borrowings["id"])["blocks"] == borrowings["blocks"]


async def test_redo_from_source_rebuilds_a_note_and_undo_restores_it(client, scripted):
    run_id, receivables, borrowings, _recv_id, _uuid = _in_review(client)
    redo = _comment(client, run_id, {"kind": "note", "note_id": borrowings["id"], "note_part": None},
                    "Redo from source")
    scripted([
        ("redo_notes", {"redos": [{"note_id": borrowings["id"], "comment_ids": [redo["id"]]}]}),
        ("answer_comment", {"answers": [{"comment_id": redo["id"], "outcome": "changed",
                                         "answer": "Copied the borrowings note again from page 24."}]}),
        ("run_checks", {}),
        (FINAL, {"summary": "Copied the borrowings note again."}),
    ])
    sent = _send(client, run_id)
    assert await worker.run_once()

    report = client.get(f"/api/runs/{run_id}/rounds/{sent['id']}").json()["report"]
    change = report["comments"][0]["notes"][0]
    assert change["changed"] and "copied again from its pages" in change["differences"]
    rebuilt = _note(run_id, borrowings["id"])
    assert all(r["line_below"] is None for r in _table(rebuilt)["rows"])   # the plain look again
    assert rebuilt["field"] == borrowings["field"]

    assert client.post(f"/api/runs/{run_id}/comments/{redo['id']}/undo").status_code == 200
    assert _note(run_id, borrowings["id"])["blocks"] == borrowings["blocks"]


async def test_taking_a_note_out_of_its_last_field_is_done_and_said_plainly(client, scripted):
    run_id, receivables, _borrowings, _recv_id, _uuid = _in_review(client)
    comment = _comment(client, run_id, {"kind": "note", "note_id": receivables["id"], "note_part": None},
                       "This note is not wanted here.")
    seen = scripted([
        ("move_notes", {"moves": [{"note_id": receivables["id"], "to_field": None,
                                   "comment_ids": [comment["id"]]}]}),
        ("answer_comment", {"answers": [{"comment_id": comment["id"], "outcome": "changed",
                                         "answer": "Took the note out of its field."}]}),
        ("run_checks", {}),
        (FINAL, {"summary": "Took the receivables note out."}),
    ])
    _send(client, run_id)
    assert await worker.run_once()
    said = returns(seen[-1], "move_notes")[0]
    assert "now placed nowhere" in said
    assert _note(run_id, receivables["id"])["field"] is None
    kinds = [i["kind"] for i in client.get(f"/api/runs/{run_id}/needs-you").json()["items"]]
    assert "unplaced_note" in kinds
    # A person's confirm after the round settles the note's gaps: Undo would undo half of it, so it says why.
    assert client.post(f"/api/runs/{run_id}/notes/{receivables['id']}/confirm").status_code == 200
    refused = client.post(f"/api/runs/{run_id}/comments/{comment['id']}/undo")
    assert refused.status_code == 409
    assert refused.json()["detail"] == ("Note 5 Trade and other receivables was changed outside this round after "
                                        "the round first wrote it, so restore it from its history instead.")


def _share_capital_run(client) -> tuple[int, dict, object, int]:
    """A run in review with the share capital note in its text field and one share capital figure, 1,000 for
    ordinary shares this year, marked Unsure."""
    from app.catalog import lookup
    from app.extraction import outline as outline_mod
    from app.figures import store as figures
    from app.notes import figure_tools

    run_id = notes_run()
    assert login(client, OWNER).status_code == 200
    with db.connect(immediate=True) as conn:
        family = lookup.run_family(conn, run_id)
        outline = outline_mod.build_with_numeric_notes(conn, family)
        line = next(f for f in outline.fields.values() if f.statement == "ISSUED_CAPITAL" and f.kind == "line"
                    and not lookup.concept(conn, f.concept_uuid).text)
        text_field = conn.execute(
            "SELECT n.concept_uuid FROM concept_nodes n JOIN template_slots s ON s.canonical_target_id = n.concept_uuid "
            "WHERE n.template_id = ? AND s.value_kind = 'html' AND s.validation_status = 'writable'",
            (family.note_template_ids["ISSUED_CAPITAL"],)).fetchone()[0]
        note = store.place_note(conn, run_id, store.NotePlacement("12", "Share capital", [(24, 2)], text_field), AGENT)
        axis, _members = figure_tools.categories(family.standard, line.sheet)
        dims = {axis: next(m for m in _members if m.endswith("OrdinarySharesMember"))} if axis else None
        figure = figures.save_figure(conn, run_id, figures.FigureWrite(
            line.concept_uuid, "CY", "Company", 1000, [figures.Line("Ordinary shares", 24, 1000)], dimensions=dims,
            certainty="unsure", reason="Printed in thousands."), figures.Actor("agent", "notes"))
        conn.execute("UPDATE runs SET status = 'in_review' WHERE id = ?", (run_id,))
    return run_id, note, line, figure["id"]


async def test_a_wrong_share_capital_figure_is_corrected_through_a_comment_counted_and_undone(client, scripted):
    run_id, note, line, figure_id = _share_capital_run(client)
    unsure = next(i for i in client.get(f"/api/runs/{run_id}/needs-you").json()["items"] if i["kind"] == "unsure")
    assert (unsure["figure_id"], unsure["statement"], unsure["note_id"]) == (figure_id, "ISSUED_CAPITAL", note["id"])

    comment = _comment(client, run_id, {"kind": "figure", "figure_id": figure_id},
                       "Page 24 prints 2,000 ordinary shares this year.")
    assert comment["target"]["statement"] == "ISSUED_CAPITAL" and comment["target"]["note_id"] == note["id"]
    assert comment["target"]["figure_id"] == figure_id and comment["target"]["field_label"]
    cid = comment["id"]
    seen = scripted([
        ("save_note_figures", {"figures": [{"field": line.id, "category": "OrdinarySharesMember",
                                            "lines": [{"label": "Ordinary shares", "page": 24, "cy": 2000}],
                                            "reason": "Page 24 prints 2,000.", "comment_ids": [cid]}]}),
        ("run_checks", {}),
        ("answer_comment", {"answers": [{"comment_id": cid, "outcome": "changed",
                                         "answer": f"Used 2,000 for {line.id}, as page 24 prints."}]}),
        (FINAL, {"summary": "Used page 24's ordinary shares."}),
    ])
    sent = _send(client, run_id)
    assert await worker.run_once()

    body = client.get(f"/api/runs/{run_id}/rounds/{sent['id']}").json()
    assert body["round"]["status"] == "done", body["round"]
    mine = body["report"]["comments"][0]
    assert mine["verified"] and [(f["figure_id"], f["statement"], f["was"], f["is_now"]) for f in mine["figures"]] \
        == [(figure_id, "ISSUED_CAPITAL", 1000, 2000)]
    first = next(m for m in seen[-1] if hasattr(m, "parts"))
    assert line.id in str(first.parts[-1].content)   # the packet names the field by id, with its outline
    answer = next(c for c in client.get(f"/api/runs/{run_id}/comments").json()["comments"] if c["id"] == cid)["answer"]
    assert line.id not in answer
    with db.connect() as conn:
        assert conn.execute("SELECT value FROM figures WHERE id = ?", (figure_id,)).fetchone()[0] == 2000

    assert client.post(f"/api/runs/{run_id}/comments/{cid}/undo").status_code == 200
    with db.connect() as conn:
        assert conn.execute("SELECT value FROM figures WHERE id = ?", (figure_id,)).fetchone()[0] == 1000
    # Right on a share capital figure confirms it, and its Unsure item clears.
    assert client.post(f"/api/runs/{run_id}/figures/{figure_id}/confirm").status_code == 200
    kinds = [(i["kind"], i.get("figure_id")) for i in client.get(f"/api/runs/{run_id}/needs-you").json()["items"]]
    assert ("unsure", figure_id) not in kinds
