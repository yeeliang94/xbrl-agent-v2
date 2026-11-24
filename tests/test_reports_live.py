"""Live: the reports agent on the test documents. Costs money; left out of the default run.

    LIVE_READING=/folder/of/saved/readings LIVE_OUT=/some/temp/folder \
        venv/bin/python -m pytest tests/test_reports_live.py -m live -s
    LIVE_DOCS="Doc_1" ...          # only the documents whose names contain these

A saved reading (`tests/test_reading_live.py`, or the copy the statements' live test keeps) is required:
nothing is read again. The setup is confirmed as the Reader suggested (as in
`tests/test_extraction_live.py`), then only the reports job runs. The bar is v1's: every field of each
report the document prints is assessed (filled with a source page, or left empty with a reason), and each
report's narrative is filled. A summary per report is printed and written to LIVE_OUT/reports-<name>.json.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from dotenv import dotenv_values

from app import db
from app.catalog import loader
from app.documents import store as documents
from app.reading import store as reading
from app.reports.job import run_reports
from app.runs import setup
from app.utils.paths import PROJECT_ROOT
from tests.conftest import OWNER
from tests.test_extraction_live import KEYS, _chosen, _setup_body

pytestmark = pytest.mark.live


@pytest.mark.parametrize("name", _chosen())
async def test_the_reports_agent_assesses_every_field_it_can_see(name, monkeypatch, tmp_path):
    saved = Path(os.environ["LIVE_READING"]) / name if os.environ.get("LIVE_READING") else None
    if saved is None or not (saved / "xbrl.db").is_file():
        pytest.skip(f"No saved reading for {name}: set LIVE_READING.")
    openai_key = dotenv_values(PROJECT_ROOT / ".env").get("OPENAI_API_KEY")
    if not openai_key:
        pytest.skip("OPENAI_API_KEY is not in .env")
    monkeypatch.setenv("OPENAI_API_KEY", openai_key)
    key = json.loads((KEYS / f"{name}.json").read_text(encoding="utf-8"))
    out = Path(os.environ.get("LIVE_OUT") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    folder = out / f"{name}-reports"
    shutil.rmtree(folder, ignore_errors=True)
    shutil.copytree(saved, folder, ignore=shutil.ignore_patterns("xbrl.db-shm", "xbrl.db-wal"))
    monkeypatch.setenv("XBRL_OUTPUT_DIR", str(folder))
    db.init_db()
    loader.load_catalogue()

    with db.connect(immediate=True) as conn:
        run_id = conn.execute("SELECT MAX(id) FROM runs").fetchone()[0]
        conn.execute("UPDATE jobs SET status = 'done', finished_at = ? WHERE run_id = ? AND status IN "
                     "('queued', 'retry')", (db.now(), run_id))
        doc_map = reading.document_map(conn, run_id)
        body = {**_setup_body(reading.suggested_setup(conn, run_id), doc_map, key), "notes_included": False}
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        _, page_count = documents.pdf_path(conn, run_id)
        setup.confirm(conn, run, body, page_count, OWNER)
        # Only the reports job runs here: the statements' own live test covers the rest.
        conn.execute("UPDATE jobs SET status = 'done', finished_at = ? WHERE run_id = ? AND kind != 'reports' "
                     "AND status IN ('queued', 'retry')", (db.now(), run_id))
        queued = conn.execute("SELECT COUNT(*) FROM jobs WHERE run_id = ? AND kind = 'reports'", (run_id,)).fetchone()[0]
    assert queued, "The Reader's map names no report section, so the reports agent did not start."

    await run_reports(run_id)

    with db.connect() as conn:
        stage = dict(conn.execute("SELECT status, error FROM stages WHERE run_id = ? AND name = 'reports'",
                                  (run_id,)).fetchone())
        rows = [dict(r) for r in conn.execute("SELECT * FROM report_fields WHERE run_id = ?", (run_id,))]
        cost = conn.execute("SELECT COALESCE(SUM(cost_usd), 0), COUNT(*) FROM model_calls WHERE run_id = ? "
                            "AND source = 'reports'", (run_id,)).fetchone()
    summary: dict = {"stage": stage, "cost_usd": round(cost[0] or 0, 4), "calls": cost[1], "reports": {}}
    for r in rows:
        rep = summary["reports"].setdefault(r["report"], {"filled": 0, "not_shown": 0, "unsure": 0, "no_page": 0})
        rep[r["status"]] = rep.get(r["status"], 0) + 1
        if r["status"] == "filled" and not json.loads(r.get("pages_json") or "[]"):
            rep["no_page"] += 1
    (out / f"reports-{name}.json").write_text(json.dumps({**summary, "fields": rows}, indent=1, default=str))
    print(json.dumps(summary, indent=1, default=str))
    assert stage["status"] == "done", stage
    for report, counts in summary["reports"].items():
        assert counts["no_page"] == 0, f"{report}: a saved value has no source page"
