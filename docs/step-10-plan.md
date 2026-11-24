# Step 10 plan — reports and part-filled workbooks

Written 24 November 2026 on branch `step-10-reports`, cut from the uncommitted step 9 work (`step-9-mpers`).
The owner said to carry on. Read with `backend-plan.md` sections 4.5, 7 and 9, `v1-reuse-map.md` section
2.9 and the `report_fields` table under section 3, `requirements.md` lines 59-64, and v1's
`docs/ROLLED-FORWARD-WORKBOOKS.md` in `.v1-reference/`.

## 1. What step 10 delivers

**Reports.** The three reports SSM files beside the statements: the directors' report (22 fields), the
statement by directors (27) and the auditors' report (13). Each has one rich-text narrative and short fields:
names, identity numbers, dates, and choices from the taxonomy's lists. An agent reads them from the document,
a person reviews and edits them, and the mTool fill writes them.

**Part-filled workbooks.** A person may attach a workbook that already holds figures (most often last year's
mTool file) before extraction. Last year's figures are imported and locked. This year's figures a person typed
are imported and kept fixed (owner, 18 November 2026: changed from v1, which overwrote them). The agents use
the imported figures as hints. The fill writes into that same workbook and proves every imported cell is
unchanged.

**Done when** (from `backend-plan.md` section 7, made checkable on the Mac):

1. All three reports load for MFRS and MPERS, Company and Group, with v1's field count, kinds and choice
   lists (v1's `test_reports.py:141`).
2. The reports agent fills every field of each report on Doc 1, 2 and 3 or says why not, with a source page
   for each value it saves. Same coverage as v1: every field assessed.
3. A report field a person edits gets a history row; a stale edit is refused.
4. The fill writes report fields into each genuine mTool template that has the report sheets, read back.
5. A workbook with last year's figures is imported: last year locked, typed subtotals kept with any
   disagreement shown, this year's typed figures kept fixed. A first-statements run or a different unit
   is refused in one sentence.
6. The agents see last year's fields and the comparative check. A sign-only difference stays open for a
   person.
7. **Imported figures survive the fill unchanged:** the fill writes into the attached workbook, never over
   an imported cell, and refuses to release a file whose imported cells changed.
8. Server tests, the browser build and browser tests pass.

**Waits on the owner:** the screens (the Reports tab, attaching a workbook at setup) start as a prototype
the owner approves (10f). Server routes come first so the screens have something to call.

**Only Windows can confirm:** reports and dates look right inside mTool.

## 2. What is already there

- The figure store's import path, `import_figure(origin="prior_workbook" | "typed_in_workbook")`, and the
  hard stops for a locked prior year, a sign question and a typed figure (`app/figures/_hard_stops.py`).
  Nothing calls them yet.
- Reading a workbook by meaning, both years, mTool or template layout (`app/scoring/workbook_read.py`).
- The taxonomy walk and registry (`app/catalog/taxonomy*.py`); the 12 report templates in `templates/`.
- The step 8 fill and receipt (`app/filing/`), the notes footnote fill, and the patcher
  (`app/workbook/offline_fill.py`).
- The Reader already finds the report sections of the document.

## 3. The parts, in build order

### 10a. Report catalogue and store

- **Builds:** `app/catalog/reports.py` from v1 `reports/registry.py:10-66`: the three reports, their fields
  from the taxonomy role, each field's kind and choice list. The rich-text row of each report template joins
  the notes catalogue the way prose notes did in step 6. A `report_fields` table with a history table
  (every write adds a history row), and `app/reports/store.py` with v1's checks from
  `reports/repository.py:75-132`: a choice from its list, a date as a date, text up to 4,096 characters,
  a stale edit refused. A value the agent saves needs a source page. A blank field is never "none".
- **Checks:** v1's `test_reports.py:141` (every field in all four standard and level pairs), `:362`
  (identity numbers, choices and dates), `:455` (no guessing), `:497` (identifier formats).

### 10b. Reports agent

- **Builds:** `app/reports/` agent on the shared loop (`app/agents/loop.py`) and page tools, run as a
  `reports` stage after setup is confirmed, when the Reader found a report section. One agent run covers the
  three reports. Its instructions are principles from v1's `prompts/reports.md`: read what is printed, copy
  names and numbers exactly, choose from the list only what the page supports, leave a field empty with a
  reason when the page does not show it. Tools: read and view pages, see the fields, save fields, finish.
  The save tool refuses in one plain sentence (a value with no source page, a page the agent has not opened,
  a choice not on the list). Every model call is recorded and the transcript kept.
- **Checks:** fake-model tests for the stage, refusals and history; one live run on Doc 1 (a few cents).

### 10c. Report routes

- **Builds:** `GET /api/runs/{id}/reports` (fields, values, status, source pages), `PATCH` one field with its
  revision, and clearing a field. Added to `docs/api-contract.md`.

### 10d. Attaching a part-filled workbook

- **Builds:** `POST /api/runs/{id}/starting-workbook` at setup (before extraction), stored in the run's folder
  through the safe-path helpers with its hash. Read with `read_filled_workbook`. v1's checks from
  `concept_model/prior_year.py:120-235`: not on first financial statements, the same unit, the same
  standard, level and layouts. Last year's figures import as `prior_workbook` (locked). Typed subtotals import
  as totals with no breakdown, a disagreement shown by the printed-totals check. This year's typed figures
  import as `typed_in_workbook`. A blank cell is never zero. Each import writes an event.
- **Checks:** v1's `test_prior_year_workbook.py:236` (zero kept, first statements refused), `:521` (Group and
  Company apart), `:887` and `:989` (typed subtotals), with the owner's rule for typed this-year figures.

### 10e. Hints for the agents

- **Builds:** the figures agent's opening message lists last year's field for each imported line (from
  `prior_year.py:369-416`, written as a principle: follow last year's field unless the line is gone or has
  changed in nature, and say why). The comparative check from `prior_year.py:446-613` as a check that
  compares the printed comparative with the imported figure and marks a sign-only difference for a person.
- **Checks:** v1's `:62`, `:1141`, `:1211`.

### 10f. Screens (prototype first)

- An HTML prototype in `prototypes/` for the Reports tab and attaching a workbook at setup, matching the v3
  and v4 look. The owner approves it before the screens are built.

### 10g. Fill keeps imported figures and writes reports

- **Builds:** when a run has a starting workbook, the fill writes into it, not a fresh template. Figures with
  origin `prior_workbook` or `typed_in_workbook` are not written ("kept as in the workbook"). Typed cells the
  run has no figure for are kept and listed. v1's `validate_export_source` and `verify_preservation`
  (`api/mtool.py:775-858`): no file is released unless every imported cell is unchanged. Report fields
  through v1's `reports/exporter.py:14-143` and `offline_fill.py:2197-2246`; the narratives through the
  existing note fill. Report lines on the receipt.
- **Checks:** v1's `test_prior_year_workbook.py:254` and `:654`, `test_reports.py:25` and `:405`, against
  the genuine `templates/mTool_*.xlsx`.
