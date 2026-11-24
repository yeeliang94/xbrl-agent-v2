"""The login lockout: it forgets old entries, and on Azure it counts the address Azure's front end
saw, not one the sender wrote."""
from __future__ import annotations


def test_the_lockout_forgets_entries_once_their_time_has_passed(monkeypatch):
    from app.auth import lockout

    clock = [1000.0]
    monkeypatch.setattr(lockout.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(lockout.config, "login_lockout_seconds", lambda: 60)
    monkeypatch.setattr(lockout.config, "login_max_attempts", lambda: 5)
    for n in range(50):
        lockout.record_failure(f"person{n}@firm.com", "10.0.0.1")
    clock[0] += 61
    lockout.record_failure("late@firm.com", "10.0.0.1")
    assert list(lockout._state) == [("late@firm.com", "10.0.0.1")]


def test_on_azure_the_lockout_counts_the_address_azure_saw_not_one_the_sender_wrote(client, monkeypatch):
    from tests.conftest import login, make_user

    monkeypatch.setenv("WEBSITE_SITE_NAME", "xbrl-test")
    make_user("ana@firm.com")
    for n in range(5):   # a new made-up address on each guess, as an attacker would send
        client.post("/api/auth/login/password", json={"email": "ana@firm.com", "password": "wrong"},
                    headers={"X-Forwarded-For": f"10.9.9.{n}, 203.0.113.7:{50000 + n}"})
    blocked = client.post("/api/auth/login/password", json={"email": "ana@firm.com", "password": "wrong"},
                          headers={"X-Forwarded-For": "10.9.9.99, 203.0.113.7:61000"})
    assert blocked.status_code == 429
    elsewhere = client.post("/api/auth/login/password", json={"email": "ana@firm.com", "password": "correct-horse-1"},
                            headers={"X-Forwarded-For": "198.51.100.4:40000"})
    assert elsewhere.status_code == 200   # a colleague at another address is not locked out
