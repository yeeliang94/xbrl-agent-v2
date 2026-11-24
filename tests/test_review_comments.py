"""Comments, sending a round, Accept and Undo, restart recovery, "Needs you",
retrying a failed extraction and the traces. No model is called: a round's
writes are made here as the Reviewer would make them."""
from __future__ import annotations

import io
import json
import zipfile

from app import db
from app.figures import store
from app.jobs import queue
from app.review import comments, rounds
from app.runs.events import list_events
from tests.review_helpers import comment_on, field_uuid, reviewed_run, save, state, value
from tests.test_extraction_job import SETUP, read_run, signed_in  # noqa: F401 - the fixture

REVIEWER = store.Actor("agent", "reviewer")


def _status(run_id: int) -> str:
    with db.connect() as conn:
        return conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0]


def _round(client, run_id: int, **body) -> dict:
    response = client.post(f"/api/runs/{run_id}/rounds", json=body or None)
    assert response.status_code == 202, response.json()
    return response.json()["round"]


def _work(run_id: int, round_id: int, writes, answers) -> None:
    """Make the round's writes as the Reviewer does, answer, and end the round."""
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE rounds SET status = 'working' WHERE id = ?", (round_id,))
    for field_id, period, amount, label, ids in writes:
        with store.tagged(round_id, ids):
            save(run_id, field_id, period, amount, label, actor=REVIEWER)
    with db.connect(immediate=True) as conn:
        for comment_id, outcome, text in answers:
            comments.record_answer(conn, round_id, comment_id, outcome, text, None)
    rounds.end(round_id, "done", summary="Fixed it.")


# Comments ------------------------------------------------------------------------

def test_a_person_adds_lists_replies_to_and_removes_comments(signed_in):
    run_id = reviewed_run(signed_in)
    first = comment_on(signed_in, run_id, "FP-s404")
    assert first["status"] == "open" and first["author_kind"] == "person" and first["scope"] == "figure"
    assert first["target"]["field_label"] == "Trade payables" and first["target"]["figure_id"] is not None
    line = signed_in.post(f"/api/runs/{run_id}/comments", json={
        "target": {"kind": "line", "statement": "SOFP", "concept_uuid": field_uuid(run_id, "FP-s28")},
        "text": "Check both years.", "scope": "run"}).json()["comment"]
    assert line["target"]["kind"] == "line" and line["target"]["figure_id"] is None
    by_id = signed_in.post(f"/api/runs/{run_id}/comments", json={
        "target": {"kind": "figure", "figure_id": first["target"]["figure_id"]}, "text": "Again."}).json()["comment"]
    assert by_id["target"]["concept_uuid"] == first["target"]["concept_uuid"]

    listed = signed_in.get(f"/api/runs/{run_id}/comments?status=open").json()["comments"]
    assert [c["id"] for c in listed] == [first["id"], line["id"], by_id["id"]]
    assert signed_in.delete(f"/api/runs/{run_id}/comments/{by_id['id']}").status_code == 204
    assert len(signed_in.get(f"/api/runs/{run_id}/comments").json()["comments"]) == 2

    # Answered, then a reply opens it again with the earlier answer kept in its thread.
    sent = _round(signed_in, run_id)
    _work(run_id, sent["id"], [], [(first["id"], "question", "Which year do you mean?"),
                                   (line["id"], "not_changed", "Page 2 prints these.")])
    assert signed_in.delete(f"/api/runs/{run_id}/comments/{first['id']}").json() == {
        "detail": "Only an open comment can be removed."}
    replied = signed_in.post(f"/api/runs/{run_id}/comments/{first['id']}/reply", json={"text": "This year."})
    comment = replied.json()["comment"]
    assert comment["status"] == "open" and comment["outcome"] is None
    assert [t["kind"] for t in comment["thread"]] == ["answer", "reply"]
    assert comment["thread"][0]["answer"] == "Which year do you mean?" and comment["thread"][1]["text"] == "This year."
    accepted = signed_in.post(f"/api/runs/{run_id}/comments/{line['id']}/accept").json()["comment"]
    assert accepted["status"] == "accepted"
    assert signed_in.post(f"/api/runs/{run_id}/comments/{line['id']}/accept").json() == {
        "detail": "Only an answered comment can be accepted."}


def test_a_comment_is_refused_with_one_plain_sentence(signed_in):
    run_id = reviewed_run(signed_in)
    uuid = field_uuid(run_id, "FP-s404")

    def refused(body):
        response = signed_in.post(f"/api/runs/{run_id}/comments", json=body)
        assert response.status_code in (404, 409, 422)
        return response.json()["detail"]

    assert refused({"target": {"kind": "statement", "statement": "SOFP"}, "text": "  "}) == \
        "Write what the comment should say."
    assert refused({"target": {"kind": "statement", "statement": "SOFP"}, "text": "x" * 2001}) == \
        "Keep a comment to 2,000 characters or fewer."
    assert refused({"target": {"kind": "note"}, "text": "x"}) == "A note comment names the note by its id."
    assert refused({"target": {"kind": "note", "note_id": 999}, "text": "x"}) == "There is no such note in this run."
    assert refused({"target": {"kind": "statement", "statement": "SOPL"}, "text": "x"}) == \
        "That statement is not part of this run."
    assert refused({"target": {"kind": "figure", "statement": "SOFP", "concept_uuid": uuid, "period": "XX"},
                    "text": "x"}) == "The period is CY (this year) or PY (last year)."
    assert refused({"target": {"kind": "statement", "statement": "SOFP"}, "text": "x", "scope": "run"}) == \
        "Only a comment on a figure or a line can apply to the run or the company."
    assert refused({"target": {"kind": "figure", "figure_id": 99999}, "text": "x"}) == \
        "There is no such figure in this run."


def test_sending_a_round_is_one_step_and_a_second_send_is_refused(signed_in):
    run_id = reviewed_run(signed_in)
    assert signed_in.post(f"/api/runs/{run_id}/rounds").json() == {"detail": "There are no open comments to send."}
    comment = comment_on(signed_in, run_id, "FP-s404")
    sent = _round(signed_in, run_id, client_id="press-1")
    assert sent["status"] == "sent" and sent["number"] == 1 and sent["comment_ids"] == [comment["id"]]
    assert _status(run_id) == "correcting"
    with db.connect() as conn:
        job = conn.execute("SELECT kind, status, max_attempts FROM jobs WHERE id = (SELECT job_id FROM rounds "
                           "WHERE id = ?)", (sent["id"],)).fetchone()
    assert tuple(job) == ("review_round", "queued", 1)
    assert signed_in.get(f"/api/runs/{run_id}/comments").json()["comments"][0]["status"] == "sent"
    # The same press again returns the same round; a new press is refused while it waits.
    assert _round(signed_in, run_id, client_id="press-1")["id"] == sent["id"]
    comment_on(signed_in, run_id, "FP-s28", text="Another.")
    second = signed_in.post(f"/api/runs/{run_id}/rounds", json={"client_id": "press-2"})
    assert second.status_code == 409 and second.json() == {"detail": "A correction round is already running."}
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM rounds WHERE run_id = ?", (run_id,)).fetchone()[0] == 1
    assert any(e["source"] == "review" and e["kind"] == "queued" for e in list_events(run_id=run_id))


def test_a_round_is_refused_while_the_mtool_file_is_being_prepared(signed_in):
    run_id = reviewed_run(signed_in)
    comment_on(signed_in, run_id, "FP-s404")
    with db.connect() as conn:
        fill_id = conn.execute("INSERT INTO fills(run_id, created_by, created_at, template_filename, template_path, "
                               "template_sha256, job_status) VALUES (?, 'ana@firm.com', '2026-11-23', 'm.xlsx', "
                               "'x', 'abc', 'filling')", (run_id,)).lastrowid
    response = signed_in.post(f"/api/runs/{run_id}/rounds")
    assert response.status_code == 409
    assert response.json() == {"detail": "The mTool file is being prepared, so send the comments when it is ready."}
    with db.connect() as conn:
        conn.execute("UPDATE fills SET job_status = 'ready' WHERE id = ?", (fill_id,))
    assert _round(signed_in, run_id)["status"] == "sent"


def test_comments_wait_until_extraction_has_finished(signed_in):
    run_id = read_run(signed_in)
    signed_in.post(f"/api/runs/{run_id}/setup", json=SETUP)
    response = signed_in.post(f"/api/runs/{run_id}/comments", json={
        "target": {"kind": "statement", "statement": "SOFP"}, "text": "Too early."})
    assert response.status_code == 409
    assert signed_in.post(f"/api/runs/{run_id}/rounds").json() == {
        "detail": "Extraction is still running, so send the comments when it finishes."}


def test_stopping_a_waiting_round_ends_it_and_reopens_its_comments(signed_in):
    run_id = reviewed_run(signed_in)
    comment = comment_on(signed_in, run_id, "FP-s404")
    sent = _round(signed_in, run_id)
    stopped = signed_in.post(f"/api/runs/{run_id}/rounds/{sent['id']}/stop").json()["round"]
    assert stopped["status"] == "stopped" and stopped["finished_at"]
    assert _status(run_id) == "in_review"
    assert signed_in.get(f"/api/runs/{run_id}/comments").json()["comments"][0]["status"] == "open"
    assert signed_in.post(f"/api/runs/{run_id}/rounds/{sent['id']}/stop").json() == {
        "detail": "This round has already ended."}
    assert comment["id"] in stopped["comment_ids"]


def test_a_round_left_working_at_restart_ends_failed_and_is_not_handed_back(signed_in):
    run_id = reviewed_run(signed_in)
    comment_on(signed_in, run_id, "FP-s404")
    sent = _round(signed_in, run_id)
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE rounds SET status = 'working' WHERE id = ?", (sent["id"],))
        conn.execute("UPDATE jobs SET status = 'working', attempts = 1 WHERE id = (SELECT job_id FROM rounds "
                     "WHERE id = ?)", (sent["id"],))
    assert rounds.recover_after_restart() == 1
    queue.recover_after_restart()
    with db.connect() as conn:
        row = conn.execute("SELECT status, error FROM rounds WHERE id = ?", (sent["id"],)).fetchone()
        job = conn.execute("SELECT status FROM jobs WHERE id = (SELECT job_id FROM rounds WHERE id = ?)",
                           (sent["id"],)).fetchone()[0]
    assert row["status"] == "failed" and "server stopped" in row["error"]
    assert job == "failed"
    assert _status(run_id) == "in_review"
    assert signed_in.get(f"/api/runs/{run_id}/comments").json()["comments"][0]["status"] == "open"


# Accept and Undo ---------------------------------------------------------------

def test_undo_restores_exactly_including_a_figure_the_round_added(signed_in):
    run_id = reviewed_run(signed_in)
    payables = comment_on(signed_in, run_id, "FP-s404")
    other = comment_on(signed_in, run_id, "FP-s28", text="Plant is fine?")
    before = state(run_id, "FP-s404")
    sent = _round(signed_in, run_id)
    _work(run_id, sent["id"], [("FP-s404", "CY", 300, "Trade payables", [payables["id"]]),
                               ("FP-s427", "CY", 50, "Accruals", [payables["id"]]),
                               ("FP-s28", "PY", 1000, "Plant and equipment", [])],
          [(payables["id"], "changed", "Used 300 as page 2 prints."), (other["id"], "not_changed", "It agrees.")])

    report = signed_in.get(f"/api/runs/{run_id}/rounds/{sent['id']}").json()["report"]
    mine = next(c for c in report["comments"] if c["comment_id"] == payables["id"])
    assert mine["changed"] and mine["verified"]
    assert {(f["field_label"], f["was"], f["is_now"]) for f in mine["figures"]} == {
        ("Trade payables", 250, 300), ("Accruals", None, 50)}
    assert next(c for c in report["comments"] if c["comment_id"] == other["id"])["verified"] is False
    assert [(o["field_label"], o["period"], o["was"], o["is_now"], o["served"]) for o in report["other"]
            if o["field_label"] == "Plant and equipment"] == [("Plant and equipment", "PY", None, 1000, [])]
    assert report["totals_recalculated"] and report["counts"]["changed"] == 1

    undone = signed_in.post(f"/api/runs/{run_id}/comments/{payables['id']}/undo")
    assert undone.status_code == 200, undone.json()
    assert [c["status"] for c in undone.json()["comments"]] == ["undone"]
    assert state(run_id, "FP-s404") == before
    assert value(run_id, "FP-s427") is None          # the round added it; undo clears it
    assert value(run_id, "FP-s28", "PY") == 1000      # the change for no comment stays
    with db.connect() as conn:
        last = conn.execute("SELECT action, actor_kind, round_id FROM figure_history WHERE figure_id = ? "
                            "ORDER BY id DESC LIMIT 1", (undone.json()["figures"][0]["id"],)).fetchone()
    assert tuple(last) == ("restore", "person", None)
    assert signed_in.post(f"/api/runs/{run_id}/comments/{payables['id']}/undo").json() == {
        "detail": "Only an answered comment can be undone."}
    assert signed_in.post(f"/api/runs/{run_id}/comments/{other['id']}/undo").json() == {
        "detail": "Nothing changed for this comment, so there is nothing to undo."}


def test_undo_is_refused_while_a_round_works_and_accept_all_skips_questions(signed_in):
    run_id = reviewed_run(signed_in)
    first = comment_on(signed_in, run_id, "FP-s404")
    second = comment_on(signed_in, run_id, "FP-s28", text="Which note?")
    sent = _round(signed_in, run_id)
    _work(run_id, sent["id"], [("FP-s404", "CY", 300, "Trade payables", [first["id"]])],
          [(first["id"], "changed", "Used 300."), (second["id"], "question", "Note 1 or 2?")])
    signed_in.post(f"/api/runs/{run_id}/comments/{second['id']}/reply", json={"text": "Note 1."})
    _round(signed_in, run_id)   # the reply goes in a second round, which now waits
    refused = signed_in.post(f"/api/runs/{run_id}/comments/{first['id']}/undo")
    assert refused.status_code == 409
    assert refused.json() == {"detail": "A correction round is running, so undo when it ends."}

    accepted = signed_in.post(f"/api/runs/{run_id}/comments/accept-all").json()["comments"]
    assert accepted == []   # the latest round has nothing answered yet
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE rounds SET status = 'done' WHERE run_id = ?", (run_id,))
        conn.execute("UPDATE comments SET status = 'answered', outcome = 'question' WHERE id = ?", (second["id"],))
        conn.execute("UPDATE comments SET round_id = (SELECT MAX(id) FROM rounds) WHERE id = ?", (first["id"],))
    accepted = signed_in.post(f"/api/runs/{run_id}/comments/accept-all").json()["comments"]
    assert [c["id"] for c in accepted] == [first["id"]]


# Needs you ------------------------------------------------------------------------

def test_needs_you_lists_checks_unsure_figures_agent_comments_and_alike_lines_in_order(signed_in):
    run_id = reviewed_run(signed_in)   # 1,200 of assets against 1,150: the balance check fails
    save(run_id, "FP-s427", "CY", 40, "Accrued expenses", certainty="unsure", reason="The note does not say.")
    save(run_id, "FP-s28", "CY", 1200, "Machinery")
    with db.connect(immediate=True) as conn:
        target = comments.resolve_target(conn, run_id, {"kind": "figure", "statement": "SOFP", "period": "CY",
                                                        "concept_uuid": field_uuid(run_id, "FP-41")})
        agent_comment = comments.add_agent_comment(conn, run_id, "figures", target, "The equity note is torn.")
    body = signed_in.get(f"/api/runs/{run_id}/needs-you").json()
    kinds = [i["kind"] for i in body["items"]]
    assert kinds[0] == "failed_check" and kinds.index("unsure") < kinds.index("agent_comment") < kinds.index("alike")
    check = body["items"][0]
    assert check["check"] == "sofp_balance" and check["statement"] == "SOFP" and check["period"] == "CY"
    unsure = next(i for i in body["items"] if i["kind"] == "unsure")
    assert unsure["message"] == "The note does not say." and unsure["figure_id"]
    assert next(i for i in body["items"] if i["kind"] == "agent_comment")["comment_id"] == agent_comment
    alike = body["items"][-1]
    # The Unsure accrual stays its own item: accepting names must never settle it.
    assert {(line["printed_label"], line["field_label"]) for line in alike["lines"]} == {
        ("Machinery", "Plant and equipment")}
    assert alike["count"] == 1 and alike["title"] == "1 line filed under a different name"
    with db.connect() as conn:
        filled = conn.execute("SELECT COUNT(*) FROM figures WHERE run_id = ? AND value IS NOT NULL "
                              "AND status != 'not_disclosed'", (run_id,)).fetchone()[0]
    named = {i.get("figure_id") for i in body["items"]} | {line["figure_id"] for line in alike["lines"]}
    assert body["passed"] == filled - len(named - {None})

    with db.connect() as conn:   # a sign question also keeps a figure out of the group
        conn.execute("UPDATE figures SET sign_question = 1 WHERE id = ?", (alike["lines"][0]["figure_id"],))
    assert "alike" not in [i["kind"] for i in signed_in.get(f"/api/runs/{run_id}/needs-you").json()["items"]]
    with db.connect() as conn:
        conn.execute("UPDATE figures SET sign_question = 0 WHERE id = ?", (alike["lines"][0]["figure_id"],))

    after = signed_in.post(f"/api/runs/{run_id}/needs-you/alike/accept").json()
    assert "alike" not in [i["kind"] for i in after["items"]]
    assert next(i for i in after["items"] if i["kind"] == "unsure")["figure_id"] == unsure["figure_id"]
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM figure_history WHERE run_id = ? AND action = 'confirm' "
                            "AND actor_kind = 'person'", (run_id,)).fetchone()[0] == 1
        assert conn.execute("SELECT certainty FROM figures WHERE id = ?",
                            (unsure["figure_id"],)).fetchone()[0] == "unsure"
    # Accepting a name changes nothing else on the figure, not even its certainty or a sign question.
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE figures SET certainty = 'unsure', sign_question = 1 WHERE id = ?",
                     (alike["lines"][0]["figure_id"],))
        store.confirm_figure(conn, run_id, alike["lines"][0]["figure_id"], store.Actor("person", "ana@firm.com"),
                             settle=False)
        kept = conn.execute("SELECT certainty, sign_question FROM figures WHERE id = ?",
                            (alike["lines"][0]["figure_id"],)).fetchone()
    assert tuple(kept) == ("unsure", 1)
    signed_in.post(f"/api/runs/{run_id}/comments/{agent_comment}/done")
    assert "agent_comment" not in [i["kind"] for i in signed_in.get(f"/api/runs/{run_id}/needs-you").json()["items"]]


# Retry, delete, traces ---------------------------------------------------------------

def test_a_failed_extraction_is_retried_on_the_same_run_keeping_its_figures(signed_in):
    run_id = read_run(signed_in)
    signed_in.post(f"/api/runs/{run_id}/setup", json=SETUP)
    assert signed_in.post(f"/api/runs/{run_id}/extract/retry").json() == {
        "detail": "Extraction has not failed, so there is nothing to try again."}
    save(run_id, "FP-s28", "CY", 1200, "Plant and equipment", actor=store.Actor("person", "ana@firm.com"))
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE stages SET status = 'failed', error = 'No figure was saved.' WHERE run_id = ? "
                     "AND name = 'extract'", (run_id,))
        conn.execute("UPDATE jobs SET status = 'failed' WHERE run_id = ? AND kind = 'extract'", (run_id,))
        conn.execute("UPDATE runs SET status = 'failed' WHERE id = ?", (run_id,))
    response = signed_in.post(f"/api/runs/{run_id}/extract/retry")
    assert response.status_code == 202 and response.json()["run"]["status"] == "ready"
    assert response.json()["run"]["failed_stage"] is None
    with db.connect() as conn:
        stages = conn.execute("SELECT status FROM stages WHERE run_id = ? AND name = 'extract'", (run_id,)).fetchall()
        jobs = [tuple(r) for r in conn.execute("SELECT kind, status FROM jobs WHERE run_id = ? AND kind = 'extract' "
                                               "ORDER BY id", (run_id,))]
    assert [s[0] for s in stages] == ["waiting"]
    assert jobs == [("extract", "failed"), ("extract", "queued")]
    assert value(run_id, "FP-s28") == 1200


def test_the_traces_hold_comments_and_rounds_with_their_report(signed_in):
    run_id = reviewed_run(signed_in)
    comment = comment_on(signed_in, run_id, "FP-s404")
    sent = _round(signed_in, run_id)
    _work(run_id, sent["id"], [("FP-s404", "CY", 300, "Trade payables", [comment["id"]])],
          [(comment["id"], "changed", "Used 300.")])
    zf = zipfile.ZipFile(io.BytesIO(signed_in.get(f"/api/runs/{run_id}/traces").content))
    saved = json.loads(zf.read("comments.json"))
    assert saved[0]["text"] == "Page 2 prints 300." and saved[0]["outcome"] == "changed"
    rounds_saved = json.loads(zf.read("rounds.json"))
    assert rounds_saved[0]["status"] == "done" and rounds_saved[0]["report"]["counts"]["changed"] == 1
    assert json.loads(zf.read("manifest.json"))["not_recorded_yet"] == []
