"""Scope questions (step 5b): the figures agent's ask_scope tool and its
refusals, a scripted agent that asks and stops, answering with the confirmed
value or with a change, the refusals of an answer, a question surviving a
restart, and the setup screen's question cards. No network."""
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from app import db
from app.extraction import agent, job
from app.figures import store
from app.jobs import queue, worker
from app.models import factory
from app.reading import store as reading
from app.runs.events import list_events
from app.scope import ask
from tests import reading_fakes as fakes
from tests.conftest import make_user
from tests.review_helpers import field_uuid, save, value
from tests.test_extraction_job import FINAL, PAYABLES, PLANT, SETUP, read_run, script, signed_in  # noqa: F401

STANDARD_CHOICES = [{"label": "MPERS", "value": "MPERS", "effect": "Restarts extraction with the MPERS templates",
                     "suggested": True},
                    {"label": "MFRS, as set up", "value": "MFRS", "effect": "Carries on"}]
EVIDENCE = [{"text": "Prepared in accordance with the Malaysian Private Entities Reporting Standard.", "page": 3},
            {"text": "The setup says MFRS.", "page": 2}]
ASK = ("ask_scope", {"field": "standard", "question": "This looks like an MPERS filing. Which standard applies?",
                     "evidence": EVIDENCE, "choices": STANDARD_CHOICES})
FINISH_STEPS = [("run_checks", {}), ("report_coverage", {"lines": [PLANT, PAYABLES]}),
                (FINAL, {"summary": "Done.", "unresolved": ["The test page prints no equity."]})]


def _row(sql: str, *params):
    with db.connect() as conn:
        return conn.execute(sql, params).fetchone()


def _states(run_id: int) -> tuple[str, str]:
    run = _row("SELECT status FROM runs WHERE id = ?", run_id)[0]
    stage = _row("SELECT status FROM stages WHERE run_id = ? AND name = 'extract'", run_id)[0]
    return run, stage


def _confirmed(client, setup=SETUP) -> int:
    run_id = read_run(client)
    response = client.post(f"/api/runs/{run_id}/setup", json=setup)
    assert response.status_code == 200, response.json()
    return run_id


def _deps(run_id: int):
    deps, _ = agent.build_deps(run_id, "SOFP")
    return SimpleNamespace(deps=deps)


def _ask(run_id: int, **overrides) -> str:
    args = {**ASK[1], **overrides}
    args["evidence"] = [ask.Evidence(**e) for e in args["evidence"]]
    args["choices"] = [ask.Choice(**c) for c in args["choices"]]
    return ask.ask_scope(_deps(run_id), **args)


@pytest.fixture
def scripted(monkeypatch):
    def use(steps):
        seen: list = []
        monkeypatch.setattr(factory, "build_model", lambda model_id: script(steps, seen))
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
        return seen
    return use


def test_ask_scope_refuses_what_is_not_a_scope_question(signed_in):
    run_id = _confirmed(signed_in)
    mpers, mfrs = STANDARD_CHOICES
    assert _ask(run_id, field="sign").startswith("Ask only about the scope:")
    assert _ask(run_id, field="layout").startswith("Name the statement whose layout")
    assert _ask(run_id, choices=[mpers]) == "Give two to four choices."
    assert _ask(run_id, choices=[mpers, {**mfrs, "suggested": True}]).startswith(
        "Mark exactly one choice as suggested")
    assert _ask(run_id, choices=[{**mpers, "value": "IFRS"}, mfrs]) == \
        "'IFRS' is not a value for the standard; use MFRS, MPERS."
    assert _ask(run_id, choices=[mpers, {**mfrs, "value": "MPERS"}]) == "Give each choice a different value."
    no_page = "Give the evidence with the PDF page of each line, so the person can check it."
    assert _ask(run_id, evidence=[{"text": "The auditors name MPERS."}]) == no_page
    assert _ask(run_id, evidence=[]) == no_page
    assert _ask(run_id, evidence=[{"text": "x", "page": 9}]) == "Evidence pages must be within the document's 4 pages."
    assert _ask(run_id, field="year_end", choices=[
        {"label": "30 June", "value": "2021-06-30", "effect": "x", "suggested": True},
        {"label": "31 March", "value": "2021-03-31", "effect": "y"}]).startswith(
        "One choice must be the setup as confirmed (2021-12-31)")
    assert _states(run_id) == ("ready", "waiting")   # nothing was asked
    assert _ask(run_id) == ask.ASKED
    assert _ask(run_id) == "A question is already waiting for the person's answer, so stop now."


async def test_an_agent_that_asks_stops_keeps_its_figures_and_waits(signed_in, scripted):
    run_id = _confirmed(signed_in)
    seen = scripted([("save_figures", {"figures": [{"field": "FP-s28", "lines": [
                         {"label": "Plant and equipment", "page": 2, "cy": 1200}]}]}),
                     ASK, ("run_checks", {}), (FINAL, {"summary": "Should never get here."})])
    assert await worker.run_once()

    assert _states(run_id) == ("needs_answer", "asking")
    assert len(seen) == 2   # no model request after the question
    assert value(run_id, "FP-s28") == 1200
    assert _row("SELECT status FROM jobs WHERE run_id = ? AND kind = 'extract'", run_id)[0] == "done"
    body = signed_in.get(f"/api/runs/{run_id}/question").json()["question"]
    assert body["field"] == "standard" and body["status"] == "open" and body["setup_value"] == "MFRS"
    assert body["evidence"][0]["page"] == 3 and [c["suggested"] for c in body["choices"]] == [True, False]
    assert body["asked_by"] == "figures" and body["stage"] == "extract" and body["asked_at"]
    messages = [e["message"] for e in list_events(run_id=run_id)]
    assert "Stopped to ask about the standard." in messages
    assert "Stopped to ask a person about the scope." in messages
    assert not any(m.startswith("Extraction stopped") for m in messages)
    listed = next(r for r in signed_in.get("/api/runs").json()["runs"] if r["id"] == run_id)
    assert listed["status"] == "needs_answer"
    # Comments wait for the answer.
    refused = signed_in.post(f"/api/runs/{run_id}/rounds")
    assert refused.status_code == 409


async def test_answering_with_the_confirmed_value_carries_on_with_the_answer_as_a_fact(signed_in, scripted):
    run_id = _confirmed(signed_in)
    save(run_id, "FP-s28", "CY", 1200, "Plant and equipment")
    save(run_id, "FP-s404", "CY", 300, "Trade payables")
    assert _ask(run_id) == ask.ASKED
    question_id = signed_in.get(f"/api/runs/{run_id}/question").json()["question"]["id"]

    response = signed_in.post(f"/api/runs/{run_id}/question/answer", json={"choice": 1})
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["question"]["answer"]["value"] == "MFRS" and body["question"]["answer"]["setup_changed"] is False
    assert body["question"]["answer"]["by"] == "ana@firm.com" and body["run"]["status"] == "ready"
    assert _row("SELECT standard FROM runs WHERE id = ?", run_id)[0] == "MFRS"
    assert signed_in.get(f"/api/runs/{run_id}/question").json() == {"question": None}

    again = signed_in.post(f"/api/runs/{run_id}/question/answer", json={"choice": 0})
    assert again.status_code == 409 and again.json()["detail"] == "This run has no open question to answer."
    again = signed_in.post(f"/api/runs/{run_id}/question/answer", json={"choice": 0, "question_id": question_id})
    assert again.status_code == 409 and again.json()["detail"] == "This question is already answered."

    seen = scripted(FINISH_STEPS)
    assert await worker.run_once()   # the extraction queued at setup takes the answer: no second job
    assert not await worker.run_once()
    first = seen[0][0].parts[-1].content
    assert "A person answered a scope question in this run." in first
    assert "Answer: «MFRS, as set up»" in first and "Which standard applies?" in first
    assert "- FP-s28 Plant and equipment: CY 1,200" in first
    assert value(run_id, "FP-s28") == 1200
    assert _states(run_id) == ("in_review", "done")
    assert any(e["message"] == "ana@firm.com answered the question about the standard with MFRS, as set up."
               for e in list_events(run_id=run_id))


def test_own_words_carry_on_and_the_answer_is_checked(signed_in):
    run_id = _confirmed(signed_in)
    assert _ask(run_id) == ask.ASKED
    for body, sentence in (({}, "Choose one of the choices or write your own answer, not both."),
                           ({"choice": 0, "text": "MPERS"}, "Choose one of the choices or write your own answer, "
                                                            "not both."),
                           ({"choice": 7}, "There is no such choice."),
                           ({"text": "x" * 1001}, "Keep the answer to 1,000 characters or fewer.")):
        response = signed_in.post(f"/api/runs/{run_id}/question/answer", json=body)
        assert (response.status_code, response.json()["detail"]) == (422, sentence)
    response = signed_in.post(f"/api/runs/{run_id}/question/answer",
                              json={"text": "It is MFRS; the auditors' wording is a template slip."})
    assert response.status_code == 200
    assert response.json()["question"]["answer"]["text"].startswith("It is MFRS")
    assert _states(run_id) == ("ready", "waiting")
    deps, message = agent.build_deps(run_id, "SOFP")
    assert "Answer: «It is MFRS; the auditors' wording is a template slip.»" in message


def test_answering_with_a_change_updates_the_setup_and_clears_only_the_agents_figures(signed_in):
    run_id = _confirmed(signed_in)
    save(run_id, "FP-s28", "CY", 1200, "Plant and equipment")
    save(run_id, "FP-s404", "CY", 300, "Trade payables", actor=store.Actor("person", "ana@firm.com"))
    old_plant = field_uuid(run_id, "FP-s28")
    assert _ask(run_id) == ask.ASKED

    response = signed_in.post(f"/api/runs/{run_id}/question/answer", json={"choice": 0})
    assert response.status_code == 200, response.json()
    answer = response.json()["question"]["answer"]
    assert answer["setup_changed"] is True and answer["cleared"] == 1
    assert tuple(_row("SELECT standard, level FROM runs WHERE id = ?", run_id)) == ("MPERS", "Company")
    plant = _row("SELECT id, value, status, person_edited FROM figures WHERE run_id = ? AND concept_uuid = ?",
                 run_id, old_plant)
    assert (plant["value"], plant["status"], plant["person_edited"]) == (None, "not_disclosed", 0)
    history = _row("SELECT action, actor_kind, actor_name FROM figure_history WHERE figure_id = ? "
                   "ORDER BY id DESC LIMIT 1", plant["id"])
    assert tuple(history) == ("clear", "person", "ana@firm.com")
    kept = _row("SELECT value FROM figures WHERE run_id = ? AND origin = 'person'", run_id)
    assert kept["value"] == 300   # a person's figure is never cleared
    assert _states(run_id) == ("ready", "waiting")
    assert _row("SELECT COUNT(*) FROM jobs WHERE run_id = ? AND kind = 'extract' AND status = 'queued'",
                run_id)[0] == 1
    assert any(e["message"].startswith("Setup changed: the standard is now MPERS; 1 figure(s)")
               for e in list_events(run_id=run_id))
    deps, message = agent.build_deps(run_id, "SOFP")   # the new templates, with the answer
    assert deps.family.standard == "mpers" and "MPERS" in message
    assert "The setup was changed to match" in message


def test_a_change_to_a_layout_the_new_standard_lacks_is_refused(signed_in):
    mpers = {**SETUP, "standard": "MPERS", "statements": [
        *SETUP["statements"][:4], {"statement": "SOCIE", "layout": "SoRE", "included": True, "pages": [2]}]}
    run_id = _confirmed(signed_in, mpers)
    choices = [{"label": "MFRS", "value": "MFRS", "effect": "Restarts", "suggested": True},
               {"label": "MPERS, as set up", "value": "MPERS", "effect": "Carries on"}]
    assert _ask(run_id, choices=choices) == ask.ASKED
    response = signed_in.post(f"/api/runs/{run_id}/question/answer", json={"choice": 0})
    assert response.status_code == 409
    assert response.json()["detail"] == ("The retained earnings layout of the statement of changes in equity does "
                                         "not exist for MFRS filings, so start a new run with the right setup.")
    assert _row("SELECT standard FROM runs WHERE id = ?", run_id)[0] == "MPERS"
    assert signed_in.get(f"/api/runs/{run_id}/question").json()["question"]["status"] == "open"
    assert _states(run_id) == ("needs_answer", "asking")


async def test_an_open_question_survives_a_restart(signed_in, monkeypatch):
    run_id = _confirmed(signed_in)
    assert _ask(run_id) == ask.ASKED

    def no_model(model_id):
        raise AssertionError("No model is called while a question waits.")
    monkeypatch.setattr(factory, "build_model", no_model)
    db.init_db()
    queue.recover_after_restart()
    await job.run_extraction(run_id)   # the job handed back after a restart
    assert _states(run_id) == ("needs_answer", "asking")
    assert signed_in.get(f"/api/runs/{run_id}/question").json()["question"]["status"] == "open"
    assert len(signed_in.get(f"/api/runs/{run_id}/questions").json()["questions"]) == 1


def test_a_question_already_answered_is_not_asked_again(signed_in):
    run_id = _confirmed(signed_in)
    assert _ask(run_id) == ask.ASKED
    assert signed_in.post(f"/api/runs/{run_id}/question/answer", json={"choice": 1}).status_code == 200
    assert _ask(run_id).startswith("The person already answered a question about the standard")


def test_the_setup_gives_a_question_card_for_each_unsure_suggestion(signed_in):
    run_id = read_run(signed_in)
    with db.connect(immediate=True) as conn:
        reading.save_map(conn, run_id, fakes.good_map(unit=fakes.finding("RM", (2,), "No unit is printed.", True)),
                         [])
    questions = signed_in.get(f"/api/runs/{run_id}/setup").json()["setup"]["questions"]
    unit = next(q for q in questions if q["field"] == "unit")
    assert unit["question"] == "Are the amounts in RM or RM thousands?" and unit["pages"] == [2]
    assert [(c["value"], c["label"], c["suggested"]) for c in unit["choices"]] == [
        ("RM", "RM", True), ("RM'000", "RM thousands", False)]
    assert unit["reason"] == "No unit is printed." and all(c["effect"] for c in unit["choices"])
    layout = next(q for q in questions if q["field"] == "layout")
    assert layout["statement"] == "SOPL"   # the fake map is unsure of profit or loss's layout
    # Only what POST /setup accepts: profit or loss has no not-printed layout, so "Not printed" switches it off.
    assert [(c["value"], c["layout"], c["included"], c["suggested"]) for c in layout["choices"]] == [
        ("Function", "Function", True, True), ("Nature", "Nature", True, False), (None, "Function", False, False)]
    assert layout["choices"][-1]["label"] == "Not printed"
    assert not any(q["field"] == "standard" for q in questions)


def test_a_comprehensive_income_card_uses_the_not_prepared_layout(signed_in):
    from app.scope.fields import layout_card_choices

    choices = layout_card_choices("SOCI", "MFRS", {"found": False, "layout": None})
    assert [(c["value"], c["included"], c["suggested"]) for c in choices] == [
        ("BeforeTax", True, False), ("NetOfTax", True, False), ("NotPrepared", False, True)]
    run_id = _confirmed(signed_in)   # a run-time question uses the same name for a statement not printed
    assert _ask(run_id, field="layout", statement="SOCI", question="Is comprehensive income printed?",
                choices=[{"label": "Before tax", "value": "BeforeTax", "effect": "x", "suggested": True},
                         {"label": "Not printed, as set up", "value": "NotPrepared", "effect": "y"}]) == ask.ASKED


def test_an_older_stages_table_is_rebuilt_to_accept_asking():
    make_user("x@y.z")
    with db.connect() as conn:
        conn.execute("INSERT INTO runs(status, owner_email, created_at, updated_at) "
                     "VALUES ('setup', 'x@y.z', 't', 't')")
        conn.execute("INSERT INTO stages(run_id, name, status) VALUES (1, 'read', 'done')")
    raw = sqlite3.connect(db.db_path())
    raw.executescript(
        "PRAGMA foreign_keys = OFF; ALTER TABLE stages RENAME TO stages_old;"
        "CREATE TABLE stages (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES runs(id) "
        "ON DELETE CASCADE, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'waiting' CHECK (status IN ("
        "'waiting', 'working', 'done', 'failed', 'stopped')), started_at TEXT, finished_at TEXT, error TEXT, "
        "UNIQUE (run_id, name)); INSERT INTO stages SELECT id, run_id, name, status, started_at, finished_at, error "
        "FROM stages_old; DROP TABLE stages_old;")
    raw.close()
    db.init_db()
    with db.connect() as conn:
        assert conn.execute("SELECT name, status FROM stages").fetchall()[0][1] == "done"
        conn.execute("INSERT INTO stages(run_id, name, status) VALUES (1, 'extract', 'asking')")


def test_a_layout_change_refiles_that_statement_only(signed_in):
    run_id = _confirmed(signed_in)
    save(run_id, "FP-s28", "CY", 1200, "Plant and equipment")
    choices = [{"label": "Order of liquidity", "value": "OrderOfLiquidity", "effect": "Restarts the balance sheet",
                "suggested": True},
               {"label": "Current and non-current, as set up", "value": "CuNonCu", "effect": "Carries on"}]
    assert _ask(run_id, field="layout", statement="SOFP", question="Which layout does the balance sheet use?",
                choices=choices) == ask.ASKED
    body = signed_in.get(f"/api/runs/{run_id}/question").json()["question"]
    assert (body["field"], body["statement"], body["setup_value"]) == ("layout", "SOFP", "CuNonCu")
    answer = signed_in.post(f"/api/runs/{run_id}/question/answer", json={"choice": 0}).json()["question"]["answer"]
    assert answer["setup_changed"] is True and answer["cleared"] == 1
    assert _row("SELECT variant FROM run_statements WHERE run_id = ? AND statement = 'SOFP'", run_id)[0] == \
        "OrderOfLiquidity"
    assert _row("SELECT standard FROM runs WHERE id = ?", run_id)[0] == "MFRS"


def test_a_standard_change_takes_notes_out_of_fields_the_new_filing_lacks_and_places_them_again(signed_in):
    from app.catalog.note_fields import run_note_fields
    from app.notes import store as notes

    run_id = _confirmed(signed_in)
    with db.connect(immediate=True) as conn:
        field_ = next(f for f in run_note_fields(conn, run_id) if not f.heading and f.template == "LIST_OF_NOTES")
        page, blocks = conn.execute("SELECT p.page, p.content_json FROM pages p JOIN documents d ON "
                                    "d.id = p.document_id WHERE d.run_id = ? AND p.content_json IS NOT NULL "
                                    "ORDER BY p.page LIMIT 1", (run_id,)).fetchone()
        assert json.loads(blocks)["blocks"]
        placed = notes.place_note(conn, run_id, notes.NotePlacement("4", "Plant", [(page, 0)], field_.field_id),
                                  store.Actor("agent", "notes"))
        conn.execute("UPDATE run_setup SET notes_included = 1 WHERE run_id = ?", (run_id,))
        conn.execute("INSERT INTO stages(run_id, name, status) VALUES (?, 'notes', 'done')", (run_id,))
    assert _ask(run_id) == ask.ASKED

    assert signed_in.post(f"/api/runs/{run_id}/question/answer", json={"choice": 0}).status_code == 200

    note = _row("SELECT node_uuid, template_id FROM notes WHERE id = ?", placed["id"])
    assert tuple(note) == (None, None)   # shown as not placed, never silently left out of the fill
    history = _row("SELECT action, actor_name, reason FROM note_history WHERE note_id = ? ORDER BY id DESC LIMIT 1",
                   placed["id"])
    assert (history["action"], history["actor_name"]) == ("clear", "ana@firm.com")
    assert "changed the standard from MFRS to MPERS" in history["reason"]
    assert _row("SELECT status FROM stages WHERE run_id = ? AND name = 'notes'", run_id)[0] == "waiting"
    assert _row("SELECT COUNT(*) FROM jobs WHERE run_id = ? AND kind = 'notes' AND status = 'queued'",
                run_id)[0] == 1
