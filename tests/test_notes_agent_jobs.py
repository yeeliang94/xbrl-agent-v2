"""The notes job beside the extract job (step 6d): confirming the setup queues
both unless the notes are switched off, the worker runs them side by side
(never two of one kind), the run is ready for review only once both ended,
and a scope question from the notes agent stops both stages. Scripted
models, no network."""
from __future__ import annotations

import asyncio
import time

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app import db
from app.jobs import queue, worker
from app.models import factory
from tests.notes_agent_helpers import FINAL, OPEN, session_of
from tests.test_extraction_job import SETUP, STEPS, read_run, signed_in  # noqa: F401 - the fixture

WITH_NOTES = {**SETUP, "notes_included": True}
NOTES_STEPS = {
    "placing": [("report_gap", {"gaps": [{"note": "1", "pages": [3], "reason": "Test: not transcribed."},
                                       {"note": "2", "pages": [3], "reason": "Test: not transcribed."}]}),
              ("report_coverage", {}),
              (FINAL, {"summary": "Reported both notes."})],
    "numeric": [("report_gap", {"gaps": [{"pages": [3], "reason": "No numeric notes are printed."}]}),
                (FINAL, {"summary": "Nothing to save."})],
}
ASK = ("ask_scope", {
    "field": "unit", "question": "The notes print amounts in thousands. Which unit applies?",
    "evidence": [{"text": "Amounts in RM'000", "page": 3}, {"text": "Amounts in RM", "page": 2}],
    "choices": [{"label": "RM, as set up", "value": "RM", "effect": "Carries on", "suggested": False},
                {"label": "RM'000", "value": "RM'000", "effect": "Restarts with the new unit", "suggested": True}]})


def one(sql: str, *args):
    with db.connect() as conn:
        row = conn.execute(sql, args).fetchone()
    return row[0] if row else None


async def until(check, seconds: float = 10.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        await asyncio.sleep(0.05)
    return False


def two_agents(figures_first, notes_first, notes_steps=NOTES_STEPS):
    """One model for both agents: the notes agent has list_notes, the figures agent does not. Each agent's
    first call runs its hook first."""
    async def answer(messages, info: AgentInfo) -> ModelResponse:
        done = sum(1 for m in messages if isinstance(m, ModelResponse))
        if any(t.name == "list_notes" for t in info.function_tools):
            session = session_of(messages)
            if session == "placing" and done == 0:
                await notes_first()
            steps = notes_steps.get(session, [])
        else:
            if done == 0:
                await figures_first()
            steps = STEPS
        name, args = steps[done] if done < len(steps) else (FINAL, {"summary": "Done.", "unresolved": OPEN})
        if name == FINAL:
            name = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(name, args)])
    return FunctionModel(answer)


async def run_worker_until(run_id: int, done) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run_forever(stop))
    try:
        assert await until(done, 30), "the jobs did not finish"
    finally:
        stop.set()
        await task


async def test_the_worker_runs_two_jobs_of_different_kinds_side_by_side_never_two_of_one_kind():
    both = asyncio.Event()
    seen: list[str] = []
    running: set[str] = set()

    async def work(job):
        running.add(job.kind)
        seen.append(",".join(sorted(running)))
        if len(running) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 5)
        await asyncio.sleep(0.05)
        running.discard(job.kind)

    for kind in ("test.side-a", "test.side-b"):
        if kind not in worker._HANDLERS:
            worker.handler(kind)(work)
    ids = [queue.enqueue("test.side-a"), queue.enqueue("test.side-a"), queue.enqueue("test.side-b")]
    await run_worker_until(0, lambda: all(queue.get(i).status == "done" for i in ids))
    assert seen[:2] == ["test.side-a", "test.side-a,test.side-b"]
    assert "test.side-a,test.side-a" not in seen and all(queue.get(i).status == "done" for i in ids)


async def test_confirming_the_setup_runs_figures_and_notes_side_by_side_then_the_run_is_ready(signed_in,
                                                                                            monkeypatch):
    run_id = read_run(signed_in)
    observed: dict = {}

    async def figures_first():   # proof the two run at once: the notes agent is working before figures start
        observed["notes_working"] = await until(
            lambda: one("SELECT status FROM stages WHERE run_id = ? AND name = 'notes'", run_id) == "working")

    async def notes_first():     # while the notes agent works, the finished figures do not end the run
        await until(lambda: one("SELECT status FROM stages WHERE run_id = ? AND name = 'extract'", run_id) == "done")
        observed["run_while_notes_work"] = one("SELECT status FROM runs WHERE id = ?", run_id)

    model = two_agents(figures_first, notes_first)
    monkeypatch.setattr(factory, "build_model", lambda model_id: model)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    assert signed_in.post(f"/api/runs/{run_id}/setup", json=WITH_NOTES).status_code == 200
    assert one("SELECT COUNT(*) FROM jobs WHERE run_id = ? AND kind IN ('extract', 'notes')", run_id) == 2

    await run_worker_until(run_id, lambda: one(
        "SELECT COUNT(*) FROM jobs WHERE run_id = ? AND kind IN ('extract', 'notes') AND status = 'done'",
        run_id) == 2)
    assert observed == {"notes_working": True, "run_while_notes_work": "extracting"}
    with db.connect() as conn:
        stages = {r[0]: r[1] for r in conn.execute("SELECT name, status FROM stages WHERE run_id = ?", (run_id,))}
        assert stages["extract"] == "done" and stages["notes"] == "done"
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "in_review"
        assert conn.execute("SELECT COUNT(*) FROM note_reports WHERE run_id = ?", (run_id,)).fetchone()[0] == 3
        sources = {r[0] for r in conn.execute("SELECT source FROM model_calls WHERE run_id = ?", (run_id,))}
        assert sources == {"figures", "notes"}


async def test_a_scope_question_from_the_notes_agent_stops_both_stages_and_the_answer_queues_both(signed_in,
                                                                                                monkeypatch):
    run_id = read_run(signed_in)

    async def figures_first():   # the notes agent asks while the figures agent works
        await until(lambda: one("SELECT COUNT(*) FROM scope_questions WHERE run_id = ?", run_id) == 1)

    async def notes_first():
        return None

    model = two_agents(figures_first, notes_first, {"placing": [ASK]})
    monkeypatch.setattr(factory, "build_model", lambda model_id: model)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    assert signed_in.post(f"/api/runs/{run_id}/setup", json=WITH_NOTES).status_code == 200
    await run_worker_until(run_id, lambda: one(
        "SELECT COUNT(*) FROM jobs WHERE run_id = ? AND kind IN ('extract', 'notes') AND status = 'done'",
        run_id) == 2)
    with db.connect() as conn:
        stages = {r[0]: r[1] for r in conn.execute("SELECT name, status FROM stages WHERE run_id = ?", (run_id,))}
        assert stages["extract"] == "asking" and stages["notes"] == "asking"
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "needs_answer"
        question = conn.execute("SELECT stage, asked_by FROM scope_questions WHERE run_id = ?", (run_id,)).fetchone()
        assert tuple(question) == ("notes", "notes")

    response = signed_in.post(f"/api/runs/{run_id}/question/answer", json={"choice": 0})
    assert response.status_code == 200, response.text
    with db.connect() as conn:
        queued = sorted(r[0] for r in conn.execute("SELECT kind FROM jobs WHERE run_id = ? AND status = 'queued'",
                                                  (run_id,)))
        assert queued == ["extract", "notes"]
        stages = {r[0]: r[1] for r in conn.execute("SELECT name, status FROM stages WHERE run_id = ?", (run_id,))}
        assert stages["extract"] == "waiting" and stages["notes"] == "waiting"
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "ready"


def test_notes_switched_off_at_setup_queue_no_notes_job(signed_in):
    run_id = read_run(signed_in)
    assert signed_in.post(f"/api/runs/{run_id}/setup", json=SETUP).status_code == 200
    with db.connect() as conn:
        kinds = [r[0] for r in conn.execute("SELECT kind FROM jobs WHERE run_id = ? AND kind != 'read'", (run_id,))]
        assert kinds == ["extract"]
        assert conn.execute("SELECT 1 FROM stages WHERE run_id = ? AND name = 'notes'", (run_id,)).fetchone() is None
        messages = [r[0] for r in conn.execute("SELECT message FROM events WHERE run_id = ?", (run_id,))]
    assert "The notes are switched off at setup, so the notes agent does not run." in messages
