# Step 8 plan — mTool fill

Written 23 November 2026 on branch `step-8-mtool-fill`, cut from `step-7-statements` (step 7 is not merged
to `main` yet). The owner said to proceed. Read with `backend-plan.md` sections 4.4 and 7, `v1-reuse-map.md`
section 2.4 and the `fills` table under section 3, `HANDOFF.md` "Deferred work, Step 8", and the approved
fill dialog and receipt in `prototypes/review-prototype-v4.html` (`modal==='fill'`, `modal==='receipt'`).

## 1. What step 8 delivers

A person uploads an empty mTool template on a run, the app fills it with the run's figures and notes, and
hands back the filled workbook with a receipt: what was written, kept and skipped, and why. When code cannot
place something (an unrecognised template, a field it cannot find, a read-back that does not match), an agent
investigates with a template toolkit and proposes a mapping. A person confirms a mapping before it is used.
Nothing is ever guessed, and only the one patcher writes the real file.

**Done when** (from `backend-plan.md` section 7, made checkable on the Mac):

1. Each of the ten genuine `templates/mTool_*.xlsx` workbooks that matches a test run's setup is identified,
   read and filled from that run's figures. Every write is read back. Reading the filled file back with the
   scoring reader gives the run's figures (fill and read agree).
2. Formula cells and locked cells are left alone. A calculated total is never written, except the equity statement's across-the-row totals, which mTool leaves as input cells (as v1). A missing figure
   leaves its cell empty, never zero. Values are written as stored: no scaling, no sign change.
3. Prose notes land in mTool's note store as the same prepared text the review screen shows.
4. The receipt lists written, kept, skipped and unresolved, each with a reason in plain words. It is
   stored in `fills` with the template's and the output's hashes and the figures and notes digests.
5. A deliberately altered template (SSM names removed from a sheet, or the column markers removed) is
   reported as unknown, and nothing is written to any cell the code could not resolve. The agent that
   investigates it is moved to the end of the build (8f below).
6. Server tests, the browser build and browser tests pass.

**Only Windows can confirm** that the filled file opens in mTool, validates, and that notes look right inside
mTool. Say so in the report; the owner runs it.

## 2. What is already there

- `app/scoring/` reads a genuine mTool workbook by meaning (`xlsx_cells`, `xlsx_formulas`, `mtool_layout`,
  `mtool_address`), copied from v1 in step 2. The same addressing must be used to fill, so read and fill agree.
- `app/notes/render/decorate.py` and the prepared text of each note field (step 6).
- The figure store, with `origin` per figure (`calculated` figures are template totals).
- The approved dialog and receipt in the prototype. The run screen's "Prepare mTool file" button.
- v1 at `.v1-reference/mtool/`: `offline_fill.py` (stdlib-only patcher, 2,434 lines, with notes into
  mTool's `fn_*` note store), `template_map.py`, `column_detect.py`, `exporter.py`, `receipt.py`, and tests
  `test_mtool_*` (listed in `v1-reuse-map.md` row 4).

## 3. The parts, in build order

### 8a. Workbook package (deferred from step 2)

- **Builds:** move `xlsx_cells`, `xlsx_formulas`, `mtool_layout`, `mtool_address` from `app/scoring/` to a new
  neutral package `app/workbook/`. Scoring imports from there. Template cells are read through
  `app/catalog/lookup.py`, not with SQL inside the reader.
- **Checks:** existing scoring tests pass unchanged apart from imports.

### 8b. The patcher

- **Builds:** v1's `offline_fill.py` copied into `app/workbook/offline_fill.py`, standard library only. It
  stays one file over the 400-line guide because it travels to the Windows machine as a single script
  (`backend-plan.md` 4.4); say so in its docstring. Copy the smallest part that does the job: the number
  patch with read-back, formula and locked-cell refusal, the note-store fill with its read-back, and the
  command line. Drop what v2 does not use (label fallback for unmarked workbooks: a cell is never found by
  label alone).
- **Checks:** the copied v1 tests for what was kept (`test_mtool_offline_fill`, `test_mtool_protected_inputs`,
  `test_mtool_formula_reconciliation` as relevant), plus one test on each genuine template: write a value, read
  it back, every other sheet's bytes unchanged.

### 8c. From figures to cells

- **Builds:** `app/filing/` (new): turn the run's current figures (both entities, both years, categories for
  equity and share classes) into write instructions, then resolve each to one cell with the same
  `mtool_address` the scoring reader uses. A calculated total is never written, except the equity statement's across-the-row totals, which mTool leaves as input cells (as v1). A figure that resolves to no cell, to
  more than one cell, to a formula cell or to a locked cell is not written and goes on the receipt with its
  reason. A prior-year figure on first financial statements is skipped. Identify the template: one of the ten
  known genuine templates (store their fingerprints, made from the files in `templates/`, in a small data file),
  a workbook that carries SSM names and mTool markers but is not on the list ("probably compatible"), or
  unknown. A confirmed saved mapping (8f) makes a template known.
- **Checks:** per genuine template matching a test setup, a run with saved figures fills, and the scoring reader
  reads back the same figures. A calculated total is never written, except the equity statement's across-the-row totals, which mTool leaves as input cells (as v1). A missing figure leaves the cell empty.

### 8d. Notes into mTool

- **Builds:** each note field's prepared text (the same text review and Copy give) goes into mTool's note
  store through the patcher, matched by the field's SSM name on its sheet. Over mTool's size limit is not
  possible (step 6 keeps notes under it); if one is, it is skipped and listed.
- **Checks:** a run with two prose notes fills; reading the note store back gives the prepared text.

### 8e. Fill, receipt, routes, screen

- **Builds:** one plain function `fill(run_id, template_path, user)` that runs 8c, 8d, the patcher, read-back
  and the receipt in order. It runs as a job (`kind` "fill") so a large workbook never blocks a request, with
  events per stage. Table `fills` as `v1-reuse-map.md` section 3 (trimmed v1 receipt). Files go through the
  safe-path helpers, written atomically; the original upload is never changed.
  Routes, added to `api-contract.md`: upload a template and start a fill; list a run's fills; one fill with its
  receipt; download the filled file (marks `downloaded_at`). Every route needs a session; permissions on the
  server. A fill is refused while the run is busy, in one plain sentence.
  Browser: the "Prepare mTool file" dialog and the receipt dialog exactly as in the prototype (upload or
  replace the template, Fill template, the three numbers, the list of skipped lines with their reason,
  Download), using existing components only. Every receipt line names the figure in words, never a cell id.
- **Checks:** route tests (session, busy run, wrong file type, download); a browser test for each dialog state
  (no template, filling, ready, failed). Open it in the browser and check every state.

### 8f. Template toolkit and the investigating agent — moved to the end of the build

The owner approved the placements screen (`prototypes/fill-placements-prototype.html`) on 23 November 2026
and asked for this part to be built last, after step 11. It is step 12 in `HANDOFF.md`. Step 8 leaves a clear
seam for it: an unknown template, an unresolved field and a read-back mismatch are listed on the receipt with
their reason, and the fill accepts a saved mapping once one exists.

What step 12 builds: `app/workbook/toolkit/` with a short `INSTRUCTIONS.md` and six one-job scripts printing
plain text (identify, list, find, read, trial fill on a copy, compare), used by the code path too. The
investigating agent runs only when a fill hits one of the three problems above. It works on a copy, proposes a
placement per figure with its evidence, and cannot write the real file or save a mapping. A person chooses Use
or Skip per placement on the approved screen; saved placements go in `template_mappings` and make the template
known next time. A proposed cell that is a formula, locked or already used is refused in code with one sentence.

## 4. Not in this step

- Starting from a part-filled workbook or last year's workbook (step 10). The patcher keeps what is already in a
  cell only as far as v1 did; the full rules of section 4.5 come in step 10.
- MPERS runs (step 9), though the MPERS templates are identified and listed.
- The readiness check (v1's `preflight.py` is not copied): v2's checks and open comments are shown instead.
