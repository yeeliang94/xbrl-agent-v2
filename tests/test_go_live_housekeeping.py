"""Go-live A7: the version and the connection test. There is no automatic clean-up (owner, 26 November 2026)."""
from __future__ import annotations

import asyncio
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from app import db
from app.models import connection
from app.utils.version import VERSION
from tests.conftest import OWNER, login, make_run, make_user

ADMIN = "mira@samplefirm.example"


@pytest.fixture
def admin(client):
    make_user(ADMIN, is_admin=True, name="Mira Quillfeather")
    assert login(client, ADMIN).status_code == 200
    return client


def test_the_version_is_on_the_health_route_and_in_the_traces_zip(admin):
    assert admin.get("/api/health").json()["version"] == VERSION
    run_id = make_run()
    with zipfile.ZipFile(io.BytesIO(admin.get(f"/api/runs/{run_id}/traces").content)) as zf:
        assert zf.read("version.txt").decode().splitlines()[0] == VERSION
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["app_version"] == VERSION and "version.txt" in manifest["files"]


# Connection test ------------------------------------------------------------

class _Refused(Exception):
    status_code = 403


def test_the_connection_test_gives_one_plain_sentence_per_model(admin, monkeypatch):
    admin.put("/api/settings", json={"models": {"review": "claude-opus-5-5"}})
    asked = []

    async def fake(model_id):
        asked.append(model_id)
        if model_id.startswith("claude"):
            raise _Refused("https://gateway.internal.example says no for key sk-secret-value")
        return SimpleNamespace(parts=[SimpleNamespace(content="ready")],
                               usage=SimpleNamespace(input_tokens=9, cache_read_tokens=0, output_tokens=1))

    monkeypatch.setattr(connection, "ask", fake)
    response = admin.post("/api/admin/connection-test")
    assert response.status_code == 200
    results = response.json()["results"]
    assert sorted(asked) == ["claude-opus-5-5", "gpt-6-luna"]   # reading and extraction share a model: asked once
    assert [(r["model"], r["ok"]) for r in results] == [("gpt-6-luna", True), ("claude-opus-5-5", False)]
    assert results[0]["sentence"].startswith("Answered in ") and results[0]["sentence"].endswith(" seconds")
    assert results[1]["sentence"] == "The model service says this key may not use this model."
    assert "gateway.internal" not in response.text and "sk-secret" not in response.text

    # Every call is recorded, the failed one with its error.
    with db.connect() as conn:
        calls = [dict(r) for r in conn.execute("SELECT * FROM model_calls WHERE source = 'connection_test' ORDER BY model")]
    assert [(c["model"], c["run_id"], c["error"] is None) for c in calls] == [
        ("claude-opus-5-5", None, False), ("gpt-6-luna", None, True)]
    assert calls[1]["input_tokens"] == 9


def test_the_connection_test_says_when_a_key_is_missing_or_the_answer_is_empty(admin, monkeypatch):
    # No key is set in tests, so the real call stops in the factory with its own sentence. No model is called.
    results = admin.post("/api/admin/connection-test").json()["results"]
    assert len(results) == 1 and results[0]["ok"] is False
    assert results[0]["sentence"] == "Model gpt-6-luna needs OPENAI_API_KEY in .env, and it is not set."

    async def silent(model_id):
        return SimpleNamespace(parts=[], usage=None)

    monkeypatch.setattr(connection, "ask", silent)
    assert admin.post("/api/admin/connection-test").json()["results"][0]["sentence"] == "The model answered with nothing."

    async def slow(model_id):
        await asyncio.sleep(5)

    monkeypatch.setattr(connection, "ask", slow)
    monkeypatch.setattr(connection, "TIMEOUT_SECONDS", 0.05)
    assert "did not answer within" in admin.post("/api/admin/connection-test").json()["results"][0]["sentence"]
