"""Regression tests for the step 5 review panel's server findings: a move is
all or nothing, Undo refuses what it would misstate or wipe and puts an
added figure back exactly, a proposed line of an undone change is refused, a
repeated scope question is found, a round always ends, recording guidance
never ends a run, the change report counts what a person sees, "newly
failing" means passed to failing, agents' notes become the activity, and the
rounds list says what Accept all would take. No network."""
from __future__ import annotations

import logging
from types import SimpleNamespace

from app import db
from app.extraction import agent as figures_agent, instructions as figures_instructions
from app.figures import store
from app.guidance import framing
from app.jobs import worker
from app.models import factory
from app.review import agent as review_agent, changes, instructions as review_instructions, job as review_job
from app.review import tools
from app.runs.events import list_events
from app.scope import ask
from tests.review_helpers import comment_on, field_uuid, reviewed_run, save, value
from tests.test_extraction_job import FINAL, SETUP, read_run, script, signed_in  # noqa: F401 - the fixture
from tests.test_review_comments import REVIEWER, _round, _work
from tests.test_scope_questions import _ask

PERSON = store.Actor("person", "ana@firm.com")


def _figure(run_id: int, field_id: str, period: str = "CY"):
    with db.connect() as conn:
        return conn.execute("SELECT * FROM figures WHERE run_id = ? AND concept_uuid = ? AND period = ?",
                            (run_id, field_uuid(run_id, field_id), period)).fetchone()


def _reviewer_ctx(round_id: int):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM rounds WHERE id = ?", (round_id,)).fetchone()
    deps, _ = review_agent.build_deps(row)
    return SimpleNamespace(deps=deps)


def test_a_move_refused_for_its_second_year_saves_nothing(signed_in):
    run_id = reviewed_run(signed_in)
    save(run_id, "FP-s28", "PY", 1000, "Plant and equipment")
    save(run_id, "FP-s404", "PY", 80, "Trade payables")
    with db.connect() as conn:   # last year's payables are kept as filed: the PY half of the move is refused
        conn.execute("UPDATE figures SET locked = 1 WHERE id = ?", (_figure(run_id, "FP-s404", "PY")["id"],))
    cid = comment_on(signed_in, run_id, "FP-s28")["id"]
    sent = _round(signed_in, run_id)
    result = tools.move_figures(_reviewer_ctx(sent["id"]), [tools.Move(field="FP-s28", to_field="FP-s404",
                                                                       comment_ids=[cid])])
    assert result.startswith("Moved 0 of 1.")
    assert "not moved, and nothing of this move was saved." in result
    assert (value(run_id, "FP-s28"), value(run_id, "FP-s404")) == (1200, 250)   # the CY half was taken back
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM figure_history WHERE round_id = ?", (sent["id"],)).fetchone()[0] == 0


def test_undo_refuses_to_reverse_another_comment_already_accepted(signed_in):
    run_id = reviewed_run(signed_in)
    first = comment_on(signed_in, run_id, "FP-s404", text="Page 2 prints 300.")["id"]
    second = comment_on(signed_in, run_id, "FP-s404", text="Check payables.", scope="run")["id"]
    sent = _round(signed_in, run_id)
    _work(run_id, sent["id"], [("FP-s404", "CY", 300, "Trade payables", [first, second])],
          [(first, "changed", "Used 300."), (second, "changed", "Used 300.")])
    assert signed_in.post(f"/api/runs/{run_id}/comments/{second}/accept").status_code == 200
    response = signed_in.post(f"/api/runs/{run_id}/comments/{first}/undo")
    assert response.status_code == 409
    assert response.json()["detail"] == (f"This would also reverse comment {second}'s change, which is already "
                                         "accepted, so restore the figure from its history instead.")
    assert value(run_id, "FP-s404") == 300


def test_undo_never_wipes_a_persons_edit_made_while_the_round_worked(signed_in):
    run_id = reviewed_run(signed_in)
    cid = comment_on(signed_in, run_id, "FP-s404")["id"]
    sent = _round(signed_in, run_id)
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE rounds SET status = 'working' WHERE id = ?", (sent["id"],))
    with store.tagged(sent["id"], [cid]):
        save(run_id, "FP-s404", "CY", 300, "Trade payables", actor=REVIEWER)
    save(run_id, "FP-s404", "CY", 310, "Trade payables", actor=PERSON)   # a person, mid-round
    with store.tagged(sent["id"], [cid]):
        save(run_id, "FP-s404", "CY", 320, "Trade payables", actor=REVIEWER)
    _work(run_id, sent["id"], [], [(cid, "changed", "Used 320.")])
    response = signed_in.post(f"/api/runs/{run_id}/comments/{cid}/undo")
    assert response.status_code == 409
    assert response.json()["detail"] == ("Trade payables was changed outside this round after the round first "
                                         "wrote it, so restore it from its history instead.")


def test_undo_of_a_figure_the_round_added_is_not_a_persons_edit(signed_in):
    run_id = reviewed_run(signed_in)
    cid = comment_on(signed_in, run_id, "FP-s28", "PY")["id"]
    sent = _round(signed_in, run_id)
    _work(run_id, sent["id"], [("FP-s28", "PY", 1000, "Plant and equipment", [cid])], [(cid, "changed", "Added.")])
    assert signed_in.post(f"/api/runs/{run_id}/comments/{cid}/undo").status_code == 200
    row = _figure(run_id, "FP-s28", "PY")
    assert (row["value"], row["person_edited"], row["origin"]) == (None, 0, "agent")


def test_the_guidance_line_of_an_undone_change_cannot_be_added(signed_in):
    run_id = reviewed_run(signed_in)
    cid = comment_on(signed_in, run_id, "FP-s404", scope="company")["id"]
    with db.connect() as conn:
        conn.execute("UPDATE comments SET status = 'undone', outcome = 'changed', proposed_guidance = 'A line.' "
                     "WHERE id = ?", (cid,))
    response = signed_in.post(f"/api/runs/{run_id}/comments/{cid}/guidance")
    assert (response.status_code, response.json()["detail"]) == (
        409, "This change was undone, so its guidance line cannot be added.")


def test_an_answered_unit_question_is_not_asked_again_whatever_statement_is_passed(signed_in):
    run_id = read_run(signed_in)
    assert signed_in.post(f"/api/runs/{run_id}/setup", json=SETUP).status_code == 200
    choices = [{"label": "RM thousands", "value": "RM'000", "effect": "x", "suggested": True},
               {"label": "RM", "value": "RM", "effect": "y"}]
    assert _ask(run_id, field="unit", statement="SOFP", choices=choices) == ask.ASKED
    assert signed_in.post(f"/api/runs/{run_id}/question/answer", json={"choice": 1}).status_code == 200
    assert _ask(run_id, field="unit", statement="SOFP", choices=choices).startswith(
        "The person already answered a question about the unit")


async def test_a_round_whose_result_cannot_be_recorded_still_ends(signed_in, monkeypatch):
    run_id = reviewed_run(signed_in)
    cid = comment_on(signed_in, run_id, "FP-s404")["id"]
    monkeypatch.setattr(factory, "build_model", lambda model_id: script([
        ("answer_comment", {"answers": [{"comment_id": cid, "outcome": "not_changed", "answer": "As printed."}]}),
        (FINAL, {"summary": "Nothing changed."})], []))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")

    def broken(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(review_job, "_record", broken)
    sent = _round(signed_in, run_id)
    assert await worker.run_once()
    with db.connect() as conn:
        status = conn.execute("SELECT status, error FROM rounds WHERE id = ?", (sent["id"],)).fetchone()
        run = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
    assert status["status"] == "failed" and status["error"].startswith("The round stopped on an unexpected error")
    assert run == "in_review"


def test_guidance_is_still_given_when_recording_it_fails(signed_in, caplog):
    run_id = reviewed_run(signed_in)
    with db.connect() as conn:
        conn.execute("DROP TABLE run_guidance")
    with caplog.at_level(logging.ERROR):
        assert framing.prepare(run_id, "extract") == ""
    assert "could not record the guidance versions" in caplog.text


def test_a_change_of_certainty_alone_counts_and_says_what_moved(signed_in):
    run_id = reviewed_run(signed_in)
    cid = comment_on(signed_in, run_id, "FP-s404")["id"]
    sent = _round(signed_in, run_id)
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE rounds SET status = 'working' WHERE id = ?", (sent["id"],))
    with store.tagged(sent["id"], [cid]):
        save(run_id, "FP-s404", "CY", 250, "Trade payables", actor=REVIEWER, certainty="unsure",
             reason="The note does not split it.")
    with db.connect() as conn:
        rep = changes.report(conn, run_id, sent["id"])
    figure = rep["comments"][0]["figures"][0]
    assert figure["changed"] is True and rep["comments"][0]["changed"] is True
    assert figure["differences"] == ["certainty sure → unsure", "reason changed"]
    assert "was 250, is now 250 (certainty sure → unsure, reason changed)" in changes.report_text(rep)


def test_newly_failing_is_a_relevant_check_gone_from_passed_to_failing():
    def check(name, status):
        return {"name": name, "entity_scope": "Company", "status": status, "title": name, "message": ""}
    before = [check("a", "passed"), check("b", "passed"), check("c", "passed"), check("d", "passed")]
    now = [check("a", "failed"), check("b", "not_assessed"), check("c", "not_applicable"), check("d", "warning")]
    summary = changes.check_summary(before, now, relevant=lambda name: name != "d")
    assert [c["name"] for c in summary["newly_failing"]] == ["a"]
    text = review_instructions.instructions(False, "off.")
    assert "lead to trace" in text and "not_fixable" not in text and "explain it in explained" in text


async def test_an_agents_notes_are_the_activity_and_internal_rows_can_be_left_out(signed_in):
    run_id = reviewed_run(signed_in)
    await figures_agent.run_figures(run_id, "SOFP", "gpt-6-luna", max_steps=4, model=script([
        ("read_pages", {"pages": [2], "note": "Reading the balance sheet to find plant and equipment."}),
        ("save_figures", {"figures": [{"field": "FP-s28", "lines": [{"label": "Plant", "page": 2, "cy": 1200}]}],
                          "note": "Saving plant and equipment from page 2."}),
        (FINAL, {"summary": "x"})], []))
    events = list_events(run_id=run_id)
    looked = next(e for e in events if e["kind"] == "looked")
    assert looked["message"] == "Reading the balance sheet to find plant and equipment." and looked["pages"] == [2]
    saved = next(e for e in events if e["kind"] == "saved")
    assert saved["message"] == "Saving plant and equipment from page 2." and saved["pages"] == [2]
    every = signed_in.get(f"/api/runs/{run_id}/events?limit=500").json()["events"]
    shown = signed_in.get(f"/api/runs/{run_id}/events?limit=500&hide_internal=true").json()["events"]
    assert {e["kind"] for e in every} >= {"step", "tool"}
    assert not {e["kind"] for e in shown} & {"step", "tool"} and len(shown) < len(every)
    assert "take a note" in figures_instructions.instructions(False, "off.")
    assert "take a note" in review_instructions.instructions(False, "off.")


def test_the_reviewers_answer_note_is_its_activity_row(signed_in):
    run_id = reviewed_run(signed_in)
    cid = comment_on(signed_in, run_id, "FP-s404")["id"]
    sent = _round(signed_in, run_id)
    tools.answer_comment(_reviewer_ctx(sent["id"]), [tools.Answer(comment_id=cid, outcome="not_changed",
                                                                  answer="Page 2 prints 250.")],
                         note="Page 2 confirms the payables, so nothing changes.")
    answered = next(e for e in list_events(run_id=run_id) if e["kind"] == "answered" and e["source"] == "review")
    assert answered["message"] == "Page 2 confirms the payables, so nothing changes."


def test_the_rounds_list_says_what_accept_all_would_take(signed_in):
    run_id = reviewed_run(signed_in)
    assert signed_in.get(f"/api/runs/{run_id}/rounds").json()["accept_all"] == {"round_id": None, "comment_ids": []}
    one = comment_on(signed_in, run_id, "FP-s404")["id"]
    two = comment_on(signed_in, run_id, "FP-s28")["id"]
    sent = _round(signed_in, run_id)
    _work(run_id, sent["id"], [("FP-s404", "CY", 300, "Trade payables", [one])],
          [(one, "changed", "Used 300."), (two, "question", "Which year?")])
    body = signed_in.get(f"/api/runs/{run_id}/rounds").json()
    assert body["accept_all"] == {"round_id": sent["id"], "comment_ids": [one]}
