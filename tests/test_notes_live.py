"""Live: place the notes of Doc 1 to 3 with the notes agent and score the placements against the
answer keys' `notes` sections. Costs money; left out of the default run. Tell the owner before it runs.

    LIVE_OUT=/some/temp/folder venv/bin/python -m pytest tests/test_notes_live.py -m live -s
    LIVE_DOCS="Doc_3" ...                # only the documents whose names contain these
    LIVE_REPEAT=1 ...                    # runs per document (default 2, as step 6 plans)
    LIVE_READING=/folder/of/the/reading/live/test ...   # reuse its saved readings, so nothing is read again

Each document is read first (or its saved reading from `tests/test_reading_live.py`, under
LIVE_READING/<Doc_1|Doc_2|Doc_3>, is copied). The setup is confirmed as the Reader suggested, with the
Reader's notes list, notes included, and the balance sheet as the one statement (setup needs one). The
worker then runs the notes job only: the figures job is left waiting, so this measures the notes alone.
The run's folder goes under LIVE_OUT (a temporary folder when it is not set), never into the repository.
A summary is printed and written to LIVE_OUT/notes-<name>-<n>.json before the score is checked.

Score: "same field" only, wording not compared (app/scoring/notes.py). The bar is v1's average on the
same keys (scripts/score_notes_v1.py, 23 November 2026; docs/answer-keys.md). One run varies, so a single
run can dip below its bar; look at the notes that are not right before changing the agent. The answer
keys are not committed: a document whose key or PDF is missing is skipped. Doc 4 is set aside.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest
from dotenv import dotenv_values

from app import db
from app.catalog import loader
from app.documents import store as documents
from app.documents.pdf_check import inspect_pdf
from app.jobs import handlers  # noqa: F401 - registers every stage's job handler
from app.jobs import worker
from app.models import usage as model_usage
from app.reading import job as reading_job, store as reading
from app.runs import setup
from app.scoring import notes as notes_score
from app.utils.paths import PROJECT_ROOT
from tests.conftest import OWNER, make_user

pytestmark = pytest.mark.live

V1_DATA = Path("/Users/user/Desktop/xbrl-agent/data")
KEYS = PROJECT_ROOT / "test-data" / "answer-keys"
DOCUMENTS = {
    # name: (PDF, v1's average "same field" score over its runs)
    "Doc_1": (V1_DATA / "Doc 1.pdf", 0.923),
    "Doc_2": (V1_DATA / "Doc 2.pdf", 0.893),
    "Doc_3": (V1_DATA / "Doc 3.pdf", 0.820),
}
NOTES_JOB = "notes"      # the job kind and stage name of the notes agent (step 6d)
WAITS = ("extract",)     # job kinds left waiting while the notes job runs


def _chosen() -> list[tuple[str, int]]:
    wanted = [w.strip() for w in os.environ.get("LIVE_DOCS", "").split(",") if w.strip()]
    names = [n for n in DOCUMENTS if not wanted or any(w in n for w in wanted)]
    repeat = int(os.environ.get("LIVE_REPEAT", "2"))
    return [(name, n) for name in names for n in range(1, repeat + 1)]


def _setup_body(suggested: dict, doc_map: dict, key: dict) -> dict:
    """The setup as the Reader suggested it, with its notes list and the balance sheet only. Where the
    Reader left a value open, the key's value stands in, as a person would choose it on the setup screen."""
    def value(name: str, allowed=None):
        found = (suggested.get(name) or {}).get("value")
        return found if found and (allowed is None or found in allowed) else fallback[name]

    fallback = {"company": key["company"], "year_end": key["year_end"], "standard": key["standard"],
                "level": key["level"], "unit": "RM'000" if "thousand" in key["unit"].lower() else "RM"}
    standard = value("standard", ("MFRS", "MPERS"))
    statements = []
    for st in suggested["statements"]:
        sofp = st["statement"] == "SOFP"
        layout = "CuNonCu" if sofp else (st["layout"] or st["layouts"][standard][0]["value"])
        pages = (st["pages"] or key["statements"]["SOFP"]["pages"]) if sofp else st["pages"]
        statements.append({"statement": st["statement"], "layout": layout, "included": sofp, "pages": pages})
    return {"company": value("company"), "year_end": value("year_end"), "standard": standard,
            "level": value("level", ("Company", "Group")), "unit": value("unit", ("RM", "RM'000")),
            "statements": statements, "notes_included": True,
            "notes": [{k: n[k] for k in ("number", "title", "first_page", "last_page")} for n in doc_map["notes"]]}


async def _read(source: Path) -> int:
    make_user(OWNER)
    data = source.read_bytes()
    with db.connect(immediate=True) as conn:
        run_id = documents.create_run_from_pdf(conn, data, inspect_pdf(data), filename=source.name, owner_email=OWNER)
    await reading_job.run_reading(run_id)
    return run_id


@pytest.mark.parametrize("name,attempt", _chosen())
async def test_notes_are_placed_at_least_as_well_as_v1(name, attempt, monkeypatch, tmp_path):
    source, baseline = DOCUMENTS[name]
    key_path = KEYS / f"{name}.json"
    if not key_path.is_file() or not source.is_file():
        pytest.skip(f"The answer key or the PDF for {name} is not on this machine.")
    key = json.loads(key_path.read_text(encoding="utf-8"))
    if "notes" not in key:
        pytest.skip(f"The answer key for {name} has no notes section.")
    openai_key = dotenv_values(PROJECT_ROOT / ".env").get("OPENAI_API_KEY")
    if not openai_key:
        pytest.skip("OPENAI_API_KEY is not in .env")
    monkeypatch.setenv("OPENAI_API_KEY", openai_key)
    out = Path(os.environ.get("LIVE_OUT") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    folder = out / f"{name}-notes-{attempt}"
    shutil.rmtree(folder, ignore_errors=True)
    saved_reading = Path(os.environ["LIVE_READING"]) / name if os.environ.get("LIVE_READING") else None
    if saved_reading and (saved_reading / "xbrl.db").is_file():
        shutil.copytree(saved_reading, folder)
    folder.mkdir(exist_ok=True)
    monkeypatch.setenv("XBRL_OUTPUT_DIR", str(folder))
    db.init_db()
    loader.load_catalogue()

    with db.connect() as conn:
        found = conn.execute("SELECT MAX(id) FROM runs").fetchone()[0]
    run_id = found if found is not None else await _read(source)
    with db.connect(immediate=True) as conn:
        # The reading ran directly, not through the worker, so its job row still waits: close it.
        conn.execute("UPDATE jobs SET status = 'done', finished_at = ? WHERE run_id = ? AND kind = 'read' "
                     "AND status IN ('queued', 'retry')", (db.now(), run_id))
        body = _setup_body(reading.suggested_setup(conn, run_id), reading.document_map(conn, run_id), key)
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        _, page_count = documents.pdf_path(conn, run_id)
        setup.confirm(conn, run, body, page_count, OWNER)

    started = time.monotonic()
    assert await worker.run_once(busy_kinds=WAITS)
    seconds = time.monotonic() - started
    with db.connect() as conn:
        kinds = [r[0] for r in conn.execute("SELECT kind FROM jobs WHERE run_id = ? AND status = 'done'", (run_id,))]
        assert NOTES_JOB in kinds, "the worker ran another job instead of the notes"
        stage = dict(conn.execute("SELECT status, error FROM stages WHERE run_id = ? AND name = ?",
                                  (run_id, NOTES_JOB)).fetchone())
        result = notes_score.score(key["notes"], notes_score.v2_placements(conn, run_id))
        labels = dict(conn.execute("SELECT node_uuid, label FROM notes_nodes").fetchall())

    def named(ids):
        return [" ".join((labels.get(i) or i).lstrip("*").split()) for i in ids]

    summary = {
        "document": name, "attempt": attempt, "run_id": run_id, "stage": stage, "seconds": round(seconds),
        "score": result["score"], "baseline": baseline, "counts": result["counts"],
        "not_right": [f"note {n['number']} {n['title']}: {n['status']}, placed in {named(n['run_fields'])}, "
                      f"key {named(n['key_fields'])} ({n['confidence']})"
                      for n in result["notes"] if n["status"] != notes_score.RIGHT],
        "not_in_key": [f"{n['number']} {n['title']}: {named(n['run_fields'])}" for n in result["not_in_key"]],
        "unnumbered": [f"{n['title']}: {n['status']}" for n in result["unnumbered"]],
        "cost": model_usage.run_totals(run_id, NOTES_JOB),
    }
    (out / f"notes-{name}-{attempt}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                                      encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    assert stage["status"] == "done", stage["error"]
    assert result["score"] is not None and result["score"] >= baseline, (
        f"{name}: notes placement {result['score']} is below v1's {baseline}")
