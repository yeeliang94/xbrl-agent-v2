"""A person never reads a field id. Whatever an agent writes for a person
(comments, answers, guidance lines, the round's summary, a figure's reason,
a scope question, activity notes) is stored with each id the outline knows
turned into the name a person finds the field by. Nothing is refused for
it. No network."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import db
from app.catalog.lookup import run_family
from app.extraction import agent as figures_agent, outline as outline_mod
from app.figures import store
from app.jobs import worker
from app.models import factory
from app.review import agent as review_agent, tools
from app.runs.events import list_events
from tests.conftest import make_run
from tests.review_helpers import comment_on, reviewed_run, save
from tests.test_extraction_job import FINAL, SETUP, read_run, script, signed_in  # noqa: F401 - the fixture
from tests.test_review_comments import REVIEWER, _round
from tests.test_scope_questions import _ask

# "Trade payables" repeats on the balance sheet (current and non-current), so its heading goes in front.
PAYABLES = "Current trade payables › Trade payables"
ALL = (("SOFP", "CuNonCu"), ("SOPL", "Function"), ("SOCI", "BeforeTax"), ("SOCF", "Indirect"), ("SOCIE", "Default"))


@pytest.fixture
def five():
    run_id = make_run(ALL)
    with db.connect() as conn:
        return outline_mod.build(conn, run_family(conn, run_id))


def _scripted(monkeypatch, steps, seen=None):
    monkeypatch.setattr(factory, "build_model", lambda model_id: script(steps, [] if seen is None else seen))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")


def test_every_id_of_a_five_statement_outline_is_found_and_named(five):
    assert len(five.fields) > 1000
    for f in five.fields.values():
        assert outline_mod._ID_TOKEN.fullmatch(f.id), f.id
        assert five.readable(f"See {f.id}.") == f"See {five.person_name(f)}.", f.id


def test_no_two_fields_of_a_statement_read_the_same(five):
    # An asset and a liability with the same label under same-named headings (Codex, 23 November 2026).
    assert five.readable("FP-s123") != five.readable("FP-s324")
    seen: dict[tuple[str, str], str] = {}
    for f in five.fields.values():
        if f.kind == outline_mod.HEADING:
            continue
        key = (f.statement, five.person_name(f).lower())
        other = seen.setdefault(key, f.id)
        assert other == f.id or five.fields[other].path + (five.fields[other].name,) == f.path + (f.name,), (
            f"{other} and {f.id} both read {key[1]!r}")


def test_names_carry_the_equity_column_and_the_heading_of_a_repeated_label(five):
    assert five.readable("CE-6-B was blank.") == "Equity at beginning of period (Issued capital) was blank."
    assert five.readable("CE-6-C") == "Equity at beginning of period (Retained earnings)"
    assert five.readable("CF-68 and CF-98") == ("Changes in working capital › Dividends received and "
                                                "Cash flows from (used in) investing activities › Dividends received")
    assert five.readable("FP-s28") == "Plant and equipment"   # a label used once keeps no heading
    assert five.readable("Per MFRS-9 and IAS-16, FP-s28-and FP-s28.") == (
        "Per MFRS-9 and IAS-16, Plant and equipment-and Plant and equipment.")


async def test_an_agents_comment_note_and_answer_are_stored_with_names(signed_in, monkeypatch):
    run_id = reviewed_run(signed_in)
    cid = comment_on(signed_in, run_id, "FP-s404")["id"]
    _scripted(monkeypatch, [
        ("read_pages", {"pages": [2], "note": "Checking FP-s404 on the face, and MFRS-9 wording."}),
        ("leave_comment", {"comments": [{"field": "FP-s28", "period": "CY", "text": "FP-s28 has no split."}]}),
        ("answer_comment", {"answers": [{"comment_id": cid, "outcome": "not_changed",
                                         "answer": "FP-s404 matches page 2."}]}),
        (FINAL, {"summary": "Checked FP-s404 against page 2."}),
    ])
    sent = _round(signed_in, run_id)
    assert await worker.run_once()

    with db.connect() as conn:
        answer = conn.execute("SELECT answer FROM comments WHERE id = ?", (cid,)).fetchone()[0]
        left = conn.execute("SELECT text FROM comments WHERE author_kind = 'agent'").fetchone()[0]
        summary = conn.execute("SELECT summary FROM rounds WHERE id = ?", (sent["id"],)).fetchone()[0]
    assert answer == f"{PAYABLES} matches page 2."
    assert left == "Plant and equipment has no split."
    assert summary == f"Checked {PAYABLES} against page 2."
    events = [e for e in list_events(run_id=run_id) if e["source"] == "review"]
    looked = next(e for e in events if e["kind"] == "looked")
    assert looked["message"] == f"Checking {PAYABLES} on the face, and MFRS-9 wording."   # an unknown id stays
    assert looked["data"]["raw"] == "Checking FP-s404 on the face, and MFRS-9 wording."
    assert "Left a comment on Plant and equipment, this year." in [e["message"] for e in events]
    assert not any("FP-s" in e["message"] for e in events if e["kind"] not in ("step", "tool"))


def test_a_proposed_guidance_line_is_stored_with_names(signed_in):
    run_id = reviewed_run(signed_in)
    cid = comment_on(signed_in, run_id, "FP-s404", scope="company")["id"]
    sent = _round(signed_in, run_id)
    with store.tagged(sent["id"], [cid]):
        save(run_id, "FP-s404", "CY", 300, "Trade payables", actor=REVIEWER)
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM rounds WHERE id = ?", (sent["id"],)).fetchone()
    deps, _ = review_agent.build_deps(row)
    tools.answer_comment(SimpleNamespace(deps=deps), [tools.Answer(
        comment_id=cid, outcome="changed", answer="Used page 2 for FP-s404.",
        proposed_guidance="Read FP-s404 from the face, not the note.")])
    with db.connect() as conn:
        stored = conn.execute("SELECT answer, proposed_guidance FROM comments WHERE id = ?", (cid,)).fetchone()
    assert tuple(stored) == (f"Used page 2 for {PAYABLES}.", f"Read {PAYABLES} from the face, not the note.")


async def test_a_figure_reason_is_stored_with_names(signed_in):
    run_id = reviewed_run(signed_in)
    await figures_agent.run_figures(run_id, "SOFP", "gpt-6-luna", max_steps=3, model=script([
        ("save_figures", {"figures": [{"field": "FP-s427", "certainty": "unsure",
                                       "reason": "Could belong in FP-s404; the note does not say.",
                                       "lines": [{"label": "Accruals", "page": 2, "cy": 40}]}]}),
        (FINAL, {"summary": "x"})], []))
    with db.connect() as conn:
        reason = conn.execute("SELECT reason FROM figures WHERE run_id = ? AND certainty = 'unsure'",
                              (run_id,)).fetchone()[0]
    assert reason == f"Could belong in {PAYABLES}; the note does not say."


def test_a_scope_question_is_stored_with_names(signed_in):
    run_id = read_run(signed_in)
    assert signed_in.post(f"/api/runs/{run_id}/setup", json=SETUP).status_code == 200
    assert _ask(run_id, field="unit", question="Is FP-s28 printed in RM thousands?",
                evidence=[{"text": "FP-s28 reads 1,200 under RM'000.", "page": 2}],
                choices=[{"label": "RM thousands", "value": "RM'000", "effect": "FP-s28 is filed as printed",
                          "suggested": True},
                         {"label": "RM", "value": "RM", "effect": "Carries on"}]).startswith("Your question")
    question = signed_in.get(f"/api/runs/{run_id}/question").json()["question"]
    assert question["question"] == "Is Plant and equipment printed in RM thousands?"
    assert question["evidence"][0]["text"] == "Plant and equipment reads 1,200 under RM'000."
    assert question["choices"][0]["effect"] == "Plant and equipment is filed as printed"
