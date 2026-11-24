"""Live: read the four test documents through the real path (upload store,
then the read job) with the Settings "Reading" model, and check the map
against the answer key. Costs money; left out of the default run.

    LIVE_OUT=/some/temp/folder venv/bin/python -m pytest tests/test_reading_live.py -m live -s
    LIVE_DOCS="Doc 3,Doc 4" ...    # only the documents whose names contain these

Each document is read where it is; the run's folder (with its copy of the
upload and every record) goes under LIVE_OUT (a temporary folder when it is
not set), never into the repository. A summary is printed and written to
LIVE_OUT/summary-<name>.json before the answer key is checked.

The answer key (PDF page numbers, checked by a person): a statement that
runs on to more pages passes when its first page is right.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from dotenv import dotenv_values

from app import db
from app.documents import store as documents
from app.documents.pdf_check import inspect_pdf
from app.models import usage as model_usage
from app.reading import job, store
from app.utils.paths import PROJECT_ROOT
from tests.conftest import OWNER, make_user

pytestmark = pytest.mark.live

V1_DATA = Path("/Users/user/Desktop/xbrl-agent/data")
NOT_PRINTED = None

# {statement: (first PDF page, layout, unsure)}. NOT_PRINTED: the document does not print it.
# A layout of None is not checked (the page does not settle it, so it must be marked unsure).
ANSWERS = {
    "Doc 1": {
        "path": V1_DATA / "Doc 1.pdf", "standard": "MFRS", "level": "Company", "unit": "RM'000", "notes": None,
        "statements": {"SOFP": (8, "CuNonCu", False), "SOPL": (9, "Function", False),
                       "SOCI": (9, "NetOfTax", False), "SOCIE": (10, "Default", False),
                       "SOCF": (11, "Indirect", False)},
    },
    "Doc 2": {
        "path": V1_DATA / "Doc 2.pdf", "standard": "MFRS", "level": "Company", "unit": "RM", "notes": None,
        "statements": {"SOFP": (6, "CuNonCu", False), "SOPL": (7, "Function", False),
                       "SOCI": (7, "NetOfTax", False), "SOCIE": (8, "Default", False),
                       "SOCF": (9, "Indirect", False)},
    },
    "Doc 3": {
        "path": V1_DATA / "Doc 3.pdf", "standard": "MFRS", "level": "Company", "unit": "RM", "notes": None,
        "statements": {"SOPL": (12, "Function", False), "SOCI": (12, "NetOfTax", False),
                       "SOFP": (13, "CuNonCu", False), "SOCIE": (14, "Default", False),
                       "SOCF": (15, "Indirect", False)},
    },
    "Doc 4": {
        # The plain copy, not the stamped one.
        "path": PROJECT_ROOT / "test-data" / "Doc 4.pdf",
        "standard": "MFRS", "level": "Company", "unit": "RM", "notes": 15,
        "statements": {"SOFP": (14, "CuNonCu", False), "SOPL": (15, None, True), "SOCI": NOT_PRINTED,
                       "SOCIE": (16, "Default", False), "SOCF": (17, "Direct", False)},
    },
}


def _chosen() -> list[str]:
    wanted = [w.strip() for w in os.environ.get("LIVE_DOCS", "").split(",") if w.strip()]
    return [name for name in ANSWERS if not wanted or any(w in name for w in wanted)]


def _check(name: str, doc_map: dict) -> list[str]:
    """Every way the map differs from the answer key, one line each."""
    key = ANSWERS[name]
    wrong = []
    for field in ("standard", "level", "unit"):
        if doc_map[field]["value"] != key[field]:
            wrong.append(f"{field}: {doc_map[field]['value']!r}, expected {key[field]!r}")
    found = {st["statement"]: st for st in doc_map["statements"]}
    for statement, expected in key["statements"].items():
        st = found[statement]
        if expected is NOT_PRINTED:
            if st["found"]:
                wrong.append(f"{statement}: found on {st['pages']}, expected not printed")
            continue
        page, layout, unsure = expected
        if not st["found"] or not st["pages"] or min(st["pages"]) != page:
            wrong.append(f"{statement}: pages {st['pages']}, expected to start on page {page}")
        if layout is not None and st["layout"] != layout:
            wrong.append(f"{statement}: layout {st['layout']!r}, expected {layout!r}")
        if unsure and not st["unsure"]:
            wrong.append(f"{statement}: not marked unsure, expected unsure")
    if key["notes"] is not None and len(doc_map["notes"]) != key["notes"]:
        wrong.append(f"notes: {len(doc_map['notes'])}, expected {key['notes']}")
    return wrong


@pytest.mark.parametrize("name", _chosen())
async def test_a_real_document_is_mapped_as_the_answer_key_says(name, monkeypatch, tmp_path):
    source = ANSWERS[name]["path"]
    assert source.is_file(), f"{source} is not on this machine"
    out = Path(os.environ.get("LIVE_OUT") or tmp_path)
    out.mkdir(parents=True, exist_ok=True)
    key = dotenv_values(PROJECT_ROOT / ".env").get("OPENAI_API_KEY")
    assert key, "OPENAI_API_KEY is not in .env"
    monkeypatch.setenv("OPENAI_API_KEY", key)
    folder = out / name.replace(" ", "_")
    folder.mkdir(exist_ok=True)
    monkeypatch.setenv("XBRL_OUTPUT_DIR", str(folder))
    db.init_db()
    make_user(OWNER)
    data = source.read_bytes()
    with db.connect(immediate=True) as conn:
        run_id = documents.create_run_from_pdf(conn, data, inspect_pdf(data), filename=source.name,
                                               owner_email=OWNER)
    started = time.monotonic()
    error = None
    try:
        await job.run_reading(run_id)
    except job.ReadingFailed as exc:
        error = str(exc)
    with db.connect() as conn:
        progress = store.progress(conn, run_id)
        doc_map = store.saved_map(conn, run_id)
        pages = store.map_pages(conn, run_id)
    wrong = _check(name, doc_map) if doc_map else ["no map was saved"]
    summary = {"document": source.name, "seconds": round(time.monotonic() - started), "error": error,
               "wrong": wrong, "progress": progress,
               "transcription": model_usage.run_totals(run_id, "transcription"),
               "reader": model_usage.run_totals(run_id, "reader"), "total": model_usage.run_totals(run_id),
               "map": doc_map, "pages": pages}
    (out / f"summary-{folder.name}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                                     encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("document", "seconds", "error", "wrong", "progress", "total")},
                     indent=2))
    assert error is None, error
    assert wrong == [], f"{name} differs from the answer key: " + "; ".join(wrong)
