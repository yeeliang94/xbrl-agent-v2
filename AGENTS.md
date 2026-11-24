# AGENTS.md — XBRL Agent v2

Operating contract for every coding agent in this repository.

## Read first

An orchestrating session reads `docs/HANDOFF.md` before anything else.

1. `docs/backend-plan.md`: the design, the build order and the decisions.
2. `docs/requirements.md` section 3: the lessons from v1 that must hold.
3. `docs/api-contract.md`: what the browser and the server say to each other.
4. `docs/build-log.md`: which step is in progress and what is already done.
5. `prototypes/review-prototype-v3.html`: the approved look and behaviour (v3 supersedes v2); `prototypes/review-prototype-v4.html` for the notes screens.

v1's latest code is in `.v1-reference/` inside this repository (commit
`4bb9c6bf`, not committed here). Read v1 from there. The copy on the Desktop
at `/Users/user/Desktop/xbrl-agent` is one merge behind. Never change either.
`docs/v1-reuse-map.md` says what to copy and what it depends on.
`docs/agent-lessons.md` holds the lessons for the AI agents' instructions. When the
plan says "copy from v1", read the v1 file and its tests first, then copy the
smallest part that does the job, with its tests.

## Layout

- `app/`: the server (Python 3.12, FastAPI, PydanticAI, SQLite).
- `web/`: the browser app (React, TypeScript, Vite, plain CSS files).
- `tests/`: server tests (pytest). Browser tests sit beside the code (Vitest).
- `scripts/`: command-line tools. `docs/`: plans and decisions.

## Rules

- **Python:** run everything with `venv/bin/python`. Never bare `python`.
- **Node:** it is not on PATH. Use
  `export PATH="/Users/user/.nvm/versions/node/v24.11.1/bin:$PATH"` first.
- **Dependencies:** only what v1 already pins in its `constraints.txt`, at
  the same versions. Anything else needs the owner's approval: stop and say so.
- **Secrets:** keys and the gateway address live in `.env` only. Never in
  code, logs, tests or responses. Every other setting lives in the database
  and on the Settings page.
- **Files:** every file the app reads or writes goes through the safe-path
  helpers. Writes are atomic (temporary file, then swap).
- **Login:** every `/api/*` route needs a session, except login and health.
  Permissions are checked on the server.
- **Models:** only `app/models/factory.py` builds a model connection. No
  Gemini. GPT models use OpenAI's Responses interface.
- **Agents:** keep `end_strategy="early"`. An agent's own step limit fires
  before the library's request limit. Hard rules live in tools, and a tool
  that refuses says why in one plain sentence.
- **Figures and notes:** every write adds a history row. Heading rows refuse
  values. A total is never forced to balance. A missing line is not zero.
- **No feature switches for unfinished work.** No speculative options.
- **Keep it small.** A file over about 400 lines is a sign to split it.
- **Record everything, so any step can be debugged later** (owner, 18
  November 2026). Every model call goes in `model_calls` with tokens, cost,
  duration and any error, failed calls included. Every agent keeps its full
  transcript, and raw model output is kept even when it fails validation.
  Each meaningful step writes an event. The server log has a line per stage
  start and end and a full traceback for every failure. Everything is
  findable by run id and goes into the run's export. Document text, keys and
  passwords never go in the server log; document text lives only in the
  run's own records.

## Writing instructions for the AI agents inside the app

The agents do well when they can look, explore, check and fix. They do
badly when they are boxed in by rules written for last month's document.

- **Principles before rules.** An instruction says what good work looks
  like and why. It does not list label-by-label cases. A principle still
  works when a template or a report layout changes.
- **Give judgement room.** The agent decides how to read the document, in
  what order to work and which tool to use.
- **Tools and feedback over guardrails.** When an agent gets something
  wrong, first ask what it could not see or check. Give it a way to see it,
  or a tool result that tells it plainly what went wrong.
- **Fix the cause.** A failure on one document is fixed by a better general
  principle, tool or feedback. Add a validation rule or a document-specific
  instruction only when no general principle can cover it, and write down
  why beside it.
- **Carry v1's lessons as principles.** v1's statement instructions hold
  hard-won tips (signs, sub-schedules, which total owns a line, comparatives).
  Read all of them before writing v2's. Keep each lesson once, in the shared
  instructions, worded so it applies across statements.
- **Hard stops are few and live in code.** They are only for writes that
  would corrupt a filing: a value in a heading row, a forced balance, a
  figure with no source page, a write outside the run. Each returns one
  plain sentence the agent can act on. Do not add to this list without the
  owner's agreement.

## Browser app

- Colours, spacing and type come from `web/src/styles/tokens.css` only. The
  values are those in the prototype's `:root`.
- One component per job: one button, one switch, one dropdown, one table,
  one status, one dialog. Reuse before adding.
- No helper text under fields, no small labels above titles, no coloured
  edge lines, no tinted status pills. A status is a dot and a word. A
  failure is the one exception: a filled dark-orange label with white text,
  as in the prototype.
- Sentence case. Two weights: regular and medium.

## Tests

- A test checks behaviour a user or another module depends on. No tests of
  private details.
- Live model calls are marked `live` and are left out of the default run.
- Do not run Playwright test suites.

## Done

A step is done when its "done when" line in the build log is true and:

- `venv/bin/python -m pytest tests/ -q` passes.
- `cd web && npm run build && npm test` passes, if `web/` changed.
- Nothing unrelated to the step changed.

Do not commit, push or open a pull request. The orchestrator does that after
checking the work.

## Reporting back

Plain business English, short sentences. Say what was built, every check
that ran with its result, every check that did not run and why, and anything
that only a Windows run can confirm.
