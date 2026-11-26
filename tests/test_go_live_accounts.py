"""Go-live A1: users, the audit log and a person's own password."""
from __future__ import annotations

import pytest

from app import db
from app.auth import store
from tests.conftest import PASSWORD, login, make_user


@pytest.fixture
def admin(client):
    make_user("mira@samplefirm.example", is_admin=True, name="Mira Quillfeather")
    assert login(client, "mira@samplefirm.example").status_code == 200
    return client


def _audit(client, **params) -> dict:
    response = client.get("/api/admin/audit", params=params)
    assert response.status_code == 200
    return response.json()


def test_every_user_action_an_admin_takes_is_in_the_audit_log(admin):
    added = admin.post("/api/admin/users", json={"email": "odell@samplefirm.example", "name": "Odell Brambleworth"})
    assert added.status_code == 200 and added.json()["temporary_password"]
    email = "odell@samplefirm.example"
    assert admin.post(f"/api/admin/users/{email}/admin", json={"is_admin": True}).json()["user"]["is_admin"] is True
    assert admin.post(f"/api/admin/users/{email}/admin", json={"is_admin": False}).json()["user"]["is_admin"] is False
    assert admin.post(f"/api/admin/users/{email}/disable").json()["user"]["disabled"] is True
    assert admin.post(f"/api/admin/users/{email}/enable").json()["user"]["disabled"] is False
    reset = admin.post(f"/api/admin/users/{email}/reset-password").json()
    assert reset["temporary_password"] and reset["user"]["must_change_password"] is True

    log = _audit(admin)
    assert [e["action"] for e in log["events"]] == [
        "password_reset", "user_enabled", "user_disabled", "role_changed", "role_changed", "user_added"]
    assert all(e["actor_name"] == "Mira Quillfeather" and e["target_name"] == "Odell Brambleworth"
               for e in log["events"])
    assert log["total"] == 6 and log["has_more"] is False


def test_the_last_admin_cannot_be_removed_or_disabled_and_the_refusal_names_them(admin):
    email = "mira@samplefirm.example"
    refused = admin.post(f"/api/admin/users/{email}/admin", json={"is_admin": False})
    assert refused.status_code == 409
    assert refused.json()["detail"] == "Mira Quillfeather is the only admin. Make someone else an admin first."
    assert admin.post(f"/api/admin/users/{email}/disable").status_code == 409
    assert _audit(admin)["events"] == []

    # With a second admin, the first can step down.
    make_user("tobin@samplefirm.example", is_admin=True)
    assert admin.post(f"/api/admin/users/{email}/admin", json={"is_admin": False}).status_code == 200


def test_a_disabled_admin_does_not_count_as_an_admin(admin):
    make_user("tobin@samplefirm.example", is_admin=True)
    assert admin.post("/api/admin/users/tobin@samplefirm.example/disable").status_code == 200
    assert admin.post("/api/admin/users/mira@samplefirm.example/disable").status_code == 409


def test_the_audit_log_filters_by_person_and_action_and_pages(admin):
    make_user("tobin@samplefirm.example", is_admin=True, name="Tobin Marrowgate")
    with db.connect() as conn:
        for i in range(25):
            store.add_audit(conn, "mira@samplefirm.example", "user_added", f"person{i}@samplefirm.example")
        store.add_audit(conn, "tobin@samplefirm.example", "setting_changed", "login.max_attempts")
        store.add_audit(conn, "tobin@samplefirm.example", "issue_closed", "11")
        store.add_audit(conn, "mira@samplefirm.example", "run_deleted", "7")

    first = _audit(admin, limit=20)
    assert first["total"] == 28 and len(first["events"]) == 20 and first["has_more"] is True
    assert first["events"][0]["action"] == "run_deleted"   # newest first
    second = _audit(admin, limit=20, offset=20)
    assert len(second["events"]) == 8 and second["has_more"] is False
    assert not {e["id"] for e in first["events"]} & {e["id"] for e in second["events"]}

    assert _audit(admin, actor="tobin@samplefirm.example")["total"] == 2
    assert _audit(admin, group="users")["total"] == 25
    assert [e["action"] for e in _audit(admin, group="settings")["events"]] == ["setting_changed"]
    assert [e["action"] for e in _audit(admin, group="issues")["events"]] == ["issue_closed"]
    assert [e["action"] for e in _audit(admin, group="runs")["events"]] == ["run_deleted"]
    assert _audit(admin, actor="tobin@samplefirm.example", group="users")["total"] == 0
    assert _audit(admin, group="nonsense")["total"] == 0

    people = {p["email"]: p["name"] for p in first["people"]}
    assert people == {"mira@samplefirm.example": "Mira Quillfeather", "tobin@samplefirm.example": "Tobin Marrowgate"}


def test_a_settings_change_writes_an_audit_row_for_each_value_that_changed(admin):
    change = {"login": {"idle_timeout_minutes": 120, "max_attempts": 5}, "code_workbench": False,
              "models": {"review": "gpt-6.1-terra"}}
    assert admin.put("/api/settings", json=change).status_code == 200
    rows = _audit(admin, group="settings")["events"]
    assert {(r["target"], r["detail"]["setting"], r["detail"]["from"], r["detail"]["to"]) for r in rows} == {
        ("login.idle_timeout_minutes", "Sign out after idle", "1 hour", "2 hours"),
        ("code_workbench", "Code workbench", "on", "off"),
        ("models.review", "Review model", "gpt-6-luna", "gpt-6.1-terra"),
    }   # max_attempts was sent with the value it already had: no row
    assert all(r["action"] == "setting_changed" and r["actor_email"] == "mira@samplefirm.example" for r in rows)

    # Saving the same values again changes nothing, so it logs nothing.
    assert admin.put("/api/settings", json=change).status_code == 200
    assert _audit(admin, group="settings")["total"] == 3

    # A refused save logs nothing.
    assert admin.put("/api/settings", json={"login": {"max_attempts": 99}}).status_code == 422
    assert _audit(admin, group="settings")["total"] == 3


def test_someone_who_is_not_an_admin_is_refused_everything_but_their_own_account(client):
    make_user("mira@samplefirm.example", is_admin=True)
    make_user("odell@samplefirm.example")
    login(client, "odell@samplefirm.example")
    for method, path, body in [
        ("get", "/api/admin/users", None),
        ("post", "/api/admin/users", {"email": "x@samplefirm.example"}),
        ("post", "/api/admin/users/mira@samplefirm.example/disable", None),
        ("post", "/api/admin/users/mira@samplefirm.example/enable", None),
        ("post", "/api/admin/users/mira@samplefirm.example/reset-password", None),
        ("post", "/api/admin/users/odell@samplefirm.example/admin", {"is_admin": True}),
        ("get", "/api/admin/audit", None),
        ("put", "/api/settings", {"login": {"max_attempts": 10}}),
        ("post", "/api/admin/connection-test", None),
        ("get", "/api/issues", None),
        ("patch", "/api/issues/1", {"status": "closed"}),
        ("delete", "/api/issues/1", None),
        ("get", "/api/issues/1/file", None),
        ("get", "/api/issues/1/traces", None),
    ]:
        response = getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert response.status_code == 403, (method, path)
        assert response.json()["detail"] == "Only an admin can do this."
    assert client.get("/api/auth/me").status_code == 200


def test_a_person_changes_their_own_password_and_signs_in_with_it(client):
    make_user("mira@samplefirm.example", is_admin=True)
    make_user("odell@samplefirm.example", name="Odell Brambleworth")
    login(client, "odell@samplefirm.example")

    wrong = client.post("/api/auth/change-password", json={"current_password": "not-it", "new_password": "maple-orbit-4821"})
    assert wrong.status_code == 403 and wrong.json()["detail"] == "The current password is wrong."
    short = client.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "short"})
    assert short.status_code == 422
    changed = client.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "maple-orbit-4821"})
    assert changed.status_code == 204
    assert client.get("/api/auth/me").status_code == 200   # still signed in

    client.cookies.clear()
    assert login(client, "odell@samplefirm.example", PASSWORD).status_code == 401
    assert login(client, "odell@samplefirm.example", "maple-orbit-4821").status_code == 200

    client.cookies.clear()
    login(client, "mira@samplefirm.example")
    rows = _audit(client, group="users")["events"]
    assert [(r["action"], r["actor_email"]) for r in rows] == [("password_changed", "odell@samplefirm.example")]
    assert "maple" not in str(rows)   # never the password itself
