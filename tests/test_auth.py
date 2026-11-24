"""Sign-in, sessions, lockout and the gate on /api routes."""
from __future__ import annotations

from app import db
from app.auth import middleware, store
from conftest import PASSWORD, login, make_user


def test_login_success_sets_cookie_and_returns_user(client):
    make_user("Ana@Firm.com", name="Ana")
    response = login(client, "ana@firm.com")
    assert response.status_code == 200
    assert response.json() == {"user": {
        "email": "ana@firm.com", "name": "Ana", "is_admin": False, "must_change_password": False,
    }}
    assert "xbrl_session" in response.cookies
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["user"]["email"] == "ana@firm.com"


def test_wrong_password_and_unknown_email_get_the_same_401(client):
    make_user("ana@firm.com")
    wrong = login(client, "ana@firm.com", "not-the-password")
    unknown = login(client, "nobody@firm.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert client.get("/api/auth/me").status_code == 401


def test_stored_password_is_argon2id(client):
    make_user("ana@firm.com")
    with db.connect() as conn:
        assert store.fetch_user(conn, "ana@firm.com").password_hash.startswith("$argon2id$")


def test_lockout_refuses_even_the_right_password(client):
    from app.settings import store as settings

    settings.update({"login": {"max_attempts": 3}}, "boss@firm.com")
    make_user("ana@firm.com")
    for _ in range(3):
        assert login(client, "ana@firm.com", "wrong-password").status_code == 401
    locked = login(client, "ana@firm.com")
    assert locked.status_code == 429
    assert locked.json()["detail"]


def test_disabled_account_cannot_sign_in(client):
    make_user("ana@firm.com")
    with db.connect() as conn:
        store.set_disabled(conn, "ana@firm.com", True)
    assert login(client, "ana@firm.com").status_code == 401


def test_protected_route_refuses_without_a_session(client):
    for path in ("/api/runs", "/api/settings", "/api/models", "/api/auth/me", "/api/admin/users"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["detail"]


def test_forged_cookie_is_refused(client):
    make_user("ana@firm.com")
    login(client, "ana@firm.com")
    session_id = client.cookies.get("xbrl_session").split(".")[0]
    client.cookies.clear()
    client.cookies.set("xbrl_session", f"{session_id}.forged")
    assert client.get("/api/runs").status_code == 401


def test_health_is_open(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok" and response.json()["version"]


def test_only_health_and_login_are_open():
    assert not middleware.is_guarded("/api/health")
    assert not middleware.is_guarded("/api/auth/login/password")
    for path in ("/api/health-detail", "/api/auth/me", "/api/auth/logout", "/api", "/api/runs"):
        assert middleware.is_guarded(path), path
    assert not middleware.is_guarded("/index.html")


def test_every_api_route_is_guarded(client):
    for route in client.app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api") and path not in middleware.OPEN_PATHS:
            assert middleware.is_guarded(path.replace("{", "x").replace("}", "")), path


def test_logout_ends_the_session(client):
    make_user("ana@firm.com")
    login(client, "ana@firm.com")
    cookie = client.cookies.get("xbrl_session")
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.clear()
    client.cookies.set("xbrl_session", cookie)
    assert client.get("/api/auth/me").status_code == 401


def test_idle_session_expires(client, monkeypatch):
    make_user("ana@firm.com")
    login(client, "ana@firm.com")
    with db.connect() as conn:
        conn.execute("UPDATE sessions SET last_seen_at = '2020-01-01T00:00:00Z'")
    assert client.get("/api/runs").status_code == 401
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_temporary_password_must_be_changed_first(client):
    make_user("ana@firm.com", must_change_password=True)
    assert login(client, "ana@firm.com").json()["user"]["must_change_password"] is True
    assert client.get("/api/runs").status_code == 403
    assert client.get("/api/auth/me").status_code == 200
    same = client.post("/api/auth/change-password", json={"new_password": PASSWORD})
    assert same.status_code == 422
    changed = client.post("/api/auth/change-password", json={"new_password": "a-new-password"})
    assert changed.status_code == 204
    assert client.get("/api/runs").status_code == 200
    client.cookies.clear()
    assert login(client, "ana@firm.com", "a-new-password").status_code == 200


def test_change_password_checks_the_current_one(client):
    make_user("ana@firm.com")
    login(client, "ana@firm.com")
    wrong = client.post("/api/auth/change-password",
                        json={"current_password": "nope", "new_password": "a-new-password"})
    assert wrong.status_code == 403
    short = client.post("/api/auth/change-password",
                        json={"current_password": PASSWORD, "new_password": "short"})
    assert short.status_code == 422
    ok = client.post("/api/auth/change-password",
                     json={"current_password": PASSWORD, "new_password": "a-new-password"})
    assert ok.status_code == 204


def _age_session(seconds: int) -> None:
    from datetime import datetime, timedelta, timezone

    stamp = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    with db.connect() as conn:
        conn.execute("UPDATE sessions SET last_seen_at = ?", (stamp,))


def test_an_extended_session_renews_the_cookie(client):
    make_user("ana@firm.com")
    login(client, "ana@firm.com")
    assert "set-cookie" not in client.get("/api/auth/me").headers  # too soon to extend

    _age_session(60)
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("xbrl_session=") and "Max-Age=" in cookie

    _age_session(60)
    logout = client.post("/api/auth/logout")
    assert 'xbrl_session=""' in logout.headers["set-cookie"]  # logout still clears it


def test_a_busy_database_skips_the_activity_bump_and_the_request_succeeds(client, monkeypatch):
    make_user("ana@firm.com")
    login(client, "ana@firm.com")
    _age_session(60)
    with db.connect() as conn:
        before = conn.execute("SELECT last_seen_at FROM sessions").fetchone()[0]

    real_open = db._open

    def quick_open():
        conn = real_open()
        conn.execute("PRAGMA busy_timeout = 100")
        return conn

    monkeypatch.setattr(db, "_open", quick_open)
    # Another connection holds the write lock for the whole request.
    other = real_open()
    other.execute("BEGIN IMMEDIATE")
    other.execute("UPDATE users SET name = name")
    try:
        response = client.get("/api/runs")
    finally:
        other.execute("ROLLBACK")
        other.close()
    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    with db.connect() as conn:
        assert conn.execute("SELECT last_seen_at FROM sessions").fetchone()[0] == before
