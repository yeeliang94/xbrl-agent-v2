"""Confirming a run's setup (docs/api-contract.md, "Confirming the setup")."""
from __future__ import annotations

import copy
import io
import json

import pymupdf
import pytest

from app import db
from app.reading import store as reading
from tests import pdf_samples, reading_fakes as fakes
from tests.conftest import OWNER, login, make_user

GOOD = {
    "company": "Test Sdn. Bhd.", "year_end": "2021-12-31", "standard": "MFRS", "level": "Company", "unit": "RM",
    "statements": [
        {"statement": "SOFP", "layout": "CuNonCu", "included": True, "pages": [2]},
        {"statement": "SOPL", "layout": "Function", "included": True, "pages": [2]},
        {"statement": "SOCI", "layout": "NotPrepared", "included": False, "pages": []},
        {"statement": "SOCF", "layout": "Indirect", "included": True, "pages": [3, 2]},
        {"statement": "SOCIE", "layout": "Default", "included": False, "pages": []},
    ],
    "notes_included": True,
    "notes": [{"number": "1", "title": "Plant and equipment", "first_page": 3, "last_page": 3},
              {"number": "", "title": "Unnumbered note", "first_page": 4, "last_page": 4}],
}


@pytest.fixture
def signed_in(client):
    make_user(OWNER)
    assert login(client, OWNER).status_code == 200
    return client


def mapped_run(client, *, status: str = "done") -> int:
    """An uploaded four-page run whose reading finished (or is in the given stage state)."""
    response = client.post("/api/runs", files={"file": ("t.pdf", io.BytesIO(fakes.build_pdf()), "application/pdf")})
    run_id = response.json()["run"]["id"]
    with db.connect(immediate=True) as conn:
        reading.stage_working(conn, run_id)
        if status == "done":
            reading.save_map(conn, run_id, fakes.good_map(), [])
            reading.stage_done(conn, run_id)
        elif status == "failed":
            reading.stage_failed(conn, run_id, "The model service did not answer.")
    return run_id


def body(**changes) -> dict:
    out = copy.deepcopy(GOOD)
    out.update(changes)
    return out


def test_a_good_setup_is_saved_and_the_run_waits_for_extraction(signed_in):
    run_id = mapped_run(signed_in)
    response = signed_in.post(f"/api/runs/{run_id}/setup", json=GOOD)
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["company"] == {"id": out["company"]["id"], "name": "Test Sdn. Bhd.", "existing": False}
    run = out["run"]
    assert (run["company"], run["year"], run["standard"], run["level"], run["status"]) == (
        "Test Sdn. Bhd.", 2021, "MFRS", "Company", "ready")

    with db.connect() as conn:
        setup = conn.execute("SELECT unit, year_end, notes_included FROM run_setup WHERE run_id = ?",
                             (run_id,)).fetchone()
        assert tuple(setup) == ("RM", "2021-12-31", 1)
        statements = {r["statement"]: (r["variant"], r["included"], json.loads(r["pages_json"])) for r in
                      conn.execute("SELECT * FROM run_statements WHERE run_id = ?", (run_id,))}
        assert statements == {"SOFP": ("CuNonCu", 1, [2]), "SOPL": ("Function", 1, [2]),
                              "SOCI": ("NotPrepared", 0, []), "SOCF": ("Indirect", 1, [2, 3]),
                              "SOCIE": ("Default", 0, [])}
        notes = [tuple(r) for r in conn.execute("SELECT number, title, first_page, last_page FROM run_notes "
                                                "WHERE run_id = ? ORDER BY position", (run_id,))]
        assert notes == [("1", "Plant and equipment", 3, 3), ("", "Unnumbered note", 4, 4)]
        stage = conn.execute("SELECT status FROM stages WHERE run_id = ? AND name = 'setup'", (run_id,)).fetchone()
        assert stage["status"] == "done"
        messages = [r[0] for r in conn.execute("SELECT message FROM events WHERE run_id = ? ORDER BY id", (run_id,))]
        assert messages[-4:] == ["Setup confirmed.",
                                 "Extraction is queued: the statement of financial position, statement of profit "
                                 "or loss and statement of cash flows.", "The notes agent is queued.",
                                 "The Reader found no directors' report, statement by directors or auditors' "
                                 "report, so the reports agent does not run."]
        # Extraction and the notes agent are queued in the same transaction, each linked to its own stage.
        jobs = [tuple(r) for r in conn.execute(
            "SELECT j.kind, j.max_attempts, s.name, s.status FROM jobs j JOIN stages s ON s.id = j.stage_id "
            "WHERE j.run_id = ? AND j.kind IN ('extract', 'notes') ORDER BY j.id", (run_id,))]
        assert jobs == [("extract", 1, "extract", "waiting"), ("notes", 1, "notes", "waiting")]
        # Statements switched off have no template, so nothing is checked for them.
        from app.catalog.lookup import run_family
        family = run_family(conn, run_id)
        assert set(family.template_ids) == {"SOFP", "SOPL", "SOCF"}
        assert conn.execute("SELECT COUNT(*) FROM check_results WHERE run_id = ?", (run_id,)).fetchone()[0] > 0

    # The statement routes now answer for the run.
    assert signed_in.get(f"/api/runs/{run_id}/statements/SOFP").status_code == 200
    # It cannot be confirmed twice.
    again = signed_in.post(f"/api/runs/{run_id}/setup", json=GOOD)
    assert again.status_code == 409 and again.json() == {"detail": "This run's setup is already confirmed."}


def test_the_company_is_matched_whatever_its_case_spacing_or_dots(signed_in):
    first = mapped_run(signed_in)
    second = mapped_run(signed_in)
    one = signed_in.post(f"/api/runs/{first}/setup", json=body(company="Seri Maju Trading Sdn. Bhd.")).json()
    two = signed_in.post(f"/api/runs/{second}/setup", json=body(company="  SERI MAJU  trading sdn bhd ")).json()
    assert one["company"]["existing"] is False
    assert two["company"] == {"id": one["company"]["id"], "name": "Seri Maju Trading Sdn. Bhd.", "existing": True}
    assert two["run"]["company"] == "Seri Maju Trading Sdn. Bhd."
    third = mapped_run(signed_in)
    other = signed_in.post(f"/api/runs/{third}/setup", json=body(company="Seri Maju Holdings Berhad")).json()
    assert other["company"]["existing"] is False and other["company"]["id"] != one["company"]["id"]


def _statement(statement: str, **changes) -> list[dict]:
    out = copy.deepcopy(GOOD["statements"])
    for item in out:
        if item["statement"] == statement:
            item.update(changes)
    return out


@pytest.mark.parametrize("changes, sentence", [
    ({"company": "  "}, "Enter the company's name."),
    ({"company": "A" * 201}, "The company's name is too long."),
    ({"year_end": "31 December 2021"}, "Enter the year end as a date."),
    ({"year_end": "2021-02-30"}, "Enter the year end as a date."),
    ({"standard": "IFRS"}, "Choose MFRS or MPERS."),
    ({"level": "Branch"}, "Choose Company or Group."),
    ({"unit": "USD"}, "Choose whether amounts are in RM, RM thousands or RM millions."),
    ({"statements": GOOD["statements"][:4]}, "Give each of the five statements once."),
    ({"statements": _statement("SOCIE", layout="SoRE", included=True)},
     "The Retained earnings layout of changes in equity does not exist for MFRS filings, so choose another layout."),
    ({"statements": _statement("SOFP", layout="Function")},
     "The By function layout of financial position does not exist for MFRS filings, so choose another layout."),
    ({"statements": _statement("SOCI", included=True)},
     "Comprehensive income is marked not printed, so switch it off or choose a layout."),
    ({"statements": [{**s, "included": False} for s in GOOD["statements"]]}, "Switch on at least one statement."),
    ({"statements": _statement("SOFP", pages=[])}, "Give the page financial position is printed on, or switch it off."),
    ({"statements": _statement("SOFP", pages=[5])}, "The pages of financial position must be within the document's 4 pages."),
    ({"statements": _statement("SOFP", pages=["2"])},
     "Give the pages of financial position as up to 10 page numbers."),
    ({"notes": [{"number": "1", "title": "", "first_page": 3, "last_page": 3}]}, "Each note needs a title."),
    ({"notes": [{"number": "1", "title": "T" * 201, "first_page": 3, "last_page": 3}]},
     "Keep each note title to 200 characters or fewer."),
    ({"notes": [GOOD["notes"][0], GOOD["notes"][0]]}, "Note 1 is listed twice."),
    ({"notes": [{"number": "1", "title": "Plant", "first_page": 3, "last_page": 9}]},
     "Note 1's pages must be within the document's 4 pages, first page first."),
    ({"notes": [{"number": "1", "title": "Plant", "first_page": 3, "last_page": 2}]},
     "Note 1's pages must be within the document's 4 pages, first page first."),
])
def test_a_wrong_setup_is_refused_with_one_sentence_and_nothing_is_saved(signed_in, changes, sentence):
    run_id = mapped_run(signed_in)
    response = signed_in.post(f"/api/runs/{run_id}/setup", json=body(**changes))
    assert response.status_code == 422
    assert response.json() == {"detail": sentence}
    with db.connect() as conn:
        assert conn.execute("SELECT status, company_id FROM runs WHERE id = ?", (run_id,)).fetchone()[:] == (
            "setup", None)
        assert conn.execute("SELECT COUNT(*) FROM run_statements WHERE run_id = ?", (run_id,)).fetchone()[0] == 0


def test_mpers_may_choose_the_retained_earnings_statement(signed_in):
    run_id = mapped_run(signed_in)
    response = signed_in.post(f"/api/runs/{run_id}/setup", json=body(
        standard="MPERS", statements=_statement("SOCIE", layout="SoRE", included=True, pages=[3])))
    assert response.status_code == 200, response.text
    with db.connect() as conn:
        assert conn.execute("SELECT variant FROM run_statements WHERE run_id = ? AND statement = 'SOCIE'",
                            (run_id,)).fetchone()[0] == "SoRE"


def test_setup_waits_for_reading_and_a_failed_reading(signed_in):
    working = mapped_run(signed_in, status="working")
    refused = signed_in.post(f"/api/runs/{working}/setup", json=GOOD)
    assert refused.status_code == 409
    assert refused.json() == {"detail": "Reading is not finished, so the setup cannot be confirmed yet."}
    failed = mapped_run(signed_in, status="failed")
    refused = signed_in.post(f"/api/runs/{failed}/setup", json=GOOD)
    assert refused.status_code == 409
    assert refused.json() == {"detail": "Reading failed, so try again before confirming the setup."}
    assert signed_in.post("/api/runs/999/setup", json=GOOD).json() == {"detail": "There is no such run."}


def test_confirming_a_setup_needs_a_session(client):
    assert client.post("/api/runs/1/setup", json=GOOD).status_code == 401


def test_a_page_picture_is_drawn_upright_by_the_map_rotation(signed_in):
    doc = pymupdf.open()
    doc.new_page(width=400, height=200)   # a landscape page whose text reads sideways
    pdf_samples.add_text_page(doc)
    data = doc.tobytes()
    doc.close()
    run_id = signed_in.post("/api/runs", files={"file": ("t.pdf", io.BytesIO(data), "application/pdf")}
                            ).json()["run"]["id"]
    before = pymupdf.Pixmap(signed_in.get(f"/api/runs/{run_id}/pages/1/image").content)
    assert before.width > before.height
    with db.connect(immediate=True) as conn:
        content = fakes.good_page(1)
        content["rotation"] = 90
        reading.save_page(conn, run_id, 1, content, None)
    after = pymupdf.Pixmap(signed_in.get(f"/api/runs/{run_id}/pages/1/image").content)
    assert (after.width, after.height) == (before.height, before.width)


def test_a_reading_run_shows_its_file_name_and_no_company(signed_in):
    run_id = mapped_run(signed_in, status="working")
    row = next(r for r in signed_in.get("/api/runs").json()["runs"] if r["id"] == run_id)
    assert (row["company"], row["filename"], row["status"]) == (None, "t.pdf", "reading")
