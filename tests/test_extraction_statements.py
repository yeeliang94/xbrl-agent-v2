"""All five statements in the extract job (steps 7b to 7d) with fake models:
one figures agent per entity fills every included statement, sees the
checks across the statements it fills and those finished before it, marks
only what its accepted finish covers, and a failed agent is named with the
statements it left while the next entity's agent still runs; a retry fills
only what is not finished, and a Group run fills and checks both entities.
No network."""
from __future__ import annotations

import json

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app import db
from app.catalog.lookup import run_family
from app.extraction import agent, outline as ol, progress
from app.jobs import worker
from app.models import factory
from app.runs.events import list_events
from app.utils.paths import output_dir
from tests.test_extraction_job import SETUP, read_run, signed_in  # noqa: F401 - the fixture

ALL_FIVE = {**SETUP, "statements": [
    {"statement": "SOFP", "layout": "CuNonCu", "included": True, "pages": [2]},
    {"statement": "SOPL", "layout": "Function", "included": True, "pages": [2]},
    {"statement": "SOCI", "layout": "NetOfTax", "included": True, "pages": [2]},
    {"statement": "SOCF", "layout": "Indirect", "included": True, "pages": [2]},
    {"statement": "SOCIE", "layout": "Default", "included": True, "pages": [2]},
]}
ORDER = ["SOFP", "SOPL", "SOCI", "SOCIE", "SOCF"]
PRINTED = ("Plant and equipment", "Trade payables")   # the test page's two printed lines


def first_prompt(messages) -> str:
    return next(p.content for m in messages if isinstance(m, ModelRequest) for p in m.parts
                if isinstance(p, UserPromptPart))


def tool_results(messages, name: str) -> list[str]:
    return [str(p.content) for m in messages for p in getattr(m, "parts", [])
            if isinstance(p, ToolReturnPart) and p.tool_name == name]


class Fake:
    """A figures agent: it reads which statements and entity its first message names, saves one line of
    each, runs the checks, accounts for the page's printed lines and finishes. `fail` names entities whose
    agent answers nothing usable."""

    def __init__(self, run_id: int, fail: set[str] = frozenset()):
        with db.connect() as conn:
            outline = ol.build(conn, run_family(conn, run_id))
        self.line = {s: "FP-s28" if s == "SOFP" else next(
            (f.id for f in outline.fields.values() if f.statement == s and f.kind == ol.LINE), None) for s in ORDER}
        self.fail = fail
        self.runs: list[tuple[tuple[str, ...], str, str]] = []   # (statements, entity, first message)
        self.checks: dict[str, str] = {}                         # entity -> the last run_checks result

    @staticmethod
    def which(prompt: str) -> tuple[tuple[str, ...], str]:
        head = prompt.split(" of Test", 1)[0]
        statements = tuple(s for s in ORDER if agent.NAMES[s] in head)
        return statements, "Group" if "Group figures only" in prompt else "Company"

    def __call__(self, messages, info: AgentInfo) -> ModelResponse:
        prompt = first_prompt(messages)
        statements, entity = self.which(prompt)
        done = sum(1 for m in messages if isinstance(m, ModelResponse))
        if done == 0:
            self.runs.append((statements, entity, prompt))
        if entity in self.fail:
            return ModelResponse(parts=[TextPart("I cannot read these statements.")])
        found = tool_results(messages, "run_checks")
        if found:
            self.checks[entity] = found[-1]
        fields = [self.line[s] for s in statements]
        steps = [
            ("save_figures", {"figures": [{"field": fid, "lines": [{"label": "Plant and equipment", "page": 2,
                                                                     "cy": 1200}]} for fid in fields]}),
            ("run_checks", {}),
            ("report_coverage", {"lines": [   # one printed line, written to a field of every statement
                {"label": PRINTED[0], "page": 2, "action": "written", "fields": fields},
                {"label": PRINTED[1], "page": 2, "action": "skipped", "reason": "Not filled in this test."}]}),
        ]
        if done < len(steps):
            name, args = steps[done]
            return ModelResponse(parts=[ToolCallPart(name, args)])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            "summary": "Filled the statements.", "unresolved": ["The test page is not a real statement."]})])


@pytest.fixture
def run(signed_in, monkeypatch):  # noqa: F811
    def make(setup=ALL_FIVE, fail: set[str] = frozenset()):
        run_id = read_run(signed_in)
        assert signed_in.post(f"/api/runs/{run_id}/setup", json=setup).status_code == 200
        fake = Fake(run_id, fail)
        monkeypatch.setattr(factory, "build_model", lambda model_id: FunctionModel(fake))
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
        return run_id, fake
    return make


def _stage(run_id: int) -> tuple:
    with db.connect() as conn:
        stage = conn.execute("SELECT status, error FROM stages WHERE run_id = ? AND name = 'extract'",
                             (run_id,)).fetchone()
        run = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
    return run, stage["status"], stage["error"]


def _saved_statements(run_id: int, entity: str = "Company") -> set[str]:
    with db.connect() as conn:
        outline = ol.build(conn, run_family(conn, run_id))
        uuids = [r[0] for r in conn.execute("SELECT concept_uuid FROM figures WHERE run_id = ? AND origin = 'agent' "
                                            "AND entity_scope = ?", (run_id, entity))]
    return {outline.for_uuid(u).statement for u in uuids}


def _finished_events(run_id: int) -> list[dict]:
    return [e for e in list_events(run_id=run_id) if e["kind"] == "finished" and e["source"] == "extraction"]


async def test_one_agent_fills_all_five_statements_with_the_checks_across_them(run):
    run_id, fake = run()
    assert await worker.run_once()
    assert _stage(run_id) == ("in_review", "done", None)
    assert [(s, e) for s, e, _ in fake.runs] == [(tuple(ORDER), "Company")]
    assert _saved_statements(run_id) == set(ORDER)
    prompt = fake.runs[0][2]
    assert prompt.startswith("Fill the statement of financial position, statement of profit or loss, statement of "
                             "comprehensive income, statement of changes in equity and statement of cash flows of ")
    assert prompt.count("Template outline:") == 5 and "This statement is a grid" in prompt
    # One mark per agent run, naming every statement its accepted finish covers.
    (mark,) = _finished_events(run_id)
    assert mark["data"]["statements"] == ORDER and mark["data"]["entity"] == "Company"
    with db.connect() as conn:
        assert progress.finished_for(conn, run_id, "Company") == tuple(ORDER)
    checks = fake.checks["Company"]
    for title in ("Profit for the year agrees to changes in equity", "Closing equity agrees to financial position",
                  "Total comprehensive income agrees to changes in equity",
                  "Cash at end of year agrees to financial position"):
        assert title in checks, title


async def test_a_failed_agent_is_named_with_its_statements_the_next_runs_and_a_retry_fills_only_the_rest(
        run, signed_in):  # noqa: F811
    run_id, fake = run({**SETUP, "level": "Group"}, fail={"Group"})   # the balance sheet only
    assert await worker.run_once()
    status, stage, error = _stage(run_id)
    assert (status, stage) == ("failed", "failed")
    assert error.startswith("The statement of financial position (Group figures) could not be filled: no figure "
                            "was saved.")
    assert [e for _, e, _ in fake.runs] == ["Group", "Company"]   # the failure did not stop the Company
    assert _saved_statements(run_id, "Company") == {"SOFP"} and _saved_statements(run_id, "Group") == set()
    assert [e["data"]["entity"] for e in _finished_events(run_id)] == ["Company"]   # a failed agent marks nothing

    fake.fail, fake.runs = set(), []
    assert signed_in.post(f"/api/runs/{run_id}/extract/retry").status_code == 202
    assert await worker.run_once()
    assert [e for _, e, _ in fake.runs] == ["Group"]   # the Company's finished statement is not filled again
    assert _stage(run_id) == ("in_review", "done", None)


async def test_a_one_statement_failure_names_that_statement(run):
    run_id, _ = run(SETUP, fail={"Company"})
    assert await worker.run_once()
    assert _stage(run_id)[2].startswith("The statement of financial position could not be filled: no figure was "
                                        "saved.")


async def test_a_group_run_fills_and_checks_both_entities_and_records_each_agents_own_usage(run):
    run_id, fake = run({**SETUP, "level": "Group"})
    messages = [e["message"] for e in list_events(run_id=run_id)]
    assert ("Extraction is queued: the statement of financial position for the Group and the Company columns."
            in messages)
    assert await worker.run_once()
    assert _stage(run_id) == ("in_review", "done", None)
    assert [(s, e) for s, e, _ in fake.runs] == [(("SOFP",), "Group"), (("SOFP",), "Company")]
    group_prompt = fake.runs[0][2]
    assert "MFRS, Group figures only." in group_prompt
    assert ("The report prints Group and Company columns side by side. This run fills the Group columns only"
            in group_prompt)
    assert _saved_statements(run_id, "Group") == _saved_statements(run_id, "Company") == {"SOFP"}
    assert "for the Group" in fake.checks["Group"] and "for the Company" not in fake.checks["Group"]
    assert "for the Company" in fake.checks["Company"]
    folder = output_dir() / "runs" / f"run-{run_id}"
    group = json.loads((folder / "extraction-SOFP-Group.json").read_text())
    company = json.loads((folder / "extraction-SOFP.json").read_text())
    assert group["entity"] == "Group" and group["finished"] == ["SOFP"]
    assert group["usage"]["calls"] == company["usage"]["calls"] == 4   # each agent run's own calls only
    marks = _finished_events(run_id)
    assert [m["data"]["calls"] for m in marks] == [4, 4]
