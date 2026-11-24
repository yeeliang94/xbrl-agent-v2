# Handoff — start here

Written 19 November 2026, updated 18 November 2026 after step 4.
A new session reads this file first. It gathers everything that is open in
one place. `build-log.md` holds the history behind it.

## Where things stand

- **Repository:** `yeeliang94/xbrl-agent-v2` (public). Local copy at
  `/Users/user/Desktop/xbrl-agent-v2`.
- **Branch:** `main`. Commits on `main` are not all pushed (check `git status`). No open pull requests.
- **Done on the Mac:** step 0 (skeleton), step 1 (templates and figures),
  step 2 (scoring tool), step 3 (reading and setup), step 4 (the figures
  agent on the balance sheet). Each was checked, reviewed and fixed.
- **Not done anywhere:** a live Claude call, anything on Windows, anything
  against a genuine mTool workbook or a workbook a person filled.
- **22 November 2026:** the owner approved `prototypes/review-prototype-v3.html`
  and decision record 3 (scope-only questions, "Needs you", Right or Wrong
  with a scope, proposed guidance lines). Step 5 builds to it. Background:
  `docs/document-agent-lessons.md`.
- **Step 5 (review loop)** is built, reviewed, fixed and merged to `main` (23 November). It was built on branch
  `step-5-review-loop`. See `build-log.md`, step 5.
- **Step 6 (notes)** is built, reviewed, fixed and merged to `main` (23 November), from branch `step-6-notes`.
  See `build-log.md`, step 6, and decision record 4.
- **Step 7 (all statements)** is built, reviewed, fixed and run live on
  branch `step-7-statements` (23 November), merged. See `build-log.md`,
  step 7. Group is proven with fakes only: no Group test document exists.
- **Step 8 (mTool fill)** is built, reviewed and fixed on branch `step-8-mtool-fill` (cut from step 7), not
  merged. See `build-log.md`, step 8. Opening the filled file in mTool waits for a Windows run.
- **Steps 7 and 8** were merged to `main` on 23 November (owner's yes).
- **Step 9 (MPERS)** is built and reviewed on branch `step-9-mpers` (23 November), not merged. Proven
  with fake models only: no MPERS test document exists. See `build-log.md`, step 9.
- **Step 10 (reports and part-filled workbooks)**: server built and reviewed on branch `step-10-reports`
  (cut from uncommitted step 9), not merged. Its screens are built from the approved
  `prototypes/step-10-prototype.html`. See `build-log.md`, step 10.
- **Next:** step 11 (switch-over). Live
  model spend is capped at $5 for now; about $2.46 is used.

What works today: log in, the run list, Settings; saving, editing, moving,
confirming and restoring a run's figures through the server, with history,
nine hard stops and live checks; reading a statement in report or template
order; attaching a filled workbook to a run and scoring it, in the app and
from the command line. Uploading a PDF, the Reader, and the setup screen
(step 3). Traces, server logs and usage downloads. Confirming setup now
runs the figures agent on the balance sheet (Company, MFRS). The browser has
no review screen yet.

## Step 4 result (for step 5 and step 7)

- The figures agent sees the template as an outline (each field its own id,
  its path, heading / line / total with parts and signs) and saves by id.
  All nine hard stops stay (owner, 18 November 2026).
- Judged on Doc 1, Doc 2 and Doc 3 against `test-data/answer-keys/`
  (`docs/answer-keys.md`). **Doc 4 is set aside** (owner: the document has
  too many problems of its own); the live test leaves it out unless
  `LIVE_DOCS` names it.
- The bar is v1's average over its recent runs: Doc 1 0.85, Doc 2 0.94,
  Doc 3 0.93. Live test: `LIVE_OUT=<folder> venv/bin/python -m pytest
  tests/test_extraction_live.py -m live -s` (about 1 to 2 cents and 2 to 4
  minutes a document). Results are in `build-log.md`, step 4.
- **Overfitting (owner's concern).** Only general principles or tool
  feedback go into the agent. Judge on several runs, not one. Ask the
  owner for 3 to 5 hold-out documents that are never tuned on.

## Read next, in this order

1. `AGENTS.md`: the rules every coding agent follows.
2. `docs/backend-plan.md`: the design, section 7 for the build order,
   section 9 for the owner's decisions.
3. `docs/build-log.md`: what each step delivered, each review and what was
   rejected.
4. `docs/api-contract.md`: what the browser and the server say to each other.
5. `docs/agent-lessons.md`: v1's lessons, for writing the agents' instructions.
6. `docs/v1-reuse-map.md`: what v1 code can be copied and what it depends on.
7. `docs/decisions/01` to `04`, and `prototypes/review-prototype-v3.html`:
   the agreed behaviour and look of the screens.

## Remaining build steps

Sizes are estimates against step 1 (= 1). About 2.6 are done; about 13 to 16
remain.

| Step | What it adds | Size |
|---|---|---|
| 3. Read | Upload a PDF (Word files are refused). The Reader agent. The document map. The setup screen | 1.5 |
| 4. One statement | The figures agent with the code workbench, on the balance sheet | 1.5 to 2 |
| 5. Review loop | The review screen, comment rounds, the Reviewer agent, the score in the app | 2.5 to 3 |
| 6. Notes | The notes agent, notes that keep the source look, the preview picture, format tools | 2.5 to 3 |
| 7. All statements | The other four statements, Group filings, one agent tested against five | 1 to 1.5 |
| 8. mTool fill | Filling the mTool file, the receipt, the template toolkit | 1.5 |
| 9. MPERS | The second accounting standard | 0.5 to 1 |
| 10. Reports and part-filled workbooks | Three reports. Starting from a workbook that already holds figures | 1.5 |
| 11. Switch-over | v1 and v2 side by side on agreed documents | 0.5 |
| 12. Template investigation | The template toolkit and the agent that proposes placements for a template code cannot read; a person checks each (owner, 23 November 2026: build last; screen approved in `prototypes/fill-placements-prototype.html`) | 0.5 to 1 |

Each step's "done when" line is in `backend-plan.md` section 7.

## Waiting on the owner

Items 3 and 5 to 11 were decided on 18 November 2026 (see "Decided by
the owner, not yet built" and `backend-plan.md` section 9). Nothing left
here blocks step 3 except the owner's go-ahead.

1. **Anthropic key.** Add `ANTHROPIC_API_KEY=...` to `.env`. Then run
   `venv/bin/python scripts/smoke_models.py` to finish step 0's own test.
2. **A run on the enterprise machine.** `start.bat`, then
   `venv\Scripts\python.exe scripts\check_gateway.py`. Send back its whole
   output. It prints PASS or FAIL per step and no document data.
3. ~~Genuine mTool template~~ Decided: the ten `templates/mTool_*.xlsx`
   workbooks are genuine and usable. `MBRS_test.xlsx` is no longer needed.
4. **A workbook a person filled, with its document.** Without one there is
   no real score for v1 or v2.
14. **An MPERS filing to test with**, ideally with a workbook a person filled. Step 9's "done when" score waits on it.
12. **A Group filing to test with.** Step 7 fills the Group columns, but no
    test document is a Group filing, so it is proven with fake models only.
13. **The medium placements in the step 7 answer keys** (`answer-keys.md`,
    "Statement placements").
5. ~~Hard stops~~ Confirmed for now; rethink in step 4 (below).
6. ~~Share-capital Total column~~ Decided and built: compared under totals.
7. ~~Login limits~~ Decided: move them to the Settings page.
8. ~~Font~~ Decided and built: the computer's own font.
9. ~~Word files~~ Decided: PDF only on every machine. No docx2pdf.
10. ~~Review depth~~ Decided: the full panel on every step.
11. ~~Speed or usage~~ Decided: independent steps may run side by side;
    pausing for the usage limit is accepted.

## Decided by the owner, not yet built

These are in `backend-plan.md` section 9 and must hold when their step is built.

- Notes splitting follows the 5 August 2026 rule: whole by default, one
  level of split, no duplicates.
- Share counts printed in thousands are copied as printed and flagged, not
  multiplied.
- Unsplit cash ("Balances with licensed banks") is firm guidance on the
  Settings page, not a shared instruction.
- Claude's code sandbox is for test documents only. A setting, off by
  default, must enforce it.
- A figure a person typed stays fixed. The agent may only comment on it.
  The store already refuses the change; the import that creates such
  figures is step 10.
- The notes agent previews a picture of its own note against the source page.
- No "remember this" feature. Guidance is per company, plus firm guidance
  for admins.
- Uploads are PDF only, on the Mac, the enterprise machine and Azure. A
  Word file is refused with one plain sentence telling the person to save
  it as a PDF in Word first. v1's Word conversion is not copied. Doc 4, the
  Word test document, is saved as a PDF before it is used.
- The ten `templates/mTool_*.xlsx` workbooks are genuine mTool templates
  and may be used in tests (steps 8 and 10 especially).
- Login idle timeout and lockout limits move from `.env` to the Settings
  page.

## Deferred work, by step

Found in reviews and left on purpose. Do each one in the step named.

**Step 5, from step 4**
- The firm's unsplit-cash convention ("Balances with licensed banks") and
  the Guidance panel need the company and firm guidance store. Until then
  the agent puts an unsplit cash balance in "Other cash and cash
  equivalents", which costs Doc 1 two cells.
- A run whose extraction failed shows "Failed" and opens the setup page,
  which refuses a second confirm. It cannot be deleted. Step 5 adds a retry
  and tells the two failures apart (consider separate statuses).
- Agent comments and raise_flag (backend-plan 4.6) are not built.
- An agent can overwrite a figure a person edited (history keeps it). A
  refusal would be a new hard stop: ask the owner.
- The worker runs one job at a time. Decide before agents run side by side.
- Anthropic caching (`anthropic_cache`) and Claude's sandbox are untried:
  no key.
- The code workbench is calculation only; no files go into the sandbox.
  It was never used in the live runs.
- Deferred as low value by the step 4 review: stage rows written inline in
  `app/extraction/job.py`; catalogue queries inside `outline.py`; reading
  and agents packages importing each other; the overall sign in
  `show_section`.

**Step 5, with the review screens**
- Tell a non-admin why Settings is greyed out.
- Show a Settings save error beside the control that failed.
- Check messages are plain sentences already; the screen should show them
  as they are.

**Step 6**
- Notes scoring ("placed in the same field"). The unused version was
  removed from step 2 and is written when notes exist.
- The check "note citations agree" is built and reports "not assessed"
  until notes are saved.
- Prose notes and reports are not loaded into the template catalogue yet.

**Step 8**
- Move the workbook-reading modules (`xlsx_cells`, `xlsx_formulas`,
  `mtool_layout`, `mtool_address`) out of `app/scoring/` into a neutral
  package, so the mTool fill does not depend on scoring.
- Read template cells through `app/catalog/lookup.py`, not with queries
  inside the reader.
- The step's test uses the genuine mTool workbooks in `templates/`.

**Before the Azure deployment** (both done, 24 November 2026)
- Lockout behind Azure's front end: on Azure the lockout reads the last
  `X-Forwarded-For` entry, which Azure's front end adds, without its port
  (`app/auth/routes.py`). Not yet seen on a real Azure request.
- The lockout list now forgets expired entries.
- The deploy itself: `docs/azure-deploy.md`. Not yet run on Azure.

**Only if runs grow much larger**
- A statement view loads every figure of the run and then filters.
- The run list and the comparison's list of differences have no paging.

## Housekeeping

- `prototypes/review-prototype.html` is superseded by
  `review-prototype-v2.html`.
- `docs/requirements.md` section 4.4 still says a note is never adjusted
  automatically. `backend-plan.md` section 4.6 replaces that line.
- The owner has not said in words that the second prototype is approved.
  They gave feedback, it was applied, and they said to build.

## Context that lives outside this repository

v1 holds two years of lessons. Most of what v2 needs was distilled into
`requirements.md` section 3, `agent-lessons.md` and `v1-reuse-map.md`. The
rest stays where it is. None of it loads by itself in a session started in
this folder, so the orchestrator reads the sources for a step BEFORE
briefing it, and puts what matters into the brief.

**Where it is**

| Source | Where | Notes |
|---|---|---|
| v1's rules and their history (31 numbered rules) | `.v1-reference/CLAUDE-REFERENCE.md`, `AGENTS.md`, and the `AGENTS.md` inside `db/`, `mtool/`, `notes/`, `tools/`, `web/` | Search for `### <number>.` |
| v1's product documents | `.v1-reference/docs/` | For example `MTOOL-NOTES-AUTHORING.md`, `ROLLED-FORWARD-WORKBOOKS.md`, `MPERS.md`, `workflows/` |
| v1's working plans and investigations | `/Users/user/Desktop/xbrl-agent/docs/local/` | Not in the reference copy, because v1 does not commit them |
| The owner's notes from past sessions (about 70 files) | `/Users/user/.claude/projects/-Users-user-Desktop-xbrl-agent/memory/` | `MEMORY.md` there is the index. A session started in this folder does not see them unless it reads that path |
| Windows test plans for mTool | `/Users/user/Desktop/xbrl-agent-private-files/docs/` | |
| The Document Agent (code sandbox through the gateway) | `/Users/user/Desktop/Document Agent/` | `prototype/sandbox_agent/WINDOWS.md` and `proxy_check.py` |
| The owner's taste guide and global instructions | `~/.agents/taste/ui.md`, `~/.claude/CLAUDE.md` | These load in every session |

**The reference copy is frozen** at v1 commit `4bb9c6bf`. If v1 changes
after 19 November 2026 (for example a fix found on Windows), v2 will not
see it. Before each step, run `git -C /Users/user/Desktop/xbrl-agent log
--oneline 4bb9c6bf..origin/main` and read anything that touches the step.

**What to read before each step**

Rule numbers are v1's. Note names are files in the owner's notes folder.

| Step | v1 rules | Owner's notes and documents |
|---|---|---|
| 3. Read | 1, 13, 26, 29, 31 | `project_word_input_brainstorm`, `project_word_formatting_fidelity`, `scanned_pdf_compaction_thrash`, `scout_run_recording`, `chunkless_rag_assessment`, `table_preparation_feedback_loop`, `notes_verbatim_and_scout_inventory`, `veracode_rescan_cwe78` (how the Word converter is called safely) |
| 4 and 7. Statements | 2, 2a, 5, 6, 12, 15, 17, 18, 21, 25 | `statement_prompt_generalisation`, `project_extraction_judgement_improvements`, `project_extraction_hardening_2026_06`, `run84_review_validated`, `rollover_sign_diagnosis_run211`, `socf_articulation_hardening`, `socf_duplicate_cash_end_label`, `save_gate_acknowledge_unresolved`, `agent_digging_regression_assessment`, `feedback_sub_sheet_prompt_wording`, `trace_audit_183_185_fixes`, `agent_architecture_review_2026_11_10`, `project_codemode_spike_outcome`, `project_harness_learnings`, `project_harness_efficiency_plan`, `openai_responses_everywhere`, `pydantic_ai_2_66_upgrade`, `project_run_latency_plan` |
| 5. Review loop | 7, 10, 19, 20, 27, 30 | `project_design_system`, `ui_audit_2026_09_29`, `project_motion_transitions_plan`, `reviewer_verify_scope_false_green`, `spot_check_clean_runs`, `project_human_file_compare`, `roles_accounts_issues` |
| 6. Notes | 14, 16, 22, 27, 31 | every note whose name starts `notes_` or `project_notes_`, plus `mtool_notes_textblock_mechanism`, `mtool_size_recon_findings`, `capital_related_party_fixes_2026_10_22`, and v1's `docs/MTOOL-NOTES-AUTHORING.md` |
| 8. mTool fill | 16, 21, 28 | `mtool_offline_patch_proven`, `mtool_size_recon_findings`, `mtool_notes_textblock_mechanism`, `export_keeps_live_formulas`, and the Windows test plans |
| 9. MPERS | 3, 15 | `mpers_labels`, `mpers_calc_split`, `abstract_row_guard_mpers_gap`, `mfrs_soci_socf_direct_linkbase_fix`, v1's `docs/MPERS.md` |
| 10. Reports and part-filled workbooks | 23 | `rolled_forward_workbooks`, `rolled_forward_workbook_status`, v1's `docs/ROLLED-FORWARD-WORKBOOKS.md` |
| Azure and security | 11, 24 | `auth_layer_status`, `veracode_findings_fix`, `veracode_rescan_cwe78` |
| Any step | | `concurrent_agents_same_checkout`, `feedback_plain_language_communication` |

A note records what was true when it was written. Check it against the code
before relying on it.

## How the work is done

- **Roles.** One orchestrating session plans, briefs, checks and commits.
  Coding is handed to Opus 5.5 agents (the owner's standing request, to
  save usage). Coding agents never commit.
- **One branch per step,** named `step-N-...`, from `main`. Merge to `main`
  by fast-forward after the review fixes. No pull requests unless the
  owner asks.
- **A brief for a coding agent** names the files to read first (always
  `AGENTS.md`, then the plan sections, the contract, the build log), what
  to build, the "done when" line, the checks to run, and what to report.
  It tells the agent to write new routes into `api-contract.md` before
  coding them.
- **The orchestrator's own checks after each agent:** the server tests,
  the browser build and tests if `web/` changed, and the real app in a
  browser or over HTTP. Never report a step as done on the agent's word.
- **Review, once per step, before reporting it:** the owner's `ship-review`
  skill. Big steps get the panel (Correctness, Security and data,
  Architecture, Agent harness where agents are touched, Simplicity,
  Performance, Spec fit, UI and taste where screens change), Codex as a
  second opinion, then an independent checker that scores each finding.
  Fix everything scoring 70 or more, and the cheap ones below that. Record
  what was rejected and why in the build log.
- **Reporting to the owner:** plain business English, short sentences:
  the verdict, why, then the step they need to take. Always say what was
  not verified and give the git state.
- **Update `build-log.md` and this file** when a step finishes or a
  decision is made.

## Things that will trip up a new session

- **Python:** always `venv/bin/python`. **Node is not on PATH:** run
  `export PATH="/Users/user/.nvm/versions/node/v24.11.1/bin:$PATH"` first.
- **v1 reference copy.** `.v1-reference/` is not committed. If it is
  missing, recreate it:
  `git clone --local --no-checkout /Users/user/Desktop/xbrl-agent .v1-reference && git -C .v1-reference checkout 4bb9c6bf`.
  The Desktop copy of v1 may be one merge behind that commit.
- **`.env` is not committed.** It holds the OpenAI key copied from v1's
  `.env`. `.env.example` lists every name.
- **Ports.** The server uses 8100. The browser dev server uses 5174.
- **Trying the app.** Set `BOOTSTRAP_ADMIN_EMAIL` and
  `BOOTSTRAP_ADMIN_PASSWORD` in `.env`, run `./start.sh`, open
  `http://localhost:8100`. `start.sh` itself has not been run end to end;
  the server was started directly each time with
  `venv/bin/python -m uvicorn app.main:app --port 8100`.
- **The demo run:** `venv/bin/python scripts/seed_demo_run.py`, then
  `scripts/make_filled_workbook.py 1 out.xlsx --seed-differences`, then
  `scripts/score_runs.py --run 1 --workbook out.xlsx`. The seed script
  needs an account to exist first.
- **Screenshots.** Playwright is not installed in this repository. A copy
  at `/Users/user/Desktop/Cosec Workspace/node_modules/playwright` was
  used to drive a browser for screenshots only. Do not run Playwright test
  suites unless the owner asks.
- **Codex review.** Run it with
  `node "$(ls -d ~/.claude/plugins/cache/openai-codex/codex/*/ | tail -1)scripts/codex-companion.mjs" adversarial-review --wait --base <commit>`.
  It fails with "ENOBUFS" when the diff holds large copied files, so put
  copied templates or data in their own commit and use that commit as the
  base. Its sandbox cannot run the test suite.
- **Usage limit.** A review panel of seven or eight agents at once has hit
  the limit each time. A stopped agent keeps its work and can be resumed
  with a message; it does not need to be restarted.
- **Live model calls cost money.** Up to step 2 only a few tiny test calls
  were made. From step 3 agents run on whole documents. Tell the owner
  before each of those.
- **Test documents** are in v1's `data` folder: Doc 1, Doc 2, Doc 3 (PDF)
  and Doc 4 (Word). None has a workbook filled by a person.
