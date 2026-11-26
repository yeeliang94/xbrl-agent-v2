# Go-live plan — closing the gaps with v1 and going further

Written 25 November 2026 after comparing v1 (`.v1-reference/`) with v2 screen by screen, route by route,
table by table and script by script. The owner asked for every gap and every recommendation in one plan
that other coding agents can build from. Read `AGENTS.md` first, then this file.

Each work package below is sized for one agent. It says what is already there, what to build, and a
"done when" line that can be checked on the Mac.

## 1. How to build each package

These hold for every package. They repeat the parts of `AGENTS.md` that matter most here and add the
owner's preferences for this work.

1. **Check the gap first.** The comparison was made by reading code. Before building, open the v2 files
   named under "already there" and confirm the gap is still real. If it is not, say so and stop.
2. **Read v1's version and its tests** (paths are given). Copy the smallest part that does the job, with
   its tests. Do not copy v1's shape when v2 already has a better one.
3. **Prototype before screens.** Any package marked *Prototype* starts as one HTML file in `prototypes/`
   that the owner approves before app code changes. Section 2 groups the prototypes so the owner approves
   five files, not twenty. A prototype:
   - builds on `prototypes/review-prototype-v3.html` and the values in `web/src/styles/tokens.css`;
   - shows every state: empty, loading, filled, error, a non-admin's view, and each dialog and dropdown;
   - uses invented data only, never a real client name;
   - has a small switcher to move between states.
4. **Server first, screens second.** Routes, permission checks and tests land before the screen that
   calls them. Document every new route in `docs/api-contract.md`.
5. **Reuse the shared components** in `web/src/components/` (Table, Dialog, Segmented, Select, Switch,
   Status, Button, TextInput). Add a component only when none fits, and say why.
6. **Settings live on the Settings page** and in the database. `.env` holds secrets only.
7. **Permissions are checked on the server.** Every admin action writes an audit row.
8. **For anything an AI agent does:** principles before rules, tools and feedback before guardrails, fix
   the cause. No document-specific instruction unless no general principle can cover it, with the reason
   written beside it. No new hard stop without the owner's agreement.
9. **No new dependency** unless v1's `constraints.txt` already pins it at that version. Otherwise stop and
   ask. Packages that need one say so.
10. **Keep it small.** No feature switch for unfinished work, no speculative option, files under about
    400 lines.
11. **Done means verified.** `venv/bin/python -m pytest tests/ -q` passes; `cd web && npm run build &&
    npm test` passes if `web/` changed; the screens are opened in a browser and every state checked.
    Do not run Playwright. Add a note to `docs/build-log.md`. Do not commit, push or open a pull request:
    the orchestrator does that after its own review.
12. **Report in plain business English:** what was built, each check and its result, what did not run
    and why, and anything only Windows or a live model run can confirm.

## 2. Prototypes the owner approves first

| Prototype file | Covers packages | Screens shown |
|---|---|---|
| `admin-prototype.html` | A1, A2, A7, C4, C5 | Settings: Users, Audit log, Account, Data retention (later dropped), Connection; Report an issue dialog; issues list |
| `runs-and-setup-prototype.html` | A3, A4, B2 | Run list with search, filters, paging and delete; setup with first-year and millions; several files at upload |
| `run-controls-prototype.html` | A5, B1, B3, B4, C3 | Redo one statement, stop reading, cost on the run screen, sheet choice in the fill dialog, notes sign-off, readiness view |
| `accuracy-prototype.html` | A6, C1, C2 | Notes in the compare view; accuracy over time; repeated correction patterns |
| `source-file-prototype.html` | C6 | Starting a run from a PDF, Word or Excel file; sheet choice at setup; where a figure's source is shown |

Build the prototypes in this order. Server work that needs no screen (A6 scoring, B5, B6)
can start straight away.

## 3. Build order and what can run side by side

Start after pull request 1 (`notes-workbench`) is merged. One branch per package, cut from `main`.

- **Lane 1 (accounts and settings):** A1 → A2 → A7 → C5 → C4. All touch `SettingsPage.tsx` and `app/auth/`.
- **Lane 2 (runs):** A4 → A3 → B2 → A5. All touch `app/runs/` or the run list and setup screens.
- **Lane 3 (accuracy):** A6 → C1 → C2. All sit in `app/scoring/` and the compare view.
- **Lane 4 (run screen and agents):** B1 → B3 → B4 → B5 → C3.
- **On its own:** B6 (scripts only), C6 (after the owner settles its design).

Lanes can run at the same time. Packages inside a lane run one after another, because they change the
same files. Phase A is what go-live needs; B and C follow in the order above.

## 4. Phase A — needed for go-live

### A1. Users, audit log and own password — *Prototype*

- **Why:** an admin cannot add, disable or reset a person from the app, nobody can view the audit log, and
  a person can change their password only when forced to.
- **Already there:** every route (`app/auth/admin_routes.py:40-118`, password change at
  `app/auth/routes.py:111`), audit rows (`app/auth/store.py:185`), `ChangePasswordPage.tsx`.
  `docs/api-contract.md:49` says the browser types come "when the Users screen is built".
- **v1 to read:** `web/src/components/UsersTab.tsx`, `AccountTab.tsx`, `auth/routes.py:380-530`.
- **Builds:** three Settings sections. *Users* (admin): list, add with a temporary password shown once,
  disable, enable, reset password, make or remove admin; the last admin cannot be removed. *Audit log*
  (admin): newest first, filter by person and action, paged. *Account* (everyone): change own password.
  Settings changes also write an audit row (today they only stamp `updated_by`).
- **Done when:** an admin does each action in the browser and each appears in the audit log; a non-admin
  sees only Account and gets a refusal from the server for the rest; a user changes their own password and
  signs in with it.

### A2. Report an issue — *Prototype*

- **Why:** `requirements.md:96` says keep it; nothing is built. At go-live it is how users tell us what broke.
- **v1 to read:** `api/issues.py:122-277`, `IssueDialog.tsx`, `IssuesPage.tsx`, tables `issues` and
  `issue_files`.
- **Builds:** `app/issues/` (table, store, routes), a "Report an issue" entry in the app shell that knows
  the run on screen, and an admin list with status and a note. **Better than v1:** the issue stores the run
  id and the admin can download that run's traces from the issue (`app/records/routes.py:40`), so a report
  arrives ready to diagnose. Attachments go through the safe-path helpers. Issue updates and deletions
  write audit rows.
- **Done when:** a user reports an issue from a run with a screenshot attached; an admin sees it, downloads
  the traces from it, and closes it; both actions are in the audit log.

### A3. Setup: first financial statements and amounts in millions — *Prototype*

- **Why:** the rules for a filing with no prior year exist, but setup never sets it. Setup offers RM and
  RM thousands only.
- **Already there:** `first_statements` in `app/db/schema.sql:323`, `app/catalog/lookup.py:51`,
  `app/figures/_hard_stops.py:114`, `app/filing/plan.py:154`; a first-time mTool template in `templates/`.
  `app/runs/setup.py:204` does not write it and `web/src/pages/setup/SetupForm.tsx` has no control.
- **Builds:** a "Reporting period" choice at setup (this year and last year, or this year only), saved by
  the setup route. The Reader may suggest it when the document shows no comparatives; the person confirms.
  Millions: first check that scoring, the checks and the fill carry a third scale correctly, then add it.
- **Done when:** a run set to "this year only" refuses a prior-year figure with its existing sentence, and
  fills the first-time template with no prior-year column; a millions run fills mTool with the right scale.
- **Only Windows can confirm:** mTool accepts the first-time file.

### A4. Run list: search, filters, paging and delete — *Prototype*

- **Why:** the list has three filters and no search or paging (`web/src/pages/RunsPage.tsx:14-18`). Only a
  run at setup or a failed run can be deleted (`app/runs/status.py:32`), and the screen never offers it.
- **v1 to read:** `web/src/components/HistoryFilters.tsx:93-165`, `api/runs.py:115-180,610,633`.
- **Builds:** search by file name and company; filters for status, standard and date; paging on the server.
  Delete for any run that is not working, with a confirm dialog that names what goes (figures, notes, files,
  traces). Decide with the owner who may delete: the run's owner and admins is the suggested rule. A delete
  writes an audit row. An admin action to clear abandoned drafts older than a chosen age.
- **Done when:** 200 seeded runs page and filter quickly; a deleted run's files are gone from disk; a
  non-owner is refused by the server.

### A5. Redo one statement, and stop reading — *Prototype*

- **Why:** `backend-plan.md:458` promises "One statement can be redone without a new run". Only failed or
  stopped work can be retried (`app/runs/extraction.py:104-133`). The reading stage cannot be stopped.
- **v1 to read:** `api/run_control.py:396-415,521-547`, `api/preparation.py:570`.
- **Builds:** "Redo this statement" on a finished statement. Figures a person edited or confirmed are kept
  unless the person chooses otherwise; everything replaced keeps its history rows. A Stop for reading.
  Stopping one agent among several is optional: build it only if the activity panel's per-agent blocks make
  it a small addition.
- **Done when:** one statement is redone while the others and their checks stay as they were; a person's
  edits survive; reading stops within one model call and can be retried.

### A6. Compare notes with an accountant's workbook

- **Why:** a filled workbook is compared for figures only. `docs/api-contract.md:454` still says notes are
  not scored. Notes scoring exists against answer keys (`app/scoring/notes.py`).
- **v1 to read:** `eval/human_compare.py:137` (`compare_notes`).
- **Builds:** read the notes sheets of the attached workbook and score "same field" with the existing notes
  scoring. Show it in `CompareView.tsx` beside figures. Wording is not compared (`backend-plan.md:571`).
- **Done when:** an attached workbook with notes gives a notes score and a list of notes placed elsewhere
  or missing; the contract line is corrected.

### A7. Housekeeping: retention, version, connection test — *Prototype*

> **Changed 26 November 2026 (owner):** no automatic clean-up. The retention periods and nightly job were
> built and then removed; runs are removed by hand (A4). A7 keeps the version and the connection test.

- **Why:** old traces are never cleaned up (v1 pruned after 90 days), the app shows no version, and testing
  the gateway needs a command line.
- **Builds:** the app version in the shell footer and in the traces zip. A "Test
  connection" button (admin) that runs what `scripts/check_gateway.py` runs and shows one plain sentence
  per model. The key and gateway address stay in `.env`.
- **Done when:** the version shows; the button reports success and a clear failure.

## 5. Phase B — lower priority

### B1. Cost on the run screen and in reports — *Prototype*

- **Already there:** every model call's tokens and cost (`app/models/usage.py`), an admin CSV
  (`app/records/routes.py:68`). `requirements.md:97` says "Keep, hide", so keep it quiet.
- **Builds:** one line of cost and time per run, opened from the Activity tab, per agent. The usage report
  gains per-person and per-company totals. A monthly budget on the Settings page, with a notice to admins
  when 80% is used. No blocking.

### B2. Several PDFs at once — *Prototype*

- **v1 to read:** `web/src/App.tsx:432-447`. Each file becomes its own run waiting at setup. The job queue
  already runs two at a time (`app/jobs/worker.py`).

### B3. Choose sheets in the mTool fill — *Prototype*

- **Check first:** whether `app/filing/identify.py` and the investigation step already cover v1's sheet
  selection (`mtool/sheet_selection.py`, `MtoolFillModal.tsx:1239`), and whether `FillDialog.tsx` says what
  will not be written before the fill, not only after. Build only what is missing.

### B4. Notes: sign off what the run could not account for — *Prototype*

- **v1 to read:** `notes/integrity.py`, `NotesIntegrityPanel.tsx`.
- **Approach:** start from v2's coverage report (`app/notes/coverage.py`). Ask first what the notes agent
  could not see, and improve the coverage feedback it gets. Then give the person a list of source parts
  left out, each to accept or send back as a comment. No blocking mode.

### B5. Warn an agent before it hits a limit

- **v1 to read:** `limit_warner.py`. v2 has a request cap and a time limit (`app/agents/loop.py:110,323`).
- **Builds:** near the limit, the next tool result tells the agent in one sentence how much room is left,
  so it saves its work and says what is unfinished. This is feedback, not a new rule.

### B6. Scripts for a new SSM taxonomy

- **Why:** v2 copies the generated templates and definitions but not the scripts that make them. When SSM
  changes the taxonomy there is no way to rebuild.
- **v1 to read:** `scripts/generate_mpers_templates.py`, `build_group_templates.py`,
  `generate_concept_definitions.py`, `generate_report_templates.py`, `generate_mtool_fingerprints.py`,
  `validate_ssm_compatibility.py`.
- **Builds:** the smallest set that rebuilds `templates/` and `app/catalog/definitions` from a taxonomy
  folder, with a document saying how to run it. Done when a rebuild from today's taxonomy matches the files
  in the repository.

## 6. Phase C — beyond v1

### C1. Accuracy over time — *Prototype*

- **Builds:** a page that reads the scores already kept for every scored run (`app/scoring/`) and shows
  completeness and accuracy by month, model, statement and company, with the kinds of difference (sign,
  scale, missing, extra). Admins only. No new measuring: only what is already scored.

### C2. Learn from corrections — *Prototype*

- **Already there:** a reviewer's comment can propose a guidance line that a person adds
  (`app/review/comments.py:204`, `app/guidance/store.py:148`).
- **Builds:** a count of correction kinds across runs (same field moved, sign flipped, same note re-placed),
  shown beside C1. For a pattern that repeats, the app drafts one general guidance line and an admin accepts,
  edits or rejects it. Nothing changes the agents' instructions without a person. Lines must be principles,
  not document-specific cases.

### C3. One readiness view per run — *Prototype*

- **Builds:** one panel answering "can this be filed?": checks passed, items in Needs you, differences from
  an attached workbook, notes coverage, and cost. It reads what exists; it adds no new checks.

### C4. Sign in with Microsoft — *Prototype*

- **Neither version has it.** Removes passwords and cuts a leaver's access automatically.
- **Waits on the owner:** an app registration in the firm's Microsoft tenant. Microsoft's sign-in library
  (`msal` 1.35.1) is pinned in v1's `constraints.txt`, so it is allowed; confirm with the owner before
  adding it to v2.
- **Builds:** Microsoft sign-in beside password login, chosen on the Settings page. A person must already
  exist as a user; signing in never creates an account. Password login stays for the first admin.

### C5. A reviewer role — *Prototype*

- **Today:** admin or not. **Builds:** preparer and reviewer, so a run is signed off by someone other than
  the person who prepared it, with the sign-off in the audit log. Settle the exact rights with the owner
  in the prototype before any server change.

### C6. Start a run from a Word or Excel file — *Prototype*

- **Owner's decision (25 November 2026):** a run starts from one file: a PDF, a Word document (.docx) or
  an Excel workbook (.xlsx). Never a PDF plus another file.
- **Why:** a Word or Excel file holds the real numbers, tables and headings, so agents need not read them
  off a picture of a page.
- **Design:**
  - **Nothing is converted with Word or LibreOffice.** The server opens the file itself. Excel uses
    `openpyxl` (already installed). Word needs `python-docx` 1.2.0 and `mammoth` 1.12.0, both pinned in
    v1's `constraints.txt`; confirm with the owner before adding them to v2.
  - The server makes a **reading copy**: pages it lays out itself from the file's content, with PyMuPDF
    (already installed). The reading copy gives the reviewer something to look at and gives every figure
    a source page, so the Reader, the page tools, the source rule and the review screen work unchanged.
    Its page numbers are its own, not the printed report's; the screen says so.
  - The file's own text and tables are also stored in the run's records, and the agents get a tool to
    search and read them, so a number is taken from the file, not from a picture. The provider's code
    sandbox is not used, so the document never leaves the server.
  - Excel: the Reader proposes which sheet holds each statement and the notes; the person confirms at
    setup. A figure's source is a sheet and cell. Formulas are read by their saved values; hidden sheets
    and working papers are left out unless the person brings them in.
  - Refused with one sentence each: old `.doc` and `.xls` files, password-protected files.
- **Build in two parts:** (a) Word, through the reading copy alone, which needs no change to the agents;
  (b) the stored tables tool, then Excel with its sheet-and-cell source.
- **Trial (25 November 2026):** see `docs/build-log.md` for the result of running the figures agent on a
  reading copy made from the one Word set of statements on hand.
- **Done when:** a Word file and an Excel file each go from upload to a filled mTool file; each scores no
  worse against its answer key than the same statements as a PDF; every figure's source opens to the
  right place.
- **Not verified:** no real Excel set of statements was on hand. The owner needs to supply two or three.

## 7. Dropped on purpose — do not rebuild

Per `requirements.md:77-98`: converting Word to PDF with Word or LibreOffice (C6 replaces it), the notes formatter and clean-up agent, benchmark and
repeat-run suites, per-company memory (company guidance replaces it), the field-label editing page, and
most of v1's 33 advanced settings. Raise it with the owner before bringing any of these back.

## 8. Decisions waiting on the owner

1. Who may delete a run (A4). Retention (A7): decided, no automatic clean-up.
2. Whether millions is needed for go-live (A3).
3. The Microsoft app registration, and adding `msal` to v2 (C4).
4. The reviewer role's rights (C5).
5. Adding `python-docx` and `mammoth` to v2, and real Excel test files (C6).
6. Whether per-agent stop is wanted (A5).

## 9. Not verified when this was written

- Whether the fill dialog warns before a fill (B3).
- Whether v2's fill already matches v1's sheet selection (B3).
- Whether all three scales pass through scoring, checks and the fill (A3).
- No live model run has used a starting workbook (`build-log.md:261`).
