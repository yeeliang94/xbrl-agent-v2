"""One figures agent for several statements (step 7d), with fake models: it
sees every outline, reports coverage per statement and is refused a finish
while one statement is not covered, and the job runs one agent per entity.
One statement stays the case built in step 4. No network."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic_ai.messages import ModelResponse

from app import db
from app.extraction import agent, checking, job, progress, tools
from app.extraction.coverage import CoverageLine
from app.reading import store as reading
from app.runs.events import list_events
from tests.test_extraction_job import FINAL, SETUP, read_run, returns, script, signed_in  # noqa: F401 - the fixture

PROFIT_PAGE = {"folio": "6", "rotation": 0, "kind": "statement", "title": "Statement of profit or loss",
               "blocks": [{"type": "table", "html": "<table><tr><th></th><th>2021 RM</th></tr>"
                                                     "<tr><td>Revenue</td><td>5,000</td></tr>"
                                                     "<tr><td>Cost of sales</td><td>(3,000)</td></tr></table>"}],
               "running_text": [], "uncertain": [], "marks": []}
TWO = {**SETUP, "statements": [SETUP["statements"][0],
                               {"statement": "SOPL", "layout": "Function", "included": True, "pages": [4]},
                               *SETUP["statements"][2:]]}
SOFP_LINES = [{"label": "Plant and equipment", "page": 2, "action": "written",
               "fields": ["FP-s28"]},
              {"label": "Trade payables", "page": 2, "action": "written", "fields": ["FP-s404"]}]
SOPL_LINES = [{"label": "Revenue", "page": 4, "action": "written", "fields": ["PL-s15"]},
              {"label": "Cost of sales", "page": 4, "action": "skipped",
               "reason": "Left out of this test."}]
SAVES = ("save_figures", {"figures": [
    {"field": "FP-s28", "lines": [{"label": "Plant and equipment", "page": 2, "cy": 1200}]},
    {"field": "FP-s404", "lines": [{"label": "Trade payables", "page": 2, "cy": 300}]},
    {"field": "PL-s15", "lines": [{"label": "Revenue", "page": 4, "cy": 5000}]}]})


@pytest.fixture
def two(signed_in):  # noqa: F811
    run_id = read_run(signed_in)
    with db.connect(immediate=True) as conn:
        reading.save_page(conn, run_id, 4, PROFIT_PAGE, None)
    assert signed_in.post(f"/api/runs/{run_id}/setup", json=TWO).status_code == 200
    return run_id


def test_one_agent_for_two_statements_sees_both_outlines_and_more_steps(two):
    deps, first = agent.build_deps(two, ("SOFP", "SOPL"))
    assert deps.statements == ("SOFP", "SOPL") and deps.statement_pages == [2, 4]
    assert first.startswith("Fill the statement of financial position and statement of profit or loss of ")
    assert ("The statements you fill are printed on these PDF pages: the statement of financial position on page 2; "
            "the statement of profit or loss on page 4.") in first
    assert "FP-s28 line: Plant and equipment" in first and "PL-s15 line:" in first
    assert first.endswith("Fill each statement, check them, report coverage for each, then finish.")
    assert deps.max_steps == agent.MAX_STEPS + agent.EXTRA_STEPS
    # It saves into either statement; a field of a statement it does not fill is refused.
    ctx = SimpleNamespace(deps=deps, run_step=1)
    out = tools.save_figures(ctx, [tools.FigureSave(field="PL-s15", lines=[tools.PrintedLine(
        label="Revenue", page=4, cy=5000)]), tools.FigureSave(field="CF-s10", lines=[tools.PrintedLine(
            label="X", page=4, cy=1)])])
    assert "PL-s15" in out and "CF-s10 is not a field id in the outline" in out


def test_one_statement_is_the_step_4_case(two):
    deps, first = agent.build_deps(two, "SOFP")
    assert deps.statements == ("SOFP",) and deps.max_steps == agent.MAX_STEPS
    assert [t for t in agent.TOOLS if t.__name__ == "report_coverage"] == [checking.report_coverage]
    assert "statements you fill" not in first


async def test_the_finish_is_refused_while_one_statement_is_not_covered(two):
    seen: list = []
    steps = [SAVES, ("run_checks", {}), ("report_coverage", {"lines": SOFP_LINES}),
             (FINAL, {"summary": "Saved both statements."}),
             ("report_coverage", {"lines": SOFP_LINES + SOPL_LINES}),
             (FINAL, {"summary": "Saved both statements.", "unresolved": ["The test page prints no equity."]})]
    outcome, deps, _ = await agent.run_figures(two, ("SOFP", "SOPL"), "gpt-6-luna", model=script(steps, seen))
    assert outcome.status == "completed"
    first_cover, second_cover = returns(seen[-1], "report_coverage")
    assert "- SOFP: 2 of 2 printed lines accounted for." in first_cover
    assert "- SOPL: 0 of 2 printed lines accounted for." in first_cover
    assert "'Revenue' (page 4)" in first_cover
    refused = str(returns(seen[-1], "final_result")[0])
    assert refused.startswith("Not finished yet:") and "Coverage leaves 2 point(s) open" in refused
    assert "- SOPL: 2 of 2 printed lines accounted for." in second_cover
    assert deps.coverage_open == [] and deps.covered == {"SOFP", "SOPL"}
    assert progress.covered(deps, completed=True) == ("SOFP", "SOPL")
    assert progress.covered(deps, completed=False) == ()


def test_a_coverage_line_takes_its_statements_from_its_fields_and_may_serve_two(two):
    deps, _ = agent.build_deps(two, ("SOFP", "SOPL"))
    ctx = SimpleNamespace(deps=deps, run_step=1)
    tools.save_figures(ctx, [tools.FigureSave(field="FP-s28", lines=[tools.PrintedLine(
        label="Plant and equipment", page=2, cy=1200)]), tools.FigureSave(field="PL-s15", lines=[
            tools.PrintedLine(label="Revenue", page=4, cy=5000)])])
    both = CoverageLine(label="Plant and equipment", page=2, action="written", fields=["FP-s28", "PL-s15"])
    assert checking.statements_of(deps, both) == {"SOFP", "SOPL"}
    skipped = CoverageLine(label="Cost of sales", page=4, action="skipped", reason="x")
    assert checking.statements_of(deps, skipped) == {"SOPL"}   # no field: the statement printed on its page
    out = checking.report_coverage(ctx, [both, CoverageLine(label="Trade payables", page=2, action="written",
                                                            fields=["CF-s10"])])
    assert "names CF-s10, which is not a field id in the outline" in out
    assert deps.covered == {"SOFP", "SOPL"}


async def test_the_job_runs_one_agent_for_all_the_statements_of_an_entity(two):
    seen: list = []
    steps = [SAVES, ("run_checks", {}), ("report_coverage", {"lines": SOFP_LINES + SOPL_LINES}),
             (FINAL, {"summary": "Saved both statements.", "unresolved": ["The test page prints no equity."]})]
    await job.run_extraction(two, model=script(steps, seen))
    with db.connect() as conn:
        stage = conn.execute("SELECT status, error FROM stages WHERE run_id = ? AND name = 'extract'",
                             (two,)).fetchone()
    assert tuple(stage) == ("done", None)
    events = [e for e in list_events(run_id=two) if e["source"] == "extraction"]
    assert [e["message"] for e in events if e["kind"] == "statement"] == [
        "Working on the statement of financial position and statement of profit or loss."]
    done = next(e for e in events if e["kind"] == "finished")
    assert done["message"] == ("The statement of financial position and statement of profit or loss are filled, "
                               "with 1 point(s) left open.")
    assert done["data"]["statements"] == ["SOFP", "SOPL"]


async def test_a_statement_the_finish_does_not_cover_stays_unfinished(two):
    steps = [SAVES, ("run_checks", {}), ("report_coverage", {"lines": SOFP_LINES}),
             (FINAL, {"summary": "Saved both."}),
             (FINAL, {"summary": "Saved both.", "unresolved": ["The profit page is unreadable."]})]
    await job.run_extraction(two, model=script(steps, []))
    with db.connect() as conn:
        assert progress.finished_for(conn, two, "Company") == ("SOFP",)
    notice = next(e["message"] for e in list_events(run_id=two) if e["message"].startswith(
        "The statement of profit or loss is partly filled."))
    assert notice


def test_an_id_this_run_cannot_change_says_why(signed_in):  # noqa: F811
    run_id = read_run(signed_in)
    setup = {**SETUP, "statements": [*SETUP["statements"][:4],
                                     {"statement": "SOCIE", "layout": "Default", "included": True, "pages": [2]}]}
    assert signed_in.post(f"/api/runs/{run_id}/setup", json=setup).status_code == 200
    deps, _ = agent.build_deps(run_id, "SOCIE")
    ctx = SimpleNamespace(deps=deps, run_step=1)
    out = tools.save_figures(ctx, [tools.FigureSave(field=fid, lines=[tools.PrintedLine(label="X", page=2, cy=1)])
                                   for fid in ("FP-s28", "CE-11", "CE-C")])
    assert ("FP-s28 Plant and equipment is a field of the statement of financial position, which this run does "
            "not fill, so it cannot change it.") in out
    assert "CE-11 is a row of the equity grid (Profit (loss)), not a cell; save by cell id, such as CE-11-B." in out
    assert "CE-C is a column of the equity grid (Retained earnings), not a cell; save by cell id, such as CE-6-C." in out


async def test_the_checks_across_statements_follow_what_is_finished_not_the_order(signed_in):  # noqa: F811
    run_id = read_run(signed_in)
    setup = {**SETUP, "statements": [SETUP["statements"][0], *SETUP["statements"][1:4],
                                     {"statement": "SOCIE", "layout": "Default", "included": True, "pages": [2]}]}
    assert signed_in.post(f"/api/runs/{run_id}/setup", json=setup).status_code == 200
    title = "Closing equity agrees to financial position"
    seen: list = []
    await agent.run_figures(run_id, "SOCIE", "gpt-6-luna", model=script([("run_checks", {})], seen))
    assert title not in returns(seen[-1], "run_checks")[0]   # the balance sheet is not finished
    with db.connect(immediate=True) as conn:
        progress.mark(conn, run_id, None, ("SOFP",), "Company", "The balance sheet is filled.", {})
        filled = progress.finished_for(conn, run_id, "Company")
    seen = []
    await agent.run_figures(run_id, "SOCIE", "gpt-6-luna", model=script([("run_checks", {})], seen), filled=filled)
    assert title in returns(seen[-1], "run_checks")[0]


def test_the_limits_for_all_five_statements_stay_within_the_shared_loop_ceiling():
    from app.agents import loop
    from app.extraction import agent
    steps, seconds = agent.limits(5)
    assert steps == loop.MAX_STEPS_CEILING and seconds > agent.MAX_SECONDS
    assert agent.limits(1) == (agent.MAX_STEPS, agent.MAX_SECONDS)
