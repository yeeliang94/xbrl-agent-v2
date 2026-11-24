"""Comments on Group figures (step 7c): accepted, and the Reviewer saves to the
entity of the comment it answers; a round may hold comments on both entities.
Scripted models only. No network."""
from __future__ import annotations

from app import db
from app.figures import store
from app.jobs import worker
from app.models import factory
from tests.review_helpers import FIGURES_AGENT, field_uuid
from tests.test_extraction_job import FINAL, SETUP, read_run, returns, script, signed_in  # noqa: F401 - the fixture


def _group_run(client) -> int:
    """A Group run in review: trade payables saved as 250 for the Group and 200 for the Company."""
    run_id = read_run(client)
    assert client.post(f"/api/runs/{run_id}/setup", json={**SETUP, "level": "Group"}).status_code == 200
    with db.connect(immediate=True) as conn:
        for entity, amount in (("Group", 250.0), ("Company", 200.0)):
            store.save_figure(conn, run_id, store.FigureWrite(
                field_uuid(run_id, "FP-s404"), "CY", entity, amount, [store.Line("Trade payables", 2, amount)]),
                FIGURES_AGENT)
        conn.execute("UPDATE stages SET status = 'done' WHERE run_id = ? AND name = 'extract'", (run_id,))
        conn.execute("UPDATE jobs SET status = 'done' WHERE run_id = ? AND kind = 'extract'", (run_id,))
        conn.execute("UPDATE runs SET status = 'in_review' WHERE id = ?", (run_id,))
    return run_id


def _comment(client, run_id: int, entity: str, text: str, kind: str = "figure") -> int:
    target = {"kind": kind, "statement": "SOFP", "concept_uuid": field_uuid(run_id, "FP-s404"),
              "entity_scope": entity, **({"period": "CY"} if kind == "figure" else {})}
    response = client.post(f"/api/runs/{run_id}/comments", json={"target": target, "text": text})
    assert response.status_code == 201, response.json()
    return response.json()["comment"]["id"]


def _value(run_id: int, entity: str):
    with db.connect() as conn:
        return store.current_figures(conn, run_id, entity)[(field_uuid(run_id, "FP-s404"), "CY")]["value"]


def test_a_comment_on_a_group_figure_or_line_is_accepted(signed_in):
    run_id = _group_run(signed_in)
    _comment(signed_in, run_id, "Group", "Check it.")
    _comment(signed_in, run_id, "Group", "Check every year.", kind="line")


async def test_the_reviewer_saves_to_the_entity_of_each_comment(signed_in, monkeypatch):
    run_id = _group_run(signed_in)
    group = _comment(signed_in, run_id, "Group", "The Group column on page 2 prints 300.")
    company = _comment(signed_in, run_id, "Company", "The Company column on page 2 prints 210.")
    line = {"label": "Trade payables", "page": 2}
    seen: list = []
    steps = [
        ("save_figures", {"figures": [   # one entry for comments on both entities, and a wrong entity: refused
            {"field": "FP-s404", "lines": [{**line, "cy": 300}], "comment_ids": [group, company]},
            {"field": "FP-s404", "lines": [{**line, "cy": 300}], "comment_ids": [group], "entity": "Company"}]}),
        ("save_figures", {"figures": [
            {"field": "FP-s404", "lines": [{**line, "cy": 300}], "comment_ids": [group], "reason": "Page 2."},
            {"field": "FP-s404", "lines": [{**line, "cy": 210}], "comment_ids": [company], "reason": "Page 2."}]}),
        ("run_checks", {}),
        ("answer_comment", {"answers": [
            {"comment_id": group, "outcome": "changed", "answer": "Used 300 from the Group column on page 2."},
            {"comment_id": company, "outcome": "changed", "answer": "Used 210 from the Company column on page 2."}]}),
        (FINAL, {"summary": "Corrected trade payables for the Group and the Company."}),
    ]
    monkeypatch.setattr(factory, "build_model", lambda model_id: script(steps, seen))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    sent = signed_in.post(f"/api/runs/{run_id}/rounds")
    assert sent.status_code == 202, sent.json()
    assert await worker.run_once()

    body = signed_in.get(f"/api/runs/{run_id}/rounds/{sent.json()['round']['id']}").json()
    assert body["round"]["status"] == "done", body["round"]
    assert (_value(run_id, "Group"), _value(run_id, "Company")) == (300, 210)
    first = seen[0][0].parts[-1].content
    assert "MFRS, Group and Company figures." in first
    assert "Group figures, this year (CY)" in first and "Company figures, this year (CY)" in first
    refused = returns(seen[-1], "save_figures")[0]
    assert f"Comments {group}, {company} are on both the Group and the Company figures" in refused
    assert f"Comment {group} is on the Group figures, so this write changes those columns" in refused
    checks = returns(seen[-1], "run_checks")[0]
    assert "(Group)" in checks and "(Company)" in checks
    with db.connect() as conn:
        rows = conn.execute("SELECT f.entity_scope, h.comment_ids_json FROM figure_history h JOIN figures f "
                            "ON f.id = h.figure_id WHERE h.run_id = ? AND h.round_id IS NOT NULL "
                            "AND h.action = 'save' ORDER BY h.id", (run_id,)).fetchall()
    assert [(r["entity_scope"], r["comment_ids_json"]) for r in rows] == [
        ("Group", f"[{group}]"), ("Company", f"[{company}]")]


def test_the_reviewer_works_on_the_statements_its_comments_are_on(signed_in):
    from app.review import agent as review_agent

    run_id = read_run(signed_in)
    setup = {**SETUP, "statements": [SETUP["statements"][0],
                                     {"statement": "SOPL", "layout": "Function", "included": True, "pages": [2]},
                                     *SETUP["statements"][2:]]}
    assert signed_in.post(f"/api/runs/{run_id}/setup", json=setup).status_code == 200
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE runs SET status = 'in_review' WHERE id = ?", (run_id,))
    response = signed_in.post(f"/api/runs/{run_id}/comments", json={"target": {
        "kind": "figure", "statement": "SOPL", "concept_uuid": field_uuid(run_id, "PL-s15"), "period": "CY"},
        "text": "Revenue is 5,000."})
    assert response.status_code == 201, response.json()
    sent = signed_in.post(f"/api/runs/{run_id}/rounds").json()["round"]
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM rounds WHERE id = ?", (sent["id"],)).fetchone()
    deps, message = review_agent.build_deps(row)
    assert deps.statements == ("SOPL",) and "The statement of profit or loss is printed on PDF page(s) 2." in message
    assert "PL-s15 line:" in message and "FP-s28 line:" not in message


def _deps(client, run_id: int):
    from app.review import agent as review_agent

    sent = client.post(f"/api/runs/{run_id}/rounds").json()["round"]
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM rounds WHERE id = ?", (sent["id"],)).fetchone()
    return review_agent.build_deps(row)[0]


def test_the_reviewer_sees_both_entities_and_settles_its_own_comments_entity(signed_in):
    from types import SimpleNamespace

    from app.extraction import tools as figure_tools
    from app.review import leave

    run_id = _group_run(signed_in)
    _comment(signed_in, run_id, "Group", "The Group column on page 2 prints 300.")
    deps = _deps(signed_in, run_id)
    ctx = SimpleNamespace(deps=deps, run_step=1)
    shown = figure_tools.show_section(ctx, ["FP-s404"])
    assert "Saved now: Group CY 250, Group PY blank, Company CY 200, Company PY blank." in shown
    # Its own comment names its entity on a Group run, as a write does.
    refused = leave.leave_comment(ctx, [leave.AgentComment(field="FP-s404", period="CY", text="Look at this.")])
    assert "FP-s404: Say which columns this changes: give entity Group or Company." in refused
    assert "comment" in leave.leave_comment(ctx, [leave.AgentComment(field="FP-s404", period="CY", entity="Group",
                                                                     text="Look at this.")])
    with db.connect() as conn:
        left = conn.execute("SELECT entity_scope, statement FROM comments WHERE run_id = ? AND author_kind = 'agent'",
                            (run_id,)).fetchall()
    assert [tuple(r) for r in left] == [("Group", "SOFP")]


async def test_the_figures_agents_comment_goes_on_its_own_entity(signed_in):
    from types import SimpleNamespace

    from app.extraction import agent as figures_agent
    from app.review import leave

    run_id = read_run(signed_in)
    assert signed_in.post(f"/api/runs/{run_id}/setup", json={**SETUP, "level": "Group"}).status_code == 200
    deps, _ = figures_agent.build_deps(run_id, "SOFP", entity="Group")
    ctx = SimpleNamespace(deps=deps, run_step=1)
    leave.leave_comment(ctx, [leave.AgentComment(field="FP-s28", text="No split is given.")])
    refused = leave.leave_comment(ctx, [leave.AgentComment(field="FP-s28", entity="Company", text="Other.")])
    assert "This run fills the Group figures, so a comment goes on those." in refused
    with db.connect() as conn:
        assert [r[0] for r in conn.execute("SELECT entity_scope FROM comments WHERE run_id = ?", (run_id,))] == [
            "Group"]


def test_a_run_wide_comment_opens_every_statement_and_either_entity(signed_in):
    from app.review import tools as review_tools

    run_id = read_run(signed_in)
    setup = {**SETUP, "level": "Group", "statements": [
        SETUP["statements"][0], {"statement": "SOPL", "layout": "Function", "included": True, "pages": [2]},
        *SETUP["statements"][2:]]}
    assert signed_in.post(f"/api/runs/{run_id}/setup", json=setup).status_code == 200
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE runs SET status = 'in_review' WHERE id = ?", (run_id,))
    response = signed_in.post(f"/api/runs/{run_id}/comments", json={"target": {
        "kind": "line", "statement": "SOFP", "concept_uuid": field_uuid(run_id, "FP-s404"), "entity_scope": "Group"},
        "text": "Payables are always split this way.", "scope": "run"})
    assert response.status_code == 201, response.json()
    cid = response.json()["comment"]["id"]
    deps = _deps(signed_in, run_id)
    assert deps.statements == ("SOFP", "SOPL")
    assert review_tools.entity_for(deps, (cid,), "Company") == ("Company", None)
    assert review_tools.entity_for(deps, (cid,), None) == ("Group", None)


def test_the_round_report_filters_checks_as_the_reviewers_run_checks_does(signed_in):
    from app.catalog.lookup import run_family
    from app.checks.runner import all_checks
    from app.review import changes, tools as review_tools

    run_id = read_run(signed_in)
    setup = {**SETUP, "statements": [SETUP["statements"][0],
                                     {"statement": "SOPL", "layout": "Function", "included": True, "pages": [2]},
                                     *SETUP["statements"][2:]]}
    assert signed_in.post(f"/api/runs/{run_id}/setup", json=setup).status_code == 200
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE runs SET status = 'in_review' WHERE id = ?", (run_id,))
    signed_in.post(f"/api/runs/{run_id}/comments", json={"target": {
        "kind": "figure", "statement": "SOPL", "concept_uuid": field_uuid(run_id, "PL-s15"), "period": "CY"},
        "text": "Revenue is 5,000."})
    deps = _deps(signed_in, run_id)
    with db.connect() as conn:
        report_filter = changes._relevant_for(conn, run_family(conn, run_id), deps.round_id)
    names = [c.name for c in all_checks()]
    assert [n for n in names if report_filter(n)] == [n for n in names if review_tools._relevant(deps, n)]
    assert "sofp_balance" not in [n for n in names if report_filter(n)]   # the round is on profit or loss
