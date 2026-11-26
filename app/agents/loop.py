"""The one shared way to run an agent.

- Builds the PydanticAI agent with `end_strategy="early"`.
- Counts one step per model request and stops at its own step limit BEFORE
  PydanticAI's request limit (v1 invariant 18: the library's hidden default of
  50 requests otherwise ends a long run with a crash, not a clear message).
- Stops at a wall-clock time limit the same clean way.
- Publishes the run's clock (`budget.timed`), so tool results can tell the
  agent when its steps or its time run low (`app/agents/budget.py`).
- Honours a stop request, checked before every step.
- An unexpected error inside a tool goes back to the agent as one plain
  sentence it can act on. Only a model or connection failure ends a run.
- Records every model call one way (`CallLog`, through `_ModelCalls`): its
  tokens (input, cached, output), an estimated cost, its duration and, for
  a failed or cut-off call, the error, in `model_calls`. Every agent built
  here records through it, the transcription agent too.
- Writes progress rows to `events`, and writes the full transcript to disk
  through the atomic writer, also when the run fails. Event rows carry
  plain sentences; the full error text stays in the transcript and the log.
- A history processor shapes only what each request sends. The stored
  conversation, and so the transcript, is never trimmed.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Sequence

# Keep the console free of the library's start-up banner.
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from pydantic_ai import Agent, CodeExecutionTool
from pydantic_ai.capabilities import AbstractCapability, Hooks, NativeTool
from pydantic_ai.exceptions import (
    ModelAPIError, ModelConnectionError, ModelQuotaExceededError, ModelRateLimitError, ModelRequestTimeout, ModelRetry,
    UnexpectedModelBehavior,
)
from pydantic_ai.messages import ModelMessagesTypeAdapter, NativeToolCallPart, ToolCallPart
from pydantic_ai.usage import UsageLimits

from app import db
from app.models import factory, usage as model_usage
from app.agents import budget, file_tools
from app.agents.pages import LOOKING, looked_row
from app.runs.events import add_event
from app.utils.atomic_io import write_json_atomic
from app.utils.masking import mask
from app.utils.paths import output_dir

logger = logging.getLogger(__name__)

DEFAULT_MAX_STEPS = 30
MAX_STEPS_CEILING = 120
DEFAULT_RETRIES = 3
DEFAULT_MAX_SECONDS = 30 * 60

# Outcome statuses.
COMPLETED, STEP_LIMIT, TIME_LIMIT, STOPPED, FAILED = (
    "completed", "step_limit", "time_limit", "stopped", "failed")


@dataclass
class AgentSpec:
    name: str
    model_id: str
    instructions: str
    tools: Sequence[Any] = ()
    output_type: Any = str
    max_steps: int = DEFAULT_MAX_STEPS
    # How often a tool call may fail and be tried again in one run.
    retries: int = DEFAULT_RETRIES
    # Wall-clock limit for the whole run.
    max_seconds: float = DEFAULT_MAX_SECONDS
    thinking: Optional[str] = None
    code_tool: bool = False
    # Shapes what each model request sends, e.g. to trim old tool results.
    # It gets a copy of the conversation and returns the messages to send; it
    # must not change the messages it is given (build new ones). The stored
    # conversation, and so the transcript, stays whole.
    history_processor: Optional[Callable[[list], list]] = None
    # Checks the agent's final answer, e.g. that it saved its work first. It
    # raises ModelRetry with one plain sentence to send the agent back.
    output_validator: Optional[Callable[..., Any]] = None
    # Names this agent on its activity rows (`data["agent"]`) when several run side by side.
    agent: Optional[str] = None
    # Names this agent run in the run's cost (`model_calls.agent`, `app/runs/cost.py`); defaults to `agent`.
    label: Optional[str] = None


@dataclass
class AgentOutcome:
    status: str
    output: Any = None
    message: str = ""  # one plain sentence, safe to show
    error: str = ""  # the full error text of a failed run, for the transcript and log
    steps: int = 0
    requests: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Optional[float] = None
    code_tool_used: bool = False
    transcript_path: Optional[Path] = None
    tool_calls: list[str] = field(default_factory=list)
    tool_errors: list[str] = field(default_factory=list)


def library_usage_limits(max_steps: int) -> UsageLimits:
    """An explicit request limit one above our step limit, so ours fires first
    and the library's default never applies."""
    return UsageLimits(request_limit=max_steps + 1)


def _transcript_path(spec: AgentSpec, run_id: Optional[int]) -> Path:
    folder = output_dir() / "transcripts" / (f"run-{run_id}" if run_id else "no-run")
    # Characters Windows forbids in file names never reach the disk.
    safe_name = re.sub(r'[<>:"/\\|?*\s]', "_", spec.name) or "agent"
    return folder / f"{safe_name}-{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 10**9}.json"


def _messages_json(messages: list) -> list:
    try:
        return ModelMessagesTypeAdapter.dump_python(messages, mode="json")
    except Exception:  # noqa: BLE001 - a transcript must still be written
        return [{"raw": repr(m)} for m in messages]


class _Recorder:
    def __init__(self, spec: AgentSpec, run_id: Optional[int], job_id: Optional[int],
                 readable: Optional[Callable[[str], str]] = None):
        self.spec, self.run_id, self.job_id = spec, run_id, job_id
        self.readable = readable   # turns ids in an agent's own words into names a person knows

    async def event(self, kind: str, message: str, data: Optional[dict] = None, pages: Any = None) -> None:
        """A progress row. Same rule as `FiguresDeps.event`: a person reads the message, so field ids become
        names (`Outline.readable`), and the agent's own wording is kept in `data["raw"]` when it changed."""
        try:
            if self.spec.agent:
                data = {**(data or {}), "agent": self.spec.agent}
            if self.readable is not None:
                shown = self.readable(message)
                if shown != message:
                    data = {**(data or {}), "raw": message}
                message = shown
            await asyncio.to_thread(
                add_event, self.spec.name, kind, message,
                run_id=self.run_id, job_id=self.job_id, data=data, pages=pages)
        except Exception:  # noqa: BLE001 - progress rows must never end a run
            logger.warning("Could not record an agent event", exc_info=True)


# Model calls -----------------------------------------------------------------

CUT_OFF = "Cut off before the model answered."


@dataclass
class CallLog:
    """Where the model calls of one agent run (or one transcribed page) are
    recorded: a `model_calls` row each, and the list for the caller's records."""
    run_id: Optional[int]
    source: str
    model_id: str
    page: Optional[int] = None
    agent: Optional[str] = None                 # the agent run as a person names it, for the run's cost
    calls: list = field(default_factory=list)   # (duration_ms, ModelResponse or None, error or None)
    cost_usd: Optional[float] = None

    def record(self, duration_ms: int, response: Any, error: Optional[str]) -> None:
        self.calls.append((duration_ms, response, error))
        cost = model_usage.record_call(self.run_id, self.source, self.model_id,
                                       response.usage if response is not None else None,
                                       page=self.page, duration_ms=duration_ms, error=error, agent=self.agent)
        if cost is not None:
            self.cost_usd = (self.cost_usd or 0.0) + cost


_CALL_LOG: ContextVar[Optional[CallLog]] = ContextVar("agent_call_log", default=None)


@contextmanager
def recording(log: CallLog) -> Iterator[CallLog]:
    """Model calls made in this block (and the tasks it starts) go to `log`."""
    token = _CALL_LOG.set(log)
    try:
        yield log
    finally:
        _CALL_LOG.reset(token)


@dataclass
class _ModelCalls(AbstractCapability[Any]):
    """Times every model request and records it, failed and cut-off ones too."""

    async def wrap_model_request(self, ctx, *, request_context, handler):
        log = _CALL_LOG.get()
        started = time.monotonic()

        def elapsed_ms() -> int:
            return int((time.monotonic() - started) * 1000)

        try:
            response = await handler(request_context)
        except asyncio.CancelledError:
            if log is not None:
                log.record(elapsed_ms(), None, CUT_OFF)   # no await: the task is being cancelled
            raise
        except Exception as exc:
            if log is not None:
                await asyncio.to_thread(log.record, elapsed_ms(), None, f"{type(exc).__name__}: {exc}")
            raise
        if log is not None:
            await asyncio.to_thread(log.record, elapsed_ms(), response, None)
        return response


@dataclass
class _RequestHistory(AbstractCapability[Any]):
    """Runs the history processor on each request's own copy of the
    conversation. Unlike PydanticAI's ProcessHistory, nothing is written back
    to the stored conversation, so the transcript keeps every message whole."""
    processor: Callable[[list], list]

    async def before_model_request(self, ctx, request_context):
        request_context.messages = list(self.processor(list(request_context.messages)))
        return request_context


def _code_step(part: NativeToolCallPart) -> dict:
    """What an event keeps of a code step: its size and language, never the
    code itself, which can hold document figures. The transcript keeps the code."""
    try:
        args = part.args_as_dict()
    except Exception:  # noqa: BLE001 - an unreadable argument is still counted
        args = {}
    code = args.get("code")
    data: dict = {"code_chars": len(code) if isinstance(code, str) else len(str(part.args or ""))}
    if isinstance(args.get("language"), str):
        data["language"] = args["language"]
    return data


async def _record_tools(node: Any, outcome: AgentOutcome, rec: _Recorder) -> None:
    for part in node.model_response.parts:
        if isinstance(part, NativeToolCallPart):
            outcome.code_tool_used = True
            await rec.event("code", "Ran a code step in the sandbox.", _code_step(part))
        elif isinstance(part, ToolCallPart):
            outcome.tool_calls.append(part.tool_name)
            await rec.event("tool", f"Used {part.tool_name}.", {"tool": part.tool_name})
            if part.tool_name in LOOKING or part.tool_name in file_tools.NAMES:
                message, pages = looked_row(part)
                await rec.event("looked", message, {"tool": part.tool_name}, pages)


def _tool_error_hook(spec: AgentSpec, tool_errors: list[str]) -> Hooks:
    """Turns an unexpected exception inside any tool into a retry the agent
    sees as one plain sentence. The full error goes to the log and the
    transcript. A tool's own `ModelRetry` refusal passes through untouched."""

    def on_error(ctx, /, *, call, tool_def, args, error: Exception):
        detail = f"{call.tool_name}: {type(error).__name__}: {error}"
        tool_errors.append(detail)
        logger.warning("Tool error in %s: %s", spec.name, detail, exc_info=error)
        raise ModelRetry(
            f"The {call.tool_name} tool hit an unexpected problem and did not finish; "
            "try again, or take another approach."
        ) from error

    return Hooks(tool_execute_error=on_error)


def build_agent(
    spec: AgentSpec, model: Any = None, tool_errors: Optional[list[str]] = None
) -> tuple[Agent, bool]:
    """The PydanticAI agent for `spec`, and whether it carries the code tool.
    Unexpected tool errors are appended to `tool_errors` when given. Model
    calls are recorded to the `CallLog` of the `recording` block around a run."""
    use_code_tool = spec.code_tool and factory.code_tool_supported(spec.model_id)
    capabilities: list[Any] = [_ModelCalls(), _tool_error_hook(spec, tool_errors if tool_errors is not None else [])]
    if use_code_tool:
        capabilities.append(NativeTool(CodeExecutionTool()))
    if spec.history_processor is not None:
        capabilities.append(_RequestHistory(spec.history_processor))
    agent = Agent(
        model if model is not None else factory.build_model(spec.model_id),
        instructions=spec.instructions,
        tools=list(spec.tools),
        output_type=spec.output_type,
        model_settings=factory.model_settings(
            spec.model_id, thinking=spec.thinking, code_tool=use_code_tool),
        capabilities=capabilities,
        retries=spec.retries,
        end_strategy="early",
        name=spec.name,
    )
    if spec.output_validator is not None:
        agent.output_validator(spec.output_validator)
    return agent, use_code_tool


def failure_sentence(exc: Exception, *, during_setup: bool) -> str:
    """One plain sentence naming the kind of failure. Never the raw provider
    text, which can carry the gateway address."""
    if during_setup and isinstance(exc, ValueError):
        return str(exc)  # the factory's own sentence, e.g. a missing key
    if isinstance(exc, (ModelConnectionError, ModelRequestTimeout)):
        return "The model service could not be reached."
    if isinstance(exc, ModelQuotaExceededError):
        return "The model account has no credit left, so an admin needs to add credit before trying again."
    if isinstance(exc, ModelRateLimitError):
        return "The model service is busy or over its limit."
    if isinstance(exc, ModelAPIError):
        return "The model service refused the request."
    if isinstance(exc, UnexpectedModelBehavior):
        return "The model's replies could not be used, so the run was ended."
    name = type(exc).__name__
    if "Connect" in name or "Timeout" in name:
        return "The model service could not be reached."
    return "The agent run stopped on an unexpected error."


class _OutOfTime(Exception):
    """Ends `agent.iter` at the time limit, so PydanticAI cancels the request in flight."""


def _duration(seconds: float) -> str:
    if seconds >= 60:
        return f"{seconds / 60:g} minutes"
    return f"{seconds:g} seconds"


async def run_agent(
    spec: AgentSpec,
    prompt: str,
    *,
    deps: Any = None,
    run_id: Optional[int] = None,
    job_id: Optional[int] = None,
    should_stop: Callable[[], Any] = lambda: False,
    model: Any = None,
    readable: Optional[Callable[[str], str]] = None,
) -> AgentOutcome:
    """Run one agent to an outcome. Never raises for a model or tool failure:
    the outcome says what happened. `model` replaces the factory's model, for
    tests with PydanticAI's TestModel or FunctionModel. `readable` turns field ids in the
    agent's own words into the names a person knows, for the activity rows (the figures agent
    and the Reviewer pass their outline's; the Reader has no fields and passes none)."""
    if not 1 <= spec.max_steps <= MAX_STEPS_CEILING:
        raise ValueError(f"The step limit must be between 1 and {MAX_STEPS_CEILING}.")
    if spec.max_seconds <= 0:
        raise ValueError("The time limit must be above zero.")
    # A run that started from a Word or Excel file: the agent also gets the file's own words and numbers.
    spec = file_tools.for_run(spec, run_id)
    rec = _Recorder(spec, run_id, job_id, readable)
    outcome = AgentOutcome(status=FAILED, transcript_path=_transcript_path(spec, run_id))
    messages: list = []
    started = db.now()
    deadline = time.monotonic() + spec.max_seconds
    time_limit_message = f"Stopped at the time limit of {_duration(spec.max_seconds)} before finishing."
    agent_run = None
    during_setup = True
    calls = CallLog(run_id, spec.name, spec.model_id, agent=spec.label or spec.agent)
    await rec.event("started", f"Started {spec.name} with {spec.model_id}.")
    try:
        agent, use_code_tool = build_agent(spec, model, outcome.tool_errors)
        during_setup = False
        if spec.code_tool and not use_code_tool:
            await rec.event("notice", "The code workbench is not available for this model here.")
        with recording(calls), budget.timed(spec.max_seconds), suppress(_OutOfTime):
            async with agent.iter(
                prompt, deps=deps, usage_limits=library_usage_limits(spec.max_steps)
            ) as agent_run:
                node = agent_run.next_node
                while not Agent.is_end_node(node):
                    stop = should_stop()   # True, or the plain sentence saying why
                    if stop:
                        outcome.status = STOPPED
                        outcome.message = stop if isinstance(stop, str) else "Stopped on request."
                        break
                    if Agent.is_model_request_node(node):
                        if outcome.steps >= spec.max_steps:
                            outcome.status = STEP_LIMIT
                            outcome.message = f"Stopped at the step limit of {spec.max_steps} before finishing."
                            break
                        outcome.steps += 1
                        await rec.event("step", f"Step {outcome.steps} of at most {spec.max_steps}.")
                    elif Agent.is_call_tools_node(node):
                        await _record_tools(node, outcome, rec)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        outcome.status, outcome.message = TIME_LIMIT, time_limit_message
                        break
                    timer = asyncio.timeout(remaining)
                    try:
                        async with timer:
                            node = await agent_run.next(node)
                    except TimeoutError:
                        if not timer.expired():
                            raise
                        outcome.status, outcome.message = TIME_LIMIT, time_limit_message
                        # Leave the run with an error: a plain exit would wait for the request in flight.
                        raise _OutOfTime() from None
                else:
                    outcome.status, outcome.output = COMPLETED, agent_run.result.output
                    outcome.message = "Finished."
    except Exception as exc:  # noqa: BLE001 - the outcome carries the failure
        outcome.status = FAILED
        outcome.message = failure_sentence(exc, during_setup=during_setup)
        outcome.error = mask(f"{type(exc).__name__}: {exc}")
        logger.warning("Agent %s failed: %s", spec.name, outcome.error, exc_info=exc)
    finally:
        outcome.cost_usd = calls.cost_usd
        if agent_run is not None:
            messages = agent_run.all_messages()
            usage = agent_run.usage
            outcome.requests = usage.requests
            outcome.input_tokens = usage.input_tokens
            outcome.cached_tokens = usage.cache_read_tokens
            outcome.output_tokens = usage.output_tokens
        await asyncio.to_thread(_write_transcript, spec, outcome, messages, started)
    await rec.event(outcome.status, outcome.message, {
        "steps": outcome.steps,
        "requests": outcome.requests,
        "input_tokens": outcome.input_tokens,
        "cached_tokens": outcome.cached_tokens,
        "output_tokens": outcome.output_tokens,
        "cost_usd": outcome.cost_usd,
    })
    return outcome


def _write_transcript(spec: AgentSpec, outcome: AgentOutcome, messages: list, started: str) -> None:
    payload = {
        "agent": spec.name,
        "model": spec.model_id,
        "setup": factory.current_setup(),
        "started_at": started,
        "finished_at": db.now(),
        "status": outcome.status,
        "message": outcome.message,
        "error": outcome.error,
        "tool_errors": outcome.tool_errors,
        "steps": outcome.steps,
        "max_steps": spec.max_steps,
        "max_seconds": spec.max_seconds,
        "usage": {
            "requests": outcome.requests,
            "input_tokens": outcome.input_tokens,
            "cached_tokens": outcome.cached_tokens,
            "output_tokens": outcome.output_tokens,
            "cost_usd": outcome.cost_usd,
        },
        "messages": _messages_json(messages),
    }
    try:
        write_json_atomic(outcome.transcript_path, payload)
    except Exception:  # noqa: BLE001 - never hide the run's own result
        logger.warning("Could not write the transcript for %s", spec.name, exc_info=True)
        outcome.transcript_path = None
