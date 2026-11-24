"""A confirmed run with notes pages read, and a scripted notes agent, for the
notes agent tests. No model is called: each session follows its own script.
"""
from __future__ import annotations

from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app import db
from app.notes import agent, job as notes_job
from tests.notes_helpers import notes_run

FINAL = "$final"
NOTES_LIST = [("4", "Property, plant and equipment", 23, 23), ("5", "Trade and other receivables", 23, 24),
              ("6", "Borrowings", 24, 24)]
OPEN = ["The report prints no corporate information or accounting policy note on these pages."]


def confirmed_notes_run(notes=NOTES_LIST) -> int:
    """A run whose setup is confirmed, its notes list saved and its notes agent queued."""
    run_id = notes_run()
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE runs SET status = 'ready' WHERE id = ?", (run_id,))
        conn.execute("UPDATE run_setup SET year_end = '2025-12-31', notes_included = 1 WHERE run_id = ?", (run_id,))
        conn.executemany("INSERT INTO run_notes(run_id, position, number, title, first_page, last_page) "
                         "VALUES (?, ?, ?, ?, ?, ?)", [(run_id, i, *n) for i, n in enumerate(notes)])
        notes_job.start(conn, run_id)
    return run_id


def field_ids(run_id: int) -> dict[str, str]:
    """The list of notes' field ids by label, plus "catch-all"."""
    deps, _ = agent.build_deps(run_id, "placing")
    out = {f.label: fid for fid, f in deps.outline.notes.items() if f.template == "LIST_OF_NOTES"}
    out["catch-all"] = next(fid for fid, f in deps.outline.notes.items()
                            if f.template == "LIST_OF_NOTES" and f.catch_all)
    return out


def session_of(messages) -> str:
    """The session kind a conversation belongs to: placing, look or numeric."""
    first = next(p.content for m in messages if isinstance(m, ModelRequest) for p in m.parts
                 if isinstance(p, UserPromptPart))
    for session, (title, _) in agent.instructions.SESSIONS.items():
        if first.startswith(f"This session: {title}."):
            return session
    raise AssertionError("unknown session")


def script(by_session: dict[str, list], seen: dict, on_step=None, before=None):
    """A model that plays each session kind's steps in order, then finishes. `on_step(session, done)` runs
    before each answer; `before(session, done)` is awaited before it, to hold sessions at a barrier."""
    async def answer(messages, info: AgentInfo) -> ModelResponse:
        session = session_of(messages)
        done = sum(1 for m in messages if isinstance(m, ModelResponse))
        if before is not None:
            await before(session, done)
        seen.setdefault(session, []).append(messages)
        steps = by_session.get(session, [])
        name, args = steps[done] if done < len(steps) else (FINAL, {"summary": "Done.", "unresolved": OPEN})
        if on_step is not None:
            on_step(session, done)
        if name == FINAL:
            name = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(name, args)])
    return FunctionModel(answer)


def returns(messages, name: str) -> list:
    return [p.content for m in messages for p in getattr(m, "parts", [])
            if isinstance(p, ToolReturnPart) and p.tool_name == name]


QUIET_SESSION = [(FINAL, {"summary": "Nothing here.", "unresolved": OPEN}),
                 (FINAL, {"summary": "Nothing here.", "unresolved": OPEN})]
NUMERIC_GAP = [("report_gap", {"gaps": [{"pages": [24], "reason": "The report prints no share capital or "
                                                                  "related-party note."}]}),
               (FINAL, {"summary": "Reported that the numeric notes are not printed."})]
