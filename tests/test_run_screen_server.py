"""Server additions for the run screen (step 5c): one run with its
statements, failure, current statement and open question; page numbers on
events; stopping a running extraction and retrying it; and the page picture
of a run with no document. No network."""
from __future__ import annotations

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app import db
from app.jobs import worker
from app.models import factory
from app.reading import job as reading_job
from app.runs import events
from app.runs.events import list_events
from tests import reading_fakes as fakes
from tests.conftest import make_run
from tests.review_helpers import field_uuid, reviewed_run, save
from tests.test_extraction_job import FINAL, SETUP, read_run, signed_in  # noqa: F401 - the fixture
from tests.test_scope_questions import _ask, _states

SAVE = ("save_figures", {"figures": [{"field": "FP-s28", "lines": [{"label": "Plant and equipment", "page": 2,
                                                                     "cy": 1200}]}]})


def _confirmed(client) -> int:
    run_id = read_run(client)
    assert client.post(f"/api/runs/{run_id}/setup", json=SETUP).status_code == 200
    return run_id


def _model(steps, on_call=None):
    """A figures model making `steps` in order; `on_call(n)` runs before answering request n (from 1)."""
    def answer(messages, info: AgentInfo) -> ModelResponse:
        done = sum(1 for m in messages if isinstance(m, ModelResponse))
        if on_call:
            on_call(done + 1)
        name, args = steps[done] if done < len(steps) else (FINAL, {"summary": "Done."})
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name if name == FINAL else name, args)])
    return FunctionModel(answer)


def _use(monkeypatch, model) -> None:
    monkeypatch.setattr(factory, "build_model", lambda model_id: model)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")


def test_one_run_gives_its_statements_failure_current_statement_and_open_question(signed_in):
    run_id = _confirmed(signed_in)
    body = signed_in.get(f"/api/runs/{run_id}").json()["run"]
    listed = next(r for r in signed_in.get("/api/runs").json()["runs"] if r["id"] == run_id)
    assert {k: body[k] for k in listed} == listed   # every run-list field
    assert body["statements"] == [{"statement": "SOFP", "name": "statement of financial position",
                                   "layout": "CuNonCu", "layout_label": "Current and non-current", "pages": [2]}]
    assert body["failure"] is None and body["working_on"] is None and body["open_question_id"] is None
    assert {s["name"]: s["status"] for s in body["stages"]} == {"upload": "done", "read": "done", "setup": "done",
                                                               "extract": "waiting"}

    with db.connect() as conn:
        conn.execute("UPDATE stages SET status = 'working', working_on = 'SOFP' WHERE run_id = ? AND name = 'extract'",
                     (run_id,))
    assert signed_in.get(f"/api/runs/{run_id}").json()["run"]["working_on"] == "SOFP"
    with db.connect() as conn:
        conn.execute("UPDATE stages SET status = 'waiting' WHERE run_id = ? AND name = 'extract'", (run_id,))
    _ask(run_id)
    assert signed_in.get(f"/api/runs/{run_id}").json()["run"]["open_question_id"] is not None
    assert signed_in.get("/api/runs/999").json() == {"detail": "There is no such run."}


async def test_a_failed_run_says_which_stage_failed_and_why(signed_in, monkeypatch):
    run_id = _confirmed(signed_in)
    _use(monkeypatch, _model([(FINAL, {"summary": "Nothing."})] * 10))
    assert await worker.run_once()
    failure = signed_in.get(f"/api/runs/{run_id}").json()["run"]["failure"]
    assert failure["stage"] == "extract" and failure["sentence"].startswith(
        "The statement of financial position could not be filled: no figure was saved.")


async def test_events_name_the_pages_their_step_concerns(signed_in, monkeypatch):
    run_id = _confirmed(signed_in)
    _use(monkeypatch, _model([("read_pages", {"pages": [3, 2]}), SAVE, ("run_checks", {}),
                              ("ask_scope", {"field": "unit", "question": "RM or RM thousands?",
                                             "evidence": [{"text": "RM'000 above the columns", "page": 2},
                                                          {"text": "Ringgit named", "page": 3}],
                                             "choices": [{"label": "RM thousands", "value": "RM'000",
                                                          "effect": "x", "suggested": True},
                                                         {"label": "RM", "value": "RM", "effect": "y"}]})]))
    assert await worker.run_once()
    by_kind = {}
    for e in list_events(run_id=run_id):
        by_kind.setdefault((e["source"], e["kind"]), []).append(e)
    assert by_kind[("extraction", "statement")][0]["pages"] == [2]
    assert by_kind[("extraction", "statement")][0]["message"] == "Working on the statement of financial position."
    read = next(e for e in by_kind[("figures", "looked")] if e["data"]["tool"] == "read_pages")
    assert read["pages"] == [2, 3] and read["message"] == "Looked at pages 2, 3."
    assert all(e["pages"] == [] for e in by_kind[("figures", "tool")])   # the internal row names no page
    assert by_kind[("figures", "saved")][0]["pages"] == [2]
    assert isinstance(by_kind[("figures", "checked")][0]["pages"], list)
    assert by_kind[("figures", "asked")][0]["pages"] == [2, 3]
    assert by_kind[("extraction", "queued")][0]["pages"] == []
    feed = signed_in.get(f"/api/runs/{run_id}/events").json()["events"]
    assert next(e for e in feed if e["kind"] == "saved")["pages"] == [2]
    detail = signed_in.get(f"/api/runs/{run_id}/events/{by_kind[('figures', 'asked')][0]['id']}").json()["event"]
    assert detail["pages"] == [2, 3]

    answered = signed_in.post(f"/api/runs/{run_id}/question/answer", json={"choice": 1})
    assert answered.status_code == 200
    assert next(e for e in list_events(run_id=run_id) if e["kind"] == "answered")["pages"] == [2, 3]


def test_the_document_map_and_failed_checks_name_their_pages(signed_in):
    run_id = reviewed_run(signed_in)
    reading_job._report_map(run_id, None, fakes.good_map(), [])
    found = [e for e in list_events(run_id=run_id) if e["kind"] == "found"]
    assert found[0]["message"] == "Financial position on page 2." and found[0]["pages"] == [2]
    assert found[-1]["message"] == "2 notes, pages 3 to 3." and found[-1]["pages"] == [3]
    with db.connect() as conn:
        assert events.figure_pages(conn, run_id, [(field_uuid(run_id, "FP-s28"), "CY", "Company"),
                                                  (None, None, None)]) == [2]


async def test_a_running_extraction_stops_between_steps_and_can_be_retried(signed_in, monkeypatch):
    run_id = _confirmed(signed_in)

    def press_stop(n):
        if n == 2:
            assert signed_in.post(f"/api/runs/{run_id}/extract/stop").status_code == 202
    calls = []
    _use(monkeypatch, _model([SAVE, ("add_up", {"sums": [{"name": "a", "amounts": [1, 2]}]}),
                              ("run_checks", {})], lambda n: (calls.append(n), press_stop(n))))
    assert await worker.run_once()
    assert calls == [1, 2]   # no request after the stop
    assert _states(run_id) == ("in_review", "stopped")
    with db.connect() as conn:
        stage = conn.execute("SELECT error, working_on, stop_requested FROM stages WHERE run_id = ? "
                             "AND name = 'extract'", (run_id,)).fetchone()
        kept = conn.execute("SELECT value FROM figures WHERE run_id = ? AND origin = 'agent'", (run_id,)).fetchone()
    assert stage["error"] == "Stopped on request; the figures saved so far are kept." and stage["working_on"] is None
    assert kept["value"] == 1200
    assert "Extraction stopped on request. The figures saved so far are kept." in [
        e["message"] for e in list_events(run_id=run_id)]
    refused = signed_in.post(f"/api/runs/{run_id}/extract/stop")
    assert refused.status_code == 409
    assert refused.json()["detail"] == "Extraction is not running, so there is nothing to stop."

    retried = signed_in.post(f"/api/runs/{run_id}/extract/retry")
    assert retried.status_code == 202 and retried.json()["run"]["status"] == "ready"
    assert _states(run_id) == ("ready", "waiting")


def test_a_queued_extraction_stops_at_once_and_a_run_with_nothing_saved_can_be_retried(signed_in):
    run_id = _confirmed(signed_in)
    response = signed_in.post(f"/api/runs/{run_id}/extract/stop")
    assert response.status_code == 202 and response.json()["run"]["status"] == "stopped"
    assert _states(run_id) == ("stopped", "stopped")
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM jobs WHERE run_id = ? AND kind = 'extract'",
                            (run_id,)).fetchone()[0] == "done"
    assert signed_in.post(f"/api/runs/{run_id}/extract/retry").status_code == 202
    assert _states(run_id) == ("ready", "waiting")


def test_stop_is_refused_when_nothing_runs(signed_in):
    run_id = reviewed_run(signed_in)
    save(run_id, "FP-s28", "PY", 1000, "Plant and equipment")
    response = signed_in.post(f"/api/runs/{run_id}/extract/stop")
    assert (response.status_code, response.json()["detail"]) == (
        409, "Extraction is not running, so there is nothing to stop.")
    assert signed_in.post("/api/runs/999/extract/stop").status_code == 404


def test_a_run_with_no_document_has_no_page_pictures(signed_in):
    run_id = make_run()
    response = signed_in.get(f"/api/runs/{run_id}/pages/1/image")
    assert (response.status_code, response.json()) == (404, {"detail": "This run has no document."})


def test_the_feed_pairs_question_events_by_id(signed_in):
    run_id = _confirmed(signed_in)
    _ask(run_id)
    question_id = signed_in.get(f"/api/runs/{run_id}/question").json()["question"]["id"]
    assert signed_in.post(f"/api/runs/{run_id}/question/answer", json={"choice": 1}).status_code == 200
    feed = signed_in.get(f"/api/runs/{run_id}/events").json()["events"]
    assert [e["question_id"] for e in feed if e["kind"] in ("asked", "answered")] == [question_id, question_id]
    assert all(e["question_id"] is None for e in feed if e["kind"] not in ("asked", "answered"))


def test_guidance_at_setup_comes_from_an_existing_company_the_suggested_name_matches(signed_in):
    first = _confirmed(signed_in)   # makes "Test Sdn. Bhd."
    with db.connect() as conn:
        company_id = conn.execute("SELECT company_id FROM runs WHERE id = ?", (first,)).fetchone()[0]
    assert signed_in.put(f"/api/companies/{company_id}/guidance",
                         json={"based_on": 0, "lines": ["Keep deposits apart."]}).status_code == 200
    at_setup = read_run(signed_in)   # the Reader suggests "Test Sdn. Bhd." again
    body = signed_in.get(f"/api/runs/{at_setup}/guidance").json()
    assert body["company_id"] == company_id and body["company_from_suggestion"] is True
    assert body["company"]["lines"] == ["Keep deposits apart."]

    other = read_run(signed_in)
    with db.connect(immediate=True) as conn:
        from app.reading import store as reading
        reading.save_map(conn, other, fakes.good_map(company=fakes.finding("New Co Bhd")), [])
        before = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    body = signed_in.get(f"/api/runs/{other}/guidance").json()
    assert body["company_id"] is None and body["company"] is None and body["company_from_suggestion"] is False
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == before   # nothing created
