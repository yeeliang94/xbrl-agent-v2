"""Regression tests for the final review: the Reviewer packet names the entity, a
round at its limit with its work complete is done, the "changed" refusal
says how to fix it, Undo reports a kept guidance line and waits for review,
a scope answer that switches the balance sheet off re-queues a queued
extraction cleanly, and a person's figure in a blank field needs its page.
No network."""
from __future__ import annotations

import json

from app import db
from app.extraction import job as extraction_job
from app.jobs import worker
from app.models import factory
from app.review import agent as review_agent
from tests.review_helpers import comment_on, field_uuid, reviewed_run, value
from tests.test_extraction_job import SETUP, read_run, returns, script, signed_in  # noqa: F401 - the fixture
from tests.test_review_comments import _round, _work
from tests.test_scope_questions import _ask, _states


def _scripted(monkeypatch, steps, seen):
    monkeypatch.setattr(factory, "build_model", lambda model_id: script(steps, seen))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")


def test_the_reviewer_packet_names_the_entity(signed_in):
    run_id = reviewed_run(signed_in)
    comment_on(signed_in, run_id, "FP-s404")
    sent = _round(signed_in, run_id)
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM rounds WHERE id = ?", (sent["id"],)).fetchone()
    _, message = review_agent.build_deps(row)
    assert "Trade payables" in message and "Company figures, this year (CY)" in message


async def test_a_round_at_its_step_limit_with_its_work_complete_is_done(signed_in, monkeypatch):
    run_id = reviewed_run(signed_in)
    cid = comment_on(signed_in, run_id, "FP-s404")["id"]
    _scripted(monkeypatch, [("answer_comment", {"answers": [{"comment_id": cid, "outcome": "not_changed",
                                                             "answer": "Page 2 prints 250."}]})]
              + [("read_pages", {"pages": [2]})] * 60, [])
    sent = _round(signed_in, run_id)
    assert await worker.run_once()
    body = signed_in.get(f"/api/runs/{run_id}/rounds/{sent['id']}").json()["round"]
    assert body["status"] == "done" and body["summary"].startswith("Stopped at the step limit")
    assert _states(run_id)[0] == "in_review"


async def test_the_changed_refusal_says_how_to_fix_it(signed_in, monkeypatch):
    run_id = reviewed_run(signed_in)
    cid = comment_on(signed_in, run_id, "FP-s404")["id"]
    seen: list = []
    _scripted(monkeypatch, [("answer_comment", {"answers": [{"comment_id": cid, "outcome": "changed",
                                                             "answer": "Done."}]})] * 3, seen)
    _round(signed_in, run_id)
    await worker.run_once()
    assert "naming this comment in comment_ids on the write that corrects it" in returns(
        seen[-1], "answer_comment")[0]


def test_undo_says_when_a_guidance_line_from_the_comment_stays(signed_in):
    run_id = reviewed_run(signed_in)
    cid = comment_on(signed_in, run_id, "FP-s404", scope="company")["id"]
    sent = _round(signed_in, run_id)
    _work(run_id, sent["id"], [("FP-s404", "CY", 300, "Trade payables", [cid])], [(cid, "changed", "Used 300.")])
    with db.connect() as conn:
        conn.execute("UPDATE comments SET proposed_guidance = 'Payables follow the face.' WHERE id = ?", (cid,))
        company_id = conn.execute("SELECT company_id FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
    assert signed_in.post(f"/api/runs/{run_id}/comments/{cid}/guidance").status_code == 200
    body = signed_in.post(f"/api/runs/{run_id}/comments/{cid}/undo").json()
    assert body["guidance_line_kept"] == [{"comment_id": cid, "company_id": company_id, "version": 1}]
    assert signed_in.get(f"/api/companies/{company_id}/guidance").json()["guidance"]["lines"] == [
        "Payables follow the face."]


def test_undo_waits_until_the_run_is_back_in_review(signed_in):
    run_id = reviewed_run(signed_in)
    cid = comment_on(signed_in, run_id, "FP-s404")["id"]
    sent = _round(signed_in, run_id)
    _work(run_id, sent["id"], [("FP-s404", "CY", 300, "Trade payables", [cid])], [(cid, "changed", "Used 300.")])
    with db.connect() as conn:   # extraction queued again after Try again
        conn.execute("UPDATE runs SET status = 'ready' WHERE id = ?", (run_id,))
    response = signed_in.post(f"/api/runs/{run_id}/comments/{cid}/undo")
    assert (response.status_code, response.json()["detail"]) == (409, "Undo once the run is back in review.")
    assert value(run_id, "FP-s404") == 300


async def test_an_answer_switching_the_balance_sheet_off_requeues_a_job_handed_back_for_the_rest(signed_in):
    setup = {**SETUP, "statements": [SETUP["statements"][0],
                                     {"statement": "SOPL", "layout": "Function", "included": True, "pages": [2]},
                                     *SETUP["statements"][2:]]}
    run_id = read_run(signed_in)
    assert signed_in.post(f"/api/runs/{run_id}/setup", json=setup).status_code == 200   # its job stays queued
    choices = [{"label": "Not printed", "value": "NotPrepared", "effect": "No balance sheet", "suggested": True},
               {"label": "As set up", "value": "CuNonCu", "effect": "Carries on"}]
    assert _ask(run_id, field="layout", statement="SOFP", question="Is a balance sheet printed?",
                choices=choices).startswith("Your question is saved")
    response = signed_in.post(f"/api/runs/{run_id}/question/answer", json={"choice": 0})
    assert response.status_code == 200, response.json()
    assert _states(run_id) == ("ready", "waiting")
    with db.connect() as conn:   # the job handed back now holds what is left: profit or loss
        job = conn.execute("SELECT status, payload_json FROM jobs WHERE run_id = ? AND kind = 'extract'",
                           (run_id,)).fetchone()
    assert job["status"] in ("queued", "retry") and json.loads(job["payload_json"]) == {"statements": ["SOPL"]}
    await extraction_job.run_extraction(run_id, statements=("SOFP",))   # a stale job still finishes cleanly
    assert _states(run_id)[1] == "done"


def test_a_person_typing_into_a_blank_field_names_the_page(signed_in):
    run_id = reviewed_run(signed_in)
    body = {"concept_uuid": field_uuid(run_id, "FP-s427"), "period": "CY", "entity_scope": "Company", "value": 40}
    missing = signed_in.post(f"/api/runs/{run_id}/figures", json=body)
    assert (missing.status_code, missing.json()["detail"]) == (422, "Give the page this amount is printed on.")
    outside = signed_in.post(f"/api/runs/{run_id}/figures", json={**body, "page": 9})
    assert (outside.status_code, outside.json()["detail"]) == (422, "The page must be within the document's "
                                                                    "4 pages.")
    saved = signed_in.post(f"/api/runs/{run_id}/figures", json={**body, "page": 2, "printed_label": "Accruals "
                                                                                                     " and others"})
    assert saved.status_code == 200, saved.json()
    assert [(line["printed_label"], line["page"]) for line in saved.json()["figure"]["lines"]] == [
        ("Accruals and others", 2)]
    plain = signed_in.post(f"/api/runs/{run_id}/figures", json={**body, "period": "PY", "page": 3})
    assert plain.status_code == 200 and plain.json()["figure"]["lines"][0]["printed_label"] == "Accruals"
