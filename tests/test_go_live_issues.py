"""Go-live A2: report an issue, and the admin's list of issues."""
from __future__ import annotations

import io
import zipfile

import pytest

from app import db
from app.issues import store
from app.utils.paths import output_dir
from tests.conftest import login, make_run, make_user

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
ADMIN = "mira@samplefirm.example"
PERSON = "odell@samplefirm.example"


@pytest.fixture
def people(client):
    make_user(ADMIN, is_admin=True, name="Mira Quillfeather")
    make_user(PERSON, name="Odell Brambleworth")
    return client


def _as(client, email):
    client.cookies.clear()
    assert login(client, email).status_code == 200
    return client


def _report(client, text="The balance sheet total does not match the report.", run_id=None, file=None):
    data = {"text": text}
    if run_id is not None:
        data["run_id"] = str(run_id)
    files = {"file": file} if file else None
    return client.post("/api/issues", data=data, files=files)


def _audit(client):
    return [(e["action"], e["target"]) for e in client.get("/api/admin/audit", params={"group": "issues"}).json()["events"]]


def test_a_report_from_a_run_with_a_screenshot_reaches_the_admin_who_downloads_traces_and_closes_it(people):
    run_id = make_run(owner=PERSON)
    sent = _report(_as(people, PERSON), run_id=run_id, file=("balance sheet.png", io.BytesIO(PNG), "image/png"))
    assert sent.status_code == 200
    issue = sent.json()["issue"]
    assert issue["status"] == "open" and issue["run_id"] == run_id and issue["run_label"] == "Test Sdn. Bhd., FY2025"
    assert issue["file_name"] == "balance sheet.png" and issue["reporter_name"] == "Odell Brambleworth"
    assert "file_path" not in issue

    admin = _as(people, ADMIN)
    listed = admin.get("/api/issues", params={"status": "open"}).json()["issues"]
    assert [i["id"] for i in listed] == [issue["id"]]

    picture = admin.get(f"/api/issues/{issue['id']}/file")
    assert picture.status_code == 200 and picture.content == PNG
    assert "attachment" in picture.headers["content-disposition"]

    traces = admin.get(f"/api/issues/{issue['id']}/traces")
    assert traces.status_code == 200
    with zipfile.ZipFile(io.BytesIO(traces.content)) as zf:
        assert "run.json" in zf.namelist() and "manifest.json" in zf.namelist()

    closed = admin.patch(f"/api/issues/{issue['id']}", json={"status": "closed", "note": "Fixed with a guidance line."})
    assert closed.status_code == 200
    assert closed.json()["issue"]["status"] == "closed" and closed.json()["issue"]["note"] == "Fixed with a guidance line."
    assert admin.get("/api/issues", params={"status": "open"}).json()["issues"] == []
    assert len(admin.get("/api/issues", params={"status": "closed"}).json()["issues"]) == 1

    number = str(issue["id"])
    assert _audit(admin) == [("issue_closed", number), ("issue_updated", number), ("issue_traces_downloaded", number)]


def test_an_issue_can_be_reported_with_no_run_and_no_screenshot(people):
    sent = _report(_as(people, PERSON), text="  I could not download the filled workbook.  ")
    issue = sent.json()["issue"]
    assert issue["text"] == "I could not download the filled workbook."
    assert issue["run_id"] is None and issue["run_label"] == "" and issue["file_name"] is None
    admin = _as(people, ADMIN)
    assert admin.get(f"/api/issues/{issue['id']}/traces").status_code == 404
    assert admin.get(f"/api/issues/{issue['id']}/file").status_code == 404


def test_a_report_is_refused_with_a_sentence_when_it_cannot_be_kept(people):
    person = _as(people, PERSON)
    assert _report(person, text="   ").json()["detail"] == "Say what went wrong."
    assert _report(person, run_id=999).status_code == 404
    not_a_picture = _report(person, file=("notes.png", io.BytesIO(b"<html>hello</html>"), "image/png"))
    assert not_a_picture.status_code == 422
    assert not_a_picture.json()["detail"] == "Attach a picture: a PNG, JPEG, GIF or WebP file."
    too_big = _report(person, file=("big.png", io.BytesIO(PNG + b"\x00" * (10 * 1024 * 1024)), "image/png"))
    assert too_big.status_code == 413
    assert _as(people, ADMIN).get("/api/issues").json()["issues"] == []
    assert not (output_dir() / "issues").exists()


def test_the_screenshot_is_stored_under_a_name_the_server_chose(people):
    sent = _report(_as(people, PERSON), file=("../../escape.png", io.BytesIO(PNG), "image/png")).json()["issue"]
    assert sent["file_name"] == "escape.png"
    folder = output_dir() / "issues" / f"issue-{sent['id']}"
    stored = [p.name for p in folder.iterdir()]
    assert len(stored) == 1 and stored[0].startswith("screenshot-") and stored[0].endswith(".png")


def test_a_note_reopening_and_deleting_are_each_in_the_audit_log(people):
    issue = _report(_as(people, PERSON), file=("a.png", io.BytesIO(PNG), "image/png")).json()["issue"]
    number = issue["id"]
    admin = _as(people, ADMIN)
    assert admin.patch(f"/api/issues/{number}", json={"note": "Checking the traces."}).status_code == 200
    assert admin.patch(f"/api/issues/{number}", json={"note": "Checking the traces."}).status_code == 200   # no change
    assert admin.patch(f"/api/issues/{number}", json={"status": "closed"}).status_code == 200
    assert admin.patch(f"/api/issues/{number}", json={"status": "open"}).json()["issue"]["status"] == "open"
    assert admin.patch(f"/api/issues/{number}", json={"status": "parked"}).status_code == 422

    assert admin.delete(f"/api/issues/{number}").status_code == 204
    assert admin.get("/api/issues").json()["issues"] == []
    assert not (output_dir() / "issues" / f"issue-{number}").exists()
    assert admin.delete(f"/api/issues/{number}").status_code == 404
    assert admin.patch(f"/api/issues/{number}", json={"note": "x"}).status_code == 404

    assert _audit(admin) == [("issue_deleted", str(number)), ("issue_reopened", str(number)),
                             ("issue_closed", str(number)), ("issue_updated", str(number))]


def test_an_issue_outlives_its_run_and_keeps_the_runs_name(people):
    run_id = make_run(owner=PERSON)
    issue = _report(_as(people, PERSON), run_id=run_id).json()["issue"]
    with db.connect() as conn:
        conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        kept = store.get(conn, issue["id"])
    assert kept["run_id"] is None and kept["run_label"] == "Test Sdn. Bhd., FY2025"


def test_reporting_needs_a_session(client):
    assert client.post("/api/issues", data={"text": "hello"}).status_code == 401
