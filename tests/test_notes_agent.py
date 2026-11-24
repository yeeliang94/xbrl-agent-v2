"""The notes agent end to end with a scripted model (step 6d): the placing
session places, a formatting session sets the look, previews, flags one and
finishes; its finish and preview limits; a stop keeps its notes; everything
it does is recorded. No network. The sessions side by side, coverage by
blocks and re-placing are in test_notes_agent_sessions.py."""
from __future__ import annotations

import json

from pydantic_ai.messages import RetryPromptPart, ToolReturnPart

from app import db
from app.notes import job as notes_job, store
from app.runs.events import list_events
from app.utils.paths import output_dir
from tests.notes_agent_helpers import (FINAL, NUMERIC_GAP, QUIET_SESSION, confirmed_notes_run, field_ids,
                                       returns, script)

PLACE = "place_note"


def placements(ids: dict, numbers=("4", "5", "6")) -> dict:
    wanted = {
        "4": {"note": "4", "field": ids["Disclosure of property, plant and equipment"], "blocks": ["p23b0-p23b2"],
              "reason": "The note is about property, plant and equipment."},
        "5": {"note": "5", "field": ids["catch-all"], "blocks": ["p23b3-p24b0"],
              "reason": "No field covers trade receivables, so the catch-all."},
        "6": {"note": "6", "field": ids["Disclosure of borrowings"], "blocks": ["p24b1-p24b3"],
              "reason": "The note is about borrowings."},
    }
    return {"placements": [wanted[n] for n in numbers], "note": "Placing the notes in their fields."}


LOOK = {"changes": [
    {"note_id": 1, "block": "p23b0", "bold": True},
    {"note_id": 1, "block": "p23b2", "target": "row", "rows": [5], "role": "total", "bold": True,
     "line_below": "double", "line_columns": [2, 3, 4, 5]},
    {"note_id": 1, "block": "p23b2", "target": "column", "columns": [2, 3, 4, 5], "align": "right"},
]}


def placing(ids: dict, numbers=("4", "5", "6"), extra=()) -> list:
    """The placing session: place these notes, report the others as gaps, report coverage, finish."""
    others = [{"note": n, "pages": [23], "reason": "Test."} for n in ("4", "5", "6") if n not in numbers]
    steps = [(PLACE, placements(ids, numbers))] + ([("report_gap", {"gaps": others})] if others else [])
    return steps + list(extra) + [("report_coverage", {}), (FINAL, {"summary": "Placed the notes."})]


def full_script(ids: dict) -> dict:
    return {
        "placing": [("list_notes", {}), *placing(ids)],
        "look": [
            ("show_note_source", {"notes": ["4", "5", "6"]}),
            ("set_look", LOOK),
            ("preview_note", {"note_ids": [1, 2, 3]}),
            ("flag_formatting", {"flags": [{"note_id": 2, "reason": "The source's split cells for trade "
                                                                    "receivables are drawn as plain rows."}]}),
            (FINAL, {"summary": "Set the look of note 4 and previewed all three."}),
        ],
        "numeric": NUMERIC_GAP,
    }


async def test_a_scripted_run_places_every_note_with_history_events_transcript_and_pictures():
    run_id = confirmed_notes_run()
    ids = field_ids(run_id)
    seen: dict = {}
    await notes_job.run_notes(run_id, model=script(full_script(ids), seen))

    with db.connect() as conn:
        stage = conn.execute("SELECT status, error FROM stages WHERE run_id = ? AND name = 'notes'",
                             (run_id,)).fetchone()
        assert tuple(stage) == ("done", None)
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "in_review"
        notes = store.run_notes(conn, run_id, blocks=True)
        by_number = {n["number"]: n for n in notes}
        assert sorted(by_number) == ["4", "5", "6"] and all(n["field"] for n in notes)
        assert by_number["4"]["field"]["node_uuid"] != by_number["5"]["field"]["node_uuid"]
        # The look was set, never the words.
        table = next(b for b in by_number["4"]["blocks"] if b["kind"] == "table")
        assert table["rows"][4]["role"] == "total" and table["rows"][4]["line_below"] == {
            "style": "double", "columns": [1, 2, 3, 4]}
        assert by_number["4"]["blocks"][0]["look"]["bold"] is True
        assert by_number["5"]["format_state"] == "check_formatting"
        assert "split cells" in by_number["5"]["format_reason"]
        history = [h["action"] for h in store.note_history(conn, run_id, by_number["4"]["id"])]
        assert history == ["place", "look"]
        reports = [r["kind"] for r in conn.execute("SELECT kind FROM note_reports WHERE run_id = ?", (run_id,))]
        assert reports == ["source_gap"]
        calls = conn.execute("SELECT COUNT(*), SUM(error IS NULL) FROM model_calls WHERE run_id = ? "
                             "AND source = 'notes'", (run_id,)).fetchone()
    responses = sum(len(v) for v in seen.values())
    assert tuple(calls) == (responses, responses)

    events = list_events(run_id=run_id)
    kinds = {(e["source"], e["kind"]) for e in events}
    assert {("notes", "place"), ("notes", "look"), ("notes", "previewed"), ("notes", "flagged"),
            ("notes", "coverage"), ("notes", "reported"), ("notes", "done")} <= kinds
    # A person reads every message: no field id or block id in it.
    assert not any("LIST-" in e["message"] or "p23b" in e["message"] for e in events), [
        e["message"] for e in events if "LIST-" in e["message"] or "p23b" in e["message"]]
    done = next(e for e in events if e["kind"] == "done" and e["source"] == "notes")
    assert done["message"].startswith("The notes are placed: 3 of 3 listed note(s) placed")

    # Every preview picture, transcript and the session record are kept for the run's export.
    folder = output_dir() / "runs" / f"run-{run_id}"
    pictures = sorted((folder / "note-previews").glob("*.png"))
    assert pictures and all(p.read_bytes().startswith(b"\x89PNG") for p in pictures)
    named = [n for e in events if e["kind"] == "previewed" for n in e["data"]["pictures"]]
    assert len(named) == 3 and sorted(p.name for p in pictures) == sorted(named)
    transcripts = list((output_dir() / "transcripts" / f"run-{run_id}").glob("notes-*.json"))
    assert len(transcripts) == 3
    record = json.loads((folder / "notes.json").read_text())
    assert sorted(s["session"] for s in record["sessions"]) == ["look-1", "numeric", "placing"]
    assert next(s for s in record["sessions"] if s["session"] == "look-1")["notes"] == [1, 2, 3]
    assert record["coverage"]["open"] == []

    # The placing session got every note's text and candidate fields from the start, so it fetched nothing.
    first = seen["placing"][0][0].parts[-1].content
    assert "p23b2 table, 5 rows x 5 columns:" in first and "p24b3 table" in first
    assert "Each note's likely fields from every template" in first and ids["Disclosure of borrowings"] in first
    placed = returns(seen["placing"][-1], PLACE)[0]
    assert "(List of notes) Disclosure of property, plant and equipment" in placed
    # The formatting session got its own notes as placed.
    assert "=== Note id 1: note 4 Property, plant and equipment" in seen["look"][0][0].parts[-1].content

    # The preview said how many tries are left, and the flags and coverage spoke plainly.
    preview = returns(seen["look"][-1], "preview_note")[0]
    text = " ".join(p for p in preview if isinstance(p, str))
    assert "of 32,767 characters, tier full" in text and "note id 1: 2" in text
    assert returns(seen["placing"][-1], "report_coverage")[0].startswith("Every note in the list is placed")


async def test_the_finish_is_refused_while_a_note_is_unaccounted_for():
    run_id = confirmed_notes_run()
    ids = field_ids(run_id)
    seen: dict = {}
    steps = {"numeric": NUMERIC_GAP, "placing": [
        (PLACE, placements(ids, ("4", "6"))),
        ("report_coverage", {}),
        (FINAL, {"summary": "Placed notes 4 and 6."}),
        (FINAL, {"summary": "Placed notes 4 and 6.", "unresolved": ["Note 5 is not placed: test."]}),
    ]}
    await notes_job.run_notes(run_id, model=script(steps, seen))

    messages = seen["placing"][-1]
    coverage = returns(messages, "report_coverage")[0]
    assert "Note 5 is neither placed nor reported." in coverage
    # The refusal comes back on the finish itself, every reason at once.
    answers = [str(p.content) for m in messages for p in getattr(m, "parts", [])
               if isinstance(p, (RetryPromptPart, ToolReturnPart)) and str(p.content).startswith("Not finished yet")]
    assert answers and "Coverage leaves 1 point(s) open: Note 5 is neither placed nor reported." in answers[0]
    record = json.loads((output_dir() / "runs" / f"run-{run_id}" / "notes.json").read_text())
    notes_session = next(s for s in record["sessions"] if s["session"] == "placing")
    assert notes_session["finish"]["unresolved"] == ["Note 5 is not placed: test."]
    assert record["coverage"]["open"] == ["Note 5 is neither placed nor reported."]


async def test_a_fourth_preview_is_refused_in_one_sentence():
    run_id = confirmed_notes_run()
    ids = field_ids(run_id)
    seen: dict = {}
    steps = {"numeric": NUMERIC_GAP, "placing": placing(ids, ("4",)), "look": [
        ("preview_note", {"note_ids": [1]}),
        ("preview_note", {"note_ids": [1]}),
        ("preview_note", {"note_ids": [1]}),
        ("preview_note", {"note_ids": [1]}),
        (FINAL, {"summary": "Previewed note 4."}),
    ]}
    await notes_job.run_notes(run_id, model=script(steps, seen))
    previews = returns(seen["look"][-1], "preview_note")
    lefts = [next(p for p in r if isinstance(p, str)) for r in previews[:3]]
    assert [x.rsplit("Previews left: note id 1: ", 1)[1][0] for x in lefts] == ["2", "1", "0"]
    assert previews[3] == ["Note id 1 has had its three previews, so flag what still differs with "
                           "flag_formatting."]


async def test_set_look_refuses_a_row_that_does_not_exist_and_keeps_the_note():
    run_id = confirmed_notes_run()
    ids = field_ids(run_id)
    seen: dict = {}
    extra = [(PLACE, {"placements": [{"note": "7", "field": ids["Disclosure of borrowings"], "blocks": ["p24b1"]}]})]
    steps = {"numeric": NUMERIC_GAP, "placing": placing(ids, extra=extra), "look": [
        ("set_look", {"changes": [{"note_id": 1, "block": "p23b2", "target": "row", "rows": [9], "bold": True},
                                  {"note_id": 3, "block": "p24b1", "target": "row", "rows": [1], "bold": True}]}),
        ("preview_note", {"note_ids": [1, 2, 3]}),
        (FINAL, {"summary": "Checked the look."}),
    ]}
    await notes_job.run_notes(run_id, model=script(steps, seen))
    look = returns(seen["look"][-1], "set_look")[0]
    assert "- Note id 1: not changed. Table p23b2 has 5 rows, so row 9 does not exist." in look
    assert "- Note id 3: not changed. p24b1 is a heading, so it has no rows, columns or cells; use target block." in look
    double = returns(seen["placing"][-1], PLACE)[1]
    assert "Some of these blocks are already placed" in double and "move that note" in double
    with db.connect() as conn:
        assert [h["action"] for h in store.note_history(conn, run_id, 1)] == ["place"]


async def test_a_stopped_run_keeps_its_notes():
    run_id = confirmed_notes_run()
    ids = field_ids(run_id)

    def stop_after_placing(session, done):
        if session == "placing" and done == 1:
            with db.connect() as conn:
                conn.execute("UPDATE stages SET stop_requested = 1 WHERE run_id = ? AND name = 'notes'", (run_id,))

    steps = {"placing": [(PLACE, placements(ids)), ("list_notes", {}), ("list_notes", {})],
             "numeric": [("list_notes", {})] * 5}
    await notes_job.run_notes(run_id, model=script(steps, {}, on_step=stop_after_placing))
    with db.connect() as conn:
        stage = conn.execute("SELECT status, error FROM stages WHERE run_id = ? AND name = 'notes'",
                             (run_id,)).fetchone()
        assert tuple(stage) == ("stopped", notes_job.STOPPED_SENTENCE)
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "in_review"
        assert len([n for n in store.run_notes(conn, run_id) if n["field"]]) == 3

    # A retry starts again from the notes already placed: the first message lists them.
    from app.runs import extraction
    with db.connect(immediate=True) as conn:
        assert extraction.retry_extraction(conn, run_id) is not None
    seen: dict = {}
    await notes_job.run_notes(run_id, model=script({"placing": QUIET_SESSION, "numeric": NUMERIC_GAP}, seen))
    first = seen["placing"][0][0].parts[-1].content
    assert "Already placed or reported in this run" in first and "4 Property, plant and equipment" in first
    assert "p23b2 table, 5 rows x 5 columns: [placed: note id 1 in" in first
    with db.connect() as conn:
        assert len(store.run_notes(conn, run_id)) == 3


async def test_the_numeric_session_saves_share_capital_figures_by_class_through_the_figure_store():
    from app.catalog import lookup
    from app.notes import agent

    run_id = confirmed_notes_run()
    deps, message = agent.build_deps(run_id, "numeric")
    assert "OrdinarySharesMember" in message and "SC-" in message
    with db.connect() as conn:
        line = next(f for f in deps.outline.fields.values() if f.statement == "ISSUED_CAPITAL" and f.kind == "line"
                    and not lookup.concept(conn, f.concept_uuid).text)
    seen: dict = {}
    gaps = [{"note": n, "pages": [23], "reason": "Test."} for n in ("4", "5", "6")]
    steps = {"placing": [("report_gap", {"gaps": gaps})], "numeric": [
        ("save_figures", {"figures": [
            {"field": line.id, "category": "OrdinarySharesMember",
             "lines": [{"label": "Ordinary shares", "page": 24, "cy": 1000, "py": 1000}]},
            {"field": line.id, "category": "NoSuchMember", "lines": [{"label": "x", "page": 24, "cy": 1}]}]}),
        (FINAL, {"summary": "Saved the ordinary shares."}),
    ]}
    await notes_job.run_notes(run_id, model=script(steps, seen))
    saved = returns(seen["numeric"][-1], "save_figures")[0]
    assert "CY 1,000 saved" in saved and "NoSuchMember is not a category of this sheet" in saved
    with db.connect() as conn:
        rows = [tuple(r) for r in conn.execute("SELECT period, value, dimension_key, origin FROM figures "
                                               "WHERE run_id = ? AND concept_uuid = ? ORDER BY period",
                                               (run_id, line.concept_uuid))]
        history = conn.execute("SELECT COUNT(*) FROM figure_history WHERE run_id = ? AND actor_name = 'notes'",
                               (run_id,)).fetchone()[0]
    assert [r[:2] for r in rows] == [("CY", 1000.0), ("PY", 1000.0)]
    assert all("OrdinarySharesMember" in r[2] and r[3] == "agent" for r in rows) and history == 2


async def test_the_runs_export_holds_its_notes_history_reports_and_preview_pictures():
    import zipfile

    from app.records import traces

    run_id = confirmed_notes_run()
    ids = field_ids(run_id)
    await notes_job.run_notes(run_id, model=script(full_script(ids), {}))
    with db.connect() as conn:
        path = traces.build(conn, run_id, include_pdf=False)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        notes = json.loads(zf.read("notes.json"))
        reports = json.loads(zf.read("note_reports.json"))
    path.unlink()
    assert [n["note_number"] for n in notes] == ["4", "5", "6"]
    assert [h["action"] for h in notes[0]["history"]] == ["place", "look"]
    assert [r["kind"] for r in reports] == ["source_gap"]
    assert "records/notes.json" in names
    assert any(n.startswith("records/note-previews/") and n.endswith(".png") for n in names)
    assert sum(n.startswith("transcripts/notes-") for n in names) == 3
