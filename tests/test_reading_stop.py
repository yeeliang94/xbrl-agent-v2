"""Stopping the reading stage: it stops within the model calls under way, keeps every page read, and can be
tried again. Fake models, no network."""
from __future__ import annotations

import io

import pymupdf
import pytest
from pydantic_ai.models.function import FunctionModel

from app import db
from app.jobs import worker
from app.models import factory
from app.reading import transcribe
from app.runs.events import list_events
from tests import pdf_samples, reading_fakes as fakes
from tests.conftest import OWNER, login, make_user

PAGES = 9
MAP_STEPS = [("read_pages", {"pages": [2]}), ("save_map", {"document_map": fakes.good_map()}), "The map is saved."]


@pytest.fixture
def signed_in(client):
    make_user(OWNER)
    assert login(client, OWNER).status_code == 200
    return client


def upload(client, pages: int = PAGES) -> int:
    doc = pymupdf.open()
    for _ in range(pages):
        pdf_samples.add_text_page(doc)
    data = doc.tobytes()
    doc.close()
    response = client.post("/api/runs", files={"file": ("t.pdf", io.BytesIO(data), "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()["run"]["id"]


def use_world(monkeypatch, on_page=lambda page: None, on_reader=lambda n: None, steps=MAP_STEPS):
    """One model for the job. `on_page(page)` runs in each transcription call, `on_reader(n)` in the Reader's
    n-th request. Returns the lists of pages transcribed and of Reader requests made."""
    pages: list[int] = []
    requests: list[int] = []
    transcription, reader = fakes.transcriber(calls=pages), fakes.reader_script(steps)

    async def answer(messages, info):
        if "save_map" in {t.name for t in info.function_tools}:
            requests.append(len(requests) + 1)
            on_reader(requests[-1])
            return reader.function(messages, info)
        on_page(fakes.page_of(messages))
        return transcription.function(messages, info)
    monkeypatch.setattr(factory, "build_model", lambda model_id: FunctionModel(answer))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    return pages, requests


def _states(run_id: int) -> tuple[str, str]:
    with db.connect() as conn:
        run = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
        stage = conn.execute("SELECT status FROM stages WHERE run_id = ? AND name = 'read'", (run_id,)).fetchone()[0]
    return run, stage


async def test_reading_stops_without_starting_another_page_and_a_retry_reads_the_rest(signed_in, monkeypatch):
    run_id = upload(signed_in)
    pressed = []

    def press_stop(page):
        if not pressed:
            pressed.append(page)
            assert signed_in.post(f"/api/runs/{run_id}/read/stop").json()["read"]["stop_requested"] is True
    pages, requests = use_world(monkeypatch, on_page=press_stop)

    assert await worker.run_once()

    # Only the pages already under way when Stop was pressed were read: no page started after it, no Reader.
    assert 1 <= len(pages) <= transcribe.CONCURRENCY and requests == []
    assert _states(run_id) == ("stopped", "stopped")
    read = signed_in.get(f"/api/runs/{run_id}/read").json()["read"]
    assert read["status"] == "stopped" and read["error"] == "Stopped on request; the pages read so far are kept."
    assert read["pages"]["read"] == len(pages) and read["pages"]["waiting"] == PAGES - len(pages)
    assert "Reading stopped on request. The pages read so far are kept." in [
        e["message"] for e in list_events(run_id=run_id)]
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM jobs WHERE run_id = ?", (run_id,)).fetchone()[0] == "done"
    refused = signed_in.post(f"/api/runs/{run_id}/read/stop")
    assert (refused.status_code, refused.json()["detail"]) == (
        409, "Reading is not running, so there is nothing to stop.")

    # Try again: the pages read are kept, only the rest are read, and the run reaches setup.
    first = list(pages)
    retried = signed_in.post(f"/api/runs/{run_id}/read/retry")
    assert retried.status_code == 202 and retried.json()["read"]["stop_requested"] is False
    assert _states(run_id) == ("reading", "waiting")
    pressed.append("no more stops")
    assert await worker.run_once()
    assert _states(run_id) == ("setup", "done")
    assert sorted(pages) == list(range(1, PAGES + 1)) and set(pages[len(first):]).isdisjoint(first)


async def test_the_reader_stops_before_its_next_step_and_a_retry_maps_without_reading_again(signed_in, monkeypatch):
    run_id = upload(signed_in, 3)

    def press_stop(n):
        if n == 1:
            assert signed_in.post(f"/api/runs/{run_id}/read/stop").status_code == 202
    pages, requests = use_world(monkeypatch, on_reader=press_stop)
    assert await worker.run_once()
    assert requests == [1]   # the call under way finished; no request after the stop
    assert _states(run_id) == ("stopped", "stopped")

    assert signed_in.post(f"/api/runs/{run_id}/read/retry").status_code == 202
    pages, requests = use_world(monkeypatch)
    assert await worker.run_once()
    assert _states(run_id) == ("setup", "done") and pages == []   # every page was already read


def test_a_reading_still_waiting_stops_at_once_and_the_run_can_be_replaced(signed_in):
    run_id = upload(signed_in, 3)
    stopped = signed_in.post(f"/api/runs/{run_id}/read/stop")
    assert stopped.status_code == 202 and stopped.json()["read"]["status"] == "stopped"
    assert _states(run_id) == ("stopped", "stopped")
    assert signed_in.get("/api/runs").json()["runs"][0]["status"] == "stopped"
    assert signed_in.post("/api/runs/999/read/stop").status_code == 404
    assert signed_in.delete(f"/api/runs/{run_id}").status_code == 204   # Replace on the setup page
