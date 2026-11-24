"""Live: fill the five statements of the test documents with the figures
agent and score each against the answer keys. Costs money; left out of the
default run.

    LIVE_OUT=/some/temp/folder venv/bin/python -m pytest tests/test_extraction_live.py -m live -s
    LIVE_DOCS="Doc_3,Doc_4" ...          # only the documents whose names contain these
    LIVE_READING=/folder/of/the/reading/live/test ...   # reuse its saved readings, so nothing is read again

Each document is read first (or its saved reading from `tests/test_reading_live.py`,
under LIVE_READING/<Doc_1|Doc_2|Doc_3|Doc_4>, is copied), then the setup is
confirmed as the Reader suggested, with every statement it found included in
its suggested layout; where the Reader left a layout or the pages open, the
key's stand in, as a person would choose them on the setup screen. The
confirmed run goes through the real job (`worker.run_once`): one agent for
all the statements. The run's folder goes under LIVE_OUT (a temporary folder when it is not
set), never into the repository. A summary per statement is printed and
written to LIVE_OUT/extraction-<name>.json before any score is
checked.

The bar is v1's baseline per statement on the same keys and definitions
(complete and accurate, entry cells, extras counted), in BASELINES. The
balance sheet's: the average of v1's recent runs of each document (Doc 1:
runs 316, 317, 330, 392, 393; Doc 2: 326, 338, 349, 352, 353; Doc 3: 341, 345
to 348; Doc 4: 270, 272, 303, 306), scored 18 November 2026 with the keys'
accepted alternatives. The other four statements' are v1's averages on the step 7
keys (key_version 3), scored 23 November 2026 from the same runs (Doc 3's
equity and cash flows from runs 347 and 348 only, the others filled fewer
statements). A statement whose key
holds no placements yet is reported only. One run varies, so a single run
can dip below its bar; look at the differences before changing the agent.
The answer keys are not committed (docs/answer-keys.md): a document whose
key or PDF is missing is skipped.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Optional

import pytest
from dotenv import dotenv_values

from app import db
from app.catalog import loader
from app.catalog.lookup import run_family
from app.catalog.statements import StatementType
from app.documents import store as documents
from app.documents.pdf_check import inspect_pdf
from app.jobs import worker
from app.models import usage as model_usage
from app.reading import job as reading_job, store as reading
from app.runs import setup
from app.scoring import answer_key, attached
from app.catalog.fields import run_edges, run_fields
from app.utils.paths import PROJECT_ROOT
from tests.conftest import OWNER, make_user

pytestmark = pytest.mark.live

V1_DATA = Path("/Users/user/Desktop/xbrl-agent/data")
KEYS = PROJECT_ROOT / "test-data" / "answer-keys"
DOCUMENTS = {
    "Doc_1": V1_DATA / "Doc 1.pdf",
    "Doc_2": V1_DATA / "Doc 2.pdf",
    "Doc_3": V1_DATA / "Doc 3.pdf",
    # The plain copy, never the stamped one. Left out unless LIVE_DOCS names it (owner, 18 November
    # 2026): the document has too many problems of its own to judge the agent by, for now.
    "Doc_4": PROJECT_ROOT / "test-data" / "Doc 4.pdf",
}
ORDER = ("SOFP", "SOPL", "SOCI", "SOCIE", "SOCF")
# v1's complete-and-accurate per statement; None: not yet known (reported, not asserted).
BASELINES = {
    "Doc_1": {"SOFP": 0.85, "SOPL": 0.844, "SOCI": 1.0, "SOCIE": 1.0, "SOCF": 1.0},
    "Doc_2": {"SOFP": 0.9394, "SOPL": 0.943, "SOCI": 1.0, "SOCIE": 1.0, "SOCF": 1.0},
    "Doc_3": {"SOFP": 0.9286, "SOPL": 1.0, "SOCI": 1.0, "SOCIE": 1.0, "SOCF": 1.0},
    "Doc_4": {"SOFP": 0.9645, "SOPL": None, "SOCI": None, "SOCIE": None, "SOCF": None},
}
# The key's template names, as layouts (`test-data/answer-keys/*.json` "template").
KEY_LAYOUTS = (("cunoncu", "CuNonCu"), ("liquidity", "OrderOfLiquidity"), ("function", "Function"),
               ("nature", "Nature"), ("net of tax", "NetOfTax"), ("netoftax", "NetOfTax"), ("before tax", "BeforeTax"),
               ("beforetax", "BeforeTax"), ("indirect", "Indirect"), ("direct", "Direct"), ("sore", "SoRE"),
               ("retained", "SoRE"), ("default", "Default"), ("socie", "Default"))


SET_ASIDE = {"Doc_4"}


def _chosen() -> list[str]:
    wanted = [w.strip() for w in os.environ.get("LIVE_DOCS", "").split(",") if w.strip()]
    if not wanted:
        return [name for name in DOCUMENTS if name not in SET_ASIDE]
    return [name for name in DOCUMENTS if any(w in name for w in wanted)]


def _key_layout(key: dict, statement: str) -> Optional[str]:
    name = str((key.get("template") or {}).get(statement) or "").lower()
    return next((layout for word, layout in KEY_LAYOUTS if word in name), None)


def _setup_body(suggested: dict, doc_map: dict, key: dict) -> dict:
    """The setup as the Reader suggested it, every statement it found included in its suggested layout. Where
    the Reader left a value open (Doc 3's standard, for one), the key's value stands in, as a person would
    choose it on the setup screen."""
    def value(name: str, allowed=None):
        found = (suggested.get(name) or {}).get("value")
        return found if found and (allowed is None or found in allowed) else fallback[name]

    fallback = {"company": key["company"], "year_end": key["year_end"], "standard": key["standard"],
                "level": key["level"], "unit": "RM'000" if "thousand" in key["unit"].lower() else "RM"}
    standard = value("standard", ("MFRS", "MPERS"))
    statements = []
    for st in suggested["statements"]:
        name = st["statement"]
        allowed = [c["value"] for c in st["layouts"][standard]]
        keyed = key["statements"].get(name) or {}
        layout = next((v for v in (st["layout"], _key_layout(key, name)) if v in allowed), allowed[0])
        pages = [] if layout == "NotPrepared" else st["pages"] or keyed.get("pages") or []
        included = bool(pages)
        statements.append({"statement": name, "layout": layout, "included": included, "pages": pages})
    return {"company": value("company"), "year_end": value("year_end"), "standard": standard,
            "level": value("level", ("Company", "Group")), "unit": value("unit", ("RM", "RM'000")),
            "statements": statements, "notes_included": True,
            "notes": [{k: n[k] for k in ("number", "title", "first_page", "last_page")} for n in doc_map["notes"]]}


async def _read(source: Path, folder: Path) -> int:
    make_user(OWNER)
    data = source.read_bytes()
    with db.connect(immediate=True) as conn:
        run_id = documents.create_run_from_pdf(conn, data, inspect_pdf(data), filename=source.name, owner_email=OWNER)
    await reading_job.run_reading(run_id)
    return run_id


def _records(folder: Path, run_id: int) -> dict[str, dict]:
    """The agent records of the run, by statement (one record may cover several)."""
    out = {}
    for path in sorted((folder / "runs" / f"run-{run_id}").glob("extraction-*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        for statement in record.get("statements") or [record.get("statement")]:
            out.setdefault(statement, record)
    return out


@pytest.mark.parametrize("name", _chosen())
async def test_each_statement_scores_at_least_as_well_as_v1(name, monkeypatch, tmp_path):
    source, baselines = DOCUMENTS[name], BASELINES[name]
    key_path = KEYS / f"{name}.json"
    if not key_path.is_file() or not source.is_file():
        pytest.skip(f"The answer key or the PDF for {name} is not on this machine.")
    openai_key = dotenv_values(PROJECT_ROOT / ".env").get("OPENAI_API_KEY")
    if not openai_key:
        pytest.skip("OPENAI_API_KEY is not in .env")
    monkeypatch.setenv("OPENAI_API_KEY", openai_key)
    key = json.loads(key_path.read_text(encoding="utf-8"))
    out = Path(os.environ.get("LIVE_OUT") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    folder = out / f"{name}-extraction"
    shutil.rmtree(folder, ignore_errors=True)
    saved_reading = Path(os.environ["LIVE_READING"]) / name if os.environ.get("LIVE_READING") else None
    if saved_reading and (saved_reading / "xbrl.db").is_file():
        shutil.copytree(saved_reading, folder)
    folder.mkdir(exist_ok=True)
    monkeypatch.setenv("XBRL_OUTPUT_DIR", str(folder))
    db.init_db()
    loader.load_catalogue()

    started = time.monotonic()
    with db.connect() as conn:
        found = conn.execute("SELECT MAX(id) FROM runs").fetchone()[0]
    run_id = found if found is not None else await _read(source, folder)
    with db.connect(immediate=True) as conn:
        # The reading ran directly, not through the worker, so its job row still waits: close it, or the
        # worker would read the document again before extracting.
        conn.execute("UPDATE jobs SET status = 'done', finished_at = ? WHERE run_id = ? AND kind = 'read' "
                     "AND status IN ('queued', 'retry')", (db.now(), run_id))
        body = _setup_body(reading.suggested_setup(conn, run_id), reading.document_map(conn, run_id), key)
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        _, page_count = documents.pdf_path(conn, run_id)
        setup.confirm(conn, run, body, page_count, OWNER)
    read_seconds = time.monotonic() - started
    assert await worker.run_once()
    with db.connect() as conn:
        kinds = [r[0] for r in conn.execute("SELECT kind FROM jobs WHERE run_id = ? AND status = 'done'", (run_id,))]
    assert "extract" in kinds, "the worker ran another job instead of the extraction"
    seconds = time.monotonic() - started - read_seconds

    with db.connect() as conn:
        family = run_family(conn, run_id)
        fields, values, edges = run_fields(conn, family), attached.run_values(conn, run_id), run_edges(conn, family)
        stage = dict(conn.execute("SELECT status, error FROM stages WHERE run_id = ? AND name = 'extract'",
                                  (run_id,)).fetchone())
        included = [s for s in ORDER if StatementType(s) in family.template_ids]
    records = _records(folder, run_id)
    per_statement = {}
    for statement in included:
        result = answer_key.score(key, statement, fields, values, edges, family.periods)
        score = next((s["score"] for s in result["statements"] if s["statement"] == statement), {}) or {}
        record = records.get(statement, {})
        per_statement[statement] = {
            "complete_and_accurate": score.get("complete_and_accurate"), "baseline": baselines.get(statement),
            "completeness": score.get("completeness"), "accuracy": score.get("accuracy"),
            "counts": {k: n for k, n in (score.get("counts") or {}).items() if n},
            "totals": {k: n for k, n in result["totals"]["counts"].items() if n},
            "extras": [f"{d['field_label']} {d['period']} {d['run_value']}" for d in result["differences"]
                       if d["kind"] == "extra"],
            "differences": [f"{d['kind']}: {d['field_label']} {d['period']} run {d['run_value']} key "
                            f"{d['person_value']}" for d in result["differences"] if d["kind"] != "extra"],
            "status": record.get("status"), "steps": record.get("steps"), "seconds": record.get("seconds"),
            "cost": (record.get("usage") or {}).get("cost_usd"),
            "unresolved": (record.get("finish") or {}).get("unresolved"),
        }
    summary = {
        "document": name, "run_id": run_id, "stage": stage,
        "seconds": round(seconds), "statements": per_statement, "cost": model_usage.run_totals(run_id, "figures"),
        "workbench": next(iter(records.values()), {}).get("workbench"),
    }
    (out / f"extraction-{name}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                                         encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    assert stage["status"] == "done", stage["error"]
    below = [f"{s}: complete and accurate {r['complete_and_accurate']} is below v1's {r['baseline']}"
             for s, r in per_statement.items() if r["baseline"] is not None
             and (r["complete_and_accurate"] is None or r["complete_and_accurate"] < r["baseline"])]
    assert not below, f"{name}: " + "; ".join(below)
