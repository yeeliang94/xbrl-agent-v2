"""The reports agent and its `reports` stage (step 10b). Scripted models, no network.

The stage starts at setup only when the Reader found a report section; the
save tools refuse in one plain sentence (an unknown field, a value with no
page, a page not opened, a choice not on the list); the finish is sent back
once while a field is unassessed; every model call and the transcript are
kept; a failed or stopped stage keeps what was saved and never fails the run.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app import db
from app.catalog.reports import REPORTS, report_fields
from app.reports import job, store
from app.runs import extraction, status as run_status
from app.utils.paths import output_dir
from tests.report_helpers import reports_run

FINAL = "$final"
DONE = {"summary": "Filled the three reports.", "unresolved": []}


def scripted(steps: list, seen: list):
    async def answer(messages, info: AgentInfo) -> ModelResponse:
        seen.append(messages)
        done = sum(1 for m in messages if isinstance(m, ModelResponse))
        name, args = steps[done] if done < len(steps) else (FINAL, DONE)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name if name == FINAL else name, args)])
    return FunctionModel(answer)


def returns(messages, name: str) -> list[str]:
    return [p.content for m in messages for p in getattr(m, "parts", [])
            if isinstance(p, ToolReturnPart) and p.tool_name == name]


def queued(run_id: int) -> int:
    with db.connect(immediate=True) as conn:
        job_id = job.start(conn, run_id)
    assert job_id is not None
    return job_id


def _rest_left_empty(done: set[str]) -> list[dict]:
    return [{"field": f.field_id, "status": "not_shown", "reason": "Not printed in this test document."}
            for r in REPORTS for f in report_fields(r, "mfrs") if f.field_id not in done]


def test_the_stage_starts_only_when_the_reader_found_a_report():
    found = reports_run()
    none = reports_run(sections=[{"kind": "statutory_declaration", "first_page": 4, "last_page": 4}])
    with db.connect(immediate=True) as conn:
        assert job.start(conn, found) is not None
        assert job.start(conn, none) is None
        stage = conn.execute("SELECT status FROM stages WHERE run_id = ? AND name = 'reports'", (found,)).fetchone()
        notice = conn.execute("SELECT message FROM events WHERE run_id = ? AND source = 'reports'", (none,)).fetchone()
        assert stage["status"] == "waiting"
        assert conn.execute("SELECT COUNT(*) FROM stages WHERE run_id = ? AND name = 'reports'",
                            (none,)).fetchone()[0] == 0
    assert "found no directors' report" in notice["message"]


def test_the_agent_fills_the_reports_with_plain_refusals_and_a_finish_sent_back_once():
    run_id = reports_run()
    job_id = queued(run_id)
    filled = {"DIR-5", "DIR-6", "DIR-7", "DIR-9", "DIR-22", "DIR-23", "DIR-26", "AUD-15"}
    steps = [
        ("search_pages", {"text": "directors' report"}),
        ("save_fields", {"fields": [{"field": "DIR-7", "status": "filled", "value": "Tan Ah Kow", "pages": [3]}]}),
        ("read_pages", {"pages": [2, 3]}),
        ("show_blocks", {"pages": [2, 3]}),
        ("save_narrative", {"report": "DIRECTORS_REPORT", "blocks": ["p2b0-p3b1"]}),
        ("save_fields", {"fields": [
            {"field": "DIR-7", "status": "filled", "value": "Tan Ah Kow", "pages": [3]},
            {"field": "DIR-9", "status": "filled", "value": "900101-14-5678", "pages": [3]},
            {"field": "DIR-6", "status": "filled", "value": "2", "pages": [3]},
            {"field": "DIR-22", "status": "filled", "value": "Not mentioned", "pages": [2]},
            {"field": "DIR-23", "status": "filled", "value": "No", "pages": [2]},
            {"field": "DIR-26", "status": "filled", "value": "2026-04-30", "pages": [3]},
            {"field": "dir-24", "status": "filled", "value": "Maybe", "pages": [2]},
            {"field": "DIR-25", "status": "filled", "value": "No"},
            {"field": "AUD-15", "status": "filled", "value": "Example & Co.", "pages": [5]},
            {"field": "XYZ-1", "status": "filled", "value": "x", "pages": [2]},
            {"field": "DIR-5", "status": "filled", "value": "x", "pages": [2]},
        ]}),
        ("view_pages", {"pages": [99]}),
        ("read_pages", {"pages": [5]}),
        ("save_fields", {"fields": [{"field": "AUD-15", "status": "filled", "value": "Example & Co.", "pages": [5]}]}),
        (FINAL, DONE),
        ("save_fields", {"fields": _rest_left_empty(filled)[:30]}),
        ("save_fields", {"fields": _rest_left_empty(filled)[30:]}),
        (FINAL, DONE),
    ]
    seen: list = []
    asyncio.run(job.run_reports(run_id, job_id, model=scripted(steps, seen)))
    last = seen[-1]
    saves = returns(last, "save_fields")
    assert saves[0] == "DIR-7: you have not opened page 3 in this run, so read or view it first."
    batch = saves[1].splitlines()
    assert batch[:6] == ["DIR-7: saved 'Tan Ah Kow'.", "DIR-9: saved '900101-14-5678'.", "DIR-6: saved '2'.",
                         "DIR-22: saved 'Not mentioned'.", "DIR-23: saved 'No'.", "DIR-26: saved '2026-04-30'."]
    assert batch[6].startswith("DIR-24: not saved.") and "takes one of: Yes; No." in batch[6]
    assert batch[7] == "DIR-25: give the PDF page the value was read from."
    assert batch[8] == "AUD-15: you have not opened page 5 in this run, so read or view it first."
    assert batch[9].startswith("XYZ-1: there is no such field")
    assert batch[10] == "DIR-5: this is the report's wording, so save it with save_narrative."
    assert returns(last, "save_narrative")[0] == "DIR-5: saved the wording."
    assert "outside the document" in returns(last, "view_pages")[0]
    sent_back = [p for m in last for p in getattr(m, "parts", []) if getattr(p, "content", None)
                 and "Not finished yet. These fields are not assessed" in str(p.content)]
    assert len(sent_back) == 1

    with db.connect() as conn:
        stage = conn.execute("SELECT status, error FROM stages WHERE run_id = ? AND name = 'reports'",
                             (run_id,)).fetchone()
        reports = {r["report"]: r for r in store.run_reports(conn, run_id)}
        calls = conn.execute("SELECT COUNT(*) FROM model_calls WHERE run_id = ? AND source = 'reports'",
                             (run_id,)).fetchone()[0]
        done = conn.execute("SELECT message FROM events WHERE run_id = ? AND source = 'reports' AND kind = 'done'",
                            (run_id,)).fetchone()
        history = conn.execute("SELECT COUNT(*) FROM report_field_history WHERE run_id = ?", (run_id,)).fetchone()[0]
    assert (stage["status"], stage["error"]) == ("done", None)
    assert all(r["assessed"] == r["total"] for r in reports.values())
    directors = {f["field_id"]: f for f in reports["DIRECTORS_REPORT"]["fields"]}
    assert directors["DIR-9"]["value"] == "900101-14-5678" and directors["DIR-9"]["pages"] == [3]
    assert "Signed in accordance" in directors["DIR-5"]["html"]
    assert calls == len(steps) and history == 62   # one save for each field
    assert done["message"] == "The reports are filled."
    record = json.loads((output_dir() / "runs" / f"run-{run_id}" / "reports.json").read_text())
    assert record["status"] == "completed" and record["not_assessed"] == 0 and record["transcript"]
    assert (output_dir() / "transcripts" / f"run-{run_id}" / record["transcript"]).exists()


def test_a_model_failure_fails_the_stage_keeps_the_fields_and_leaves_the_run_in_review():
    run_id = reports_run()
    job_id = queued(run_id)
    calls = {"n": 0}

    async def answer(messages, info: AgentInfo) -> ModelResponse:
        calls["n"] += 1
        if calls["n"] == 1:
            return ModelResponse(parts=[ToolCallPart("read_pages", {"pages": [5]})])
        if calls["n"] == 2:
            return ModelResponse(parts=[ToolCallPart("save_fields", {"fields": [
                {"field": "AUD-15", "status": "filled", "value": "Example & Co.", "pages": [5]}]})])
        raise ModelAPIError("test-model", "The service broke.")

    with pytest.raises(job.ReportsFailed, match="refused the request; the report fields saved so far are kept"):
        asyncio.run(job.run_reports(run_id, job_id, model=FunctionModel(answer)))
    with db.connect() as conn:
        stage = conn.execute("SELECT status FROM stages WHERE run_id = ? AND name = 'reports'", (run_id,)).fetchone()
        run = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
        kept = store.get_field(conn, run_id, "AUDITORS_REPORT", "AUD-15")
    assert stage["status"] == "failed" and run["status"] == "in_review" and kept["value"] == "Example & Co."


def test_a_stop_before_the_start_ends_the_stage_stopped_and_retry_queues_it_again():
    run_id = reports_run()
    with db.connect(immediate=True) as conn:
        job.start(conn, run_id)
        assert extraction.stop_extraction(conn, run_id) is True
        stage = conn.execute("SELECT status, error FROM stages WHERE run_id = ? AND name = 'reports'",
                             (run_id,)).fetchone()
        assert (stage["status"], stage["error"]) == ("stopped", job.STOPPED_SENTENCE)
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "stopped"
        assert extraction.retry_extraction(conn, run_id) is not None
        assert job.stage_status(conn, run_id) == "waiting"


def test_the_run_waits_for_the_reports_stage_before_review():
    run_id = reports_run()
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE runs SET status = 'extracting' WHERE id = ?", (run_id,))
        conn.executemany("INSERT INTO stages(run_id, name, status) VALUES (?, ?, ?)",
                         [(run_id, "extract", "done"), (run_id, "notes", "done"), (run_id, "reports", "working")])
        run_status.settle(conn, run_id)
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "extracting"
        conn.execute("UPDATE stages SET status = 'failed' WHERE run_id = ? AND name = 'reports'", (run_id,))
        run_status.settle(conn, run_id)
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "in_review"


def test_confirming_the_setup_queues_the_reports_agent_beside_the_others(client):
    from app.reading import store as reading
    from tests import reading_fakes as fakes
    from tests.conftest import OWNER, login, make_user
    from tests.test_setup_confirm import GOOD, mapped_run

    make_user(OWNER)
    assert login(client, OWNER).status_code == 200
    run_id = mapped_run(client)
    with db.connect(immediate=True) as conn:   # the Reader found a directors' report on page 1
        reading.save_map(conn, run_id, fakes.good_map(other_sections=[
            {"kind": "directors_report", "title": "Directors' report", "first_page": 1, "last_page": 1}]), [])
    assert client.post(f"/api/runs/{run_id}/setup", json=GOOD).status_code == 200
    with db.connect() as conn:
        kinds = sorted(r[0] for r in conn.execute("SELECT kind FROM jobs WHERE run_id = ?", (run_id,)))
        assert job.stage_status(conn, run_id) == "waiting"
    assert kinds == ["extract", "notes", "read", "reports"]


def test_the_first_message_lists_the_statutory_declaration_and_short_fields_may_come_from_it():
    from pydantic_ai.messages import UserPromptPart

    from app.reports import instructions

    run_id = reports_run()
    job_id = queued(run_id)
    seen: list = []
    steps = [("save_fields", {"fields": _rest_left_empty(set())[:30]}), (FINAL, DONE)]
    asyncio.run(job.run_reports(run_id, job_id, model=scripted(steps, seen)))
    first = next(p.content for p in seen[0][0].parts if isinstance(p, UserPromptPart))
    assert "- Statutory declaration (not a report to fill, but its facts may answer short fields): 4" in first
    text = instructions.INSTRUCTIONS
    assert "never take one from anywhere but the report it belongs to" not in text
    assert "whichever page of this filing states it" in text and "primarily responsible" in text


def test_a_retry_that_finds_every_field_assessed_and_saves_nothing_is_done():
    run_id = reports_run()
    with db.connect(immediate=True) as conn:
        for item in _rest_left_empty(set()):
            f = next(x for r in REPORTS for x in report_fields(r, "mfrs") if x.field_id == item["field"])
            store.save_field(conn, run_id, f.report, f.element_id,
                             store.FieldWrite("not_shown", reason=item["reason"]), store.Actor("agent", "reports"))
    job_id = queued(run_id)
    asyncio.run(job.run_reports(run_id, job_id, model=scripted([(FINAL, DONE)], [])))
    with db.connect() as conn:
        assert job.stage_status(conn, run_id) == "done"

    # With fields still unassessed, a run that saves nothing still fails.
    empty = reports_run()
    with pytest.raises(job.ReportsFailed, match="No report field was saved"):
        asyncio.run(job.run_reports(empty, queued(empty), model=scripted([(FINAL, DONE), (FINAL, DONE)], [])))


def test_a_page_counts_as_opened_only_when_its_words_or_picture_were_shown(monkeypatch):
    from types import SimpleNamespace

    from app.agents import pages as page_tools
    from app.reports import tools

    deps = tools.ReportsDeps(run_id=1, pdf_path="x.pdf", page_count=4, contents={
        1: {"folio": "1", "rotation": 0, "kind": "directors_report", "blocks": [{"type": "paragraph", "text": "Hi"}]},
        2: {"blank": True, "folio": None, "rotation": 0, "kind": "blank", "blocks": []}})
    ctx = SimpleNamespace(deps=deps)
    asyncio.run(tools.read_pages(ctx, [1, 2, 3]))            # 2 is blank, 3 was never transcribed
    assert deps.opened == {1}
    tools.show_blocks(ctx, [2, 3])
    assert deps.opened == {1}
    asyncio.run(tools.view_pages(ctx, [9]))                  # refused: outside the document
    asyncio.run(tools.zoom_page(ctx, 3, 0.5, 0, 0.2, 1))     # refused: a bad region
    assert deps.opened == {1}
    monkeypatch.setattr(page_tools.pdf_viewer, "render_page_png", lambda *a, **k: b"png")
    asyncio.run(tools.view_pages(ctx, [3]))
    asyncio.run(tools.zoom_page(ctx, 4, 0, 0, 1, 0.5))
    assert deps.opened == {1, 3, 4}


def test_a_reason_is_kept_to_500_characters():
    run_id = reports_run()
    with db.connect(immediate=True) as conn:
        saved = store.save_field(conn, run_id, "DIRECTORS_REPORT", "DIR-7",
                                 store.FieldWrite("not_shown", reason="Not printed. " * 100),
                                 store.Actor("agent", "reports"))
    assert len(saved["reason"]) == 500
