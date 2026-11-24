"""Deleting a run (the setup screen's Replace), masking secrets in what the app
keeps, and what the log leaves out."""
from __future__ import annotations

import io
import json
import logging
import zipfile

import pytest

from app import db
from app.models import usage as model_usage
from app.reading import store as reading
from app.records import server_log, traces
from app.settings import store as settings
from app.utils import masking
from app.utils.paths import output_dir
from tests import reading_fakes as fakes
from tests.conftest import OWNER, login, make_run, make_user

OTHER = "ben@firm.com"


@pytest.fixture
def signed_in(client):
    make_user(OWNER)
    assert login(client, OWNER).status_code == 200
    return client


def upload(client) -> int:
    response = client.post("/api/runs", files={"file": ("t.pdf", io.BytesIO(fakes.build_pdf()), "application/pdf")})
    return response.json()["run"]["id"]


def finish_reading(run_id: int, status: str = "done") -> None:
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE jobs SET status = 'done' WHERE run_id = ?", (run_id,))
        reading.stage_working(conn, run_id)
        if status == "done":
            reading.save_map(conn, run_id, fakes.good_map(), [])
            reading.stage_done(conn, run_id)
        else:
            reading.stage_failed(conn, run_id, "The model service could not be reached.")


# Deleting a run ----------------------------------------------------------------

@pytest.mark.parametrize("status", ["done", "failed"])
def test_a_run_at_setup_or_failed_is_deleted_with_its_rows_and_files(signed_in, status):
    run_id = upload(signed_in)
    finish_reading(run_id, status)
    folder = output_dir() / "runs" / f"run-{run_id}"
    transcripts = output_dir() / "transcripts" / f"run-{run_id}"
    transcripts.mkdir(parents=True)
    (transcripts / "reader.json").write_text("{}", encoding="utf-8")
    (folder / "reading").mkdir()
    (folder / "reading" / "page-001.json").write_text("{}", encoding="utf-8")
    model_usage.record_call(run_id, "reader", "gpt-6-luna", None, duration_ms=5)

    response = signed_in.delete(f"/api/runs/{run_id}")

    assert response.status_code == 204
    assert not folder.exists() and not transcripts.exists()
    assert signed_in.get(f"/api/runs/{run_id}/document").status_code == 404
    with db.connect() as conn:
        for table in ("runs", "documents", "stages", "jobs", "events", "document_maps", "model_calls"):
            column = "id" if table == "runs" else "run_id"
            assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} = ?", (run_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0


def test_anyone_who_may_open_the_run_may_delete_it(signed_in, client):
    run_id = upload(signed_in)
    finish_reading(run_id)
    make_user(OTHER)
    assert login(client, OTHER).status_code == 200
    assert client.delete(f"/api/runs/{run_id}").status_code == 204


def test_a_run_reading_or_past_setup_is_not_deleted(signed_in):
    reading_run = upload(signed_in)
    refused = signed_in.delete(f"/api/runs/{reading_run}")
    assert refused.status_code == 409
    assert refused.json() == {"detail": "Only a run waiting at setup, or one whose reading or extraction failed, can be deleted."}
    confirmed = make_run()
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE runs SET status = 'ready' WHERE id = ?", (confirmed,))
    assert signed_in.delete(f"/api/runs/{confirmed}").status_code == 409
    assert signed_in.delete("/api/runs/999").json() == {"detail": "There is no such run."}
    assert (output_dir() / "runs" / f"run-{reading_run}").is_dir()


def test_a_run_with_work_in_progress_is_not_deleted(signed_in):
    run_id = upload(signed_in)
    finish_reading(run_id, "failed")
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE jobs SET status = 'working' WHERE run_id = ?", (run_id,))
    response = signed_in.delete(f"/api/runs/{run_id}")
    assert response.status_code == 409
    assert response.json() == {"detail": "This run still has work in progress, so it cannot be deleted yet."}


def test_deleting_a_run_needs_a_session(client):
    assert client.delete("/api/runs/1").status_code == 401


# Masking -------------------------------------------------------------------------

SECRETS = {"OPENAI_API_KEY": "plainkeyvalue12345", "LLM_PROXY_URL": "https://gateway.internal.example/v1",
           "SESSION_SECRET": "session-secret-value-1"}


@pytest.fixture
def secrets(monkeypatch):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    return SECRETS


@pytest.mark.parametrize("text, kept", [
    ('{"api_key": "abc123secretvalue"}', '{"api_key": "[masked]"}'),
    ("Authorization: Bearer abcdefgh12345678", "Authorization: Bearer [masked]"),
    ("Authorization: Basic dXNlcjpwYXNzd29yZA==", "Authorization: Basic [masked]"),
    ("key sk-proj-abcdefghijklmnop", "key sk-proj[masked]"),
    ("https://ana:hunter2pass@proxy.example:8080", "https://ana:[masked]@proxy.example:8080"),
])
def test_text_shaped_like_a_secret_is_masked(text, kept):
    assert masking.mask(text) == kept


def test_the_exact_value_of_every_secret_in_the_environment_is_masked(secrets):
    text = "Failed: plainkeyvalue12345 at https://gateway.internal.example/v1/responses, session-secret-value-1"
    masked = masking.mask(text)
    assert all(value not in masked for value in secrets.values())
    assert masked == "Failed: [masked] at [masked]/responses, [masked]"


def test_a_model_calls_error_is_stored_masked(secrets):
    make_user(OWNER)
    run_id = make_run()
    model_usage.record_call(run_id, "reader", "gpt-6-luna", None, error="APIError: plainkeyvalue12345 refused")
    with db.connect() as conn:
        assert conn.execute("SELECT error FROM model_calls WHERE run_id = ?", (run_id,)).fetchone()[0] == (
            "APIError: [masked] refused")


def test_the_server_log_masks_secrets_and_leaves_out_successful_polls(secrets):
    server_log.setup_logging()
    access = logging.getLogger("uvicorn.access")
    try:
        logging.getLogger("app.test").warning("Gateway https://gateway.internal.example/v1 said no")
        for path, status in (("/api/runs/7/read", 200), ("/api/runs/7/events?after_id=3", 200),
                             ("/api/runs/7/read", 500), ("/api/runs/7/map", 200)):
            access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", path, "1.1", status)
        text = "".join(path.read_text(encoding="utf-8") for path in server_log.log_files())
    finally:
        for logger in (logging.getLogger(), logging.getLogger("uvicorn"), access):
            for handler in [h for h in logger.handlers if isinstance(h, server_log.DailyFileHandler)]:
                logger.removeHandler(handler)
                handler.close()
    assert "gateway.internal.example" not in text and "Gateway [masked] said no" in text
    assert "/api/runs/7/read HTTP/1.1\" 500" in text and "/api/runs/7/map" in text
    assert "/api/runs/7/read HTTP/1.1\" 200" not in text and "/api/runs/7/events" not in text


def test_everything_in_the_traces_zip_is_masked(secrets):
    make_user(OWNER)
    run_id = make_run()
    model_usage.record_call(run_id, "reader", "gpt-6-luna", None, error="raw error")
    with db.connect() as conn:
        conn.execute("INSERT INTO events(run_id, source, kind, message, data_json, created_at) "
                     "VALUES (?, 'reader', 'failed', 'x', ?, 'now')",
                     (run_id, json.dumps({"detail": "key plainkeyvalue12345"})))
    folder = output_dir() / "transcripts" / f"run-{run_id}"
    folder.mkdir(parents=True)
    (folder / "reader.json").write_text(json.dumps({"error": "at https://gateway.internal.example/v1"}),
                                        encoding="utf-8")
    with db.connect() as conn:
        path = traces.build(conn, run_id, include_pdf=False)
    with zipfile.ZipFile(path) as zf:
        everything = "".join(zf.read(name).decode("utf-8") for name in zf.namelist())
    path.unlink()
    assert all(value not in everything for value in secrets.values())
    assert "[masked]" in everything


def test_login_limits_that_cannot_be_read_fall_back_with_a_warning(monkeypatch, caplog):
    def broken(**kwargs):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(settings.db, "connect", broken)
    with caplog.at_level(logging.WARNING, logger="app.settings.store"):
        assert settings.login_limits() == settings.DEFAULTS["login"]
    record = next(r for r in caplog.records if "login limits" in r.getMessage())
    assert record.exc_info is not None
