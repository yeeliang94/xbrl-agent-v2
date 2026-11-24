"""Admin-only routes, the audit log, the bootstrap admin and production refusals."""
from __future__ import annotations

import pytest

from app import db
from app.auth import startup, store
from conftest import login, make_user


def test_admin_routes_refuse_a_non_admin(client):
    make_user("ana@firm.com")
    login(client, "ana@firm.com")
    assert client.get("/api/admin/users").status_code == 403
    assert client.post("/api/admin/users", json={"email": "x@firm.com"}).status_code == 403
    assert client.post("/api/admin/users/ana@firm.com/admin", json={"is_admin": True}).status_code == 403
    assert client.get("/api/admin/audit").status_code == 403
    assert client.put("/api/settings", json={"code_workbench": False}).status_code == 403


def test_admin_adds_a_user_with_a_temporary_password(client):
    make_user("boss@firm.com", is_admin=True)
    login(client, "boss@firm.com")
    added = client.post("/api/admin/users", json={"email": "New@Firm.com", "name": "New"})
    assert added.status_code == 200
    temporary = added.json()["temporary_password"]
    assert "password_hash" not in added.json()["user"]
    assert client.post("/api/admin/users", json={"email": "new@firm.com"}).status_code == 409

    audit = client.get("/api/admin/audit").json()["events"]
    assert audit[0]["action"] == "user_added" and audit[0]["actor_email"] == "boss@firm.com"

    client.cookies.clear()
    signed_in = login(client, "new@firm.com", temporary)
    assert signed_in.json()["user"]["must_change_password"] is True


def test_the_only_admin_cannot_be_disabled_or_demoted(client):
    make_user("boss@firm.com", is_admin=True)
    login(client, "boss@firm.com")
    assert client.post("/api/admin/users/boss@firm.com/disable").status_code == 409
    assert client.post("/api/admin/users/boss@firm.com/admin", json={"is_admin": False}).status_code == 409


def test_disabling_a_user_ends_their_session(client):
    make_user("boss@firm.com", is_admin=True)
    make_user("ana@firm.com")
    login(client, "ana@firm.com")
    ana_cookie = client.cookies.get("xbrl_session")
    client.cookies.clear()
    login(client, "boss@firm.com")
    assert client.post("/api/admin/users/ana@firm.com/disable").status_code == 200
    client.cookies.clear()
    client.cookies.set("xbrl_session", ana_cookie)
    assert client.get("/api/runs").status_code == 401


def test_bootstrap_admin_is_created_once_and_not_reset(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@firm.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "first-password")
    assert startup.bootstrap_admin_from_env() == "created"
    with db.connect() as conn:
        first_hash = store.fetch_user(conn, "admin@firm.com").password_hash
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "second-password")
    assert startup.bootstrap_admin_from_env() == "already-present"
    with db.connect() as conn:
        user = store.fetch_user(conn, "admin@firm.com")
    assert user.is_admin and user.password_hash == first_hash


def test_bootstrap_admin_can_sign_in(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app

    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@firm.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "first-password")
    with TestClient(create_app(start_worker=False)) as client:
        response = login(client, "admin@firm.com", "first-password")
    assert response.status_code == 200 and response.json()["user"]["is_admin"] is True


def test_local_start_never_refuses():
    startup.check_production_config()


@pytest.mark.parametrize("problem", ["dev_mode", "no_secret", "no_users"])
def test_production_refuses_a_bad_config(monkeypatch, problem):
    monkeypatch.setenv("WEBSITE_SITE_NAME", "xbrl-agent")
    monkeypatch.setenv("SESSION_SECRET", "s" * 64)
    if problem != "no_users":
        make_user("ana@firm.com")
    if problem == "dev_mode":
        monkeypatch.setenv("AUTH_MODE", "dev")
    if problem == "no_secret":
        monkeypatch.delenv("SESSION_SECRET")
    with pytest.raises(RuntimeError):
        startup.check_production_config()


def test_production_refusal_stops_the_app(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app

    monkeypatch.setenv("WEBSITE_SITE_NAME", "xbrl-agent")
    make_user("ana@firm.com")
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        with TestClient(create_app(start_worker=False)):
            pass


def test_production_with_a_secret_and_a_user_starts(monkeypatch):
    monkeypatch.setenv("WEBSITE_SITE_NAME", "xbrl-agent")
    monkeypatch.setenv("SESSION_SECRET", "s" * 64)
    make_user("ana@firm.com")
    startup.check_production_config()
