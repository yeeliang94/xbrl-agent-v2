"""Attaching a filled workbook to a run and reading the comparison (docs/api-contract.md, Step 2).

The workbooks are made from the demo run's own figures by
`scripts/make_filled_workbook.py`, in the app's own template layout.
"""
from __future__ import annotations

import sqlite3
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from app import db
from app.figures import store
from app.scoring import attached
from app.utils.paths import output_dir
from tests.conftest import OWNER, login, make_run, make_user

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import make_filled_workbook  # noqa: E402
import seed_demo_run  # noqa: E402


@pytest.fixture
def demo(client):
    make_user(OWNER)
    assert login(client, OWNER).status_code == 200
    return seed_demo_run.seed(OWNER)


def _workbook(run_id: int, path: Path, **kwargs) -> list[dict]:
    with db.connect() as conn:
        return make_filled_workbook.build(conn, run_id, path, **kwargs)


def _attach(client, run_id: int, path: Path, name: str = "filled.xlsx"):
    with path.open("rb") as handle:
        return client.post(f"/api/runs/{run_id}/filled-workbook", files={"file": (name, handle)})


def _comparison(client, run_id: int) -> dict:
    response = client.get(f"/api/runs/{run_id}/comparison")
    assert response.status_code == 200, response.text
    return response.json()["comparison"]


def test_a_workbook_filled_from_the_runs_own_figures_scores_full_marks(client, demo, tmp_path):
    path = tmp_path / "same.xlsx"
    _workbook(demo, path)

    response = _attach(client, demo, path)

    assert response.status_code == 200, response.text
    workbook = response.json()["workbook"]
    assert workbook["layout"] == "template" and workbook["not_assessed"] == 0 and workbook["cells_read"] > 0
    comparison = _comparison(client, demo)
    overall = comparison["overall"]
    assert overall["person_filled"] > 0
    assert (overall["completeness"], overall["accuracy"], overall["complete_and_accurate"]) == (1.0, 1.0, 1.0)
    assert comparison["differences"] == [] and comparison["not_assessed"] == []
    assert comparison["totals"]["differences"] == []
    assert [s["statement"] for s in comparison["statements"]] == ["SOFP", "SOPL", "SOCF"]


def test_seeded_differences_score_exactly_what_was_seeded(client, demo, tmp_path):
    path = tmp_path / "seeded.xlsx"
    seeded = _workbook(demo, path, seed_differences=True)
    assert [s["kind"] for s in seeded] == list(make_filled_workbook.SEEDED)
    assert _attach(client, demo, path).status_code == 200

    comparison = _comparison(client, demo)

    counts = comparison["overall"]["counts"]
    assert {k: counts[k] for k in ("extra", "missing", "sign_only", "scale", "different", "zero_left_blank",
                                   "not_assessed")} == {
        "extra": 1, "missing": 1, "sign_only": 1, "scale": 1, "different": 1, "zero_left_blank": 0,
        "not_assessed": 0}
    found = {(d["kind"], d["concept_uuid"], d["period"], d["run_value"], d["person_value"])
             for d in comparison["differences"]}
    assert found == {(s["kind"], s["concept_uuid"], s["period"], s["run_value"], s["person_value"]) for s in seeded}
    overall = comparison["overall"]
    assert overall["person_filled"] == overall["agree"] + 4 + 0   # sign, scale, different, missing
    assert overall["both_filled"] == overall["person_filled"] - 1
    sign = next(d for d in comparison["differences"] if d["kind"] == "sign_only")
    assert sign["figure_id"] and sign["workbook_cell"] and sign["statement"] == "SOFP"
    assert sign["sheet"] and sign["row"] and sign["entity_scope"] == "Company" and sign["matrix_col"] is None
    assert comparison["totals"]["differences"], "a changed line shows in the totals above it, unscored"


def test_editing_a_figure_changes_the_comparison_on_the_next_read(client, demo, tmp_path):
    path = tmp_path / "seeded.xlsx"
    seeded = _workbook(demo, path, seed_differences=True)
    _attach(client, demo, path)
    different = next(s for s in seeded if s["kind"] == "different")
    before = _comparison(client, demo)["overall"]

    edited = client.post(f"/api/runs/{demo}/figures", json={
        "concept_uuid": different["concept_uuid"], "period": "CY", "entity_scope": "Company",
        "value": different["person_value"]})
    assert edited.status_code == 200, edited.text

    after = _comparison(client, demo)["overall"]
    assert after["counts"]["different"] == before["counts"]["different"] - 1
    assert after["agree"] == before["agree"] + 1


def test_one_workbook_per_run_replaced_and_removed(client, demo, tmp_path):
    first, second = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    _workbook(demo, first)
    _workbook(demo, second, seed_differences=True)
    assert client.get(f"/api/runs/{demo}/filled-workbook").json() == {"workbook": None}
    assert _attach(client, demo, first, "a.xlsx").status_code == 200
    assert _attach(client, demo, second, "b.xlsx").status_code == 200

    assert client.get(f"/api/runs/{demo}/filled-workbook").json()["workbook"]["filename"] == "b.xlsx"
    folder = output_dir() / "runs" / f"run-{demo}"
    assert len(list(folder.glob("*.xlsx"))) == 1

    assert client.delete(f"/api/runs/{demo}/filled-workbook").status_code == 204
    assert list(folder.glob("*.xlsx")) == []
    assert client.get(f"/api/runs/{demo}/comparison").status_code == 404
    assert client.delete(f"/api/runs/{demo}/filled-workbook").json() == {"detail": "This run has no filled workbook."}


def test_a_refused_upload_keeps_the_workbook_already_attached(client, demo, tmp_path):
    good = tmp_path / "good.xlsx"
    _workbook(demo, good)
    _attach(client, demo, good, "good.xlsx")
    junk = tmp_path / "junk.xlsx"
    junk.write_bytes(b"not a workbook")
    empty = tmp_path / "empty.xlsx"
    empty.write_bytes(b"")

    assert _attach(client, demo, junk).json() == {"detail": "This file could not be read as an Excel workbook."}
    assert _attach(client, demo, empty).json() == {"detail": "This file is empty."}
    response = _attach(client, demo, good, "good.csv")
    assert response.status_code == 422 and response.json() == {"detail": "Choose an .xlsx or .xlsm workbook."}

    assert client.get(f"/api/runs/{demo}/filled-workbook").json()["workbook"]["filename"] == "good.xlsx"
    assert len(list((output_dir() / "runs" / f"run-{demo}").glob("*.xlsx"))) == 1


def test_a_workbook_for_other_statements_is_refused(client, demo, tmp_path):
    other_run = make_run((("SOCIE", "Default"),))
    path = tmp_path / "socie-run.xlsx"
    _workbook(demo, path)
    response = _attach(client, other_run, path)
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Nothing in this workbook matches the run's templates")


def test_routes_need_a_session_and_a_real_run(client, tmp_path):
    assert client.get("/api/runs/1/comparison").status_code == 401
    make_user(OWNER)
    login(client, OWNER)
    assert client.get("/api/runs/999/comparison").json() == {"detail": "There is no such run."}
    assert client.get("/api/runs/999/filled-workbook").status_code == 404


def _figure_save_goes_through(run_id: int, concept_uuid: str) -> bool:
    """Save a figure on another connection, as the review screen does. False if it is held up."""
    saved = []

    def save():
        with db.connect(immediate=True) as conn:
            store.edit_by_person(conn, run_id, store.Actor("person", OWNER), concept_uuid=concept_uuid,
                                 period="CY", entity_scope="Company", value=1.0)
        saved.append(True)

    thread = threading.Thread(target=save)
    thread.start()
    thread.join(2)
    return saved == [True]


def _slow_read(monkeypatch, run_id: int, concept_uuid: str) -> list[bool]:
    """Make reading a workbook slow, and check a figure save goes through while it runs."""
    real, outcomes = attached.read_filled_workbook, []

    def slow(*args, **kwargs):
        outcomes.append(_figure_save_goes_through(run_id, concept_uuid))
        return real(*args, **kwargs)

    monkeypatch.setattr(attached, "read_filled_workbook", slow)
    return outcomes


def test_reading_an_upload_does_not_hold_up_figure_saves(client, demo, tmp_path, monkeypatch):
    path = tmp_path / "seeded.xlsx"
    concept = _workbook(demo, path, seed_differences=True)[0]["concept_uuid"]
    outcomes = _slow_read(monkeypatch, demo, concept)

    assert _attach(client, demo, path).status_code == 200
    assert outcomes == [True]


def test_a_stale_read_is_refreshed_outside_the_write_lock(client, demo, tmp_path, monkeypatch):
    path = tmp_path / "seeded.xlsx"
    concept = _workbook(demo, path, seed_differences=True)[0]["concept_uuid"]
    _attach(client, demo, path)
    with db.connect() as conn:
        read_for = conn.execute("SELECT read_for FROM filled_workbooks WHERE run_id = ?", (demo,)).fetchone()[0]
        conn.execute("UPDATE filled_workbooks SET read_for = '[]' WHERE run_id = ?", (demo,))
        conn.execute("DELETE FROM filled_workbook_cells WHERE run_id = ?", (demo,))
    outcomes = _slow_read(monkeypatch, demo, concept)

    comparison = _comparison(client, demo)

    assert outcomes == [True]
    assert comparison["workbook"]["cells_read"] > 0 and comparison["overall"]["person_filled"] > 0
    with db.connect() as conn:
        assert conn.execute("SELECT read_for FROM filled_workbooks WHERE run_id = ?", (demo,)).fetchone()[0] == read_for
    _comparison(client, demo)
    assert outcomes == [True], "a fresh read is not read again"


@contextmanager
def _failing_commit(*, immediate: bool = False):
    with _REAL_CONNECT(immediate=immediate) as conn:
        yield conn
        if immediate:
            raise sqlite3.OperationalError("disk I/O error")


_REAL_CONNECT = db.connect


def test_the_old_file_is_kept_until_the_change_commits(client, demo, tmp_path, monkeypatch):
    first, second = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    _workbook(demo, first)
    _workbook(demo, second, seed_differences=True)
    assert _attach(client, demo, first, "a.xlsx").status_code == 200
    folder = output_dir() / "runs" / f"run-{demo}"
    kept = list(folder.glob("*.xlsx"))

    monkeypatch.setattr(db, "connect", _failing_commit)
    with pytest.raises(sqlite3.OperationalError):
        attached.attach(demo, second.read_bytes(), filename="b.xlsx", uploaded_by=OWNER)
    with pytest.raises(sqlite3.OperationalError):
        attached.remove(demo)
    monkeypatch.setattr(db, "connect", _REAL_CONNECT)

    assert list(folder.glob("*.xlsx")) == kept, "the old file stays and the unsaved new one is gone"
    assert client.get(f"/api/runs/{demo}/filled-workbook").json()["workbook"]["filename"] == "a.xlsx"
    assert _comparison(client, demo)["overall"]["accuracy"] == 1.0
