"""The extract job end to end with a scripted figures agent: from confirming
the setup to a finished stage. No network."""
from __future__ import annotations

import io
import json

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app import db
from app.extraction import agent, checking
from app.jobs import worker
from app.models import factory
from app.reading import store as reading
from app.runs.events import list_events
from app.settings import store as settings
from app.utils.paths import output_dir
from tests import reading_fakes as fakes
from tests.conftest import OWNER, login, make_user

FINAL = "$final"
SETUP = {
    "company": "Test Sdn. Bhd.", "year_end": "2021-12-31", "standard": "MFRS", "level": "Company", "unit": "RM",
    "statements": [
        {"statement": "SOFP", "layout": "CuNonCu", "included": True, "pages": [2]},
        {"statement": "SOPL", "layout": "Function", "included": False, "pages": [2]},
        {"statement": "SOCI", "layout": "NotPrepared", "included": False, "pages": []},
        {"statement": "SOCF", "layout": "Indirect", "included": False, "pages": [2]},
        {"statement": "SOCIE", "layout": "Default", "included": False, "pages": [2]},
    ],
    "notes_included": False,   # these tests run the figures agent alone; tests/test_notes_agent*.py run both
    "notes": [{"number": "1", "title": "Plant and equipment", "first_page": 3, "last_page": 3},
              {"number": "2", "title": "Trade payables", "first_page": 3, "last_page": 3}],
}
PLANT = {"label": "Plant and equipment", "page": 2, "action": "written", "fields": ["FP-s28"]}
PAYABLES = {"label": "Trade payables", "page": 2, "action": "written", "fields": ["FP-s404"]}
STEPS = [
    ("find_fields", {"queries": ["plant and equipment", "trade payables"]}),
    ("save_figures", {"figures": [
        {"field": "FP-7", "lines": [{"label": "Non-current assets", "page": 2, "cy": 1200}]},
        {"field": "FP-s28", "lines": [{"label": "Plant and equipment", "page": 2, "cy": 1200}],
         "reason": "Face line, note 1 gives no finer split."},
        {"field": "FP-s404", "lines": [{"label": "Trade payables", "page": 2, "cy": 300}]},
    ]}),
    (FINAL, {"summary": "Saved the balance sheet."}),
    ("run_checks", {}),
    ("report_coverage", {"lines": [PLANT]}),
    ("report_coverage", {"lines": [PLANT, PAYABLES]}),
    (FINAL, {"summary": "Saved both printed lines.",
             "unresolved": ["The balance does not agree: the test page prints no equity."]}),
]


def script(steps: list, seen: list):
    def answer(messages, info: AgentInfo) -> ModelResponse:
        seen.append(messages)
        done = sum(1 for m in messages if isinstance(m, ModelResponse))
        name, args = steps[done] if done < len(steps) else (FINAL, {"summary": "Done."})
        if name == FINAL:
            name = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(name, args)])
    return FunctionModel(answer)


@pytest.fixture
def signed_in(client):
    make_user(OWNER)
    assert login(client, OWNER).status_code == 200
    return client


def read_run(client) -> int:
    """An uploaded run whose pages were transcribed and mapped, waiting at setup."""
    response = client.post("/api/runs", files={"file": ("t.pdf", io.BytesIO(fakes.build_pdf()), "application/pdf")})
    run_id = response.json()["run"]["id"]
    with db.connect(immediate=True) as conn:
        reading.stage_working(conn, run_id)
        for page in (1, 2, 3):
            reading.save_page(conn, run_id, page, fakes.good_page(page), None)
        reading.save_map(conn, run_id, fakes.good_map(), [])
        reading.stage_done(conn, run_id)
        conn.execute("UPDATE jobs SET status = 'done' WHERE run_id = ? AND kind = 'read'", (run_id,))
    return run_id


def returns(messages, name: str) -> list:
    return [p.content for m in messages for p in getattr(m, "parts", [])
            if isinstance(p, ToolReturnPart) and p.tool_name == name]


async def test_confirming_the_setup_runs_the_figures_agent_to_a_finished_stage(signed_in, monkeypatch):
    seen: list = []
    monkeypatch.setattr(factory, "build_model", lambda model_id: script(STEPS, seen))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    run_id = read_run(signed_in)
    assert signed_in.post(f"/api/runs/{run_id}/setup", json=SETUP).status_code == 200
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "ready"

    assert await worker.run_once()

    with db.connect() as conn:
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "in_review"
        stage = conn.execute("SELECT status, error FROM stages WHERE run_id = ? AND name = 'extract'",
                             (run_id,)).fetchone()
        assert tuple(stage) == ("done", None)
        assert conn.execute("SELECT status FROM jobs WHERE run_id = ? AND kind = 'extract'",
                            (run_id,)).fetchone()[0] == "done"
        figures = {(r["render_row"], r["period"]): (r["value"], r["origin"]) for r in conn.execute(
            "SELECT n.render_row, f.period, f.value, f.origin FROM figures f JOIN concept_nodes n "
            "ON n.concept_uuid = f.concept_uuid WHERE f.run_id = ? AND f.origin = 'agent'", (run_id,))}
        assert figures == {(28, "CY"): (1200.0, "agent"), (404, "CY"): (300.0, "agent")}
        line = conn.execute("SELECT l.printed_label, l.page FROM figure_lines l JOIN figures f ON f.id = l.figure_id "
                            "JOIN concept_nodes n ON n.concept_uuid = f.concept_uuid WHERE f.run_id = ? "
                            "AND n.render_row = 28", (run_id,)).fetchone()
        assert tuple(line) == ("Plant and equipment", 2)
        calls = conn.execute("SELECT COUNT(*) FROM model_calls WHERE run_id = ? AND source = 'figures'",
                             (run_id,)).fetchone()[0]
    assert calls == len(STEPS)

    # What the agent was given and told.
    first = seen[0][0].parts[-1].content
    assert "The statement of financial position is printed on PDF page 2." in first
    assert "- 1 Plant and equipment: p3" in first and "Amounts are in RM as printed" in first
    assert "FP-s39 total (face row): *Property, plant and equipment = FP-s20 + " in first
    assert "    FP-s28 line: Plant and equipment" in first
    last = seen[-1]
    assert "- FP-s28 line: Non-current assets › Property, plant and equipment › Plant and equipment" in \
        returns(last, "find_fields")[0]
    saved = returns(last, "save_figures")[0]
    assert saved.startswith("Saved 2 of 3 figure(s) by year; 1 refused.")
    assert ("FP-7 Non-current assets: CY not saved. Non-current assets is a heading and cannot hold a value, "
            "so save the figure on a line under it.") in saved
    sent_back = str(returns(last, "final_result")[0])   # the first finish, sent back
    assert sent_back.startswith("Not finished yet:\n- Run the checks with run_checks after your last change.\n"
                                "- Account for every printed line with report_coverage.")
    checks = returns(last, "run_checks")[0]
    action = checks.split("\n\n")[0].split("Passed:")[0]
    assert action.startswith("Action required:\n- ") and "total assets" in action.lower()
    first_cover, second_cover = returns(last, "report_coverage")
    assert "Not accounted for yet:\n- 'Trade payables' (page 2)" in first_cover
    assert second_cover == "Every printed line is accounted for: 2 written, 0 skipped."

    # Recorded for the run: events, the transcript, the finish and coverage.
    messages = [e["message"] for e in list_events(run_id=run_id)]
    for expected in ("Extraction is queued: the statement of financial position.", "Saved 2 figure(s), 1 refused.",
                     "Working on the statement of financial position.",
                     "The statement of financial position is filled, with 1 point(s) left open.",
                     "Extraction is finished. The run is ready for review."):
        assert expected in messages, expected
    record = json.loads((output_dir() / "runs" / f"run-{run_id}" / "extraction-SOFP.json").read_text())
    assert record["status"] == "completed" and record["coverage_open"] == []
    assert record["finish"]["unresolved"] == ["The balance does not agree: the test page prints no equity."]
    assert record["usage"]["calls"] == len(STEPS) and "cost_usd" in record["usage"]
    assert (output_dir() / "transcripts" / f"run-{run_id}").is_dir()
    done = next(e for e in list_events(run_id=run_id) if e["message"].startswith("The statement of financial position is filled"))
    assert set(done["data"]) >= {"cost_usd", "input_tokens", "steps"}


async def test_the_agent_is_told_its_steps_run_low_and_its_last_reply_is_kept(signed_in, monkeypatch):
    run_id = read_run(signed_in)
    signed_in.post(f"/api/runs/{run_id}/setup", json=SETUP)
    seen: list = []
    steps = [("add_up", {"sums": [{"name": "a", "amounts": [1, 2.5]}]})] * 3 + [(FINAL, {"summary": "Out of steps."})]
    settings.update({"code_workbench": False}, OWNER)
    outcome, deps, bench = await agent.run_figures(run_id, "SOFP", "gpt-6-luna", model=script(steps, seen),
                                                   max_steps=4)
    assert outcome.status == "completed"
    results = returns(seen[-1], "add_up")
    assert results[0] == "a: 3.50 (2 amounts)"
    assert "[Steps: 2 of 4 used, 2 left." not in results[1]   # 2 of 4 is below 70%
    assert results[2].endswith("[Steps: 3 of 4 used. Your next reply is your last one. Stop calling tools and "
                               "finish now: say what you saved and list what is left in unresolved.]")
    assert deps.finish["at_last_step"] is True and deps.finish["summary"] == "Out of steps."
    assert not bench.on and "switched off on the Settings page" in bench.why


async def test_an_agent_that_saves_nothing_fails_the_stage_with_one_sentence(signed_in, monkeypatch):
    run_id = read_run(signed_in)
    signed_in.post(f"/api/runs/{run_id}/setup", json=SETUP)

    def answer(messages, info):
        return ModelResponse(parts=[TextPart("I cannot do this.")])
    monkeypatch.setattr(factory, "build_model", lambda model_id: FunctionModel(answer))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    assert await worker.run_once()
    with db.connect() as conn:
        run = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
        stage = conn.execute("SELECT status, error FROM stages WHERE run_id = ? AND name = 'extract'",
                             (run_id,)).fetchone()
    assert run == "failed" and stage["status"] == "failed"
    assert stage["error"].startswith("The statement of financial position could not be filled: no figure was saved.")
    # The run list tells a failed extraction from a failed reading, and the run can be deleted (step 5a).
    listed = next(r for r in signed_in.get("/api/runs").json()["runs"] if r["id"] == run_id)
    assert listed["failed_stage"] == "extract"
    assert signed_in.delete(f"/api/runs/{run_id}").status_code == 204


def test_the_finish_check_names_every_reason_at_once():
    from types import SimpleNamespace

    deps = SimpleNamespace(writes=0, checked_at=-1, coverage_open=None, coverage_at=-1, checks_open=[],
                           refused_finish=False,
                           max_steps=60, finish=None, event=lambda *a, **k: None)
    ctx = SimpleNamespace(deps=deps, run_step=5)
    with pytest.raises(Exception) as refused:
        checking.finish(ctx, checking.FinishReport(summary="x"))
    assert "No figure is saved yet" in str(refused.value) and "report_coverage" in str(refused.value)
    # After one refusal, an honest finish with open points is accepted.
    report = checking.finish(ctx, checking.FinishReport(summary="x", unresolved=["The page is unreadable."]))
    assert report.unresolved == ["The page is unreadable."] and deps.finish["open_when_finished"]


async def test_the_agent_is_told_at_70_and_90_percent_of_its_steps(signed_in):
    run_id = read_run(signed_in)
    signed_in.post(f"/api/runs/{run_id}/setup", json=SETUP)
    seen: list = []
    steps = [("add_up", {"sums": [{"name": "a", "amounts": [1]}]})] * 9 + [(FINAL, {"summary": "Out of steps."})]
    await agent.run_figures(run_id, "SOFP", "gpt-6-luna", model=script(steps, seen), max_steps=10)
    notes = [r.split("\n\n", 1)[1] if "\n\n" in r else "" for r in returns(seen[-1], "add_up")]
    assert notes[6].startswith("[Steps: 7 of 10 used, 3 left. Save what is left")
    assert notes[8].startswith("[Steps: 9 of 10 used. Your next reply is your last one.")
    assert [n for n in notes if n] == [notes[6], notes[8]]   # each notice once


async def test_a_model_failure_after_a_save_fails_the_stage_and_keeps_the_figures(signed_in, monkeypatch):
    from pydantic_ai.exceptions import UnexpectedModelBehavior

    def answer(messages, info):
        if sum(1 for m in messages if isinstance(m, ModelResponse)) == 0:
            return ModelResponse(parts=[ToolCallPart("save_figures", {"figures": [
                {"field": "FP-s28", "lines": [{"label": "Plant and equipment", "page": 2, "cy": 1200}]}]})])
        raise UnexpectedModelBehavior("no usable reply")
    monkeypatch.setattr(factory, "build_model", lambda model_id: FunctionModel(answer))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    run_id = read_run(signed_in)
    signed_in.post(f"/api/runs/{run_id}/setup", json=SETUP)
    assert await worker.run_once()
    with db.connect() as conn:
        run = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
        stage = conn.execute("SELECT status, error FROM stages WHERE run_id = ? AND name = 'extract'",
                             (run_id,)).fetchone()
        kept = conn.execute("SELECT COUNT(*) FROM figures WHERE run_id = ? AND origin = 'agent'",
                            (run_id,)).fetchone()[0]
    assert run == "failed" and stage["status"] == "failed"
    assert stage["error"] == ("The statement of financial position could not be filled: the model's replies could "
                              "not be used, so the run was ended; the figures saved so "
                              "far are kept.")
    assert kept == 1


async def test_a_new_attempt_starts_from_the_figures_already_saved(signed_in, monkeypatch):
    from app.figures import store

    seen: list = []
    steps = [("run_checks", {}), ("report_coverage", {"lines": [PLANT, PAYABLES]}),
             (FINAL, {"summary": "Checked the saved figures.",
                      "unresolved": ["The balance does not agree: the test page prints no equity."]})]
    monkeypatch.setattr(factory, "build_model", lambda model_id: script(steps, seen))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    run_id = read_run(signed_in)
    signed_in.post(f"/api/runs/{run_id}/setup", json=SETUP)
    deps, _ = agent.build_deps(run_id, "SOFP")
    plant, payables = (deps.outline.fields[f].concept_uuid for f in ("FP-s28", "FP-s404"))
    with db.connect(immediate=True) as conn:   # an earlier attempt's saves
        store.save_figures(conn, run_id, [
            store.FigureWrite(plant, "CY", "Company", 1200.0, [store.Line("Plant and equipment", 2, 1200.0)]),
            store.FigureWrite(payables, "CY", "Company", 300.0, [store.Line("Trade payables", 2, 300.0)])],
            store.Actor("agent", "figures"))
    assert await worker.run_once()

    first = seen[0][0].parts[-1].content
    assert "Figures already saved for this statement, from an earlier attempt" in first
    assert "- FP-s28 Plant and equipment: CY 1,200" in first
    with db.connect() as conn:
        stage = conn.execute("SELECT status, error FROM stages WHERE run_id = ? AND name = 'extract'",
                             (run_id,)).fetchone()
    assert tuple(stage) == ("done", None)
    checks = returns(seen[-1], "run_checks")[0]
    assert "in unresolved" not in checks and "No figure is saved" not in str(returns(seen[-1], "final_result"))
