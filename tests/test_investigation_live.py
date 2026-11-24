"""Live: the investigating agent on a deliberately altered template (step 12's "done when"). The Company
template's sub-classification sheet loses its SSM names, so the fill cannot place its figures; the agent
proposes places from the labels and headers. Every proposal must be the cell the genuine template keeps the
figure in: a wrong cell fails the test, a figure left in not_found does not. Costs money (a few cents); left
out of the default run.

    venv/bin/python -m pytest tests/test_investigation_live.py -m live -s
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from dotenv import dotenv_values

from app import db
from app.filing.investigate import job as investigate, store
from app.models import usage
from tests.test_template_investigation import _cell, filled_altered  # noqa: F401 - the fixture

pytestmark = pytest.mark.live
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_the_agent_proposes_only_the_genuine_cells(filled_altered, monkeypatch):  # noqa: F811
    key = dotenv_values(PROJECT_ROOT / ".env").get("OPENAI_API_KEY")
    if not key:
        pytest.skip("OPENAI_API_KEY is not in .env")
    monkeypatch.setenv("OPENAI_API_KEY", key)
    f = filled_altered
    asyncio.run(investigate.run_investigation(f.fill_id, f.run_id))
    with db.connect() as conn:
        status = conn.execute("SELECT investigation, investigation_error FROM fills WHERE id = ?",
                              (f.fill_id,)).fetchone()
        rows = store.for_fill(conn, f.fill_id)
    lines = {tuple(l[k] for k in store.KEY): l for l in store.to_place(f.report)}
    wrong = [(r["figure_name"], f"{r['sheet']}!{r['cell']}", _cell(f, lines[tuple(r[k] for k in store.KEY)]))
             for r in rows if f"{r['sheet']}!{r['cell']}" != _cell(f, lines[tuple(r[k] for k in store.KEY)])]
    spent = usage.run_totals(f.run_id, "investigate")
    print(json.dumps({"status": tuple(status), "figures": len(lines), "proposed": len(rows), "wrong": wrong,
                      "cost_usd": spent["cost_usd"], "calls": spent["calls"],
                      "sample": [dict(place=r["place"], evidence=r["evidence"]) for r in rows[:3]]}, indent=2))
    assert status["investigation"] == "done"
    assert rows, "No place was proposed."
    assert not wrong
