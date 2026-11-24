"""The mTool fill routes and the `fill` job (docs/api-contract.md, Step 8).
A genuine template under `templates/` is filled from saved figures; no model
is called."""
from __future__ import annotations

import logging

import pytest

from app import db
from app.jobs import queue, worker
from app.runs.events import list_events
from tests.conftest import OWNER, login
from tests.mtool_fill_helpers import GENUINE, matching_run, seed_input_figures

TEMPLATE = GENUINE[0]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _status(run_id: int, status: str) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))


def _upload(client, run_id: int, data: bytes, name: str = TEMPLATE.name):
    return client.post(f"/api/runs/{run_id}/fills", files={"file": (name, data, XLSX)})


@pytest.fixture
def run_id(client):
    run = matching_run(TEMPLATE)
    _status(run, "in_review")
    assert login(client, OWNER).status_code == 200
    return run


def test_every_fill_route_needs_a_session(client):
    run = matching_run(TEMPLATE)
    assert _upload(client, run, TEMPLATE.read_bytes()).status_code == 401
    for path in ("", "/1", "/1/file"):
        assert client.get(f"/api/runs/{run}/fills{path}").status_code == 401


def test_a_fill_is_refused_while_the_run_is_busy(client, run_id):
    _status(run_id, "extracting")
    response = _upload(client, run_id, TEMPLATE.read_bytes())
    assert response.status_code == 409
    assert response.json()["detail"] == "The run is still working, so prepare the mTool file when it finishes."
    assert client.get(f"/api/runs/{run_id}/fills").json() == {"fills": []}


def test_a_second_fill_is_refused_while_one_waits(client, run_id):
    assert _upload(client, run_id, TEMPLATE.read_bytes()).status_code == 202
    response = _upload(client, run_id, TEMPLATE.read_bytes())
    assert response.status_code == 409
    assert response.json()["detail"] == "A fill is already running for this run."


def test_a_file_that_is_not_a_workbook_is_refused(client, run_id):
    response = _upload(client, run_id, b"%PDF-1.7", name="report.pdf")
    assert response.status_code == 422
    assert response.json()["detail"] == "Choose an .xlsx or .xlsm mTool template."


async def test_a_genuine_template_fills_to_ready_and_downloads(client, run_id):
    seed_input_figures(run_id, every=5)
    original = TEMPLATE.read_bytes()
    started = _upload(client, run_id, original)
    assert started.status_code == 202
    fill = started.json()["fill"]
    assert fill["job_status"] == "queued" and fill["template_filename"] == TEMPLATE.name
    assert client.get(f"/api/runs/{run_id}/fills/{fill['id']}/file").status_code == 409

    assert await worker.run_once()
    got = client.get(f"/api/runs/{run_id}/fills/{fill['id']}").json()["fill"]
    assert got["job_status"] == "ready" and got["status"] in ("ok", "needs review")
    receipt = got["receipt"]
    assert receipt["counts"]["written"] > 0
    assert all(line["name"] and line["reason"] and "!" not in line["name"] for line in receipt["lines"])
    assert "path" not in str(got)
    assert got["downloaded_at"] is None

    download = client.get(f"/api/runs/{run_id}/fills/{fill['id']}/file")
    assert download.status_code == 200
    assert download.content[:2] == b"PK" and download.content != original
    assert "filled.xlsx" in download.headers["content-disposition"]
    listed = client.get(f"/api/runs/{run_id}/fills").json()["fills"]
    assert [f["id"] for f in listed] == [fill["id"]] and listed[0]["downloaded_at"]
    assert TEMPLATE.read_bytes() == original
    kinds = [e["kind"] for e in list_events(run_id=run_id) if e["source"] == "fill"]
    assert kinds == ["queued", "started", "done"]


async def test_a_failed_fill_keeps_its_sentence_and_logs_the_traceback(client, run_id, caplog):
    fill = _upload(client, run_id, b"not a workbook at all").json()["fill"]
    with caplog.at_level(logging.WARNING):
        assert await worker.run_once()
    got = client.get(f"/api/runs/{run_id}/fills/{fill['id']}").json()["fill"]
    assert got["job_status"] == "failed" and got["receipt"] is None
    assert got["error"] and got["error"].endswith(".") and "\n" not in got["error"]
    failure = [r for r in caplog.records if "mTool fill" in r.getMessage() and "failed" in r.getMessage()]
    assert failure and failure[0].exc_info is not None
    with db.connect() as conn:
        job = conn.execute("SELECT status FROM jobs WHERE kind = 'fill'").fetchone()
    assert job["status"] == "failed"
    events = [e for e in list_events(run_id=run_id) if e["source"] == "fill"]
    assert events[-1]["kind"] == "failed" and got["error"] in events[-1]["message"]
    # A failed fill does not block the next one.
    assert _upload(client, run_id, TEMPLATE.read_bytes()).status_code == 202


async def test_the_traces_export_holds_the_fill(client, run_id):
    import io
    import json
    import zipfile

    seed_input_figures(run_id, every=7)
    _upload(client, run_id, TEMPLATE.read_bytes())
    assert await worker.run_once()
    zf = zipfile.ZipFile(io.BytesIO(client.get(f"/api/runs/{run_id}/traces").content))
    fills = json.loads(zf.read("fills.json"))
    assert fills[0]["job_status"] == "ready" and fills[0]["report"]["counts"]["written"] > 0
    assert not [n for n in zf.namelist() if n.endswith(".xlsx")]
    with_files = zipfile.ZipFile(io.BytesIO(client.get(f"/api/runs/{run_id}/traces?include_pdf=1").content))
    assert len([n for n in with_files.namelist() if n.startswith("uploaded/fill-")]) == 2
    assert queue.get(fills[0]["job_id"]).status == "done"


@pytest.mark.parametrize("where", ["started_event", "fill", "plain_sentence"])
async def test_any_failure_after_the_fill_begins_marks_it_failed(client, run_id, monkeypatch, caplog, where):
    """Nothing is left "filling". Only a sentence written for a person is shown; any other
    error gets the general sentence, with its full traceback in the log."""
    from app.filing import job
    from app.filing.fill import FillError

    add_event = job.add_event

    def failing_event(source, kind, *args, **kwargs):
        if kind == "started":
            raise RuntimeError("database is locked (internal detail)")
        return add_event(source, kind, *args, **kwargs)

    def failing_fill(*args, **kwargs):
        if where == "plain_sentence":
            raise FillError("There is no such run, or its setup is not confirmed.")
        raise KeyError("internal detail")

    if where == "started_event":
        monkeypatch.setattr(job, "add_event", failing_event)
    else:
        monkeypatch.setattr(job, "fill_workbook", failing_fill)
    fill = _upload(client, run_id, TEMPLATE.read_bytes()).json()["fill"]
    with caplog.at_level(logging.ERROR):
        assert await worker.run_once()

    got = client.get(f"/api/runs/{run_id}/fills/{fill['id']}").json()["fill"]
    assert got["job_status"] == "failed"
    if where == "plain_sentence":
        assert got["error"] == "There is no such run, or its setup is not confirmed."
    else:
        assert got["error"] == job.UNEXPECTED and "internal detail" not in got["error"]
    assert any(r.exc_info is not None and "internal detail" in str(r.exc_info[1]) or
               r.exc_info is not None and where == "plain_sentence" for r in caplog.records)
    assert _upload(client, run_id, TEMPLATE.read_bytes()).status_code == 202
