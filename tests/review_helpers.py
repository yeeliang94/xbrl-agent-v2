"""A run waiting in review, with figures saved as the figures agent would,
for the review-loop tests. No model is called."""
from __future__ import annotations

from app import db
from app.catalog.lookup import run_family
from app.extraction import outline as outline_mod
from app.figures import store
from tests.test_extraction_job import SETUP, read_run

FIGURES_AGENT = store.Actor("agent", "figures")


def field_uuid(run_id: int, field_id: str) -> str:
    with db.connect() as conn:
        return outline_mod.build(conn, run_family(conn, run_id)).get(field_id).concept_uuid


def save(run_id: int, field_id: str, period: str, value: float, label: str, *, actor=FIGURES_AGENT,
         certainty: str = "sure", reason: str = "") -> dict:
    with db.connect(immediate=True) as conn:
        return store.save_figure(conn, run_id, store.FigureWrite(
            field_uuid(run_id, field_id), period, "Company", value, [store.Line(label, 2, value)],
            certainty=certainty, reason=reason), actor)


def reviewed_run(client, figures=(("FP-s28", 1200, "Plant and equipment"), ("FP-s404", 250, "Trade payables"),
                                  ("FP-41", 900, "Retained earnings"))) -> int:
    """An uploaded, read and confirmed run whose extraction is done: CY figures saved, status in_review."""
    run_id = read_run(client)
    assert client.post(f"/api/runs/{run_id}/setup", json=SETUP).status_code == 200
    for field_id, value, label in figures:
        save(run_id, field_id, "CY", value, label)
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE stages SET status = 'done' WHERE run_id = ? AND name = 'extract'", (run_id,))
        conn.execute("UPDATE jobs SET status = 'done' WHERE run_id = ? AND kind = 'extract'", (run_id,))
        conn.execute("UPDATE runs SET status = 'in_review' WHERE id = ?", (run_id,))
    return run_id


def comment_on(client, run_id: int, field_id: str, period: str = "CY", text: str = "Page 2 prints 300.",
               scope: str = "figure") -> dict:
    response = client.post(f"/api/runs/{run_id}/comments", json={
        "target": {"kind": "figure", "statement": "SOFP", "concept_uuid": field_uuid(run_id, field_id),
                   "period": period}, "text": text, "scope": scope})
    assert response.status_code == 201, response.json()
    return response.json()["comment"]


def value(run_id: int, field_id: str, period: str = "CY"):
    with db.connect() as conn:
        row = conn.execute("SELECT value, status FROM figures WHERE run_id = ? AND concept_uuid = ? AND period = ?",
                           (run_id, field_uuid(run_id, field_id), period)).fetchone()
    return None if row is None or row["status"] == "not_disclosed" else row["value"]


def state(run_id: int, field_id: str, period: str = "CY"):
    with db.connect() as conn:
        row = conn.execute("SELECT id FROM figures WHERE run_id = ? AND concept_uuid = ? AND period = ?",
                           (run_id, field_uuid(run_id, field_id), period)).fetchone()
        return store.figure_state(conn, run_id, row["id"]) if row else None
