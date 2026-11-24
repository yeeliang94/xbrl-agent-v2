"""The shared agent loop, driven by PydanticAI's TestModel and FunctionModel."""
from __future__ import annotations

import asyncio
import json

import pytest
from pydantic_ai.exceptions import ModelConnectionError, ModelHTTPError
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from app.agents import loop
from app.runs.events import list_events


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def _spec(**overrides) -> loop.AgentSpec:
    values = dict(name="test agent", model_id="gpt-6-luna", instructions="Be brief.", tools=[add])
    values.update(overrides)
    return loop.AgentSpec(**values)


def _forever(messages, info: AgentInfo) -> ModelResponse:
    """A model that never stops calling a tool."""
    return ModelResponse(parts=[ToolCallPart("add", {"a": 1, "b": 2})])


async def test_a_run_completes_and_records_usage_events_and_transcript():
    outcome = await loop.run_agent(_spec(), "Add 1 and 2.", model=TestModel())
    assert outcome.status == loop.COMPLETED
    assert outcome.steps == 2 and outcome.requests == 2
    assert outcome.input_tokens > 0 and outcome.output_tokens > 0
    assert outcome.tool_calls == ["add"]

    transcript = json.loads(outcome.transcript_path.read_text(encoding="utf-8"))
    assert transcript["status"] == "completed"
    assert transcript["usage"]["requests"] == 2
    assert any(p.get("tool_name") == "add" for m in transcript["messages"] for p in m["parts"])

    kinds = [e["kind"] for e in list_events()]
    assert kinds[0] == "started" and kinds[-1] == "completed"
    assert "tool" in kinds and kinds.count("step") == 2
    assert list_events()[-1]["data"]["input_tokens"] == outcome.input_tokens


async def test_own_step_limit_fires_before_the_librarys_request_limit():
    # 60 steps is above PydanticAI's default request limit of 50.
    outcome = await loop.run_agent(_spec(max_steps=60), "Keep going.", model=FunctionModel(_forever))
    assert outcome.status == loop.STEP_LIMIT
    assert outcome.steps == 60 and outcome.requests == 60
    assert "step limit of 60" in outcome.message
    assert outcome.transcript_path.is_file()


async def test_a_small_step_limit_is_honoured():
    outcome = await loop.run_agent(_spec(max_steps=3), "Keep going.", model=FunctionModel(_forever))
    assert outcome.status == loop.STEP_LIMIT and outcome.requests == 3


async def test_a_stop_request_ends_the_run_and_keeps_the_transcript():
    seen = []

    def should_stop() -> bool:
        seen.append(1)
        return len(seen) > 4

    outcome = await loop.run_agent(_spec(), "Keep going.", model=FunctionModel(_forever),
                                   should_stop=should_stop, run_id=None)
    assert outcome.status == loop.STOPPED
    assert 0 < outcome.steps < loop.DEFAULT_MAX_STEPS
    transcript = json.loads(outcome.transcript_path.read_text(encoding="utf-8"))
    assert transcript["status"] == "stopped" and transcript["messages"]


async def test_a_failed_run_still_writes_its_transcript():
    def broken(messages, info):
        raise RuntimeError("The provider went away.")

    outcome = await loop.run_agent(_spec(), "Hello.", model=FunctionModel(broken))
    assert outcome.status == loop.FAILED
    assert outcome.message == "The agent run stopped on an unexpected error."
    assert "The provider went away." in outcome.error
    transcript = json.loads(outcome.transcript_path.read_text(encoding="utf-8"))
    assert transcript["status"] == "failed"
    assert "The provider went away." in transcript["error"]
    assert transcript["messages"][0]["parts"][0]["content"] == "Hello."
    assert list_events()[-1]["kind"] == "failed"


async def test_a_run_that_cannot_build_its_model_fails_with_a_transcript():
    outcome = await loop.run_agent(_spec(), "Hello.")  # no OPENAI_API_KEY in tests
    assert outcome.status == loop.FAILED and "OPENAI_API_KEY" in outcome.message
    assert outcome.transcript_path.is_file()


_GATEWAY = "https://gateway.corp.example/v1/responses"


@pytest.mark.parametrize("error, sentence", [
    (ModelConnectionError("gpt-6-luna", f"Could not connect to {_GATEWAY}"),
     "The model service could not be reached."),
    (ModelHTTPError(403, "gpt-6-luna", body={"error": f"Blocked by policy at {_GATEWAY}"}),
     "The model service refused the request."),
])
async def test_a_failed_run_puts_a_plain_sentence_in_the_event(error, sentence):
    def broken(messages, info):
        raise error

    outcome = await loop.run_agent(_spec(), "Hello.", model=FunctionModel(broken))
    assert outcome.status == loop.FAILED
    event = list_events()[-1]
    assert event["kind"] == "failed" and event["message"] == sentence
    assert "http" not in json.dumps(event)
    assert outcome.message == sentence
    transcript = json.loads(outcome.transcript_path.read_text(encoding="utf-8"))
    assert "gateway.corp.example" in transcript["error"]  # the full error stays in the transcript


async def test_a_tool_that_fails_twice_then_works_lets_the_run_finish():
    calls = []

    def lookup(code: str) -> str:
        """Look up a code."""
        calls.append(code)
        if len(calls) <= 2:
            raise KeyError(f"no row for {code} at C:\\secret\\path")
        return "found"

    def model(messages, info: AgentInfo) -> ModelResponse:
        worked = [p for m in messages for p in m.parts
                  if getattr(p, "part_kind", "") == "tool-return" and p.content == "found"]
        if worked:
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(parts=[ToolCallPart("lookup", {"code": "A1"})])

    outcome = await loop.run_agent(_spec(tools=[lookup]), "Look up A1.", model=FunctionModel(model))
    assert outcome.status == loop.COMPLETED, outcome.message
    assert len(calls) == 3
    transcript = json.loads(outcome.transcript_path.read_text(encoding="utf-8"))
    retries = [p["content"] for m in transcript["messages"] for p in m["parts"]
               if p.get("part_kind") == "tool-return" and p.get("outcome") == "retried"]
    assert len(retries) == 2
    for content in retries:
        assert content == ("The lookup tool hit an unexpected problem and did not finish; "
                           "try again, or take another approach.")
    assert len(transcript["tool_errors"]) == 2 and "KeyError" in transcript["tool_errors"][0]


def test_the_agent_allows_three_tool_retries_by_default():
    assert loop.AgentSpec(name="a", model_id="gpt-6-luna", instructions="").retries == 3


async def test_the_time_limit_stops_the_run_cleanly():
    async def slow(messages, info: AgentInfo) -> ModelResponse:
        await asyncio.sleep(0.05)
        return ModelResponse(parts=[ToolCallPart("add", {"a": 1, "b": 2})])

    outcome = await loop.run_agent(_spec(max_seconds=0.2), "Keep going.", model=FunctionModel(slow))
    assert outcome.status == loop.TIME_LIMIT
    assert outcome.message == "Stopped at the time limit of 0.2 seconds before finishing."
    assert 0 < outcome.steps < loop.DEFAULT_MAX_STEPS
    transcript = json.loads(outcome.transcript_path.read_text(encoding="utf-8"))
    assert transcript["status"] == "time_limit"
    assert list_events()[-1]["kind"] == "time_limit"


async def test_every_model_call_is_recorded_once_with_its_time_and_a_cut_off_call_too():
    from app import db
    from tests.conftest import make_run

    run_id = make_run()

    async def slow_second(messages, info: AgentInfo) -> ModelResponse:
        if sum(isinstance(m, ModelResponse) for m in messages):
            await asyncio.sleep(30)      # cut off by the time limit
        return ModelResponse(parts=[ToolCallPart("add", {"a": 1, "b": 2})])

    outcome = await loop.run_agent(_spec(max_seconds=3), "Go.", run_id=run_id, model=FunctionModel(slow_second))
    assert outcome.status == loop.TIME_LIMIT
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT source, duration_ms, error, input_tokens FROM model_calls "
                                              "WHERE run_id = ? ORDER BY id", (run_id,))]
    assert [r["error"] for r in rows] == [None, loop.CUT_OFF]
    assert rows[0]["source"] == "test agent" and rows[0]["input_tokens"] > 0
    assert all(r["duration_ms"] is not None for r in rows)


def test_agent_is_built_with_end_strategy_early():
    agent, _ = loop.build_agent(_spec(), TestModel())
    assert agent.end_strategy == "early"


def test_code_tool_is_offered_to_gpt():
    _, use_code_tool = loop.build_agent(_spec(code_tool=True), TestModel())
    assert use_code_tool is True


def test_code_tool_is_left_out_for_claude_on_the_gateway(monkeypatch):
    monkeypatch.setenv("LLM_PROXY_URL", "https://gateway.example/v1")
    _, use_code_tool = loop.build_agent(_spec(model_id="claude-opus-4-7", code_tool=True), TestModel())
    assert use_code_tool is False


async def test_a_refused_code_tool_is_reported_and_the_run_goes_on(monkeypatch):
    monkeypatch.setenv("LLM_PROXY_URL", "https://gateway.example/v1")

    def answer(messages, info: AgentInfo) -> ModelResponse:
        assert not info.model_request_parameters.native_tools
        return ModelResponse(parts=[TextPart("done")])

    outcome = await loop.run_agent(
        _spec(model_id="claude-opus-4-7", code_tool=True, tools=[]), "Hi.", model=FunctionModel(answer))
    assert outcome.status == loop.COMPLETED
    assert any(e["kind"] == "notice" for e in list_events())


async def test_the_code_tool_reaches_the_model_request():
    def answer(messages, info: AgentInfo) -> ModelResponse:
        assert [t.kind for t in info.model_request_parameters.native_tools] == ["code_execution"]
        return ModelResponse(parts=[TextPart("done")])

    model = FunctionModel(answer)
    outcome = await loop.run_agent(_spec(code_tool=True, tools=[]), "Hi.", model=model)
    assert outcome.status == loop.COMPLETED, outcome.message


async def test_a_code_step_event_keeps_the_code_size_not_the_code():
    from pydantic_ai.messages import NativeToolCallPart

    code = "print(1200 + 300)"

    def answer(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[NativeToolCallPart("code_execution", {"code": code}, tool_call_id="c1"),
                                    TextPart("done")])

    outcome = await loop.run_agent(_spec(code_tool=True, tools=[]), "Hi.", model=FunctionModel(answer))
    assert outcome.status == loop.COMPLETED and outcome.code_tool_used, outcome.message
    event = next(e for e in list_events() if e["kind"] == "code")
    assert event["data"] == {"code_chars": len(code)}
    assert code in outcome.transcript_path.read_text(encoding="utf-8")   # the transcript keeps the code
