"""The Reviewer end to end with a scripted model: a seeded wrong figure is
corrected through a comment, the server counts what changed, and the finish
holds the round to every comment answered, a check run after the last change
and no check broken by the round. No network."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import db
from app.jobs import worker
from app.models import factory
from app.review import changes, tools
from app.runs.events import list_events
from tests.review_helpers import comment_on, reviewed_run, value
from tests.test_extraction_job import FINAL, returns, script, signed_in  # noqa: F401 - the fixture


@pytest.fixture
def scripted(monkeypatch):
    def use(steps):
        seen: list = []
        monkeypatch.setattr(factory, "build_model", lambda model_id: script(steps, seen))
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
        return seen
    return use


def _round(client, run_id):
    response = client.post(f"/api/runs/{run_id}/rounds")
    assert response.status_code == 202, response.json()
    return response.json()["round"]


async def test_a_seeded_wrong_figure_is_corrected_through_a_comment_and_undo_restores_it(signed_in, scripted):
    run_id = reviewed_run(signed_in)   # trade payables saved as 250; page 2 prints 300
    comment = comment_on(signed_in, run_id, "FP-s404", text="Page 2 prints 300 for trade payables.")
    cid = comment["id"]
    seen = scripted([
        ("read_pages", {"pages": [2]}),
        ("save_figures", {"figures": [
            {"field": "FP-s404", "lines": [{"label": "Trade payables", "page": 2, "cy": 300}], "comment_ids": [cid],
             "reason": "Page 2 prints 300."},
            {"field": "FP-s28", "lines": [{"label": "Plant and equipment", "page": 2, "cy": 1200, "py": 1000}]}]}),
        (FINAL, {"summary": "Used page 2's trade payables."}),
        ("answer_comment", {"answers": [{"comment_id": cid, "outcome": "changed",
                                         "answer": "Used 300 for trade payables, as page 2 prints."}]}),
        ("run_checks", {}),
        ("leave_comment", {"comments": [{"field": "FP-s28", "period": "CY",
                                         "text": "Note 1 gives no split of plant and equipment."}]}),
        (FINAL, {"summary": "Used page 2's trade payables; the balance now agrees."}),
    ])
    sent = _round(signed_in, run_id)

    assert await worker.run_once()

    body = signed_in.get(f"/api/runs/{run_id}/rounds/{sent['id']}").json()
    assert body["round"]["status"] == "done", body["round"]
    assert body["round"]["summary"] == "Used page 2's trade payables; the balance now agrees."
    assert value(run_id, "FP-s404") == 300
    report = body["report"]
    mine = report["comments"][0]
    assert mine["verified"] and [(f["field_label"], f["was"], f["is_now"]) for f in mine["figures"]] == [
        ("Trade payables", 250, 300)]
    assert [(o["field_label"], o["period"], o["was"], o["is_now"], o["served"]) for o in report["other"]] == [
        ("Plant and equipment", "PY", None, 1000, [])]
    assert report["totals_recalculated"]
    assert report["checks"]["now"].get("failed", 0) == 0 or report["checks"]["newly_failing"] == []

    # The agent saw the server's count after its save, and the finish was sent back once.
    saved = returns(seen[-1], "save_figures")[0]
    assert "counted by the server" in saved and "was 250, is now 300" in saved and "written for no comment" in saved
    with db.connect() as conn:
        run = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
        history = conn.execute("SELECT actor_name, round_id, comment_ids_json FROM figure_history WHERE run_id = ? "
                               "AND round_id IS NOT NULL AND action = 'save' ORDER BY id", (run_id,)).fetchall()
        calls = conn.execute("SELECT COUNT(*) FROM model_calls WHERE run_id = ? AND source = 'review'",
                             (run_id,)).fetchone()[0]
    assert run == "in_review"
    assert {(h["actor_name"], h["round_id"]) for h in history} == {("reviewer", sent["id"])}
    assert f"[{cid}]" in {h["comment_ids_json"] for h in history}
    assert calls == 7
    events = [e for e in list_events(run_id=run_id) if e["source"] == "review"]
    kinds = [e["kind"] for e in events]
    assert {"queued", "started", "saved", "answered", "checked", "notice", "done"} <= set(kinds)
    assert any("1 of 1 comment(s) changed" in e["message"] for e in events if e["kind"] == "done")
    listed = signed_in.get(f"/api/runs/{run_id}/comments").json()["comments"]
    assert [(c["author_kind"], c["status"]) for c in listed] == [("person", "answered"), ("agent", "open")]
    assert listed[1]["author_name"] == "reviewer" and listed[1]["round_id"] == sent["id"]
    needs = signed_in.get(f"/api/runs/{run_id}/needs-you").json()["items"]
    assert any(i["kind"] == "agent_comment" and i["comment_id"] == listed[1]["id"] for i in needs)

    undone = signed_in.post(f"/api/runs/{run_id}/comments/{cid}/undo")
    assert undone.status_code == 200, undone.json()
    assert value(run_id, "FP-s404") == 250
    assert value(run_id, "FP-s28", "PY") == 1000


async def test_a_check_the_round_broke_blocks_the_finish_until_it_is_explained(signed_in, scripted):
    run_id = reviewed_run(signed_in, figures=(("FP-s28", 1200, "Plant and equipment"),
                                              ("FP-s404", 300, "Trade payables"),
                                              ("FP-41", 900, "Retained earnings")))   # the balance check passes
    cid = comment_on(signed_in, run_id, "FP-s404", text="Should this be 350?")["id"]
    seen = scripted([
        ("save_figures", {"figures": [{"field": "FP-s404", "lines": [{"label": "Trade payables", "page": 2,
                                                                       "cy": 350}], "comment_ids": [cid]}]}),
        ("answer_comment", {"answers": [{"comment_id": cid, "outcome": "changed", "answer": "Used 350."}]}),
        (FINAL, {"summary": "Used 350."}),
        ("run_checks", {}),
        (FINAL, {"summary": "Used 350."}),
        (FINAL, {"summary": "Used 350; the balance no longer agrees.",
                 "explained": [{"check": "sofp_balance", "reason": "Page 2 prints no equity line that balances."}]}),
    ])
    sent = _round(signed_in, run_id)
    assert await worker.run_once()

    retries = [str(getattr(p, "content", "")) for m in seen[-1] for p in getattr(m, "parts", [])
               if str(getattr(p, "content", "")).startswith("Not finished yet")]
    assert "Run the checks with run_checks after your last change." in str(retries[0])
    assert "passed when the round began and does not pass now" in str(retries[1])
    checked = returns(seen[-1], "run_checks")[0]
    assert "Passed when the round began and do not pass now. Each is a lead to trace" in checked
    round_ = signed_in.get(f"/api/runs/{run_id}/rounds/{sent['id']}").json()
    assert round_["round"]["status"] == "done"
    assert [c["name"] for c in round_["report"]["checks"]["newly_failing"]] == ["sofp_balance"]


async def test_changed_is_refused_when_the_server_sees_no_change_and_limits_end_the_round_failed(signed_in, scripted):
    run_id = reviewed_run(signed_in)
    cid = comment_on(signed_in, run_id, "FP-s404")["id"]
    seen = scripted([("answer_comment", {"answers": [{"comment_id": cid, "outcome": "changed", "answer": "Done."}]})]
                    + [("read_pages", {"pages": [2]})] * 60)
    sent = _round(signed_in, run_id)
    assert await worker.run_once()
    answered = returns(seen[-1], "answer_comment")[0]
    assert "Nothing has changed for comment" in answered
    with db.connect() as conn:
        row = conn.execute("SELECT status, error FROM rounds WHERE id = ?", (sent["id"],)).fetchone()
        job = conn.execute("SELECT status FROM jobs WHERE id = (SELECT job_id FROM rounds WHERE id = ?)",
                           (sent["id"],)).fetchone()[0]
    assert row["status"] == "failed" and "step limit" in row["error"] and "kept" in row["error"]
    assert job == "failed"
    assert signed_in.get(f"/api/runs/{run_id}/comments").json()["comments"][0]["status"] == "open"
    assert signed_in.get("/api/runs").json()["runs"][0]["status"] == "in_review"


def test_the_finish_names_every_reason_and_not_changed_is_never_verified():
    deps = SimpleNamespace(comment_ids=[1, 2], answered={1: "not_changed"}, writes=2, checked_at=1,
                           newly_failing=[], assessed=True)
    reasons = tools.finish_reasons(deps, tools.ReviewFinish(summary=""))
    assert any("Answer comment 2" in r for r in reasons)
    assert "Run the checks with run_checks after your last change." in reasons
    assert "Give a one-sentence summary for the person." in reasons
    deps.answered[2], deps.checked_at = "changed", 2
    deps.newly_failing = [{"name": "sofp_balance", "title": "Total assets equal total equity and liabilities"}]
    assert tools.finish_reasons(deps, tools.ReviewFinish(summary="x"))
    assert tools.finish_reasons(deps, tools.ReviewFinish(summary="x", explained=[
        {"check": "Total assets equal total equity and liabilities", "reason": "The page shows it."}])) == []
    # A re-check that assessed nothing is never read as passed, and is not "newly failing" either.
    summary = changes.check_summary([{"name": "a", "entity_scope": "Company", "status": "passed", "title": "A",
                                      "message": ""}],
                                    [{"name": "a", "entity_scope": "Company", "status": "not_assessed", "title": "A",
                                      "message": "No figures."}])
    assert summary["assessed"] is False and summary["newly_failing"] == []
