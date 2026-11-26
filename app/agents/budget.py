"""Telling an agent how much room it has left, before a limit ends its run.

The shared loop ends a run at its step limit and at its time limit. An agent
that is never told the end is near loses the work it had not saved yet (v1's
`limit_warner.py`: a reviewer lost a finished batch of corrections to a time
limit it could not see). So once 70% and again once 90% of a limit is used,
the next tool result ends with one plain sentence saying how much is left
and what to do with it; the result before the last step says the next reply
is the last.

This is feedback, not a rule: nothing is refused and the limits themselves
are unchanged. The agent's own deps say what "wrap up" means for its work
(`SOON_NOTE`, `LAST_NOTE`). Each notice is given once.

The loop publishes the run's clock here (`timed`); a tool wrapped with
`budgeted` reads it, so the time note needs nothing from the agent's deps.
"""
from __future__ import annotations

import functools
import inspect
import math
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Optional

WARN_AT = (0.7, 0.9)

_now = time.monotonic
# (when the run started, its time limit in seconds) of the agent run this task belongs to.
_CLOCK: ContextVar[Optional[tuple[float, float]]] = ContextVar("agent_run_clock", default=None)


@contextmanager
def timed(max_seconds: float) -> Iterator[None]:
    """The agent run in this block (and the tool calls it starts) has `max_seconds` from now."""
    token = _CLOCK.set((_now(), float(max_seconds)))
    try:
        yield
    finally:
        _CLOCK.reset(token)


def _span(seconds: float) -> str:
    if seconds >= 90:
        return f"{round(seconds / 60)} minutes"
    return f"{max(int(seconds), 0)} seconds"


def step_note(deps: Any, step: int) -> str:
    """The note on steps left after the response of step `step`, or ''. When a share falls on the step before
    the last, the last-reply note carries it."""
    left = deps.max_steps - step
    due = [share for share in WARN_AT if share not in deps.warned
           and step >= math.ceil(share * deps.max_steps - 1e-9)]
    deps.warned.update(due)
    if left <= 1:
        deps.warned.update(WARN_AT)
        return f"\n\n[Steps: {step} of {deps.max_steps} used. Your next reply is your last one. {deps.LAST_NOTE}]"
    if due:
        return f"\n\n[Steps: {step} of {deps.max_steps} used, {left} left. {deps.SOON_NOTE}]"
    return ""


def time_note(deps: Any) -> str:
    """The note on time left, or '': once at 70% of the run's time limit, once at 90%. '' outside a run."""
    clock = _CLOCK.get()
    if clock is None:
        return ""
    started, limit = clock
    used = _now() - started
    due = [share for share in WARN_AT if ("time", share) not in deps.warned and used >= share * limit]
    if not due:
        return ""
    deps.warned.update(("time", share) for share in WARN_AT if share <= max(due))
    minutes = limit >= 90
    spent = round(used / 60) if minutes else int(used)
    room = f"[Time: {spent} of {_span(limit)} used, about {_span(limit - used)} left."
    if max(due) >= WARN_AT[-1]:
        return f"\n\n{room} A reply still being written when the time is up is lost. {deps.LAST_NOTE}]"
    return f"\n\n{room} {deps.SOON_NOTE}]"


def budget_note(deps: Any, step: int) -> str:
    """What a tool result adds about the room left: steps, time, both or ''."""
    return step_note(deps, step) + time_note(deps)


def _with_note(result: Any, note: str) -> Any:
    if not note:
        return result
    if isinstance(result, list):
        return result + [note.strip()]
    return f"{result}{note}"


def budgeted(tool):
    """The tool, with the note on the room left added to its result."""
    if inspect.iscoroutinefunction(tool):
        @functools.wraps(tool)
        async def run_async(ctx, *args, **kwargs):
            return _with_note(await tool(ctx, *args, **kwargs), budget_note(ctx.deps, ctx.run_step))
        return run_async

    @functools.wraps(tool)
    def run(ctx, *args, **kwargs):
        return _with_note(tool(ctx, *args, **kwargs), budget_note(ctx.deps, ctx.run_step))
    return run
