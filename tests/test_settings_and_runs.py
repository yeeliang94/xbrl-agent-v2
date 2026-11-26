"""Settings read and admin write, the model list and the run list."""
from __future__ import annotations

import pytest

from app import db
from app.models import catalog
from app.runs import store as runs
from conftest import login, make_run, make_user


def _sign_in(client, *, admin: bool) -> None:
    email = "boss@firm.com" if admin else "ana@firm.com"
    make_user(email, is_admin=admin)
    login(client, email)


def test_settings_defaults(client):
    _sign_in(client, admin=False)
    settings = client.get("/api/settings").json()
    assert settings == {
        "route": "direct",
        "models": {"reading": "gpt-6-luna", "extraction": "gpt-6-luna", "review": "gpt-6-luna"},
        "code_workbench": True,
        "claude_sandbox_real_documents": False,
        "house_style": {
            "body_text": "justified", "table_font_pt": 10, "smallest_table_font_pt": 8,
            "double_underline": "thick_bottom_border", "bold_totals": False,
        },
        "login": {"idle_timeout_minutes": 60, "max_attempts": 5, "lockout_minutes": 15},
    }


def test_route_follows_the_gateway_address(client, monkeypatch):
    _sign_in(client, admin=False)
    monkeypatch.setenv("LLM_PROXY_URL", "https://gateway.example/v1")
    assert client.get("/api/settings").json()["route"] == "gateway"


def test_admin_saves_a_subset_and_it_persists(client):
    _sign_in(client, admin=True)
    saved = client.put("/api/settings", json={
        "models": {"review": "gpt-6.1-terra"},
        "code_workbench": False,
        "house_style": {"bold_totals": True},
    })
    assert saved.status_code == 200
    again = client.get("/api/settings").json()
    assert again["models"] == {"reading": "gpt-6-luna", "extraction": "gpt-6-luna", "review": "gpt-6.1-terra"}
    assert again["code_workbench"] is False
    assert again["house_style"]["bold_totals"] is True
    assert again["house_style"]["table_font_pt"] == 10


def test_bad_settings_are_refused_with_a_sentence(client):
    _sign_in(client, admin=True)
    for body in (
        {"route": "gateway"},
        {"colour": "red"},
        {"code_workbench": "yes"},
        {"models": {"reading": "gemini-3-pro"}},
        {"models": {"writing": "gpt-6-luna"}},
        {"house_style": {"table_font_pt": 14}},
        {"house_style": {"smallest_table_font_pt": 9, "table_font_pt": 9}} | {"code_workbench": 1},
    ):
        response = client.put("/api/settings", json=body)
        assert response.status_code == 422, body
        assert response.json()["detail"].endswith(".")
    # Nothing from the refused changes was saved.
    assert client.get("/api/settings").json()["house_style"]["table_font_pt"] == 10


def test_house_style_values_outside_the_allowed_lists_are_refused(client):
    _sign_in(client, admin=True)
    allowed = {
        "body_text": ["justified", "left"],
        "table_font_pt": [9, 10, 11],
        "smallest_table_font_pt": [8, 9],
        "double_underline": ["thick_bottom_border", "single_bottom_border"],
        "bold_totals": [True, False],
    }
    refused = {
        "body_text": ["centred", "", 1],
        "table_font_pt": [8, 12, "10", 10.5, 10.0, True],
        "smallest_table_font_pt": [7, 10, "8", True],
        "double_underline": ["double", None],
        "bold_totals": ["yes", 1, None],
    }
    for name, values in allowed.items():
        for value in values:
            assert client.put("/api/settings", json={"house_style": {name: value}}).status_code == 200, (name, value)
    for name, values in refused.items():
        for value in values:
            response = client.put("/api/settings", json={"house_style": {name: value}})
            assert response.status_code == 422, (name, value)
            assert response.json()["detail"]
    assert client.put("/api/settings", json={"house_style": {"font": "Arial"}}).status_code == 422


def test_two_partial_saves_at_the_same_time_both_keep_their_change(monkeypatch):
    import threading
    import time

    from app.settings import store

    real_check = store._check_house_style
    other: list[threading.Thread] = []

    def check_then_let_another_save_in(value):
        if not other:
            # The first save is between its read and its write. A second save
            # of a different house-style field starts now.
            thread = threading.Thread(target=store.update, args=(
                {"house_style": {"bold_totals": True}}, "b@firm.com"))
            other.append(thread)
            thread.start()
            time.sleep(0.3)
        return real_check(value)

    monkeypatch.setattr(store, "_check_house_style", check_then_let_another_save_in)
    store.update({"house_style": {"table_font_pt": 11}}, "a@firm.com")
    other[0].join(timeout=10)
    style = store.read()["house_style"]
    assert style["table_font_pt"] == 11 and style["bold_totals"] is True


def test_model_list_without_keys(client, monkeypatch):
    _sign_in(client, admin=False)
    models = client.get("/api/models").json()["models"]
    by_id = {m["id"]: m for m in models}
    assert by_id["gpt-6-luna"] == {
        "id": "gpt-6-luna", "provider": "openai", "family": "luna", "label": "GPT-6 Luna",
        "available": False,
    }
    assert by_id["gpt-6.1-terra"]["family"] == "terra"
    assert by_id["gpt-6.1-terra"]["label"] == "GPT-6.1 Terra"


def test_model_list_asks_the_providers(client, monkeypatch):
    _sign_in(client, admin=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    async def fake_ids(provider):
        return {"openai": ["gpt-6-luna", "gpt-5.4", "text-embedding-3-large", "gpt-4o-audio-preview"],
                "anthropic": ["claude-sonnet-4-6"]}[provider]

    monkeypatch.setattr(catalog, "_ids_from", fake_ids)
    models = {m["id"]: m for m in client.get("/api/models").json()["models"]}
    assert set(models) == {"gpt-6-luna", "gpt-5.4", "gpt-6.1-terra"}
    assert all(m["available"] for m in models.values())
    assert models["gpt-5.4"]["family"] == "other"


def test_model_list_on_the_gateway(client, monkeypatch):
    _sign_in(client, admin=False)
    monkeypatch.setenv("LLM_PROXY_URL", "https://gateway.example/v1")
    monkeypatch.setenv("LLM_PROXY_API_KEY", "test-key")

    async def fake_ids(provider):
        return ["openai.global.gpt-6-luna", "openai.eu.gpt-6-luna",
                "bedrock.anthropic.claude-opus-4-7", "vertex_ai.gemini-3.6-flash"]

    monkeypatch.setattr(catalog, "_ids_from", fake_ids)
    models = {m["id"]: m for m in client.get("/api/models").json()["models"]}
    assert set(models) == {"gpt-6-luna", "openai.eu.gpt-6-luna", "claude-opus-4-7", "gpt-6.1-terra"}
    assert models["claude-opus-4-7"]["family"] == "claude"
    assert models["claude-opus-4-7"]["label"] == "Claude Opus 4.7"


def test_run_list_is_empty_at_first(client):
    _sign_in(client, admin=False)
    assert client.get("/api/runs").json() == {"runs": [], "total": 0, "page": 0, "per_page": 25}


def test_run_list_shape(client):
    _sign_in(client, admin=False)
    stamp = db.now()
    with db.connect() as conn:
        conn.execute("INSERT INTO companies(name, created_at) VALUES ('Acme Berhad', ?)", (stamp,))
        conn.execute(
            "INSERT INTO runs(company_id, year, standard, level, status, owner_email, created_at, "
            "updated_at) VALUES (1, 2025, 'MFRS', 'Group', 'in_review', 'ana@firm.com', ?, ?)",
            (stamp, stamp),
        )
    assert client.get("/api/runs").json() == {"runs": [{
        "id": 1, "company": "Acme Berhad", "year": 2025, "standard": "MFRS", "level": "Group",
        "status": "in_review", "updated_at": stamp, "owner_name": "ana", "owner_email": "ana@firm.com",
        "filename": None, "failed_stage": None,
    }], "total": 1, "page": 0, "per_page": 25}


def test_a_layout_the_standard_does_not_have_is_refused_when_the_run_is_created():
    with pytest.raises(runs.RunRefused) as caught:
        make_run([("SOFP", "CuNonCu"), ("SOCIE", "SoRE")], standard="MFRS")
    assert str(caught.value) == ("The SoRE layout of SOCIE does not exist for MFRS filings, "
                                 "so choose another layout.")
