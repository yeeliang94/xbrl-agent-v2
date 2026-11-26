"""A new run from an uploaded PDF, and its document (docs/api-contract.md, Step 3)."""
from __future__ import annotations

import hashlib
import io
import sqlite3
import zipfile

import pymupdf
import pytest

from app import db
from app.documents import pdf_check, routes as document_routes
from app.utils.paths import output_dir
from tests import pdf_samples
from tests.conftest import OWNER, login, make_run, make_user


@pytest.fixture
def signed_in(client):
    make_user(OWNER)
    assert login(client, OWNER).status_code == 200
    return client


def _upload(client, data: bytes, name: str = "report.pdf"):
    return client.post("/api/runs", files={"file": (name, io.BytesIO(data), "application/pdf")})


def test_an_upload_makes_a_reading_run_with_one_row_per_page(signed_in):
    data = pdf_samples.build("text", "scan", "stamped", "rotated", "ocr")

    response = _upload(signed_in, data, "Doc 1.pdf")

    assert response.status_code == 200, response.text
    run, document = response.json()["run"], response.json()["document"]
    assert run["status"] == "reading" and run["owner_email"] == OWNER and run["filename"] == "Doc 1.pdf"
    assert (run["company"], run["year"], run["standard"], run["level"]) == (None, None, None, None)
    assert document["page_count"] == 5 and document["scanned_pages"] == 2
    assert document["sha256"] == hashlib.sha256(data).hexdigest() and document["size_bytes"] == len(data)
    pages = document["pages"]
    assert [p["page"] for p in pages] == [1, 2, 3, 4, 5]
    assert [p["has_text_layer"] for p in pages] == [True, False, False, True, True]
    assert pages[0] == {"page": 1, "width": 595.0, "height": 842.0, "rotation": 0, "has_text_layer": True}
    assert (pages[3]["rotation"], pages[3]["width"], pages[3]["height"]) == (90, 842.0, 595.0)
    assert signed_in.get(f"/api/runs/{run['id']}/document").json() == {"document": document}


def test_the_pdf_is_kept_in_the_runs_folder(signed_in):
    data = pdf_samples.build("text")
    run_id = _upload(signed_in, data).json()["run"]["id"]

    with db.connect() as conn:
        stored = conn.execute("SELECT stored_path FROM documents WHERE run_id = ?", (run_id,)).fetchone()[0]
    assert stored.startswith(f"runs/run-{run_id}/")
    assert (output_dir() / stored).read_bytes() == data


def test_a_stamp_on_every_scanned_page_does_not_make_them_text(signed_in):
    document = _upload(signed_in, pdf_samples.build(*["stamped"] * 4)).json()["document"]
    assert document["scanned_pages"] == 4


def test_a_reading_run_is_listed_and_has_no_statements_or_checks(signed_in):
    run_id = _upload(signed_in, pdf_samples.build("scan")).json()["run"]["id"]

    listed = signed_in.get("/api/runs").json()["runs"]
    assert [(r["id"], r["status"], r["company"], r["filename"]) for r in listed] == [
        (run_id, "reading", None, "report.pdf")]
    assert signed_in.get(f"/api/runs/{run_id}/statements/SOFP").status_code == 404
    assert signed_in.get(f"/api/runs/{run_id}/checks").json() == {"checks": []}


def test_the_upload_is_in_the_activity_feed_and_the_read_stage_waits(signed_in):
    run_id = _upload(signed_in, pdf_samples.build("text", "scan")).json()["run"]["id"]

    events = signed_in.get(f"/api/runs/{run_id}/events").json()["events"]
    assert [e["message"] for e in events] == ["The PDF is stored: 2 pages, 1 of them scanned."]
    with db.connect() as conn:
        stages = conn.execute("SELECT name, status FROM stages WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
    assert [tuple(s) for s in stages] == [("upload", "done"), ("read", "waiting")]


@pytest.mark.parametrize("data, detail", [
    (b"", "This file is empty."),
    (b"Revenue,100\nCost of sales,-60\n",
     "report.pdf is not a PDF, a Word document (.docx) or an Excel workbook (.xlsx)."),
    (b"%PDF-1.7\n" + b"\x00garbage" * 50, "This file could not be read as a PDF."),
    (pdf_samples.build("text", password="secret"),
     "report.pdf is protected by a password. Remove the password and upload it again."),
])
def test_anything_but_a_readable_pdf_is_refused_and_no_run_is_made(signed_in, data, detail):
    response = _upload(signed_in, data)
    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert signed_in.get("/api/runs").json()["runs"] == []


def _pdf(sizes: list[tuple[float, float]]) -> bytes:
    doc = pymupdf.open()
    for width, height in sizes:
        doc.new_page(width=width, height=height)
    data = doc.tobytes()
    doc.close()
    return data


def test_a_page_larger_than_a0_is_refused_before_anything_is_drawn(signed_in):
    response = _upload(signed_in, _pdf([(595, 842), (14_000, 14_000)]))
    assert response.status_code == 422
    assert response.json() == {"detail": "Page 2 is larger than A0 paper, so upload a PDF with ordinary page sizes."}
    assert pdf_check.inspect_pdf(_pdf([(3370, 2384)]))[0].width == 3370      # A0 itself, turned, is fine


def test_a_pdf_over_the_page_limit_is_refused(signed_in):
    response = _upload(signed_in, _pdf([(595, 842)] * (pdf_check.MAX_PAGES + 1)))
    assert response.status_code == 422
    assert response.json() == {"detail": "This PDF has more than 500 pages, so upload the financial statements on "
                                         "their own."}
    assert signed_in.get("/api/runs").json()["runs"] == []


def test_uploading_and_reading_a_document_need_a_session(client):
    assert _upload(client, pdf_samples.build("text")).status_code == 401
    assert client.get("/api/runs/1/document").status_code == 401


def test_a_run_without_a_document_says_so(signed_in):
    run_id = make_run()
    assert signed_in.get(f"/api/runs/{run_id}/document").json() == {"detail": "This run has no document."}
    assert signed_in.get("/api/runs/999/document").json() == {"detail": "There is no such run."}


def test_text_layer_rule_page_by_page():
    pages = pdf_check.inspect_pdf(pdf_samples.build("scan", "text", "stamped", "ocr"))
    assert [p.has_text_layer for p in pages] == [False, True, False, True]


# An older database ---------------------------------------------------------

_OLD_RUNS = """CREATE TABLE runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    year        INTEGER,
    standard    TEXT NOT NULL CHECK (standard IN ('MFRS', 'MPERS')),
    level       TEXT NOT NULL CHECK (level IN ('Company', 'Group')),
    status      TEXT NOT NULL DEFAULT 'reading',
    owner_email TEXT NOT NULL REFERENCES users(email),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE run_setup (
    run_id            INTEGER PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    first_statements  INTEGER NOT NULL DEFAULT 0,
    unit              TEXT NOT NULL DEFAULT 'RM'
);"""


def test_a_database_made_before_step_3_keeps_its_runs_and_accepts_a_reading_run(tmp_path, monkeypatch):
    monkeypatch.setenv("XBRL_OUTPUT_DIR", str(tmp_path / "old"))
    path = db.db_path()
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE users (email TEXT PRIMARY KEY, created_at TEXT NOT NULL);"
            "CREATE TABLE companies (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, "
            "created_at TEXT NOT NULL);" + _OLD_RUNS +
            "INSERT INTO users VALUES ('ana@firm.com', 't');"
            "INSERT INTO companies(name, created_at) VALUES ('Acme', 't');"
            "INSERT INTO runs(company_id, year, standard, level, status, owner_email, created_at, updated_at) "
            "VALUES (1, 2025, 'MFRS', 'Company', 'setup', 'ana@firm.com', 't', 't');"
            "INSERT INTO run_setup(run_id) VALUES (1);")

    db.init_db()
    db.init_db()   # a second start-up changes nothing

    with db.connect() as conn:
        notnull = {r["name"]: r["notnull"] for r in conn.execute("PRAGMA table_info(runs)")}
        assert (notnull["company_id"], notnull["standard"], notnull["level"]) == (0, 0, 0)
        assert tuple(conn.execute("SELECT id, company_id, year, standard FROM runs").fetchone()) == (
            1, 1, 2025, "MFRS")
        conn.execute("INSERT INTO runs(status, owner_email, created_at, updated_at) "
                     "VALUES ('reading', 'ana@firm.com', 't', 't')")
        conn.execute("INSERT INTO runs(status, owner_email, created_at, updated_at) "
                     "VALUES ('ready', 'ana@firm.com', 't', 't')")   # step 3c's status
        with pytest.raises(sqlite3.IntegrityError):   # sign-off was dropped
            conn.execute("INSERT INTO runs(status, owner_email, created_at, updated_at) "
                         "VALUES ('reviewed', 'ana@firm.com', 't', 't')")
        with pytest.raises(sqlite3.IntegrityError):   # run_setup still points at runs
            conn.execute("INSERT INTO run_setup(run_id) VALUES (99)")
