"""The read job end to end, through the worker and the routes, with fake models."""
from __future__ import annotations

import io

import pytest
from pydantic_ai.messages import BinaryContent, ToolReturnPart

from app import db
from app.jobs import worker
from app.models import factory
from app.reading import reader
from app.runs.events import list_events
from tests import reading_fakes as fakes
from tests.conftest import OWNER, login, make_run, make_user

FIRST_SAVE = fakes.good_map(notes=[{"number": "1", "title": "Plant", "first_page": 3, "last_page": 3}])
STEPS = [
    ("read_pages", {"pages": [9]}),
    ("read_pages", {"pages": [2]}),
    ("view_pages", {"pages": [2]}),
    ("search_pages", {"text": "trade payables"}),
    ("zoom_page", {"page": 2, "left": 0, "top": 0, "right": 1, "bottom": 0.5}),
    ("save_map", {"document_map": fakes.good_map(statements=fakes.statements(SOFP={"pages": [52]}))}),
    ("save_map", {"document_map": FIRST_SAVE}),
    ("save_map", {"document_map": fakes.good_map()}),
    "The map is saved.",
]


@pytest.fixture
def signed_in(client):
    make_user(OWNER)
    assert login(client, OWNER).status_code == 200
    return client


def upload(client) -> int:
    response = client.post("/api/runs", files={"file": ("t.pdf", io.BytesIO(fakes.build_pdf()), "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()["run"]["id"]


def use_world(monkeypatch, steps, seen: list | None = None):
    world = fakes.world(steps)
    if seen is not None:
        reader = fakes.reader_script(steps, seen)

        async def answer(messages, info):
            names = {t.name for t in info.function_tools}
            model = reader if "save_map" in names else fakes.transcriber()
            return model.function(messages, info)
        world = fakes.FunctionModel(answer)
    monkeypatch.setattr(factory, "build_model", lambda model_id: world)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")


def tool_results(messages, name):
    return [p for m in messages for p in getattr(m, "parts", []) if isinstance(p, ToolReturnPart)
            and p.tool_name == name]


async def test_an_upload_is_read_and_mapped_and_the_run_waits_at_setup(signed_in, monkeypatch):
    seen: list = []
    use_world(monkeypatch, STEPS, seen)
    run_id = upload(signed_in)

    assert await worker.run_once()

    with db.connect() as conn:
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "setup"
        job = conn.execute("SELECT * FROM jobs WHERE run_id = ?", (run_id,)).fetchone()
        assert job["kind"] == "read" and job["status"] == "done" and job["stage_id"] is not None
        sources = {r[0] for r in conn.execute("SELECT DISTINCT source FROM model_calls WHERE run_id = ?", (run_id,))}
    assert sources == {"transcription", "reader"}

    # What the Reader saw: transcriptions, a page picture, search hits, refusals and points.
    last = seen[-1]
    outside, read = (p.content for p in tool_results(last, "read_pages"))
    assert outside == "Page 9 is outside the document, which has 4 pages."
    assert "=== PDF page 2 (printed folio 4, statement)" in read and "<td>Trade payables</td>" in read
    before_save = tool_results(seen[6], "view_pages")[0].content   # the request that carries the first save
    assert any(isinstance(item, BinaryContent) for item in before_save)
    assert "PDF page 2 (printed folio 4)" in before_save[0]
    # Once saved, older pictures make way; the latest (the zoom) stays.
    assert not any(isinstance(item, BinaryContent) for item in tool_results(last, "view_pages")[0].content)
    assert any(isinstance(item, BinaryContent) for item in tool_results(last, "zoom_page")[0].content)
    assert "2 page(s) hold 'trade payables'" in tool_results(last, "search_pages")[0].content
    saves = tool_results(last, "save_map")
    assert "Page 52 for SOFP is outside the document" in str(saves[0].content)
    assert "Note 2 is cited on page 2 but is not in the notes list" in saves[1].content
    assert saves[2].content.startswith("Saved. The code sees no gaps")

    messages = [e["message"] for e in list_events(run_id=run_id)]
    for expected in ("Reading 4 pages.", "Read page 3 of 4.", "Page 4 is blank.", "Read 4 of 4 pages.",
                     "Financial position on page 2.", "Profit or loss on page 2, unsure of the layout.",
                     "Comprehensive income is not printed.", "2 notes, pages 3 to 3.",
                     "The document map is saved. Setup is ready."):
        assert expected in messages, expected

    progress = signed_in.get(f"/api/runs/{run_id}/read").json()["read"]
    assert progress["status"] == "done" and progress["map_saved"] is True
    assert progress["pages"] == {"total": 4, "read": 3, "blank": 1, "failed": 0, "waiting": 0}

    doc_map = signed_in.get(f"/api/runs/{run_id}/map").json()["map"]
    assert [s["statement"] for s in doc_map["statements"]] == ["SOFP", "SOPL", "SOCI", "SOCF", "SOCIE"]
    assert doc_map["notes"][0] == {"number": "1", "title": "Plant and equipment", "first_page": 3,
                                   "last_page": 3, "sub_notes": []}
    assert doc_map["open_points"] == [] and doc_map["unit"]["value"] == "RM"
    assert doc_map["pages"][1] == {"page": 2, "folio": "4", "rotation": 0, "kind": "statement",
                                   "title": "Statement of financial position", "status": "read", "reason": None}
    assert doc_map["pages"][3]["status"] == "blank"

    setup = signed_in.get(f"/api/runs/{run_id}/setup").json()["setup"]
    assert setup["year"] == 2021 and setup["standard"]["value"] == "MFRS"
    soci = next(s for s in setup["statements"] if s["statement"] == "SOCI")
    assert soci["layout"] == "NotPrepared"
    assert soci["layouts"]["MFRS"] == [{"value": "BeforeTax", "label": "Before tax"},
                                       {"value": "NetOfTax", "label": "Net of tax"},
                                       {"value": "NotPrepared", "label": "Not printed"}]
    socie = next(s for s in setup["statements"] if s["statement"] == "SOCIE")
    # Retained earnings is offered only under MPERS.
    assert [c["value"] for c in socie["layouts"]["MFRS"]] == ["Default"]
    assert socie["layouts"]["MPERS"] == [{"value": "Default", "label": "Changes in equity"},
                                         {"value": "SoRE", "label": "Retained earnings"}]


async def test_a_reader_that_never_saves_fails_the_stage_and_a_retry_reuses_its_row(signed_in, monkeypatch):
    use_world(monkeypatch, [("read_pages", {"pages": [1]}), "I could not decide."])
    run_id = upload(signed_in)
    assert await worker.run_once()

    progress = signed_in.get(f"/api/runs/{run_id}/read").json()["read"]
    assert progress["status"] == "failed" and progress["error"].startswith("The Reader did not save the document map.")
    assert signed_in.get(f"/api/runs/{run_id}/map").json() == {"detail": "The document has not been mapped yet."}
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "failed"
        transcribed = conn.execute("SELECT COUNT(*) FROM model_calls WHERE run_id = ? AND source = 'transcription'",
                                   (run_id,)).fetchone()[0]

    use_world(monkeypatch, [("save_map", {"document_map": fakes.good_map()}), "Saved."])
    response = signed_in.post(f"/api/runs/{run_id}/read/retry")
    assert response.status_code == 202 and response.json()["read"]["status"] == "waiting"
    assert await worker.run_once()

    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM stages WHERE run_id = ? AND name = 'read'",
                            (run_id,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM jobs WHERE run_id = ?", (run_id,)).fetchone()[0] == 2
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "setup"
        # The pages were not transcribed again.
        assert conn.execute("SELECT COUNT(*) FROM model_calls WHERE run_id = ? AND source = 'transcription'",
                            (run_id,)).fetchone()[0] == transcribed
    assert signed_in.get(f"/api/runs/{run_id}/read").json()["read"]["status"] == "done"
    again = signed_in.post(f"/api/runs/{run_id}/read/retry")
    assert again.status_code == 409
    assert again.json() == {"detail": "Reading has not failed, so there is nothing to try again."}


async def test_a_reader_is_sent_back_until_it_saves_and_refused_saves_cost_no_retries(signed_in, monkeypatch):
    bad = {"document_map": fakes.good_map(statements=fakes.statements(SOFP={"pages": [52]}), unit=fakes.finding("$"))}
    # More refused saves than the tool's four retries, and an answer in words before any save.
    steps = ["I think the map is clear.", *[("save_map", bad)] * 6, ("save_map", {"document_map": fakes.good_map()}),
             "Saved."]
    seen: list = []
    use_world(monkeypatch, steps, seen)
    run_id = upload(signed_in)
    assert await worker.run_once()

    with db.connect() as conn:
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "setup"
    sent_back = " ".join(str(p.content) for p in seen[1][-1].parts)   # the request after the words
    assert reader.SAVE_FIRST in sent_back
    saves = [p.content for p in tool_results(seen[-1], "save_map")]
    assert len(saves) == 7 and saves[-1].startswith("Saved")
    for refused in saves[:-1]:   # every problem in one answer
        assert refused.startswith(reader.NOT_SAVED)
        assert "Page 52 for SOFP" in refused and "The unit must be RM, RM'000 or RM'000,000" in refused


def test_reading_routes_need_a_document(signed_in):
    run_id = make_run()
    for path in ("read", "map", "setup"):
        assert signed_in.get(f"/api/runs/{run_id}/{path}").json() == {"detail": "This run has no document."}
    assert signed_in.get("/api/runs/999/map").status_code == 404


def test_reading_routes_need_a_session(client):
    assert client.get("/api/runs/1/map").status_code == 401


def test_in_dev_sign_in_mode_an_upload_works(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import create_app

    monkeypatch.setenv("AUTH_MODE", "dev")
    with TestClient(create_app(start_worker=False)) as dev_client:
        response = dev_client.post("/api/runs", files={"file": ("t.pdf", io.BytesIO(fakes.build_pdf()),
                                                                 "application/pdf")})
    assert response.status_code == 200, response.text
    assert response.json()["run"]["owner_email"] == "dev@localhost"
    with db.connect() as conn:
        assert conn.execute("SELECT password_hash FROM users WHERE email = 'dev@localhost'").fetchone()[0] is None


def test_outside_dev_mode_no_dev_user_is_made(client):
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE email = 'dev@localhost'").fetchone()[0] == 0
