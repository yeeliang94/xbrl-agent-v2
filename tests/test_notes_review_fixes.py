"""Step 6 review fixes on the server: preview pictures are trimmed like page
pictures, a person's confirm marks every not-sure look done and its undo
brings them and the settled gaps back, the look response names its history
row, comments on the notes as a whole or on one report, and the Reviewer's
copy of the notes principles. No network."""
from __future__ import annotations

from types import SimpleNamespace

from pydantic_ai.messages import BinaryContent, ModelRequest, ToolReturnPart

from app import db
from app.agents import workbench
from app.notes import agent as notes_agent, instructions as notes_instructions, store
from app.review import agent as review_agent, comments, instructions as review_instructions
from tests.notes_agent_helpers import confirmed_notes_run
from tests.test_note_store import RECEIVABLES, place
from tests.test_notes_review_routes import _report, _review_run

AGENT = store.Actor("agent", "notes")


def _preview(call_id: str) -> ModelRequest:
    picture = ["Note id 1:", BinaryContent(b"x", media_type="image/png")]
    return ModelRequest(parts=[ToolReturnPart("preview_note", picture, tool_call_id=call_id)])


def _pictures(messages) -> int:
    return sum(1 for m in messages for p in m.parts if isinstance(p.content, list)
               and any(isinstance(i, BinaryContent) for i in p.content))


def test_earlier_preview_pictures_are_dropped_once_past_the_budget():
    run_id = confirmed_notes_run()
    deps, _ = notes_agent.build_deps(run_id, "look")
    trimmer = notes_agent.spec("gpt-5.4", deps, workbench.Workbench(False, "Off in this test.")).history_processor
    previews = [_preview(f"p{i}") for i in range(notes_agent.PICTURE_BUDGET + 2)]
    assert _pictures(trimmer(previews)) == len(previews)   # nothing goes before the first save
    deps.writes = 1
    shaped = trimmer(previews)
    assert _pictures(shaped) == notes_agent.PICTURE_BUDGET // 2
    assert _pictures(shaped[-1:]) == 1                       # the newest is kept
    assert "preview_notes" in review_agent.PICTURE_TOOLS


def _unsure_receivables(run_id: int) -> dict:
    note = place(run_id, RECEIVABLES)
    blocks = [dict(b) for b in note["blocks"]]
    blocks[0] = {**blocks[0], "look": {**blocks[0]["look"], "unsure": ["bold"]}}
    with db.connect(immediate=True) as conn:
        return store.set_look(conn, run_id, note["id"], blocks, AGENT)


def test_a_persons_confirm_marks_every_not_sure_look_done_and_undo_brings_them_and_the_gaps_back(client):
    run_id = _review_run(client)
    note = _unsure_receivables(run_id)
    assert note["has_unsure"] and note["format_state"] == "not_sure"
    gap = _report(run_id, "source_gap", note_number="5", pages=[24])
    base = f"/api/runs/{run_id}/notes/{note['id']}"
    reports = f"/api/runs/{run_id}/notes/reports"

    confirmed = client.post(f"{base}/confirm").json()["note"]
    assert not confirmed["has_unsure"] and confirmed["format_state"] == "fine"
    assert {r["id"]: r["status"] for r in client.get(reports).json()["reports"]}[gap] == "settled"
    confirm_id = client.get(f"{base}/history").json()["history"][-1]["id"]

    undone = client.post(f"{base}/undo", json={"history_id": confirm_id}).json()["note"]
    assert undone["has_unsure"] and undone["format_state"] == "not_sure" and undone["confirmed_by"] is None
    assert {r["id"]: r["status"] for r in client.get(reports).json()["reports"]}[gap] == "open"

    # Confirmed again, a later look change stays fine, and its response names the history row it added.
    client.post(f"{base}/confirm")
    looked = client.post(f"{base}/look", json={"blocks": client.get(base).json()["note"]["blocks"]}).json()
    assert looked["note"]["format_state"] == "fine"
    assert looked["history_id"] == client.get(f"{base}/history").json()["history"][-1]["id"]


def test_the_notes_agents_comment_on_the_notes_as_a_whole_is_titled_the_notes_in_needs_you(client):
    run_id = _review_run(client)
    target = {"kind": "statement", "statement": "NOTES", "concept_uuid": None, "period": None,
              "entity_scope": None, "dimension_key": ""}
    with db.connect(immediate=True) as conn:
        comment_id = comments.add_agent_comment(conn, run_id, "notes", target, "Note 9 is printed twice.")
    item = next(i for i in client.get(f"/api/runs/{run_id}/needs-you").json()["items"]
                if i.get("comment_id") == comment_id)
    assert item["title"] == "The notes" and item["statement"] == "NOTES" and item["target_kind"] == "notes"
    assert item["concept_uuid"] is None and item["figure_id"] is None


def test_a_person_comments_on_the_notes_or_on_a_missing_field_and_the_reviewer_reads_the_report(client):
    run_id = _review_run(client)
    missing = _report(run_id, "missing_mandatory_field", node_uuid="test-other")
    url = f"/api/runs/{run_id}/comments"
    on_field = client.post(url, json={"target": {"kind": "statement", "statement": "NOTES", "report_id": missing},
                                      "text": "The report prints this note on page 30."})
    assert on_field.status_code == 201, on_field.text
    target = on_field.json()["comment"]["target"]
    assert target["report_id"] == missing and target["field_label"] == "Disclosure of other notes to accounts"
    whole = client.post(url, json={"target": {"kind": "statement", "statement": "NOTES"}, "text": "Check note 9."})
    assert whole.json()["comment"]["target"]["field_label"] == "The notes"
    unknown = client.post(url, json={"target": {"kind": "statement", "statement": "NOTES", "report_id": 999},
                                     "text": "x"})
    assert unknown.status_code == 404 and unknown.json()["detail"] == "There is no such report in this run."

    with db.connect() as conn:
        row = conn.execute("SELECT * FROM comments WHERE id = ?", (on_field.json()["comment"]["id"],)).fetchone()
        deps = SimpleNamespace(run_id=run_id, outline=SimpleNamespace(note_ids={"test-other": "LIST-5"}))
        where = review_agent._where(row, deps, conn)
    assert "LIST-5 Disclosure of other notes to accounts" in where and "Test reason." in where

    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE run_setup SET notes_included = 0 WHERE run_id = ?", (run_id,))
    off = client.post(url, json={"target": {"kind": "statement", "statement": "NOTES"}, "text": "x"})
    assert off.status_code == 422 and "leaves the notes out" in off.json()["detail"]


def test_the_notes_principle_places_a_note_whole_and_the_reviewers_copy_names_its_own_way_to_say_so():
    assert "field whose meaning covers the whole note" in notes_instructions.INSTRUCTIONS
    text = review_instructions.instructions(False, notes=True)
    assert "field whose meaning covers the whole note" in text
    assert "report the note as routed" not in text and "say in your answer that it belongs there" in text
