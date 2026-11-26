"""An agent is told when its time or its steps run low, in the next tool result, and the run carries on: the
note is feedback, not a stop. Driven by a fake clock and PydanticAI's FunctionModel."""
from __future__ import annotations

from dataclasses import dataclass, field

from pydantic_ai import RunContext
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agents import budget, loop
from app.reading import reader


@dataclass
class Deps:
    max_steps: int = 20
    warned: set = field(default_factory=set)
    SOON_NOTE = "Save what is left and finish before it runs out."
    LAST_NOTE = "Finish now and say what is left."


class Clock:
    """Stands in for the wall clock: the test moves it."""
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def note(ctx: RunContext[Deps], text: str) -> str:
    """Keep a note."""
    return f"Kept {text}."


def _returns(messages) -> list[str]:
    return [p.content for m in messages for p in getattr(m, "parts", []) if isinstance(p, ToolReturnPart)]


def test_the_time_note_comes_once_at_70_percent_and_once_at_90_percent(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(budget, "_now", clock)
    deps = Deps()
    assert budget.time_note(deps) == ""   # outside an agent run there is no clock
    with budget.timed(30 * 60):
        clock.now += 20 * 60
        assert budget.time_note(deps) == ""
        clock.now += 60
        assert budget.time_note(deps) == ("\n\n[Time: 21 of 30 minutes used, about 9 minutes left. "
                                          "Save what is left and finish before it runs out.]")
        clock.now += 60
        assert budget.time_note(deps) == ""   # each notice once
        clock.now += 6 * 60
        assert budget.time_note(deps) == (
            "\n\n[Time: 28 of 30 minutes used, about 2 minutes left. A reply still being written when the "
            "time is up is lost. Finish now and say what is left.]")
        clock.now += 60
        assert budget.time_note(deps) == ""


def test_a_run_already_past_90_percent_gets_the_last_note_alone(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(budget, "_now", clock)
    deps = Deps()
    with budget.timed(100):
        clock.now += 95
        assert "about 5 seconds left" in budget.time_note(deps) and budget.time_note(deps) == ""


async def test_the_next_tool_result_says_the_time_runs_low_and_the_run_still_finishes(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(budget, "_now", clock)
    seen: list = []

    def answer(messages, info: AgentInfo) -> ModelResponse:
        seen.append(messages)
        done = sum(1 for m in messages if isinstance(m, ModelResponse))
        if done == 1:
            clock.now += 420   # the second reply took the run to 70% of its ten minutes
        if done < 3:
            return ModelResponse(parts=[ToolCallPart("note", {"text": f"line {done + 1}"})])
        return ModelResponse(parts=[TextPart("Saved two lines; the third is left.")])

    spec = loop.AgentSpec(name="test agent", model_id="gpt-6-luna", instructions="Be brief.",
                          tools=[budget.budgeted(note)], max_steps=20, max_seconds=600)
    outcome = await loop.run_agent(spec, "Keep notes.", deps=Deps(), model=FunctionModel(answer))

    results = _returns(seen[-1])
    assert results[0] == "Kept line 1."
    assert results[1] == ("Kept line 2.\n\n[Time: 7 of 10 minutes used, about 3 minutes left. "
                          "Save what is left and finish before it runs out.]")
    assert results[2] == "Kept line 3."
    # Feedback only: the run was not ended, and the agent's own words are its result.
    assert outcome.status == loop.COMPLETED and outcome.output == "Saved two lines; the third is left."
    assert outcome.steps == 4 and outcome.tool_calls == ["note"] * 3


def test_the_step_limit_still_fires_before_the_librarys_and_runs_still_end_early():
    spec = loop.AgentSpec(name="test agent", model_id="gpt-6-luna", instructions="Be brief.",
                          tools=[budget.budgeted(note)])
    agent, _ = loop.build_agent(spec, FunctionModel(lambda messages, info: ModelResponse(parts=[TextPart("x")])))
    assert agent.end_strategy == "early"
    assert loop.library_usage_limits(spec.max_steps).request_limit == spec.max_steps + 1


def test_the_reader_is_told_too_and_what_to_do_is_in_its_own_words():
    deps = reader.ReaderDeps(run_id=1, pdf_path="", page_count=1, contents={})
    assert budget.step_note(deps, 27) == ""
    assert budget.step_note(deps, 28) == (
        "\n\n[Steps: 28 of 40 used, 12 left. Save the map with what you have settled before they run out; you can "
        "save it again to correct it.]")
    assert "Your next reply is your last one. Save the map now with save_map" in budget.step_note(deps, 39)
    names = {getattr(t, "__name__", "") for t in reader.spec("gpt-6-luna").tools}
    assert "save_map" in names and "read_pages" in names   # wrapped tools keep their names for the model
