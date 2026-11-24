# Build log

**Resuming in a new session? Read `HANDOFF.md` first.** It lists what is
left, what is waiting on the owner, what was deferred and how the work is
done. This file is the history behind it.

The running record of the build. A new session reads this first to see where
to pick up. The steps and their "done when" lines come from
`backend-plan.md` section 7.

How the work is done: an orchestrating session hands each step to coding
agents (Opus 5.5), checks their work (tests, build, browser), has it
reviewed, then commits. Coding agents do not commit.

Review: each finished chunk gets one review before it is reported. Codex can
be called to review any chunk. Each finding is checked against the code
first. Valid ones are fixed. Rejected ones are named with the reason.

## Status

| Step | Status | Commit |
|---|---|---|
| 0. Skeleton | Done on the Mac, 19 November 2026, except a live Claude call (no key). Windows not run | see `git log` on `main` |
| 1. Templates and figures | Done on the Mac, 19 November 2026. Windows not run | see `git log` on `main` |
| 2. Scoring tool | Done on the Mac, 19 November 2026. Not proven on a genuine mTool workbook. Windows not run | see `git log` on `main` |
| 3. Read | Done on the Mac, 18 November 2026. The four test documents match the answer key live. Windows not run | see `git log` on `main` |
| 4. One statement | Done on the Mac, 18 November 2026. Beats or equals v1 on the balance sheet of Doc 1, 2 and 3 live (Doc 4 set aside by the owner). Windows not run | see `git log` on `main` |
| 5. Review loop | Done on the Mac, 22 November 2026; merged to `main` 23 November 2026. Live correction rounds passed on Doc 1, 2 and 3. Windows not run | `main` |
| 6. Notes | Done on the Mac, 23 November 2026; merged to `main` 23 November 2026. Beats v1's notes placement on Doc 1, 2 and 3 live. Windows (mTool paste) not run | `main` |
| 7. All statements | Done on the Mac, 23 November 2026; merged to `main`. Meets or beats v1 on every statement of Doc 1, 2 and 3 live. Group proven with fakes only (no Group document). Windows not run | `step-7-statements` |
| 8. mTool fill | Done on the Mac, 23 November 2026, merged | Opening the file in mTool waits for Windows |
| 9. MPERS | Built on the Mac, 23 November 2026, on branch `step-9-mpers`, not merged. Proven with fake models only: no MPERS test document exists, so the "done when" score is not met | `step-9-mpers` |
| 10. Reports and part-filled workbooks | Server built on the Mac, 24 November 2026, on branch `step-10-reports` (cut from uncommitted step 9), not merged. Screens built after the owner approved `prototypes/step-10-prototype.html` | `step-10-reports` |
| 11. Switch-over | Not started | |
| 12. Template investigation | Not started | Moved out of step 8 by the owner, 23 November 2026 |

The steps were renumbered on 19 November 2026 (see `backend-plan.md`
section 7).

## Standing facts

- **Keys on the Mac:** v1's `.env` has an OpenAI key. It has no Anthropic
  key, so a live Claude call cannot be made until the owner adds one.
- **Scoring with real filed workbooks:** allowed, but getting results out of
  the enterprise environment is manual. The owner tests there and sends
  screenshots. On the Mac, scoring uses the test documents in v1's `data`
  folder.
- **Windows:** nothing is confirmed there until the owner runs it.

## Standing instructions from the owner (18 November 2026)

- Build every step through to the end without stopping for approval
  between steps.
- A true blocker, such as a missing key, is noted here and left for later.
  The build carries on around it.
- Each step is still checked and reviewed before it is committed.

**Changed on 19 November 2026:** the owner asked for the build to pause once
step 2 is fully complete. Step 3 does not start until the owner says so.

## Open blockers

| Blocker | Affects | Needed from the owner |
|---|---|---|
| No Anthropic key on the Mac | Live Claude calls. Unit tests still cover the Claude connection | `ANTHROPIC_API_KEY` in v2's `.env` |
| Nothing has run on Windows | Gateway route, certificates, mTool rendering of notes | A run on the enterprise machine |

## Questions for the owner (not blocking)

| Question | Until answered |
|---|---|
| Splitting a note: allowed at first-level sub-sections. Owner, 24 November 2026: keep the split, and give people a view that shows at a glance where every note sits and lets them move it. The screen follows `prototypes/notes-placement-prototype-v2.html`, with quiet flags (a hollow ring and the one grey word "Check"). Built 24 November 2026: the Placement map under Notes | Whole by default, one level of split |
| A split note's opening paragraph. Owner, 24 November 2026: the team repeats it in every field the note is split into, when it is truly general and only a few sentences long. A long or specific opening paragraph goes once into "Material accounting policy information" (owner, 24 November 2026) | The notes agent judges whether it is general and short |
| A note a person moves. Owner, 24 November 2026: the move counts as checked ("Confirmed"). Needs a small server change: a move by a person also confirms | Moves stay unconfirmed until the change is made |
| Closest-line suggestions for figures. Owner, 24 November 2026: can wait | Figures are moved by hand, with no suggestions |
| Share counts printed in thousands: multiply by 1,000? Owner, 24 November 2026: leave as it is for now | Copy as printed and flag for review |
| Unsplit cash ("Balances with licensed banks") is a firm convention, not a general principle | Put it in firm guidance on the Settings page, not in the shared instructions |

## Where the build stands (18 November 2026)

Steps 0 to 3 are on `main`. The owner restarted the build on 18 November
2026 and asked for the remaining steps to proceed. Next is step 4 ("One
statement") from `backend-plan.md` section 7.

**What works today, on the Mac**

- Log in, see the run list, open Settings and change them.
- A run's figures can be saved, edited, moved, confirmed and restored
  through the server, with history, nine hard stops and live checks.
- A statement can be read in report order or template order.
- A workbook a person filled can be attached to a run and scored. The same
  scoring runs from the command line and prints counts only.
- Upload a PDF from "New run". The Reader transcribes every page and maps
  the statements, layouts and notes; the setup screen shows its
  suggestions with the source page and reason, and "Start run" confirms
  them. The run then waits at "Ready" for step 4's extraction.
- Download a run's traces from the server (the button arrives with step
  5's run screen), and server logs and usage from Settings.
- The browser has no review screen yet.

**To try it**

1. `./start.sh` (or set `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD`
   in `.env` first, so there is an account to log in with).
2. `venv/bin/python scripts/seed_demo_run.py`
3. `venv/bin/python scripts/make_filled_workbook.py 1 out.xlsx --seed-differences`
4. `venv/bin/python scripts/score_runs.py --run 1 --workbook out.xlsx`

**Waiting on the owner**

| Item | Why it matters |
|---|---|
| An Anthropic key in `.env` | No live Claude call has been made. Step 0's own test is not fully met |
| A run on the enterprise machine: `start.bat`, then `scripts/check_gateway.py` | Nothing is confirmed on Windows: the gateway, the certificates, both ways of getting a sandbox |
| A workbook a person filled, with its document | No real score exists for v1 or v2 |

**Decided on 18 November 2026:** uploads are PDF only on every machine (no
Word conversion, no docx2pdf). The ten mTool workbooks in `templates/` are
genuine and may be used for tests. Login idle timeout and lockout limits
move to the Settings page. The nine hard stops stand for now; the owner
expects to rethink them with the figures agent's design in step 4. The
share-capital and related-party Total column is compared under totals, not
scored, when a category beside it is filled (built the same day). The app
uses the computer's own font; Geist and the Google Fonts link are gone
(built the same day). Reviews keep the full panel on every step, and
independent steps may run side by side; pausing for the usage limit is
accepted. See `backend-plan.md` section 9.

## Start scripts, packages and Azure (built on the Mac, 24 November 2026; branch `step-10-reports`, not committed)

The owner asked for v1's scripts, made for v2, and for v2 to run on the App
Service v1 already uses. Steps and reasons: `docs/azure-deploy.md`.

- `start.sh` and `start.bat` now do what v1's did:
  - they look for Python 3.12 in more places, and remake a broken or old
    Python environment;
  - they find Node.js when it is not on the path;
  - they build the browser app;
  - they skip a step whose inputs have not changed (`scripts/startup_cache.py`).
- `scripts/package.py` builds two zips:
  - `azure`: only what the running app reads, with the commit in `version.txt`;
  - `veracode`: source code only.
  `scripts/package_for_veracode.sh` and `.bat` wrap the Veracode one, and
  `scripts/deploy_azure.bat` builds the Azure one and sends it.
- On Azure, the live database sits on the container's own disk. Copies go to
  `<XBRL_OUTPUT_DIR>/v2-db-copies` (`app/db/copies.py`, ported from v1's PR 68).
- `server.py` lets v1's startup command (`uvicorn server:app ... --proxy-headers`)
  run v2 unchanged.
- `/api/health` now reports the deployed commit and the copies' state.
- The login lockout forgets expired entries. On Azure it keys on the address
  Azure's front end adds, the last `X-Forwarded-For` entry. It ignores the
  first one, which `--proxy-headers` uses and the sender can write. This closes
  both "before the Azure deployment" items.

Checked on the Mac:

- the exact startup command, with a pretend `/home`;
- a stop, then a fresh container restoring the copy and signing in;
- the Azure zip installed into an empty folder with its own Python environment;
- `start.sh` run twice, the second time skipping every step.

`start.bat`, `deploy_azure.bat` and a real Azure deploy are not run: only
the Windows laptop can.

## Step 12 (built on the Mac, 24 November 2026; branch `step-10-reports`, not committed)

Template investigation, as `docs/step-8-plan.md` 8f and the approved `prototypes/fill-placements-prototype.html`.

- **Toolkit** (`app/workbook/toolkit/`, `INSTRUCTIONS.md`): six one-job scripts printing plain text: identify,
  list_rows, find, read, trial_fill (a temporary copy, read back, deleted) and compare. None changes a workbook.
- **Investigating agent** (`app/filing/investigate/`): queued by the fill job for the figures a fill left with no
  single cell or that did not read back, never for totals (the template works them out), and only for figures no
  finished investigation of the same template looked at. It proposes a cell per figure with evidence; code refuses
  a formula, a locked cell, a cell holding a value, a cell the fill wrote or one proposed for another figure. Each
  figure line gives its headings, its SSM name and "this year" or "last year" (a blank template's dates are its
  own placeholders). What it found no place for is kept with its reason; only those read "No place found in this
  template." on the receipt.
- **Saved places** (`template_mappings`): a person's Use saves the cell with its row's words for the template's
  fingerprint. A later fill uses it only while that row still holds those words, and it wins over the code's own
  cell for that figure. Saving with nothing used fills nothing.
- **Screens:** the receipt says "Looking for places in the template", offers Check placements, and shows a failed
  search with the failure label; Check placements lists figure, place in words, evidence, Use or Skip.

**Live** (`tests/test_investigation_live.py`, the Company template with the sub-classification sheet's SSM names
removed): first run put this year's figures in last year's column (the template's placeholder dates); fixed by
saying "this year/last year". After the review fixes: 190 figures to place, 190 proposed, 0 wrong, 8 model calls,
$0.014.

**Review** (big tier: correctness, simplicity, architecture, performance, spec fit, UI, agent harness, security,
Codex; checker scored 26 findings). Fixed: a failed investigation blocked the template for good; Use did nothing
for a read-back or shared-cell figure; figure lines lacked headings and SSM name; totals were sent to the agent;
"No place found" for figures never looked at; saved cells used after rows moved; Group columns; failure label;
the shared table; formatter-only changes reverted; an investigation no longer makes the run busy; saving with
nothing used. Rejected: a saved place making the template known (the plan asks for it), the refusals on proposed
cells (owner-approved in 8f), and five layering or duplication points with no effect on people. The fixes were not
re-reviewed. Not built: removing or listing saved places; a history row for each saved place.

**Checks:** server 912 passed (18 live deselected); browser build passes; browser tests 222 passed. Checked in the
browser on a seeded demo run: the receipt, Check placements, Save and fill again (536 to 538 written), and skipping
every place. Playwright not run.

## Step 11 (live comparison with v1, 24 November 2026)

Docs 1 to 3 with saved readings (Doc 4 set aside), one run each; v1's average in brackets.

| | Balance sheet | Profit or loss | Comprehensive income | Equity | Cash flows | Notes | Cost |
|---|---|---|---|---|---|---|---|
| Doc 1 | 0.833 (0.85) | 0.889 (0.844) | 1.0 (1.0) | 1.0 (1.0) | 1.0 (1.0) | 1.0 (0.923) | $0.096 |
| Doc 2 | 0.941 (0.939) | 1.0 (0.943) | 1.0 (1.0) | 1.0 (1.0) | 1.0 (1.0) | 1.0 (0.893) | $0.054 |
| Doc 3 | 0.929 (0.929) | 1.0 (1.0) | 1.0 (1.0) | 1.0 (1.0) | 1.0 (1.0) | 0.95 (0.820) | $0.053 |

Reports: every field assessed on all three, every value with a source page, $0.027 in all. 14 of 15 statements
meet or beat v1; Doc 1's balance sheet dipped (it scored 1.0 in step 7): its misses are line choices (machinery
for plant and equipment, long-term for short-term leasehold, a split of other payables). Total live spend for
steps 11 and 12 about $0.30, so about $2.76 of the $5 cap is used. **Still needed from the owner:** the agreed
score and the agreed documents for the switch-over.

## Step 10 (server built on the Mac, 24 November 2026; branch `step-10-reports`, not merged)

Plan: `docs/step-10-plan.md`. The owner said to carry on and to have Fable 5.2 review the work. Built by three
agents (reports; part-filled workbooks; the fill), each briefed from the plan.

**Built:**
- 10a-c, reports: the three reports from the taxonomy (22, 27 and 13 fields on both standards, as v1), a
  `report_fields` table with history, a reports agent run as its own stage when the Reader found a report
  section, and routes to read, edit (with revision) and clear a field. Narratives are kept as note bodies on
  the field, copied by code from page blocks. Six taxonomy files for the report roles were copied from v1.
- 10d-e, part-filled workbooks: an mTool workbook attached at setup is imported when setup is confirmed. Last
  year's figures are locked, this year's typed figures kept fixed, typed totals kept as totals; a misfit
  (first statements, unit, standard, level, year end, layouts) refuses the confirm in one sentence. The figures
  agent sees the imported figures as hints; its last-year readings on kept figures are recorded and compared, and
  a sign-only difference stays open for a person. A new check shows open differences.
- 10g, the fill: with a starting workbook, the fill writes into it, never over an imported cell, lists typed
  cells it cannot account for, and refuses to release a file whose imported cells changed. Report fields and
  narratives are written into all ten genuine templates. mTool locks its date, choice and identity-type cells
  and sets them with its own picker, so those fields are listed "choose it in mTool", as v1.
- 10f: `prototypes/step-10-prototype.html`, approved by the owner on 24 November 2026, then built in `web/`:
  a "Starting workbook" panel at setup (attach, refused with its sentence, attached with what the workbook
  says of itself, remove; a refused start scrolls its sentence into view); a Reports group in the run sidebar
  with each report's unsure count; a report's fields with value, status and page, a side editor per kind
  (text, date, choice) with Save and Clear and the source page, and the wording on its A4 page; an imported
  figure shows "From workbook", the report's comparative beside it, and "Keep the workbook's" for a sign
  question; the fill dialog fills the starting workbook with no upload and counts what it kept. The statement
  view's cells gained `comparison` and `sign_question` for this. Departures from the prototype, each because
  the server has no route for it: no "Use the report's" (last year's imported figures are locked for
  everyone), no comment box on a report field, and no import counts at setup (they exist after the start).
  Checked in a browser on a demo copy of the Doc 3 live run. Review (big tier: correctness, simplicity,
  architecture, performance, spec fit, UI, Codex; an independent checker scored 21 findings). Kept and fixed:
  a starting workbook could be filled only once ("Fill again" added), and a kept figure whose report amount
  differs could not be settled (the cell's comparison now says whether it is open; "Keep the workbook's"
  shows for any open difference, and a row failure still shows first). Also fixed from "worth considering":
  Start run waits while a workbook uploads or is removed; the fill dialog offers nothing until it knows
  whether the run has a workbook; Enter no longer saves an unchanged report field; a stale edit reloads the
  field and a save refreshes the run; a failed or missing reports stage says why above the fields; shared
  CSS de-duplicated. The fixes were not re-reviewed.

**Live:** the reports agent on Doc 1, 2 and 3 (saved readings, no figures agent): every field assessed, every
value has a source page, under 1 cent a document. Two improvements came from these runs: the statutory
declaration may answer short fields (the director primarily responsible for financial management and their
identity number), and agents now see a page's letterhead text, where an audit firm's address is printed (all
agents: `as_reading` and search include it). No live run of the figures agent with a starting workbook.

**Review (big tier):** two correctness reviewers (reports; workbooks), structure with security and speed,
agent harness with spec fit and UI, Codex, and Fable 5.2 (owner's request; verdict "Fix first"). An independent
checker scored 22 findings. Kept (70+): the comparison check invisible to the agents, and the reports agent
forbidden from the statutory declaration. Fixed from "worth considering" (50-69): a setup change after the import
mixing units (now refused, and the fill rechecks the fit); a person-edited typed figure an agent could then
overwrite while the file kept the old number (hard stop 9 now covers any figure from the workbook; a differing
figure is never counted as kept); last year's report values and narrative left in the file unflagged; a statement
fully typed in the workbook failing "no figure was saved"; a stale comparison check; last-year figures added where
the workbook was blank (listed, needs review); a wrong sentence while a sign question is open; the prototype's
invented choice lists, toolbar and switch. Also fixed: an unreadable year end now refuses, a retry with nothing
new no longer fails, a page counts as opened only when it showed something, report reasons capped, the
report patcher moved out of `offline_fill.py`, `app/figures/store.py` back under 470 lines. Not fixed (scored
under 50): stage plumbing shared by notes and reports, the workbook parsed twice at confirm, cell addresses in
the release-failure sentence (the contract documents them), two routers loaded with `__import__`. The fixes
were not re-reviewed.

**Owner decision (24 November 2026):** a person's own in-app edit of a figure typed in the workbook is written
into the filed workbook and listed as "replaced". This is how it works today, so nothing changes.

## Step 9 (built on the Mac, 23 November 2026; branch `step-9-mpers`, not merged)

The owner said to proceed. Most of MPERS was already in place from steps 1 to 8: the MPERS templates and
catalogue, the retained earnings statement (SoRE) as a SOCIE layout, the setup choice, the SoRE balance sheet
check and the three genuine MPERS mTool workbooks in the fill tests. Step 9 found and closed these gaps:

- **Names.** A SoRE run called the statement "changes in equity" in the agent's brief, the run's messages, the
  Reader's events, the review agent's packet and every screen. It is now "statement of retained earnings" (or
  "Retained earnings" on screen) wherever the layout is SoRE.
- **mTool works out two SoRE lines.** The genuine MPERS mTool workbook calculates the restated opening and the
  closing balance with formulas and ignores typed amounts. v1's (and v2's) template had both as typed lines, so
  a statement whose lines did not add up would have filed a closing balance the report does not print. v2's
  two `10-SoRE.xlsx` templates now carry mTool's formulas: the agent sees both as totals, saves the movements,
  and the worked-out closing balance is what the balance sheet check compares. This is v2's one departure from
  v1's catalogue; `test_catalogue_tables_are_identical_to_v1` undoes exactly this change and still matches v1.
- **New check:** "Profit for the year agrees to retained earnings" (SOPL against SoRE). v1 had none.

**Review (big tier):** correctness, simplicity with architecture, agent harness with spec fit and performance,
Codex, and an independent checker scoring 16 findings. Kept (70+): a test that passed without proving anything
(fixed), and the outline showing mTool's two calculated lines as typed (fixed at the root, above). A first
roll-forward check was dropped with that fix, which also removed its findings: first-year filings failing, a
restated-only prior year passing, a prior year with only a closing balance failing, and wording that ignored
the tolerance. Also fixed from "worth considering": the profit check duplicated an existing helper (moved
beside its twin), SoRE still named "Changes in equity" in the agent's list of other statements and in the
Reader's events, the lessons file, a missing MPERS Group SoRE test, and one shared layouts type in the browser.
Not done: the server and browser each keep one line that renames SoRE (scored 40), and the layouts value is
threaded beside the entities rather than passed as the family (scored 25). The fixes were not re-reviewed.

**Checks:** server 818 passed (14 live deselected); browser build passes; browser tests 187 passed. The browser was checked on a seeded MPERS
run: the menu, the statement heading in both orders, the Source tab, comments, Checks, Compare (empty) and
the mTool dialog. Playwright not run. No live model calls: no MPERS document exists.

**Open:** "Scores at least as well as v1 on an MPERS document" is not met. The report v1 ran MPERS on
("Audited Financial Statements for the FYE 31 December 2022", Oriental 1936 Berhad) is an MFRS filing (its
basis-of-preparation note names MFRS), so there is no MPERS document with v1 figures. Needs an MPERS
document from the owner, ideally with a filled workbook.

## Step 8 (done on the Mac, 23 November 2026; branch `step-8-mtool-fill`, merged to `main` 23 November)

Plan: `docs/step-8-plan.md`. The owner said to proceed, approved the placements screen
(`prototypes/fill-placements-prototype.html`) and moved the template investigation agent (8f) to a new last
step, step 12.

**Built:**
- 8a: the workbook readers moved from `app/scoring/` to `app/workbook/`. Fill and scoring place cells through one
  module, `app/workbook/mtool_map.py`, so what is filled is what scoring reads. Template cells come through
  `app/catalog/lookup.py`.
- 8b: v1's patcher as `app/workbook/offline_fill.py`, standard library only, one file so it travels to Windows.
  Finding a cell by label alone was dropped. Every write is read back.
- 8c: `app/filing/`: figures to cells by SSM name, period, entity and equity component. Formula cells, locked
  cells and template totals are never written, except the equity statement's across-the-row totals, which
  mTool leaves as input cells (as v1). A missing figure leaves its cell empty. Values pass through unchanged.
  The ten genuine templates are fingerprinted; others are "probably compatible" or unknown.
- 8d: each note field's prepared text goes into mTool's note store, read back whole. mTool's own
  "[Text block added]" marker goes in the locked visible note cell, as v1 proved on Windows.
- 8e: the `fills` table, a "fill" job with events and log lines, four routes (upload and fill, list, one fill
  with its receipt, download), and the fill and receipt dialogs as in the prototype. A template that is not
  recognised gives "mTool file needs a check" with the reason. Totals the template works out and prior-year
  lines of notes that file the current year only are expected and not listed (owner's call delegated,
  23 November). A correction round is refused while a fill runs.

**Results on the genuine templates** (test runs with every field filled): all ten fill and the scoring reader
reads every written figure back. MFRS Company 2,012 to 2,014 written, MFRS Group 2,292 to 4,024, nothing
unresolved. A large Group fill takes about 1.1 seconds after the review's speed fix (5.4 before).

**Review (big tier):** seven reviewers, Codex and an independent checker scored 25 findings. Fixed: polling
that stopped after one failed request, receipt rows sharing a key, a fill stuck at "filling" after an early
failure, technical errors shown to people, patcher errors dropped (a duplicate note key now marks the note
not written), the receipt counting expected totals as skipped, no way to download a finished file again,
duplicate note-size constants, the equity totals rule narrowed to v1's, a correction round during a fill,
an id shown instead of words, patcher speed, and the fill list reading every receipt. The fixes were not
re-reviewed. Not fixed, scored low or optional: the workbook is still parsed several times per fill (about
a second), one query per note field, a third copy of the upload size helper, the 200 MB unpacked limit.
Repeated totals (Total comprehensive income on two SOCI rows, Profit (loss) on two SOPL-Nature rows, Cash at
end of period on SOCF) are checked and not written, as v1; mTool's cash-at-end input cell stays empty, as v1.

**Checks:** server 811 passed (14 live deselected); browser build passes; browser tests 187 passed. The
dialog was opened in the browser: ready (restored on reopen) and "needs a check" on a template with its SSM
names stripped. Filling and failed were checked by the builder in the browser and in tests. Playwright not
run. No live model calls.

**Only Windows can confirm:** the filled file opens and validates in mTool, notes look right in mTool, and
mTool adds up the totals left to its formulas.

## Step 7 (done on the Mac, 23 November 2026; branch `step-7-statements`, merged to `main` 23 November)

Plan: `docs/step-7-plan.md`. The owner said to build and test.

**Built:**
- 7a: the equity statement as a grid in the agent's outline. Columns and rows are listed once, and a cell is `CE-<row>-<column>`. Before this the agent saw only the total column.
- 7b: all five statements extracted. The checks across statements are shown once both statements are filled. A failed run names the statements left unfinished, and a retry fills only those.
- 7c: Group runs fill the Group columns, then the Company columns. Comments on Group figures are accepted, and the Reviewer saves to the comment's entity. The notes agent stays on the Company.
- 7d: one agent for several statements.
- 7e: answer-key placements for profit or loss, comprehensive income, equity and cash flows (Doc 1 to 3, `key_version` 3; `docs/answer-keys.md`), and v1's baseline per statement.

**One agent against five (7d).** First live round, one run of each mode per document; both met or beat v1 on every statement:

| | Doc 1 | Doc 2 | Doc 3 |
|---|---|---|---|
| One agent per statement | 9 min, $0.032 | 9.5 min, $0.034 | 9.3 min, $0.035 |
| One agent for all five | 8 min, $0.052 | 5.9 min, $0.030 | 6 min, $0.035 |

One agent for all five was faster, cost about the same, and scored as well or better (Doc 1 balance sheet 0.958 against 0.875). It is now the only mode: one agent per entity fills every unfinished statement. The step limit for it is the shared loop's ceiling of 120; the live runs used 18 to 30 model calls.

**Live after the review fixes** (complete and accurate; v1's average in brackets):

| | Balance sheet | Profit or loss | Comprehensive income | Equity | Cash flows | Time, cost |
|---|---|---|---|---|---|---|
| Doc 1 | 1.0 (0.85) | 1.0 (0.844) | 1.0 (1.0) | 1.0 (1.0) | 1.0 (1.0) | 7.5 min, $0.045 |
| Doc 2 | 0.941 (0.939) | 1.0 (0.943) | 1.0 (1.0) | 1.0 (1.0) | 1.0 (1.0) | 6 min, $0.031 |
| Doc 3 | 0.929 (0.929) | 1.0 (1.0) | 1.0 (1.0) | 1.0 (1.0) | 1.0 (1.0) | 6 min, $0.032 |

The misses left: Doc 2's RM1 of office equipment (step 4's known miss) and Doc 3's related-party trade receivables placed as other receivables (v1 makes the same choice). Live spend in step 7: about $0.36, so about $2.46 of the $5 cap is used.

**Review (big tier: correctness, simplicity, architecture, performance, spec fit, agent harness, and Codex; then an independent check).** Fixed:
- comments limited to the first statement and the Company;
- a scope answer re-running every statement;
- per-statement cost showing the run's running total;
- the Reviewer seeing Company figures on a Group correction;
- whole-run comments unable to reach other statements or the other entity;
- "same amount in two fields" advice firing where equal amounts are right;
- the refusal for a field of another statement or a grid row;
- the round report's check filter;
- "filled" taken from order instead of results;
- two sources of truth for the statements, and a second coverage tool;
- imports running upward;
- a stage error not naming its statement.

The fixes were checked by the second live round and the tests, not re-reviewed.

Rejected, with the reason:
- a combined-page coverage refusal (scored 25: the agent can report the line under each statement);
- re-running a partly filled statement on retry (scored 0: intended);
- style nits;
- the grid test using invented cells (the keys are not committed).

Also fixed during the live runs: the one-agent step limit asked for 240 steps against the loop's ceiling of 120.

**Not done:**
- No Group document exists, and v1 never ran one, so Group is proven with fake models only.
- Nothing has run on Windows.
- The owner should confirm the medium placements in the keys (`open_points`, listed in `answer-keys.md`).

## Step 6 (done on the Mac, 23 November 2026; branch `step-6-notes`, not merged)

Plan: `docs/step-6-plan.md`. Decisions: `docs/decisions/04-notes.md` (the
owner accepted all ten recommendations; prototype v4 approved; v1's six
prose-note presentation files copied into `templates/`).

**Built, in parts:** 6a prose-note templates in the catalogue (688 rows,
ids identical to v1's); 6b note blocks, the note store with history,
copying from pages with merged cells split, routes; 6c the one renderer
(v1's decorator, tiers and preview picture, beautifulsoup4 4.14.3 and
soupsieve 2.8.3 as pinned in v1); 6d the notes agent with its own stage
beside extraction; 6e notes in the review loop (note comments, the
Reviewer's note tools, Needs you kinds, round counts, undo; Right and Wrong
on share-capital and related-party figures); 6f the notes screens to
prototype v4; 6g notes placement keys (owner-confirmed, not committed),
the "same field" score and v1's baseline.

**Also fixed on the way:** a sideways page could be stored turned the wrong
way (Doc 1 page 17, three live runs out of three). The model now names the
edge the text faces and one look at the turned picture confirms it; a live
re-read of Doc 1 and Doc 2 turned all four sideways pages correctly.

**Shape of the notes agent after review:** one placing pass sees every
note's text and candidate fields from every template; formatting groups
then run side by side, the share-capital and related-party figures
alongside. Coverage is checked over source blocks. Preview pictures leave
the history like page pictures.

**Live, notes placement ("same field" score), final version, 23 November:**

| Document | Runs | v1 average |
|---|---|---|
| Doc 1 | 1.0, 1.0 | 0.923 |
| Doc 2 | 1.0, 1.0 | 0.893 |
| Doc 3 | 0.95, 0.90 | 0.820 |

About 2 minutes and 3 to 4 cents a run for the notes stage (it was 7 to 11
minutes before the speed work). Doc 3's remaining misses: "Amount due from
a related company" goes to related parties in every run (the key, low
confidence, says receivables); once "Retained earnings" went to dividends.
Earlier versions scored lower (first version 0.69 to 1.0 on Doc 1; the
cause was a label list in the session text and fields shown per template).

**Reviews:** Fable 5.2 (seven findings, all fixed); then the big tier:
eight specialists, Codex (through its task runner; its review command
could not take a diff this size), an independent checker. Kept and fixed:
the notes stage not restarting after a quick scope answer; preview
pictures never trimmed; a note with no Confirm when its placement was
unsure; the note header overflowing on a split note; plus twelve smaller
ones (duplicate share-capital placements, a failed turn check discarding a
page, Confirm leaving not-sure marks, undo guessing its entry, read
failures shown as "no notes", quick look changes racing, the sidebar,
tables past the page, comments on the notes as a whole and on a missing
field). The fixes were not re-reviewed.

**Not done, by choice:** tidying repeated code and constants; a stale
whole-note look write can overwrite another person's change at the same
moment (history keeps both); after a standard or level change, notes in
old fields still count as placed; a note's blocks after its last placed
block are not judged. "Note citations agree" stays not assessed: the
owner dropped it for now (decision record 4).

**Not verified:** how notes look inside mTool after a paste (Windows); the
reduced styling tiers and "too long" on a real document (none reaches
them); Playwright. At 1440 wide the widest note tables still make the note
area scroll sideways by about 130 px.

**Checks:** 697 server tests pass; the web build passes; 175 browser tests
pass. Screens checked in the browser on copies of a live Doc 1 run.

## Step 5 (done on the Mac, 22 November 2026; merged to `main` 23 November 2026)

Built to decision record 3 and `prototypes/review-prototype-v3.html`, in
three parts by Opus coding agents, checked by the orchestrator after each:

- **5a, server:** comments (figure, line, statement; scope Figure / Run /
  Company), correction rounds (atomic send, stop, always a final state), the
  Reviewer agent (`app/review/`) with the server's count of what a round
  changed, Accept, Accept all, exact Undo, Reply, agent comments
  (`leave_comment` for both agents), the Needs you list, retry of a failed
  extraction.
- **5b, server:** scope questions (`ask_scope`; run status `needs_answer`,
  stage `asking`; carry on or change setup and restart), setup question
  cards, versioned company and firm guidance fed to both agents, proposed
  guidance lines from Company-scoped corrections.
- **5c:** the run screen (grid, Needs you, Source with Right / Wrong,
  Comments with round results and the proposal card, Activity with notes and
  page links, Checks, Guidance, Compare with a filled workbook, Download
  traces), question cards at setup and in the run, firm guidance in
  Settings, the three Settings fixes; server additions (one-run route, stop
  extraction, pages on events).

**Checks:** server tests 498 passed (8 live left out); browser build passed,
138 tests passed. In a browser against a real server on a seeded run: Needs
you, Right / Wrong with Company scope, add and remove a comment, Guidance,
Compare with a seeded filled workbook (all five difference kinds) opening
its figure. Live, Doc 1 (about 1.4 cents): extraction 0.917 complete and
accurate (v1 0.85), the agent left two comments; a real correction round
put a figure seeded RM 1,000 wrong back to its printed 66,189 and answered
"changed", confirmed by the server's count, no other change.

**Review:** the full panel (eight reviewers), Codex, and a checker scoring
every finding; then, at the owner's request, a second Codex review and a
Fable 5.2 review of the finished work. Everything kept was fixed, among it:
a refused move that kept half its writes, an undo that reversed an accepted
correction, a repeatable scope question, a round that could stay working,
the missing Compare screen, Activity not in the agent's words, Accept all
counting, event loading, "Accept all" on renamed lines clearing Unsure
flags, Group comments acting on Company figures, a stranded run after a
restart, and a person unable to add a figure the agent missed. Rejected:
removing "Only an admin can change these settings." (HANDOFF asked for it).
The last two rounds of fixes were not reviewed again.

**Live on Doc 2 and Doc 3 (owner's request, about 2.2 cents):** extraction
Doc 2 0.941 (v1 0.939), Doc 3 0.929 (v1 0.929), accuracy 1.0 on both. A
real correction round on each put the seeded figure back to its printed
amount, answered "changed", and the server agreed. Doc 2's round also
re-saved last year's retained earnings with the same amount and a new
reason (counted by the server as one other change; the reason describes
this year's fix). Activity lines are in the agents' own words with page
links. Found: internal field codes reach the person in "Left a comment on
FP-s38." and in one Reviewer answer ("FP-s182").

**Fixed the same day (owner's request):** every text a person reads (notes,
comments, answers, guidance lines, round summaries, figure reasons, scope
questions) is stored with field ids turned into names a person can find:
the label, plus headings until no two fields of a statement read the same,
plus the column for equity fields. No refusals; one principle in both
agents' instructions. Reviewed by Correctness, Simplicity, Architecture,
Agent harness, Performance and Codex (twice); the first design (refusing
text with ids) was replaced on their advice. Server tests 505 passed. A live
round on Doc 3 (0.2 cents) showed no codes in the answer, summary or activity.

**Not verified:** a live scope question (only scripted tests); anything on
Windows. The highlight of a line
on its source page needs line positions from the Reader (not built).

**Left for later:** `app/figures/store.py` (465 lines), `web/src/api/types.ts`
and `RunPage.test.tsx` are over the 400-line guide; duplicated refusal classes
and figure-by-key queries (review, optional); the unsplit-cash convention
still has to be typed into firm guidance by an admin (Doc 1 loses two cells
until then).

## Step 4 (done, 18 November 2026)

Built by a coding agent, run live on the test documents, reviewed, and the
review's findings fixed (below). The fixes themselves were not re-reviewed.

**Live after the review fixes** (two rounds, complete and accurate against
the answer keys; v1's average in brackets): Doc 1 1.0 and 0.917 (0.85),
Doc 2 0.941 and 0.941 (0.939), Doc 3 0.929 and 0.929 (0.929). About 1 to 3
cents and 2 to 8 minutes a document. Removing the "unsplit balance goes in
the field for its main part" line (the review judged it the firm's cash
convention in disguise) brought back the Doc 1 cash miss in one round. Doc
2's one miss is RM1 of combined computer and office equipment, placed in
the key's own named alternative; the key is unchanged.

**The owner's design (18 November 2026).** The agent no longer reads the SSM
sheet and writes by label. It sees the template as an outline: every field
with its own id, its place under its headings, and whether it is a heading,
a line to fill or a total of named parts with their signs. A face row fed
by the sub-sheet carries its sub-sheet lines nested under it. It saves by
id. All nine hard stops stay, unchanged, as a safety net.

**What was built**

- The outline: `app/extraction/outline.py` (ids such as `FP-8` on the face
  and `FP-s141` on the sub-sheet, paths from the formula tree, kinds,
  required marks, face rows and their sub-sheet lines, each part's sign)
  and `outline_text.py` (the compact text for the first message, about
  27,000 characters for the balance sheet, and the detailed view of one
  section).
- The figures agent: `app/extraction/agent.py`, `tools.py`, `checking.py`,
  `coverage.py`, `feedback.py`, `state.py`, `instructions.py`. Tools: the
  four page tools (moved from the Reader to `app/agents/pages.py`, shared,
  not copied), find_fields, show_section, lookup_definitions, save_figures
  (by id, both years, printed lines, certainty, reason; refusals are the
  store's sentences; a printed line's page must be inside the document),
  clear_figures, add_up, run_checks (action required, not assessed,
  passed: a pass never sits under action required; required lines still
  blank are listed for information only, since blank is right when the
  report does not show them), report_coverage (matched to the printed lines
  of the statement pages, tolerant of wording; a bare year such as 2021 is
  a column heading, not an amount), and the finish check (sent back unless
  figures are saved and, after the last change, the checks ran and every
  printed line is accounted for; an honest finish with open points is
  taken after one refusal, and when only failing checks are left it is
  taken at once; at the last step any finish is kept).
- Advice after a save, never a refusal: a negative figure explained through
  the formula, the same amount in two fields, an "Other" field filled
  beside empty dedicated fields, a face row whose sub-sheet lines are empty.
  Each point is given once per field until that field's value changes.
- Steps: tool results say how many steps are left at 70% and 90%, and the
  result before the last step says the next reply is the last (it carries
  the 90% notice when the two fall on the same step).
- Page pictures are never dropped before the first save; after it, in one
  large cut when more than 12 are kept. The Reader's trimmer was moved to
  `app/agents/history.py`; each agent passes its own text tools and its
  own "has it saved yet" check (the figures agent: a figure is saved).
- The code workbench: `app/agents/workbench.py` is the one place that
  decides, from the caller's choice, Settings `code_workbench`,
  `factory.code_tool_supported` and, for Claude,
  `claude_sandbox_real_documents`. The instructions say plainly when it is
  off and why. A local add_up tool is always there.
- Official definitions: v1's `concept_definitions_mfrs.json` and
  `_mpers.json` copied unchanged to `app/catalog/definitions/`, with a
  loader and v1's ranking in `app/catalog/definitions.py`.
- The job: `app/extraction/job.py`, started by
  `app/runs/extraction.start_extraction` inside confirm-setup's
  transaction. Stage `extract`, run status `extracting`, then `in_review`
  or `failed`. Events for each save, check, coverage report and the
  finish, with cost. A record of the finish and coverage in the run's
  folder (in the traces zip). A run whose extraction failed cannot be
  deleted from the setup page. The stage fails with one plain sentence
  when nothing was saved, the model failed or the run was stopped; saved
  figures are kept. Only the step or time limit ends "done" with a "partly
  filled" notice. A new attempt after a restart starts from the figures
  already saved and counts them.
- Company only: until step 7 the agent fills the Company columns. On a
  Group run the job writes a notice that only the Company columns are
  filled; it does not refuse the run.
- Scoring against the answer keys: `app/scoring/answer_key.py` (pure) and
  `scripts/score_answer_key.py` (a v2 run, or a v1 run with
  `--v1-database` and `--v1-run`). It reproduces the v1 baseline exactly:
  Doc 1 0.9167, Doc 2 0.9394, Doc 3 0.9286, Doc 4 0.9524. v1 and v2 both
  store the entity as `Company`.
- The live test `tests/test_extraction_live.py` (marked `live`): reads each
  document or reuses a saved reading (`LIVE_READING`), confirms the setup
  as the Reader suggested with the balance sheet only, runs the real job
  and asserts the v1 baseline per document.

**Checked with fake models.** A scripted agent on the small test PDF
goes from confirming the setup to a finished stage. On the saved readings
of the four real documents, a scripted agent that saves exactly the
answer key scores 1.0 on each, passes the balance check and accounts for
every printed line, so the outline, the saves, the checks, coverage and
scoring agree with one another. How a real model does: see the live
results below.

**Deferred, on purpose**

- Caching the growing conversation on direct Claude calls
  (`anthropic_cache`): no Anthropic key to try it.
- The worker still runs one job at a time, so an extraction waits behind a
  reading and the reverse. Left as is until agents run side by side.
- The workbench is for calculation only: no page text, template or
  workbook is put into the sandbox yet. The container fee of OpenAI's code
  interpreter is not in the cost estimate; the finished event says
  whether code steps ran.
- Group columns (the agent fills the Company columns only, and a Group run
  gets a notice saying so), equity statement columns and other statements:
  step 7.
- Firm and company guidance, including the unsplit cash convention: the
  guidance store is not built, so the agent is not told the convention.
  This may cost a point on documents whose key follows it.
- A retry of a failed extraction: with the run screen, step 5.
- The setup page opens for any `failed` run in the run list, including one
  whose extraction failed; that page then refuses a second confirm. The
  run list needs to tell the two failures apart (step 5's run screen).

**Live results (18 November 2026).** The figures agent beat v1's averages
on the three documents it is judged by: v1 averages Doc 1 0.85, Doc 2
0.9394, Doc 3 0.9286. v2, after the fixes from the live runs, averaged Doc
1 0.958, Doc 2 1.0, Doc 3 0.964 over two runs each.

**The owner's decisions (18 November 2026)**

- All nine hard stops stay, unchanged, together with the outline view.
- Doc 4 is set aside from judging the agents for now: the document has too
  many problems of its own. `tests/test_extraction_live.py` leaves it out
  unless `LIVE_DOCS` names it.
- Doc 4's deferred income is right in either Contract liabilities or the
  Deferred income field on the sub-sheet. The answer key records this as
  `alternatives`, which `app/scoring/answer_key.py` accepts.
- An accrued bonus is an accrual.

**Review (18 November 2026) and fixes.** One review of the whole step,
findings checked against the code. Fixed:

- C1: a failed or stopped agent fails the stage with one plain sentence,
  keeping saved figures; the agent's error is always logged.
- C2: the finish asks for coverage again when figures changed after the
  last coverage report.
- C3: a new attempt after a restart counts the figures already saved.
- C4: nothing between the stage start and the agent can leave the run
  "extracting".
- C5: a bare year in a table row is not an amount.
- C6: tests for the 70% and 90% step notices, the restart path and a model
  failure after a save.
- S1: save_figures refuses a page outside the document (a tool check, not a
  new hard stop).
- S3: a code step's event keeps the code's size, not the code; the
  transcript keeps the code.
- SP1: the agent fills the Company columns only, and a Group run is told.
- H1: required fields left blank are information only in run_checks.
- H2: two worked rules left the instructions: the related-party loan
  example (the principle that the definition names the deciding fact
  stays) and "an unsplit balance goes in the field for its main part"
  (that is the firm's cash convention, which belongs in Settings guidance).
- H3: each advice point once per field until its value changes.
- A1: one read of the run's current figures (`store.current_figures`) for
  the tools, the checks and the first message.
- A4: each agent passes its own "has it saved yet" check to the trimmer;
  the Reader's defaults moved into the Reader.
- A5: the figures agent's template family and outline are required, with
  no silent fallbacks.
- SI1: the honest finish with only failing checks left is judged from the
  agent's state, not from the wording of a reason.
- SI3: the outline uses its own `descendants`; the workbench switch for
  tests is gone (tests change the Settings switch instead).

Rejected or deferred, with the reason:

- SP2 (failing checks accepted at the first finish) and SP3 (a run whose
  extraction failed cannot be deleted): both are documented decisions
  above.
- A2, A3, A6, SI2, H5: low value now; left for a later step.
- S2 (an agent write can replace a figure a person edited): it would be a
  new hard stop, so it needs the owner's agreement.

## Step 3 result and review (18 November 2026)

**Built.** PDF upload (Word refused everywhere), page pictures at the
scan's own resolution with a pixel budget, a 500-page and A0 page limit.
The Reader: every page transcribed once on GPT-6 Luna with a cache
breakpoint, then an agent maps statements, layouts, notes, standard, level
and unit, with plain feedback on gaps in the notes list. The setup screen
in reading, failed and ready states, with page pictures, reasons, unsure
dots, Other page, Replace and an editable notes list. Confirming setup
stores the filing, statements with pages, and notes; the run waits at
"Ready". Traces zip, daily server log files kept 30 days, Settings records
(logs, usage) and sign-in limits on Settings. Sign-off removed. Every model
call recorded with tokens, cost, duration and errors; secrets masked.

**Checks.** Server tests 402 passed (4 live left out). Browser build passed,
66 tests passed. The live answer key (`tests/test_reading_live.py`) passed
on Doc 1, Doc 2, Doc 3 and Doc 4: every statement page and layout, the
standard, level and unit, Doc 4's layout marked unsure and its
comprehensive income "not printed". The setup screen was checked in a
browser on a real Doc 3 reading, in every state. Playwright not run.
Windows not run.

**Cost.** About 3 to 4 cents and 2 to 3 minutes per document. All live work
in step 3 cost about $0.36 of the owner's $5 cap.

**Review.** Full panel (correctness, simplicity, architecture,
performance, spec fit, security and data, UI and taste, agent harness),
Codex and a checker. 37 findings; two scored 75 (transcripts lost trimmed
text; the answer key was not a repeatable test) and were fixed. Of the 50s,
all were fixed: render and page limits, failed reads cancel their page
calls, the Reader hears every save problem at once and is told to save
before finishing, cache-friendly trimming, secrets masked in logs, records
and traces, one source for layouts, one model-call recorder, run status in
one module, Replace and Other page, and small screen fixes. The live run
then showed the Reader reading "MFRS and IFRS" as two standards; the
instruction now says MFRS mirrors IFRS. That fix was not re-reviewed.

**Rejected or left:** the hand-written setup checks stay (they give plain
sentences; scored 25). The extraction start point stays as step 4's seam
(25). Raw events inside transactions stay (they keep the caller's
transaction; 25). The runs-table migration stays: databases from steps 0 to
2 exist on the Mac (0). Concurrency stays at 4 until the gateway's rate
limit is known (25). Gateway caching waits for a Windows run (25). Terra has
no price (25). The Guidance panel waits for a guidance store (25).

## Step 2 result and review (19 November 2026)

- Tests: 246 passed in 18 seconds. Browser build and its 37 tests still pass.
- A workbook made from the demo run's own figures scores 100% complete and
  100% accurate with no totals off. A workbook with one seeded difference
  of each kind scores exactly one extra, one sign-only, one scale, one
  different and one missing.
- Scored: data-entry cells only. Calculated totals are reported
  separately. A cell that cannot be read or matched is listed as not
  assessed, never dropped and never counted as agreeing.
- Review: six reviewers, Codex, and a checker that scored 19 findings and
  reproduced three.
- Kept and fixed: a valid Total cell was lost on genuine mTool sheets with
  categories.
- Also fixed: an unreadable total counted as agreeing; a run's totals not
  worked out from its own lines; the workbook read while holding the write
  lock; unbounded formula work; opening a comparison writing inside a read;
  the old file deleted before the save committed; unmatched fields listed
  twice; baseline table rows that did not add up; the baseline code moved
  beside its script; one comparison entry point; unused notes code removed.
- Rejected: dropping the stored per-cell copy of the workbook (it avoids a
  1 to 3 second re-read on every open).
- Left for step 8: moving the workbook-reading modules to a neutral
  package, and reading template cells through the catalogue's own lookup.
- The fixes themselves were not reviewed again.

## Step 1 result and review (19 November 2026)

- Tests: 176 passed in 13 seconds. The demo run opens in both orders and
  shows exactly one failed check, the seeded 9,000 difference.
- All 38 statement templates load: 6,520 lines, identical to v1 table by
  table. A test pins this.
- The taxonomy was trimmed to the 308 files the loader reads (10 MB, not
  70 MB). The reuse map had said to copy the folder whole.
- Review: seven reviewers, Codex (second attempt, after the templates were
  put in their own commit), and a checker that scored 20 findings.
- Kept and fixed: a no-breakdown total that disagrees with lines saved
  later is now flagged; values that are not ordinary numbers are refused;
  restore brings back how a total is calculated.
- Also fixed: two hard stops that could block a correct figure (a true
  zero, a sign slip), the `extra` back door, protection of figures a person
  typed, edits on fields with categories, edits that dropped printed lines,
  plain check messages, the rounding tolerance, and six smaller items.
- Rejected: a restore check said to be in the wrong place (nothing to
  mismatch); page numbers of zero or below (already refused).
- Left for later: a statement view loads all of a run's figures; the run
  list has no paging. Both are fine at current sizes.
- The fixes themselves were not reviewed again.
- There are now nine hard stops. Their sentences are in
  `api-contract.md`, "Step 1". The owner has not yet confirmed the list.

## Step 0 result

Checked by the orchestrator on 19 November 2026, after the review fixes:

- Server tests: 99 passed. Browser build passed. Browser tests: 37 passed.
- In a browser: login, a wrong password, the forced password change, the
  empty run list, Settings for an admin (a change saved) and for a
  non-admin (read-only).
- One live call to `gpt-6-luna` with a code step passed.
- Not run: a live Claude call, anything on Windows, Playwright suites.
- The review fixes themselves were not reviewed again.

## Step 0 review (19 November 2026)

Full panel: eight reviewers, Codex as a second opinion, and an independent
checker that scored all 30 findings against the code.

**Kept (score 70 or more):** the session cookie was never renewed, so a
person was signed out an hour after login even while working.

**Fixed as well, because later steps build on them:** the "database is
locked" error on a request, blocking database work on the event loop, a job
left "working" after a failed save, start-up recovery on a job's last
attempt, Settings saves that could lose a change, a tool error ending a
whole agent run, no time limit on an agent, raw provider errors in the
Activity feed, a gateway check that could pass while the app fails, and
five browser items (save one field, loading state, unknown-family notice,
the dead "New run" button, loose types).

**Rejected, with the reason:**

| Finding | Why not |
|---|---|
| Dialog, Count, IconButton and TextArea are unused | Built first on purpose. Later screens need them |
| Luna and Terra are two families with the same handling | The plan and the contract name both |
| A test handler sits in the job code | Step 0's own test needs it |
| The gateway key still accepts two Gemini-era names | v1's enterprise `.env` holds the gateway key under one of them |
| "Log in" is both the card title and the button | A common pattern. The taste rule is about subtitles and badges |

**Carried to a later step:**

| Finding | When |
|---|---|
| The workbench switches are stored but not read. One place must decide whether an agent gets the sandbox | Step 4, with the first real agent |
| The agent is not told how many steps remain, or that the workbench is off | Step 4 |
| Direct Claude calls do not cache the growing conversation | Step 4. Cannot be tried without an Anthropic key |
| Cost per run is not recorded | Step 4 |
| The activity list has no row limit | Step 1, when the route that serves it is built |
| The run list reads user names outside the login module | Step 1 |
| Lockout behind Azure's front end can be abused. The lockout list is never pruned | Before the Azure deployment |
| A non-admin sees Settings greyed out with no reason. The error line sits above the panels | With the review screens |

**For the owner:** the login idle timeout and the lockout limits are read
from `.env`, as in v1. The rule says only secrets live there. Move them to
the Settings page, or accept the exception?

## Research running alongside step 0

- `docs/agent-lessons.md`: v1's agent instructions distilled into principles.
  Written 18 November 2026. It also lists v1 guidance found to be out of
  date, which v2 must not copy.
- `docs/v1-reuse-map.md`: what v1 code can really be copied, confirmed by
  reading it, and the data model that code needs. Written 19 November 2026.
  It changed the build order.

## Step notes

### Step 0. Skeleton

Split in two, built side by side:

- **0a, server:** database, login, job queue, shared agent loop, model
  factory, settings, the gateway check script.
- **0b, browser:** design tokens, the shared components, login, the run
  list, Settings.

Done when: a user can log in and see an empty run list. A test job runs,
fails and retries, and a restart cannot leave it stuck. A GPT call and a
Claude call succeed from the Mac, each with a code step. The gateway check
script exists for the enterprise machine.
