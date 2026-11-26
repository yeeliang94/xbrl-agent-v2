"""The run list's search, filters and paging; who may delete a run and what
goes with it; and clearing abandoned drafts (go-live plan A4)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from app import db
from app.auth import store as auth_store
from app.figures import store as figures
from app.utils.paths import output_dir
from tests.conftest import OWNER, field, login, make_run, make_user

OTHER, ADMIN = "ben@firm.com", "chief@firm.com"
STATUSES = ["filed", "in_review", "setup", "needs_answer", "failed", "stopped", "ready", "extracting",
            "reading", "correcting"]


def stamp(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def seed(count: int = 200) -> None:
    """`count` invented runs: ten statuses, two standards, two owners, one a day going back."""
    with db.connect(immediate=True) as conn:
        for i in range(count):
            status = STATUSES[i % len(STATUSES)]
            early = status in ("reading", "setup")
            company_id = None
            if not early:
                name = f"Contoh {i:03d} {'Logistik' if i % 4 == 0 else 'Trading'} Sdn. Bhd."
                company_id = conn.execute("INSERT INTO companies(name, created_at) VALUES (?, ?)",
                                          (name, stamp(i))).lastrowid
            run_id = conn.execute(
                "INSERT INTO runs(company_id, year, standard, level, status, owner_email, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (company_id, None if early else 2025, None if early else ("MFRS" if i % 3 else "MPERS"),
                 None if early else "Company", status, OWNER if i % 2 == 0 else OTHER, stamp(i), stamp(i))).lastrowid
            conn.execute("INSERT INTO run_setup(run_id) VALUES (?)", (run_id,))
            conn.execute(
                "INSERT INTO documents(run_id, filename, stored_path, sha256, size_bytes, page_count, uploaded_by, "
                "uploaded_at) VALUES (?, ?, ?, ?, 10, 3, ?, ?)",
                (run_id, f"Rekaan {i:03d} AFS 2025.pdf", f"runs/run-{run_id}/document.pdf", f"{i:064d}", OWNER,
                 stamp(i)))


@pytest.fixture
def signed_in(client):
    make_user(OWNER)
    make_user(OTHER)
    make_user(ADMIN, is_admin=True)
    assert login(client, OWNER).status_code == 200
    return client


def listed(client, **params) -> dict:
    response = client.get("/api/runs", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# Search, filters and paging -------------------------------------------------------

def test_two_hundred_runs_come_a_page_at_a_time_newest_first_and_quickly(signed_in):
    seed(200)
    started = time.perf_counter()
    first = listed(signed_in)
    last = listed(signed_in, page=7)
    filtered = listed(signed_in, q="logistik", status="filed", standard="MFRS")
    took = time.perf_counter() - started

    assert (first["total"], first["page"], first["per_page"], len(first["runs"])) == (200, 0, 25, 25)
    assert [r["filename"] for r in first["runs"][:2]] == ["Rekaan 000 AFS 2025.pdf", "Rekaan 001 AFS 2025.pdf"]
    stamps = [r["updated_at"] for r in first["runs"]]
    assert stamps == sorted(stamps, reverse=True)
    assert len(last["runs"]) == 25 and last["runs"][-1]["filename"] == "Rekaan 199 AFS 2025.pdf"
    assert filtered["total"] == len(filtered["runs"]) > 0
    assert took < 2.0, f"three list requests over 200 runs took {took:.2f}s"


def test_a_page_past_the_end_gives_the_last_page(signed_in):
    seed(30)
    page = listed(signed_in, page=9)
    assert (page["page"], page["total"], len(page["runs"])) == (1, 30, 5)
    assert listed(signed_in, q="no such thing") == {"runs": [], "total": 0, "page": 0, "per_page": 25}


def test_search_finds_a_company_or_a_file_name_in_any_case(signed_in):
    seed(40)
    by_company = listed(signed_in, q="contoh 004")
    assert [r["company"] for r in by_company["runs"]] == ["Contoh 004 Logistik Sdn. Bhd."]
    by_file = listed(signed_in, q="REKAAN 002")      # run 2 is at setup: it has a file and no company yet
    assert [(r["company"], r["filename"]) for r in by_file["runs"]] == [(None, "Rekaan 002 AFS 2025.pdf")]
    assert listed(signed_in, q="100%")["total"] == 0  # a % is a character to find, never a wildcard
    assert listed(signed_in, q="_")["total"] == 0


def test_filters_narrow_by_status_standard_date_and_owner_together(signed_in):
    seed(200)
    assert listed(signed_in, status="in_review")["total"] == 20
    working = listed(signed_in, status="working", per_page=100)
    assert working["total"] == 60
    assert {r["status"] for r in working["runs"]} == {"reading", "extracting", "correcting"}
    mpers = listed(signed_in, standard="MPERS", per_page=100)
    assert mpers["total"] > 0 and {r["standard"] for r in mpers["runs"]} == {"MPERS"}
    week = listed(signed_in, updated_since=stamp(6.5))
    assert week["total"] == 7
    local = (datetime.now(timezone.utc) - timedelta(days=6.5)).astimezone(timezone(timedelta(hours=8)))
    assert listed(signed_in, updated_since=local.isoformat())["total"] == 7   # another time zone, the same moment
    mine = listed(signed_in, mine="true", per_page=100)
    assert mine["total"] == 100 and {r["owner_email"] for r in mine["runs"]} == {OWNER}
    both = listed(signed_in, mine="true", status="filed", standard="MFRS", updated_since=stamp(60))
    assert all(r["owner_email"] == OWNER and r["status"] == "filed" and r["standard"] == "MFRS"
               for r in both["runs"]) and both["total"] == len(both["runs"]) > 0


@pytest.mark.parametrize("params, sentence", [
    ({"status": "nearly"}, "Choose a status from the list."),
    ({"standard": "IFRS"}, "Choose MFRS or MPERS."),
    ({"updated_since": "last week"}, "Give the earliest update time as a date and time."),
])
def test_a_filter_the_list_does_not_have_is_refused_in_one_sentence(signed_in, params, sentence):
    response = signed_in.get("/api/runs", params=params)
    assert response.status_code == 422 and response.json() == {"detail": sentence}


def test_the_run_list_needs_a_session(client):
    assert client.get("/api/runs").status_code == 401
    assert client.get("/api/runs/1/deletion").status_code == 401
    assert client.get("/api/admin/drafts").status_code == 401


# Deleting ---------------------------------------------------------------------------

def run_with_work(status: str = "in_review", owner: str = OWNER) -> int:
    """A run past setup with a figure, a note, a fill and files on disk."""
    run_id = make_run(owner=owner)
    with db.connect(immediate=True) as conn:
        refused = figures.save_figures(conn, run_id, [figures.FigureWrite(
            field("mfrs-company-sofp-cunoncu-v1", "SOFP-CuNonCu", 11), "CY", "Company", 500.0,
            [figures.Line("Trade receivables", 4, 500.0)])], figures.Actor("agent", "figures"))
        assert all(r["ok"] for r in refused), refused
        conn.execute("INSERT INTO notes(run_id, note_number, title, blocks_json, created_at, updated_at) "
                     "VALUES (?, '1', 'Corporate information', '{}', ?, ?)", (run_id, db.now(), db.now()))
        conn.execute("INSERT INTO fills(run_id, created_by, created_at, template_filename, template_sha256, "
                     "template_path) VALUES (?, ?, ?, 'template.xlsx', 'abc', 'x')", (run_id, owner, db.now()))
        conn.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))
    for folder in ("runs", "transcripts"):
        path = output_dir() / folder / f"run-{run_id}" / "fills"
        path.mkdir(parents=True)
        (path / "filled.xlsx").write_text("x", encoding="utf-8")
    return run_id


def test_the_owner_deletes_a_reviewed_run_with_its_rows_its_files_and_an_audit_row(signed_in):
    run_id = run_with_work()

    before = signed_in.get(f"/api/runs/{run_id}/deletion").json()
    response = signed_in.delete(f"/api/runs/{run_id}")

    assert before == {"allowed": True, "refused": None, "figures": 1, "notes": 1, "filled_workbook": True}
    assert response.status_code == 204
    assert not (output_dir() / "runs" / f"run-{run_id}").exists()
    assert not (output_dir() / "transcripts" / f"run-{run_id}").exists()
    assert signed_in.get(f"/api/runs/{run_id}").status_code == 404
    with db.connect() as conn:
        for table in ("figures", "figure_history", "notes", "fills", "run_statements", "check_results"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE run_id = ?", (run_id,)).fetchone()[0] == 0
        audit = auth_store.list_audit(conn)
    assert [(a["actor_email"], a["action"], a["target"]) for a in audit] == [(OWNER, "run_deleted", f"Run {run_id}")]
    assert audit[0]["detail"] == {"run_id": run_id, "company": "Test Sdn. Bhd.", "filename": None,
                                  "status": "in_review", "owner_email": OWNER}


def test_someone_who_is_not_the_owner_is_refused_by_the_server_and_an_admin_is_not(signed_in, client):
    run_id = run_with_work()
    assert login(client, OTHER).status_code == 200

    preview = client.get(f"/api/runs/{run_id}/deletion").json()
    refused = client.delete(f"/api/runs/{run_id}")

    sentence = "Only the run's owner or an admin can delete this run."
    assert preview["allowed"] is False and preview["refused"] == {"code": "owner", "detail": sentence}
    assert refused.status_code == 403 and refused.json() == {"detail": sentence}
    assert (output_dir() / "runs" / f"run-{run_id}").is_dir()
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == 1
        assert auth_store.list_audit(conn) == []

    assert login(client, ADMIN).status_code == 200
    assert client.delete(f"/api/runs/{run_id}").status_code == 204
    with db.connect() as conn:
        assert [a["actor_email"] for a in auth_store.list_audit(conn)] == [ADMIN]


@pytest.mark.parametrize("status", ["reading", "extracting", "correcting"])
def test_a_run_that_is_working_is_not_deleted_even_by_an_admin(signed_in, client, status):
    run_id = run_with_work(status)
    assert login(client, ADMIN).status_code == 200
    sentence = "This run is still working, so stop it or wait until it finishes, then delete it."
    assert client.get(f"/api/runs/{run_id}/deletion").json()["refused"] == {"code": "working", "detail": sentence}
    response = client.delete(f"/api/runs/{run_id}")
    assert response.status_code == 409 and response.json() == {"detail": sentence}
    assert (output_dir() / "runs" / f"run-{run_id}").is_dir()


@pytest.mark.parametrize("status", ["setup", "ready", "needs_answer", "in_review", "filed", "failed", "stopped"])
def test_a_run_in_any_status_that_is_not_working_can_be_deleted(signed_in, status):
    run_id = run_with_work(status)
    assert signed_in.delete(f"/api/runs/{run_id}").status_code == 204


# Abandoned drafts -------------------------------------------------------------------

def draft(days_ago: float, status: str = "setup", owner: str = OTHER) -> int:
    run_id = make_run(owner=owner)
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE runs SET status = ?, updated_at = ? WHERE id = ?", (status, stamp(days_ago), run_id))
    folder = output_dir() / "runs" / f"run-{run_id}"
    folder.mkdir(parents=True)
    (folder / "document.pdf").write_text("x", encoding="utf-8")
    return run_id


def test_an_admin_clears_drafts_older_than_the_chosen_age_and_nothing_else(signed_in, client):
    old, older = draft(31), draft(120)
    fresh, reviewed = draft(3), draft(200, "in_review")
    queued = draft(90)
    with db.connect(immediate=True) as conn:
        conn.execute("INSERT INTO jobs(kind, status, run_after, run_id, created_at) VALUES ('read', 'queued', ?, ?, ?)",
                     (db.now(), queued, db.now()))
    assert login(client, ADMIN).status_code == 200

    assert client.get("/api/admin/drafts", params={"older_than_days": 30}).json() == {"older_than_days": 30, "count": 2}
    assert client.get("/api/admin/drafts", params={"older_than_days": 90}).json()["count"] == 1
    cleared = client.post("/api/admin/drafts/clear", json={"older_than_days": 30})

    assert cleared.status_code == 200 and cleared.json() == {"older_than_days": 30, "cleared": 2}
    with db.connect() as conn:
        left = {r["id"] for r in conn.execute("SELECT id FROM runs")}
        audit = auth_store.list_audit(conn)
        runs_filter = auth_store.list_audit(conn, group="runs")
    assert [a["action"] for a in runs_filter] == ["drafts_cleared"]   # the audit screen's Runs filter shows it
    assert left == {fresh, reviewed, queued}
    assert not (output_dir() / "runs" / f"run-{old}").exists()
    assert not (output_dir() / "runs" / f"run-{older}").exists()
    assert (output_dir() / "runs" / f"run-{fresh}").is_dir()
    assert [(a["actor_email"], a["action"], a["target"]) for a in audit] == [(ADMIN, "drafts_cleared", "2 runs")]
    assert audit[0]["detail"]["older_than_days"] == 30
    assert [r["run_id"] for r in audit[0]["detail"]["runs"]] == [old, older]
    assert client.post("/api/admin/drafts/clear", json={"older_than_days": 30}).json()["cleared"] == 0
    with db.connect() as conn:
        assert len(auth_store.list_audit(conn)) == 1    # clearing nothing is not an audit row


def test_only_an_admin_clears_drafts_and_the_age_is_a_whole_number_of_days(signed_in, client):
    run_id = draft(400)
    assert signed_in.get("/api/admin/drafts").status_code == 403
    refused = signed_in.post("/api/admin/drafts/clear", json={"older_than_days": 30})
    assert refused.status_code == 403 and refused.json() == {"detail": "Only an admin can do this."}
    assert (output_dir() / "runs" / f"run-{run_id}").is_dir()
    assert login(client, ADMIN).status_code == 200
    for body in ({}, {"older_than_days": 0}, {"older_than_days": "30"}, {"older_than_days": 2.5}, None):
        response = client.post("/api/admin/drafts/clear", json=body)
        assert response.status_code == 422, body
        assert response.json() == {"detail": "Give the age as a whole number of days from 1 to 3650."}
    assert client.get("/api/admin/drafts", params={"older_than_days": 0}).status_code == 422
