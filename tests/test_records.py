"""Records: the server log files, a run's traces zip, the Settings page's
downloads and the login limits that moved to Settings."""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import zipfile
from datetime import date, timedelta

import pytest

from app import db
from app.models import usage as model_usage
from app.records import server_log
from app.reading import store as reading
from app.settings import store as settings
from app.utils.paths import output_dir
from tests import reading_fakes as fakes
from tests.conftest import OWNER, login, make_user


@pytest.fixture
def signed_in(client):
    make_user(OWNER)
    assert login(client, OWNER).status_code == 200
    return client


@pytest.fixture
def admin(client):
    make_user("boss@firm.com", is_admin=True)
    assert login(client, "boss@firm.com").status_code == 200
    return client


def _upload(client) -> int:
    response = client.post("/api/runs", files={"file": ("Doc 1.pdf", io.BytesIO(fakes.build_pdf()), "application/pdf")})
    return response.json()["run"]["id"]


def _flush() -> None:
    for handler in logging.getLogger().handlers:
        handler.flush()


def _zip(response) -> zipfile.ZipFile:
    assert response.status_code == 200, response.text
    return zipfile.ZipFile(io.BytesIO(response.content))


# The server log ---------------------------------------------------------------

def test_the_server_log_goes_to_a_daily_file_with_the_run_and_without_secrets(client):
    log = logging.getLogger("app.test")
    token = server_log.RUN_ID.set(7)
    try:
        log.warning("Run 7: the read stage starts. Key sk-proj-abcdefghijklmnopqrstuvwxyz used.")
    finally:
        server_log.RUN_ID.reset(token)
    log.warning("No run here, password=hunter2")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        token = server_log.RUN_ID.set(7)
        log.exception("Run 7 failed")
        server_log.RUN_ID.reset(token)
    _flush()
    path = output_dir() / "logs" / f"server-{date.today().isoformat()}.log"
    text = path.read_text(encoding="utf-8")
    assert " run=7 " in text and " run=- " in text
    assert "abcdefghijklmnopqrstuvwxyz" not in text and "hunter2" not in text
    lines = list(server_log.lines_for_run(7))
    assert any("the read stage starts" in line for line in lines)
    assert any("RuntimeError: boom" in line for line in lines)   # the traceback follows its line
    assert not any("No run here" in line for line in lines)
    assert not list(server_log.lines_for_run(70))


def test_log_files_older_than_30_days_are_removed(client):
    folder = output_dir() / "logs"
    old = folder / f"server-{(date.today() - timedelta(days=30)).isoformat()}.log"
    kept = folder / f"server-{(date.today() - timedelta(days=29)).isoformat()}.log"
    folder.mkdir(parents=True, exist_ok=True)
    for path in (old, kept):
        path.write_text("x\n", encoding="utf-8")
    server_log.prune(folder, date.today())
    assert not old.exists() and kept.exists()


def test_a_job_logs_with_its_run(client):
    import asyncio

    from app.jobs import queue, worker

    @worker.handler("test.logs-run")
    def logs(job):
        logging.getLogger("app.test").info("working on it")

    make_user(OWNER)
    run_id = _make_reading_run()
    try:
        queue.enqueue("test.logs-run", run_id=run_id)
        assert asyncio.run(worker.run_once())
    finally:
        worker._HANDLERS.pop("test.logs-run", None)
    _flush()
    assert any("working on it" in line for line in server_log.lines_for_run(run_id))
    assert server_log.RUN_ID.get() is None


def _make_reading_run() -> int:
    from app.runs import store as runs

    with db.connect() as conn:
        return runs.create_reading_run(conn, owner_email=OWNER)


# Traces ---------------------------------------------------------------------

def test_traces_hold_everything_recorded_for_the_run(signed_in):
    run_id = _upload(signed_in)
    with db.connect(immediate=True) as conn:
        reading.stage_working(conn, run_id)
        reading.save_page(conn, run_id, 1, fakes.good_page(1), None)
        reading.save_map(conn, run_id, fakes.good_map(), ["Note 3 is not in the list; find it or say why it is absent."])
        reading.stage_done(conn, run_id)
    model_usage.record_call(run_id, "reader", "gpt-6-luna", None, duration_ms=12, error="Timeout")
    run_folder = output_dir() / "runs" / f"run-{run_id}" / "reading"
    run_folder.mkdir(parents=True)
    (run_folder / "page-001.json").write_text('{"raw": "answer"}', encoding="utf-8")
    transcripts = output_dir() / "transcripts" / f"run-{run_id}"
    transcripts.mkdir(parents=True)
    (transcripts / "reader-1.json").write_text('{"messages": []}', encoding="utf-8")
    logging.getLogger("app.test").info("only this run")
    signed_in.get(f"/api/runs/{run_id}/read")   # a request about the run
    with server_log_run(run_id):
        logging.getLogger("app.test").info("Run %s: a stage ended.", run_id)
    _flush()

    zf = _zip(signed_in.get(f"/api/runs/{run_id}/traces"))
    names = set(zf.namelist())
    for name in ("manifest.json", "run.json", "events.json", "model_calls.json", "model_calls.csv", "pages.json",
                 "document.json", "document_map.json", "figures.json", "checks.json", "server-log.txt",
                 "comments.json", "rounds.json", "records/reading/page-001.json", "transcripts/reader-1.json"):
        assert name in names, name
    assert not any(n.endswith(".pdf") for n in names)
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["run_id"] == run_id and manifest["include_pdf"] is False
    assert not any("Comments" in item for item in manifest["not_recorded_yet"])
    assert json.loads(zf.read("document_map.json"))["open_points"] == [
        "Note 3 is not in the list; find it or say why it is absent."]
    assert json.loads(zf.read("pages.json"))[0]["content"]["title"] == "Contents"
    assert json.loads(zf.read("run.json"))["stages"][0]["name"] == "upload"
    calls = list(csv.DictReader(io.StringIO(zf.read("model_calls.csv").decode())))
    assert calls[0]["error"] == "Timeout" and calls[0]["source"] == "reader"
    assert "a stage ended" in zf.read("server-log.txt").decode()

    with_pdf = _zip(signed_in.get(f"/api/runs/{run_id}/traces?include_pdf=1"))
    assert with_pdf.read("uploaded/Doc 1.pdf")[:5] == b"%PDF-"
    assert signed_in.get("/api/runs/999/traces").json() == {"detail": "There is no such run."}
    assert not list((output_dir() / "tmp").glob("*.zip"))   # the temporary zips are removed


class server_log_run:
    def __init__(self, run_id: int):
        self.run_id = run_id

    def __enter__(self):
        self.token = server_log.RUN_ID.set(self.run_id)

    def __exit__(self, *exc):
        server_log.RUN_ID.reset(self.token)


def test_traces_never_follow_a_link_or_a_stored_path_out_of_the_run(signed_in, tmp_path):
    run_id = _upload(signed_in)
    secret = tmp_path / "outside.txt"
    secret.write_text("not this run's", encoding="utf-8")
    folder = output_dir() / "runs" / f"run-{run_id}"
    os.symlink(secret, folder / "link.txt")
    other = output_dir() / "runs" / "run-999"
    other.mkdir(parents=True)
    (other / "page.json").write_text("other run", encoding="utf-8")
    with db.connect() as conn:   # a tampered stored path must not pull in another file
        conn.execute("UPDATE documents SET stored_path = '../outside.txt' WHERE run_id = ?", (run_id,))
    zf = _zip(signed_in.get(f"/api/runs/{run_id}/traces?include_pdf=1"))
    assert not any("link" in n or "outside" in n or n.startswith("uploaded/") for n in zf.namelist())
    assert b"not this run's" not in b"".join(zf.read(n) for n in zf.namelist())
    assert b"other run" not in b"".join(zf.read(n) for n in zf.namelist())


def test_traces_need_a_session(client):
    assert client.get("/api/runs/1/traces").status_code == 401


# The Settings page's records --------------------------------------------------

def test_an_admin_downloads_the_server_logs(admin):
    logging.getLogger("app.test").warning("a line for the logs")
    _flush()
    zf = _zip(admin.get("/api/settings/records/logs"))
    name = f"server-{date.today().isoformat()}.log"
    assert name in zf.namelist()
    assert "a line for the logs" in zf.read(name).decode("utf-8")


def test_an_admin_downloads_usage_by_run_and_day(admin):
    run_id = _upload(admin)
    with db.connect() as conn:
        conn.execute("INSERT INTO companies(name, created_at) VALUES ('=Acme', 't')")
        conn.execute("UPDATE runs SET company_id = 1 WHERE id = ?", (run_id,))
    usage = type("U", (), {"input_tokens": 1000, "cache_read_tokens": 200, "output_tokens": 50})()
    model_usage.record_call(run_id, "reader", "gpt-6-luna", usage)
    model_usage.record_call(run_id, "reader", "gpt-6-luna", None, error="Timeout")
    model_usage.record_call(None, "smoke", "gpt-6-luna", usage)
    response = admin.get("/api/settings/records/usage")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    mine = next(r for r in rows if r["run_id"] == str(run_id))
    assert (mine["calls"], mine["failed_calls"], mine["input_tokens"], mine["model"]) == ("2", "1", "1000", "gpt-6-luna")
    assert mine["run"] == "'=Acme"   # never run as a formula in a spreadsheet
    assert mine["day"] == date.today().isoformat() or len(mine["day"]) == 10
    assert any(r["run_id"] == "" for r in rows)


def test_the_records_are_for_admins_only(signed_in):
    for path in ("/api/settings/records/logs", "/api/settings/records/usage"):
        response = signed_in.get(path)
        assert response.status_code == 403
        assert response.json() == {"detail": "Only an admin can do this."}


# Login limits on the Settings page -------------------------------------------

def test_login_limits_are_settings_with_bounds(admin):
    assert admin.get("/api/settings").json()["login"] == {
        "idle_timeout_minutes": 60, "max_attempts": 5, "lockout_minutes": 15}
    saved = admin.put("/api/settings", json={"login": {"max_attempts": 10}})
    assert saved.json()["login"] == {"idle_timeout_minutes": 60, "max_attempts": 10, "lockout_minutes": 15}
    for change, sentence in (
            ({"idle_timeout_minutes": 2}, "Sign out after idle must be a whole number of minutes from 5 to 1440."),
            ({"max_attempts": 2.5}, "Attempts before lockout must be a whole number of attempts from 3 to 20."),
            ({"lockout_minutes": True}, "Lockout time must be a whole number of minutes from 1 to 1440."),
            ({"other": 1}, "That is not a sign-in setting.")):
        refused = admin.put("/api/settings", json={"login": change})
        assert refused.status_code == 422 and refused.json() == {"detail": sentence}


def test_the_idle_timeout_comes_from_settings(signed_in, monkeypatch):
    monkeypatch.setenv("AUTH_IDLE_TIMEOUT_S", "1")   # no longer read
    with db.connect() as conn:
        conn.execute("UPDATE sessions SET last_seen_at = ?", (_minutes_ago(20),))
    assert signed_in.get("/api/runs").status_code == 200
    settings.update({"login": {"idle_timeout_minutes": 15}}, "boss@firm.com")
    with db.connect() as conn:
        conn.execute("UPDATE sessions SET last_seen_at = ?", (_minutes_ago(20),))
    assert signed_in.get("/api/runs").status_code == 401


def test_the_lockout_time_comes_from_settings(client):
    from app.auth import config

    settings.update({"login": {"lockout_minutes": 2, "max_attempts": 4}}, "boss@firm.com")
    assert config.login_lockout_seconds() == 120 and config.login_max_attempts() == 4


def _minutes_ago(minutes: int) -> str:
    from datetime import datetime, timezone

    when = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return when.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def test_env_example_no_longer_names_the_login_limits():
    from app.utils.paths import PROJECT_ROOT

    text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "AUTH_IDLE_TIMEOUT_S" not in text and "AUTH_LOGIN_MAX_ATTEMPTS" not in text
