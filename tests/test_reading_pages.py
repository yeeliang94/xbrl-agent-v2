"""Transcribing each page once (docs/api-contract.md, "Reading"), with fake models."""
from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError
from pydantic_ai.models.function import FunctionModel

from app import db
from app.agents import loop
from app.documents import store as documents
from app.documents.pdf_check import inspect_pdf
from app.models import usage as model_usage
from app.reading import job, store, transcribe
from app.reading.content import Block, PageContent
from tests import reading_fakes as fakes
from tests.conftest import OWNER, make_user


def make_reading_run(data: bytes | None = None) -> int:
    make_user(OWNER)
    data = data or fakes.build_pdf()
    with db.connect(immediate=True) as conn:
        return documents.create_run_from_pdf(conn, data, inspect_pdf(data), filename="t.pdf", owner_email=OWNER)


def stored_pages(run_id: int) -> dict[int, tuple]:
    with db.connect() as conn:
        doc = conn.execute("SELECT id FROM documents WHERE run_id = ?", (run_id,)).fetchone()[0]
        return {r["page"]: (json.loads(r["content_json"]) if r["content_json"] else None, r["read_error"])
                for r in conn.execute("SELECT * FROM pages WHERE document_id = ?", (doc,))}


async def transcribe_only(run_id: int, model) -> None:
    await job._transcribe(run_id, None, "gpt-6-luna", model)


# Content -------------------------------------------------------------------

def test_a_table_keeps_only_its_structure_and_ordinary_spaces():
    block = Block(type="table", html='<table class="x"><tr><td colspan="2" style="a"><b>Total</b>　RM</td>'
                                     "<td>(1,234)</td></tr></table>")
    assert block.html == '<table><tr><td colspan="2">Total RM</td><td>(1,234)</td></tr></table>'


@pytest.mark.parametrize("html, words", [
    ("<table><td>x</td></table>", "directly inside a <tr>"),
    ("<table><tr><td>x</td></tr>", "not all closed"),
    ("<table><tr><td><img src=x></td></tr></table>", "not <img>"),
    ("<p>no table</p>", "exactly one <table>"),
])
def test_a_malformed_table_is_refused_in_a_plain_sentence(html, words):
    with pytest.raises(ValidationError, match=words):
        Block(type="table", html=html)


def test_a_page_with_content_needs_its_blocks():
    with pytest.raises(ValidationError, match="give its blocks"):
        PageContent(folio="3", rotation=0, kind="notes", blocks=[])


# Transcription -------------------------------------------------------------

async def test_every_page_is_read_once_and_a_blank_page_needs_no_call():
    run_id = make_reading_run()
    calls: list[int] = []

    await transcribe_only(run_id, fakes.transcriber(calls=calls))

    assert sorted(calls) == [1, 2, 3]
    pages = stored_pages(run_id)
    assert pages[4][0]["blank"] is True and pages[4][0]["kind"] == "blank"
    statement = pages[2][0]
    assert statement["folio"] == "4" and statement["kind"] == "statement"
    assert "　" not in json.dumps(statement, ensure_ascii=False)
    assert pages[3][0]["blocks"][2]["text"] == "Cost and depreciation."
    assert pages[3][0]["running_text"] == ["TEST SDN. BHD."]
    with db.connect() as conn:
        assert store.progress(conn, run_id)["pages"] == {"total": 4, "read": 3, "blank": 1, "failed": 0,
                                                         "waiting": 0}
    messages = [e["message"] for e in __import__("app.runs.events", fromlist=["x"]).list_events(run_id=run_id)]
    assert "Reading 4 pages." in messages and "Read page 2 of 4." in messages and "Page 4 is blank." in messages


async def test_a_malformed_answer_is_retried_once_with_the_problem_and_then_kept():
    run_id = make_reading_run()
    calls: list[int] = []

    await transcribe_only(run_id, fakes.transcriber(malformed_once={2}, calls=calls))

    assert calls.count(2) == 2
    assert stored_pages(run_id)[2][0]["kind"] == "statement"
    record = json.loads(next((transcribe.records_dir(run_id)).glob("page-002-*.json")).read_text(encoding="utf-8"))
    assert record["status"] == "read" and len(record["calls"]) == 2
    sent_back = json.dumps(record["messages"])
    assert "directly inside a <tr>" in sent_back          # the plain sentence went back to the model


async def test_a_page_that_stays_malformed_fails_alone_with_a_plain_reason_and_its_records():
    run_id = make_reading_run()

    await transcribe_only(run_id, fakes.transcriber(always_bad={3}))

    pages = stored_pages(run_id)
    assert pages[3] == (None, "The model's answer for this page was malformed twice, so the page was not read.")
    assert pages[1][0] and pages[2][0]
    record = json.loads(next(transcribe.records_dir(run_id).glob("page-003-*.json")).read_text(encoding="utf-8"))
    assert record["status"] == "failed" and "UnexpectedModelBehavior" in record["error_detail"]
    assert "<picture of" in json.dumps(record["messages"])     # the picture itself is not kept
    with db.connect() as conn:
        rows = conn.execute("SELECT page, duration_ms, cost_usd FROM model_calls WHERE run_id = ? AND page = 3",
                            (run_id,)).fetchall()
    assert len(rows) == 2 and all(r["duration_ms"] is not None and r["cost_usd"] is not None for r in rows)


async def test_a_retry_reads_only_the_pages_not_yet_read():
    run_id = make_reading_run()
    await transcribe_only(run_id, fakes.transcriber(always_bad={3}))
    calls: list[int] = []

    await transcribe_only(run_id, fakes.transcriber(calls=calls))

    assert calls == [3]
    assert stored_pages(run_id)[3][0]["kind"] == "notes"


async def test_when_no_page_can_be_read_the_stage_fails_and_says_why():
    run_id = make_reading_run()
    with db.connect(immediate=True) as conn:
        store.stage_working(conn, run_id)

    with pytest.raises(job.ReadingFailed, match="No page could be read"):
        await transcribe_only(run_id, fakes.transcriber(always_bad={1, 2, 3}))

    with db.connect() as conn:
        assert store.progress(conn, run_id)["status"] == "failed"
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "failed"


async def test_a_missing_key_fails_the_stage_before_any_page_is_tried():
    run_id = make_reading_run()
    with pytest.raises(job.ReadingFailed, match="OPENAI_API_KEY"):
        await transcribe_only(run_id, None)
    assert all(content is None and error is None for content, error in stored_pages(run_id).values())


def test_cost_is_estimated_from_list_prices_with_cached_input_cheaper():
    assert model_usage.cost_usd("gpt-6-luna", 1_000_000, 0, 0) == pytest.approx(0.10)
    assert model_usage.cost_usd("gpt-6-luna", 1_000_000, 1_000_000, 1_000_000) == pytest.approx(0.51)
    assert model_usage.cost_usd("openai.global.gpt-6-luna", 0, 0, 2_000_000) == pytest.approx(1.0)
    assert model_usage.cost_usd("some-unknown-model", 10, 0, 10) is None


async def test_a_page_that_cannot_be_drawn_fails_alone(monkeypatch):
    run_id = make_reading_run()
    real = transcribe.pdf_viewer.render_page_png

    def render(path, page, **kwargs):
        if page == 2:
            raise RuntimeError("broken page")
        return real(path, page, **kwargs)
    monkeypatch.setattr(transcribe.pdf_viewer, "render_page_png", render)

    await transcribe_only(run_id, fakes.transcriber())

    pages = stored_pages(run_id)
    assert pages[2] == (None, "The agent run stopped on an unexpected error.")
    assert pages[1][0] and pages[3][0] and pages[4][0]["blank"]


async def test_an_unexpected_error_stops_every_page_before_the_stage_fails(monkeypatch):
    run_id = make_reading_run()
    started: list[int] = []

    async def answer(messages, info):
        page = fakes.page_of(messages)
        started.append(page)
        if page != 1:
            await asyncio.sleep(30)          # still reading when page 1 fails to save
        return fakes.transcriber().function(messages, info)

    def broken_save(*args, **kwargs):
        raise RuntimeError("the disk is full")
    monkeypatch.setattr(store, "save_page", broken_save)

    with pytest.raises(job.ReadingFailed, match="Reading stopped on an unexpected error."):
        await job.run_reading(run_id, transcription_model=FunctionModel(answer))

    def snapshot():
        with db.connect() as conn:
            return [tuple(r) for r in conn.execute(
                "SELECT page, error FROM model_calls WHERE run_id = ? ORDER BY id", (run_id,))]
    calls = snapshot()
    assert sorted(started) == [1, 2, 3]
    # The pages still reading were cut off and recorded before the stage was marked failed.
    assert sorted(p for p, error in calls if error == loop.CUT_OFF) == [2, 3]
    await asyncio.sleep(0.2)
    assert snapshot() == calls                # nothing is called or recorded afterwards
    assert all(content is None for content, _ in stored_pages(run_id).values())
    with db.connect() as conn:
        assert store.progress(conn, run_id)["status"] == "failed"


async def test_a_retry_counts_the_failed_pages_as_waiting_again():
    run_id = make_reading_run()
    await transcribe_only(run_id, fakes.transcriber(always_bad={3}))
    with db.connect(immediate=True) as conn:
        store.stage_failed(conn, run_id, "Stopped.")
        assert store.progress(conn, run_id)["pages"]["failed"] == 1
        store.retry(conn, run_id)
        assert store.progress(conn, run_id)["pages"] == {"total": 4, "read": 2, "blank": 1, "failed": 0,
                                                         "waiting": 1}
        assert store.map_pages(conn, run_id)[2]["status"] == "waiting"


async def test_a_page_records_error_is_kept_with_secrets_masked(monkeypatch):
    monkeypatch.setenv("LLM_PROXY_URL", "https://gateway.internal.example/v1")
    run_id = make_reading_run()

    def answer(messages, info):
        raise RuntimeError("POST https://gateway.internal.example/v1/responses refused")

    with pytest.raises(job.ReadingFailed):     # every page fails, so the stage does
        await transcribe_only(run_id, FunctionModel(answer))

    record = json.loads(next(transcribe.records_dir(run_id).glob("page-001-*.json")).read_text(encoding="utf-8"))
    assert record["error_detail"] == "RuntimeError: POST [masked]/responses refused"
    with db.connect() as conn:
        errors = {r[0] for r in conn.execute("SELECT error FROM model_calls WHERE run_id = ?", (run_id,))}
    assert errors == {"RuntimeError: POST [masked]/responses refused"}
