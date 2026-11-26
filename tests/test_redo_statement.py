"""Redo one statement of a run in review: the others and their checks stay, a person's edits and confirms are
kept unless the person says otherwise, and everything replaced keeps its history. Scripted agent, no network."""
from __future__ import annotations

import pytest

from app import db
from app.catalog.lookup import run_family
from app.extraction import outline as outline_mod, progress
from app.figures import store
from app.jobs import worker
from app.models import factory
from app.runs.events import list_events
from tests.conftest import OWNER, login, make_user
from tests.test_extraction_job import FINAL, PAYABLES, PLANT, SETUP, read_run, returns, script

AGENT = store.Actor("agent", "figures")
PERSON = store.Actor("person", OWNER)
BOTH = {**SETUP, "statements": [{**s, "included": s["statement"] in ("SOFP", "SOPL")} for s in SETUP["statements"]]}
# The redo's agent: saves the two printed lines again (payables differently), and tries the kept line too.
REDO_STEPS = [
    ("save_figures", {"figures": [
        {"field": "FP-s28", "lines": [{"label": "Plant and equipment", "page": 2, "cy": 1250}]},
        {"field": "FP-s404", "lines": [{"label": "Trade payables", "page": 2, "cy": 310}]},
    ]}),
    ("clear_figures", {"figures": [{"field": "FP-s28", "period": "CY", "reason": "Trying."}]}),
    ("run_checks", {}),
    ("report_coverage", {"lines": [PLANT, PAYABLES]}),
    (FINAL, {"summary": "Redone.", "unresolved": ["The balance does not agree: the test page prints no equity."]}),
]


@pytest.fixture
def signed_in(client):
    make_user(OWNER)
    assert login(client, OWNER).status_code == 200
    return client


def _field(outline, field_id: str) -> str:
    return outline.fields[field_id].concept_uuid


def reviewed_run(client) -> tuple[int, dict]:
    """A run in review with two finished statements: two agent figures on the balance sheet, one on profit or
    loss. Returns its id and the figures by name."""
    run_id = read_run(client)
    assert client.post(f"/api/runs/{run_id}/setup", json=BOTH).status_code == 200
    with db.connect(immediate=True) as conn:
        outline = outline_mod.build(conn, run_family(conn, run_id))
        revenue = next(f for f in outline.fields.values() if f.statement == "SOPL" and f.kind == outline_mod.LINE)

        def save(uuid: str, value: float, label: str) -> int:
            return store.save_figure(conn, run_id, store.FigureWrite(
                uuid, "CY", "Company", value, [store.Line(label, 2, value)]), AGENT)["id"]
        ids = {"plant": save(_field(outline, "FP-s28"), 1200, "Plant and equipment"),
               "payables": save(_field(outline, "FP-s404"), 300, "Trade payables"),
               "revenue": save(revenue.concept_uuid, 900, "Revenue")}
        progress.mark(conn, run_id, None, ("SOFP", "SOPL"), "Company", "The statements are filled.", {})
        conn.execute("UPDATE jobs SET status = 'done' WHERE run_id = ?", (run_id,))
        conn.execute("UPDATE stages SET status = 'done' WHERE run_id = ? AND name = 'extract'", (run_id,))
        conn.execute("UPDATE runs SET status = 'in_review' WHERE id = ?", (run_id,))
    return run_id, ids


def _figure(run_id: int, figure_id: int) -> dict:
    with db.connect() as conn:
        return store.get_figure(conn, run_id, figure_id)


def _checks(run_id: int) -> list[tuple]:
    """The checks that do not read the balance sheet."""
    with db.connect() as conn:
        return [tuple(r) for r in conn.execute(
            "SELECT check_name, entity_scope, status, expected, actual FROM check_results WHERE run_id = ? "
            "AND check_name NOT LIKE '%sofp%' ORDER BY check_name, entity_scope", (run_id,))]


async def test_one_statement_is_redone_and_a_persons_lines_are_kept(signed_in, monkeypatch):
    run_id, ids = reviewed_run(signed_in)
    with db.connect(immediate=True) as conn:   # a person corrects plant; the agent's payables stay the agent's
        store.save_figure(conn, run_id, store.FigureWrite(
            _figure(run_id, ids["plant"])["concept_uuid"], "CY", "Company", 1234.0), PERSON)
    revenue_before = _figure(run_id, ids["revenue"])
    other_checks = _checks(run_id)
    assert ("sopl_attribution_footing", "Company", "failed", -900.0, None) in other_checks

    preview = signed_in.get(f"/api/runs/{run_id}/statements/SOFP/redo").json()["redo"]
    assert preview["refusal"] is None and preview["name"] == "statement of financial position"
    assert [(k["label"], k["how"]) for k in preview["kept"]] == [("Plant and equipment", "edited")]

    seen: list = []
    monkeypatch.setattr(factory, "build_model", lambda model_id: script(REDO_STEPS, seen))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    response = signed_in.post(f"/api/runs/{run_id}/statements/SOFP/redo", json={"keep_mine": True})
    assert response.status_code == 202, response.text
    assert response.json()["run"]["status"] == "ready" and response.json()["kept"] == 1
    # Cleared at once, with a history row naming the person; the kept line and the other statement untouched.
    assert _figure(run_id, ids["payables"])["value"] is None
    assert _figure(run_id, ids["plant"])["value"] == 1234.0
    assert _figure(run_id, ids["revenue"]) == revenue_before
    detail = signed_in.get(f"/api/runs/{run_id}").json()["run"]
    assert detail["redo"] == {"statement": "SOFP", "kept": [ids["plant"]]}

    assert await worker.run_once()

    with db.connect() as conn:
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "in_review"
        history = store.figure_history(conn, run_id, ids["payables"])
        assert progress.finished(conn, run_id) == {("SOFP", "Company"), ("SOPL", "Company")}
    assert [(h["action"], h["actor_kind"]) for h in history] == [("save", "agent"), ("clear", "person"),
                                                                 ("save", "agent")]
    assert history[1]["before"]["value"] == 300.0 and history[1]["actor_name"] == OWNER
    assert _figure(run_id, ids["payables"])["value"] == 310.0
    # The person's line survived the agent's save and clear, and the agent was told why.
    kept = _figure(run_id, ids["plant"])
    assert kept["value"] == 1234.0 and kept["person_edited"] is True
    assert "CY not saved. A person edited or confirmed this figure and chose to keep it" in returns(
        seen[-1], "save_figures")[0]
    assert "CY not cleared. A person edited or confirmed this figure" in returns(seen[-1], "clear_figures")[0]
    first = seen[0][0].parts[-1].content
    assert "chose to keep these figures" in first and "CY 1,234" in first
    assert "Fill the statement of financial position of" in first   # this statement alone
    # The other statement and its own checks are as they were.
    assert _figure(run_id, ids["revenue"]) == revenue_before
    assert _checks(run_id) == other_checks
    messages = [e["message"] for e in list_events(run_id=run_id)]
    for expected in ("Started redoing the statement of financial position.",
                     "Kept 1 line a person edited or confirmed.",
                     "The statement of financial position is redone, with 1 point(s) left open."):
        assert expected in messages, expected
    assert signed_in.get(f"/api/runs/{run_id}").json()["run"]["redo"] is None   # finished again: closed


def test_a_redo_can_replace_a_persons_lines_and_a_confirmed_line_counts_as_theirs(signed_in):
    run_id, ids = reviewed_run(signed_in)
    assert signed_in.post(f"/api/runs/{run_id}/figures/{ids['payables']}/confirm").status_code == 200
    with db.connect(immediate=True) as conn:
        store.save_figure(conn, run_id, store.FigureWrite(
            _figure(run_id, ids["plant"])["concept_uuid"], "CY", "Company", 1234.0), PERSON)
    kept = signed_in.get(f"/api/runs/{run_id}/statements/SOFP/redo").json()["redo"]["kept"]
    assert sorted(k["how"] for k in kept) == ["confirmed", "edited"]

    response = signed_in.post(f"/api/runs/{run_id}/statements/SOFP/redo", json={"keep_mine": False})
    assert response.status_code == 202 and response.json()["kept"] == 0 and response.json()["cleared"] >= 2
    for name in ("plant", "payables"):
        cleared = _figure(run_id, ids[name])
        assert cleared["value"] is None and cleared["person_edited"] is False
    with db.connect() as conn:   # what was replaced can be restored from its history
        last = store.figure_history(conn, run_id, ids["plant"])[-1]
    assert last["action"] == "clear" and last["before"]["value"] == 1234.0
    assert _figure(run_id, ids["revenue"])["value"] == 900.0


def test_redo_is_refused_while_the_run_is_busy_or_for_a_statement_it_does_not_have(signed_in):
    run_id, ids = reviewed_run(signed_in)
    missing = signed_in.post(f"/api/runs/{run_id}/statements/SOCF/redo")
    assert (missing.status_code, missing.json()["detail"]) == (404, "That statement is not part of this run.")
    assert signed_in.post("/api/runs/999/statements/SOFP/redo").status_code == 404
    assert signed_in.post(f"/api/runs/{run_id}/statements/SOFP/redo").status_code == 202
    again = signed_in.post(f"/api/runs/{run_id}/statements/SOPL/redo")
    assert again.status_code == 409
    assert again.json()["detail"] == "A statement can be redone once the run is in review and no agent is working on it."
    assert signed_in.get(f"/api/runs/{run_id}/statements/SOPL/redo").json()["redo"]["refusal"] == again.json()["detail"]
    assert _figure(run_id, ids["revenue"])["value"] == 900.0


def test_a_stopped_redo_is_tried_again_with_the_kept_lines_still_kept(signed_in):
    run_id, ids = reviewed_run(signed_in)
    assert signed_in.post(f"/api/runs/{run_id}/figures/{ids['plant']}/confirm").status_code == 200
    assert signed_in.post(f"/api/runs/{run_id}/statements/SOFP/redo").status_code == 202
    assert signed_in.post(f"/api/runs/{run_id}/extract/stop").json()["run"]["status"] == "in_review"
    assert signed_in.post(f"/api/runs/{run_id}/extract/retry").status_code == 202
    detail = signed_in.get(f"/api/runs/{run_id}").json()["run"]
    assert detail["redo"] == {"statement": "SOFP", "kept": [ids["plant"]]}
    assert _figure(run_id, ids["plant"])["value"] == 1200.0


def test_a_line_a_person_corrects_after_a_stopped_redo_is_kept_through_the_retry(signed_in):
    run_id, ids = reviewed_run(signed_in)
    assert signed_in.post(f"/api/runs/{run_id}/statements/SOFP/redo").status_code == 202
    assert signed_in.post(f"/api/runs/{run_id}/extract/stop").json()["run"]["status"] == "in_review"
    with db.connect(immediate=True) as conn:   # the cleared payables are filled in by hand while the redo waits
        store.save_figure(conn, run_id, store.FigureWrite(_figure(run_id, ids["payables"])["concept_uuid"], "CY",
                                                          "Company", 305.0, [store.Line("Payables", 14, 305.0)]),
                          PERSON)
    assert signed_in.post(f"/api/runs/{run_id}/extract/retry").status_code == 202
    detail = signed_in.get(f"/api/runs/{run_id}").json()["run"]
    assert detail["redo"] == {"statement": "SOFP", "kept": [ids["payables"]]}


def test_another_statement_waits_until_a_stopped_redo_is_finished(signed_in):
    run_id, ids = reviewed_run(signed_in)
    assert signed_in.post(f"/api/runs/{run_id}/statements/SOFP/redo").status_code == 202
    assert signed_in.post(f"/api/runs/{run_id}/extract/stop").json()["run"]["status"] == "in_review"
    other = signed_in.post(f"/api/runs/{run_id}/statements/SOPL/redo")
    assert (other.status_code, other.json()["detail"]) == (409, "The redo of the statement of financial position "
                                                                "was stopped before it finished, so try it again "
                                                                "before redoing another statement.")
    assert _figure(run_id, ids["revenue"])["value"] == 900.0
    assert signed_in.post(f"/api/runs/{run_id}/statements/SOFP/redo").status_code == 202   # the same one may
