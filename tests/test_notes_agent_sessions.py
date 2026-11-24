"""The notes agent's sessions side by side, with scripted models: placing and
the numeric figures run at once, then the formatting sessions run at once,
each on its own notes; coverage is checked by source blocks across them; a
note placed again with other blocks is replaced, the share capital double is
a second placement; a failed or asking session leaves the others' work
correct. No network."""
from __future__ import annotations

import asyncio
import json

from pydantic_ai.messages import RetryPromptPart, ToolReturnPart

from app import db
from app.notes import briefing, job as notes_job, store
from app.runs.events import list_events
from app.utils.paths import output_dir
from tests.notes_agent_helpers import FINAL, NUMERIC_GAP, confirmed_notes_run, field_ids, returns, script
from tests.test_notes_agent import placements, placing

PLACE = "place_note"
ASK = ("ask_scope", {
    "field": "unit", "question": "The notes print amounts in thousands. Which unit applies?",
    "evidence": [{"text": "Amounts in RM'000", "page": 23}, {"text": "Amounts in RM", "page": 24}],
    "choices": [{"label": "RM, as set up", "value": "RM", "effect": "Carries on", "suggested": False},
                {"label": "RM'000", "value": "RM'000", "effect": "Restarts with the new unit", "suggested": True}]})


def stage(run_id: int) -> tuple:
    with db.connect() as conn:
        return tuple(conn.execute("SELECT status, error FROM stages WHERE run_id = ? AND name = 'notes'",
                                  (run_id,)).fetchone())


def record(run_id: int) -> dict:
    return json.loads((output_dir() / "runs" / f"run-{run_id}" / "notes.json").read_text())


def refusals(messages) -> list[str]:
    return [str(p.content) for m in messages for p in getattr(m, "parts", [])
            if isinstance(p, (RetryPromptPart, ToolReturnPart)) and str(p.content).startswith("Not finished yet")]


async def test_placing_and_the_figures_run_at_once_then_one_formatting_session_per_group_at_once(monkeypatch):
    monkeypatch.setattr(briefing, "LOOK_NOTES", 1)   # one table note a session: three formatting sessions
    run_id = confirmed_notes_run()
    ids = field_ids(run_id)
    first_pair, looks = asyncio.Barrier(2), asyncio.Barrier(3)

    async def hold(session, done):
        # Each barrier opens only when its sessions are all waiting at once; run one after another, it times out.
        if done == 0 and session in ("placing", "numeric"):
            await asyncio.wait_for(first_pair.wait(), 5)
        if done == 0 and session == "look":
            await asyncio.wait_for(looks.wait(), 5)

    seen: dict = {}
    steps = {"placing": placing(ids), "numeric": NUMERIC_GAP,
             "look": [("preview_note", {"note_ids": [1, 2, 3]}), (FINAL, {"summary": "Previewed my note."})]}
    await notes_job.run_notes(run_id, model=script(steps, seen, before=hold))

    assert stage(run_id) == ("done", None)
    sessions = {s["session"]: s for s in record(run_id)["sessions"]}
    assert sorted(sessions) == ["look-1", "look-2", "look-3", "numeric", "placing"]
    assert sorted(n for k in ("look-1", "look-2", "look-3") for n in sessions[k]["notes"]) == [1, 2, 3]
    assert all(s["status"] == "completed" and s["transcript"] for s in sessions.values())
    transcripts = list((output_dir() / "transcripts" / f"run-{run_id}").glob("notes-*.json"))
    assert len(transcripts) == 5
    # Each formatting session previews only its own note: the others' are another session's.
    for messages in seen["look"]:
        for result in returns(messages, "preview_note"):
            assert sum(isinstance(p, str) and p.startswith("LIST-") for p in result) <= 3
    with db.connect() as conn:
        assert conn.execute("SELECT working_on FROM stages WHERE run_id = ? AND name = 'notes'",
                            (run_id,)).fetchone()[0] is None
    started = [e["data"]["session"] for e in list_events(run_id=run_id) if e["kind"] == "session"]
    assert sorted(started) == ["look-1", "look-2", "look-3", "numeric", "placing"]


async def test_a_formatting_session_leaves_another_sessions_note_alone(monkeypatch):
    monkeypatch.setattr(briefing, "LOOK_NOTES", 1)
    run_id = confirmed_notes_run()
    ids = field_ids(run_id)
    seen: dict = {}
    every = {"changes": [{"note_id": i, "block": b, "bold": True} for i, b in ((1, "p23b0"), (2, "p23b3"),
                                                                               (3, "p24b1"))]}
    steps = {"placing": placing(ids), "numeric": NUMERIC_GAP,
             "look": [("set_look", every), ("preview_note", {"note_ids": [1, 2, 3]}), (FINAL, {"summary": "Done."})]}
    await notes_job.run_notes(run_id, model=script(steps, seen))
    results = [r for m in seen["look"] for r in returns(m, "set_look")]
    assert results and all(r.count("look changed") == 1 and r.count("Another formatting session working beside "
                                                                    "this one has this note") == 2 for r in results)
    with db.connect() as conn:
        assert all([h["action"] for h in store.note_history(conn, run_id, i)] == ["place", "look"] for i in (1, 2, 3))


async def test_coverage_counts_blocks_and_a_note_placed_again_with_other_blocks_replaces_them():
    run_id = confirmed_notes_run()
    ids = field_ids(run_id)
    seen: dict = {}
    partial = placements(ids)
    partial["placements"][0]["blocks"] = ["p23b0", "p23b2"]   # note 4 without its paragraph
    steps = {"numeric": NUMERIC_GAP, "placing": [
        (PLACE, partial),
        ("report_coverage", {}),
        (FINAL, {"summary": "Placed the notes."}),
        (PLACE, placements(ids, ("4",))),
        ("report_coverage", {}),
        (FINAL, {"summary": "Placed the notes."}),
    ]}
    await notes_job.run_notes(run_id, model=script(steps, seen))
    messages = seen["placing"][-1]
    first, again = returns(messages, PLACE)
    assert "Still open for these notes:\n- Note 4: placed; 1 of 3 blocks are in no field (p23b1)." in first
    assert "Note 4: placed again from 3 other blocks in" in again and "Still open" not in again
    assert "Note 4: placed; 1 of 3 blocks are in no field (p23b1)." in refusals(messages)[0]
    assert returns(messages, "report_coverage")[-1].startswith("Every note in the list is placed")
    with db.connect() as conn:
        note = next(n for n in store.run_notes(conn, run_id, blocks=True) if n["number"] == "4")
        assert [b["id"] for b in note["blocks"]] == ["p23b0", "p23b1", "p23b2"]
        assert [h["action"] for h in store.note_history(conn, run_id, note["id"])] == ["place", "place"]
    assert stage(run_id) == ("done", None)


async def test_half_a_split_note_stays_open_and_is_recorded_open_at_the_end():
    run_id = confirmed_notes_run()
    ids = field_ids(run_id)
    seen: dict = {}
    half = placements(ids)
    half["placements"][0].update(blocks=["p23b2"], part=2, parts=2)   # only the table, as part 2 of 2
    steps = {"numeric": NUMERIC_GAP, "placing": [
        (PLACE, half),
        ("report_gap", {"gaps": [{"note": "4", "pages": [23], "reason": "Routed by a test."}]}),
        ("report_coverage", {}),
        (FINAL, {"summary": "Placed the notes."}),
        (FINAL, {"summary": "Placed the notes.", "unresolved": ["Note 4's first part is left: test."]}),
    ]}
    await notes_job.run_notes(run_id, model=script(steps, seen))
    point = "Note 4: part 2 of 2 placed; 2 of 3 blocks are in no field (p23b0-p23b1); part 1 is not placed."
    assert point in returns(seen["placing"][-1], "report_coverage")[0]   # a report does not excuse it
    assert record(run_id)["coverage"]["open"] == [point]
    done = next(e for e in list_events(run_id=run_id) if e["kind"] == "done" and e["source"] == "notes")
    assert "1 point(s) open" in done["message"]


def _note_six(field: str, double: bool = False) -> tuple:
    return (PLACE, {"placements": [{"note": "6", "field": field, "blocks": ["p24b1-p24b3"], "double": double,
                                    "reason": "Test: share capital."}]})


async def test_the_share_capital_double_is_a_second_placement_not_a_move_and_a_repeat_reuses_it():
    run_id = confirmed_notes_run()
    ids = field_ids(run_id)
    seen: dict = {}
    steps = {"numeric": NUMERIC_GAP, "placing": [
        (PLACE, placements(ids, ("4", "5"))), _note_six(ids["Disclosure of share capital"]),
        _note_six("SCT-4", double=True), _note_six("SCT-4", double=True),
        ("report_coverage", {}), (FINAL, {"summary": "Placed the notes."})]}
    await notes_job.run_notes(run_id, model=script(steps, seen))
    said = returns(seen["placing"][-1], PLACE)
    assert "placed in" in said[2] and "already in" in said[3]
    with db.connect() as conn:
        sixes = [n for n in store.run_notes(conn, run_id) if n["number"] == "6"]
    assert sorted(n["field"]["label"] for n in sixes) == ["Disclosure of classes of share capital",
                                                         "Disclosure of share capital"]


async def test_a_double_outside_the_share_capital_fields_is_refused_with_what_to_do():
    run_id = confirmed_notes_run()
    ids = field_ids(run_id)
    seen: dict = {}
    steps = {"numeric": NUMERIC_GAP, "placing": placing(ids, extra=[
        _note_six(ids["catch-all"], double=True), _note_six("SCT-4", double=True)])}
    await notes_job.run_notes(run_id, model=script(steps, seen))
    said = returns(seen["placing"][-1], PLACE)
    assert "is not a share capital field" in said[1] and "set double to false" in said[1]
    assert "already placed: note id 3 (note 6 Borrowings)" in said[2] and "move that note" in said[2]
    with db.connect() as conn:
        assert len([n for n in store.run_notes(conn, run_id) if n["number"] == "6"]) == 1


async def test_a_failed_session_leaves_the_others_to_finish_and_the_stage_fails_keeping_the_notes():
    run_id = confirmed_notes_run()
    ids = field_ids(run_id)

    async def broken_numeric(session, done):
        if session == "numeric":
            raise RuntimeError("test: the provider is down")
        await asyncio.sleep(0.01)

    seen: dict = {}
    steps = {"placing": placing(ids), "look": [("preview_note", {"note_ids": [1, 2, 3]}), (FINAL, {"summary": "x"})]}
    await_failed = None
    try:
        await notes_job.run_notes(run_id, model=script(steps, seen, before=broken_numeric))
    except notes_job.NotesFailed as exc:
        await_failed = str(exc)
    assert await_failed and await_failed.endswith("the notes placed so far are kept.")
    assert stage(run_id) == ("failed", await_failed)
    sessions = {s["session"]: s["status"] for s in record(run_id)["sessions"]}
    assert sessions == {"numeric": "failed", "placing": "completed", "look-1": "completed"}
    with db.connect() as conn:
        assert len([n for n in store.run_notes(conn, run_id) if n["field"]]) == 3


async def test_a_scope_question_from_the_figures_session_stops_placing_and_no_formatting_starts():
    run_id = confirmed_notes_run()
    ids = field_ids(run_id)

    async def after_the_question(session, done):
        if session == "numeric" and done == 0:   # it asks once placing has placed, so the test does not race
            for _ in range(100):
                with db.connect() as conn:
                    if conn.execute("SELECT COUNT(*) FROM notes WHERE run_id = ?", (run_id,)).fetchone()[0] == 3:
                        return
                await asyncio.sleep(0.02)
        if session == "placing" and done == 1:
            for _ in range(100):
                with db.connect() as conn:
                    if conn.execute("SELECT 1 FROM scope_questions WHERE run_id = ?", (run_id,)).fetchone():
                        return
                await asyncio.sleep(0.02)

    seen: dict = {}
    steps = {"numeric": [ASK], "placing": [(PLACE, placements(ids)), ("list_notes", {}), ("list_notes", {})]}
    await notes_job.run_notes(run_id, model=script(steps, seen, before=after_the_question))
    assert stage(run_id)[0] == "asking"
    sessions = {s["session"]: s["status"] for s in record(run_id)["sessions"]}
    assert sessions == {"numeric": "stopped", "placing": "stopped"} and "look" not in seen
    with db.connect() as conn:
        assert len([n for n in store.run_notes(conn, run_id) if n["field"]]) == 3
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "needs_answer"


async def test_an_answer_that_lands_before_the_last_session_ends_starts_the_stage_again_with_fresh_sessions():
    run_id = confirmed_notes_run()
    ids = field_ids(run_id)
    answered: list[bool] = []

    async def answer_once_asked(session, done):
        if session == "numeric" and done == 0 and not answered:   # it asks once placing has placed
            for _ in range(100):
                with db.connect() as conn:
                    if conn.execute("SELECT COUNT(*) FROM notes WHERE run_id = ?", (run_id,)).fetchone()[0] == 3:
                        break
                await asyncio.sleep(0.02)
        if session == "placing" and done == 1 and not answered:
            for _ in range(100):
                with db.connect() as conn:
                    if conn.execute("SELECT 1 FROM scope_questions WHERE run_id = ?", (run_id,)).fetchone():
                        break
                await asyncio.sleep(0.02)
            with db.connect() as conn:   # a person answers while placing is still mid-step
                conn.execute("UPDATE scope_questions SET status = 'answered', answered_at = ? WHERE run_id = ?",
                             (db.now(), run_id))
            answered.append(True)
            # Once answered, each session starts again and works to its end.
            steps["numeric"], steps["placing"] = NUMERIC_GAP, placing(ids)

    seen: dict = {}
    steps = {"numeric": [ASK], "placing": [(PLACE, placements(ids)), ("list_notes", {}), ("list_notes", {})]}
    await notes_job.run_notes(run_id, model=script(steps, seen, before=answer_once_asked))
    assert answered and stage(run_id)[0] == "done"
    kept = record(run_id)
    assert kept["restarts"] == 1
    assert [s["session"] for s in kept["sessions"]].count("placing") == 2
    assert [s["status"] for s in kept["sessions"] if s["session"] == "numeric"] == ["stopped", "completed"]
    assert any("starts again" in e["message"] for e in list_events(run_id=run_id) if e["source"] == "notes")
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] != "needs_answer"


async def test_a_stop_ends_every_session_between_steps():
    run_id = confirmed_notes_run()
    ids = field_ids(run_id)

    def stop_once_placed(session, done):
        if session == "placing" and done == 1:
            with db.connect() as conn:
                conn.execute("UPDATE stages SET stop_requested = 1 WHERE run_id = ? AND name = 'notes'", (run_id,))

    async def slow_numeric(session, done):
        await asyncio.sleep(0.05 if session == "numeric" else 0)

    steps = {"placing": [(PLACE, placements(ids)), ("list_notes", {})], "numeric": [("list_notes", {})] * 20}
    await notes_job.run_notes(run_id, model=script(steps, {}, on_step=stop_once_placed, before=slow_numeric))
    assert stage(run_id) == ("stopped", notes_job.STOPPED_SENTENCE)
    sessions = {s["session"]: s for s in record(run_id)["sessions"]}
    assert sorted(sessions) == ["numeric", "placing"] and all(s["status"] == "stopped" for s in sessions.values())
    assert sessions["numeric"]["steps"] < 20

