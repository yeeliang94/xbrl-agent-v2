"""A run's cost and time per agent, from the model calls already recorded."""
from __future__ import annotations

import pytest

from app import db
from tests.conftest import OWNER, login, make_run, make_user


@pytest.fixture
def signed_in(client):
    make_user(OWNER)
    assert login(client, OWNER).status_code == 200
    return client


def _call(conn, run_id, source, ended: str, seconds: float, cost, model="gpt-6-luna", agent=None) -> None:
    conn.execute(
        "INSERT INTO model_calls(run_id, source, model, input_tokens, cached_tokens, output_tokens, cost_usd, "
        "duration_ms, created_at, agent) VALUES (?, ?, ?, 100, 0, 10, ?, ?, ?, ?)",
        (run_id, source, model, cost, int(seconds * 1000), f"2026-11-25T09:{ended}.000000Z", agent))


def test_cost_and_time_are_given_per_agent_in_working_order_with_a_total(signed_in):
    run_id = make_run()
    other = make_run()
    with db.connect(immediate=True) as conn:
        # Two pages transcribed side by side for 30 s count 30 s, not 60; the Reader adds 20 s later.
        _call(conn, run_id, "transcription", "00:30", 30, 0.02)
        _call(conn, run_id, "transcription", "00:30", 30, 0.03)
        _call(conn, run_id, "reader", "01:00", 20, 0.10)
        _call(conn, run_id, "review", "30:00", 45, 0.25)
        _call(conn, run_id, "figures", "10:00", 120, 0.50)
        _call(conn, run_id, "figures", "12:00", 60, None)     # a failed or unpriced call: time, no cost
        _call(conn, run_id, "notes", "12:00", 90, None, model="unknown-model")
        _call(conn, other, "figures", "10:00", 500, 9.0)      # another run's calls are not counted
    cost = signed_in.get(f"/api/runs/{run_id}/cost").json()["cost"]
    assert cost["agents"] == [
        {"agent": "Reading the document", "seconds": 50, "calls": 3, "cost_usd": 0.15, "unpriced": 0},
        {"agent": "Figures", "seconds": 180, "calls": 2, "cost_usd": 0.5, "unpriced": 1},
        {"agent": "Notes", "seconds": 90, "calls": 1, "cost_usd": None, "unpriced": 1},
        {"agent": "Corrections", "seconds": 45, "calls": 1, "cost_usd": 0.25, "unpriced": 0},
    ]
    assert cost["total"] == {"seconds": 365, "calls": 7, "cost_usd": 0.9, "unpriced": 2}


def test_a_run_with_no_model_calls_has_an_empty_cost_and_a_missing_run_is_not_found(signed_in, client):
    run_id = make_run()
    assert signed_in.get(f"/api/runs/{run_id}/cost").json()["cost"] == {
        "agents": [], "total": {"seconds": 0, "calls": 0, "cost_usd": None, "unpriced": 0}}
    assert signed_in.get("/api/runs/999/cost").status_code == 404
    signed_in.post("/api/auth/logout")
    assert client.get(f"/api/runs/{run_id}/cost").status_code == 401


def test_an_agent_run_that_names_itself_has_its_own_row_in_the_order_it_started(signed_in):
    run_id = make_run()
    with db.connect(immediate=True) as conn:
        _call(conn, run_id, "notes", "20:00", 60, 0.30, agent="Placing the notes")
        _call(conn, run_id, "figures", "10:00", 100, 0.40, agent="Statement of financial position")
        _call(conn, run_id, "figures", "11:00", 50, 0.20, agent="Statement of profit or loss")
        _call(conn, run_id, "notes", "20:30", 30, 0.10, agent="Note figures")
        _call(conn, run_id, "figures", "40:00", 40, 0.15, agent="Statement of financial position, redone")
        _call(conn, run_id, "figures", "12:00", 10, 0.05, agent="Statement of financial position")
    cost = signed_in.get(f"/api/runs/{run_id}/cost").json()["cost"]
    assert [(a["agent"], a["seconds"], a["calls"]) for a in cost["agents"]] == [
        ("Statement of financial position", 110, 2), ("Statement of profit or loss", 50, 1),
        ("Statement of financial position, redone", 40, 1), ("Placing the notes", 60, 1), ("Note figures", 30, 1)]
    assert cost["total"]["cost_usd"] == 1.2


async def test_the_shared_loop_records_the_agent_runs_name_with_each_call():
    from pydantic_ai.models.test import TestModel

    from app.agents import loop

    run_id = make_run()
    spec = loop.AgentSpec(name="figures", model_id="gpt-5.4", instructions="Say hello.", label="Statement of cash flows")
    outcome = await loop.run_agent(spec, "Hello", deps=None, run_id=run_id, model=TestModel())
    assert outcome.status == loop.COMPLETED
    with db.connect() as conn:
        rows = conn.execute("SELECT source, agent FROM model_calls WHERE run_id = ?", (run_id,)).fetchall()
    assert rows and {(r["source"], r["agent"]) for r in rows} == {("figures", "Statement of cash flows")}
