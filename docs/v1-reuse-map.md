# v1 reuse map

Draft 1 · 18 November 2026 · Status: for the owner's review. Nothing is copied yet.

This document checks section 8 of `backend-plan.md` ("Reuse from v1") against
v1's code. The plan's list was made from folder listings. This one was made by
reading the files, their imports and their tests.

**Which v1 was read.** The v1 checkout at `/Users/user/Desktop/xbrl-agent` is
on `main` at commit `8ba30614` (PR #64). GitHub's `main` is one merge ahead, at
`4bb9c6bf` (PR #65, the notes formatting preview the plan builds on). This map
was read from a clean worktree at `4bb9c6bf`. All `file:line` references are to
that commit. Paths are relative to the v1 repository root.

**Terms used below.**

- *Concept*: one fillable or calculated line of an SSM template, for example
  "Total assets" on the balance sheet. v1 gives each one a fixed ID.
- *Taxonomy element*: the official SSM name for a line, for example
  `ifrs-full_Assets`. mTool finds cells by this name.
- *Matrix*: the equity statement (SOCIE), whose cells are a grid of rows by
  equity columns.
- *Category*: a split inside a numeric note, such as a class of shares or a
  type of related party.
- *Fixture*: the test set-up code that builds a database or a workbook for a
  test to run against.

---

## 1. Summary

| Area | Verdict | Main v1 files (lines) | v1 tests that cover them (test functions) | Third-party packages (v1 version) |
|---|---|---|---|---|
| 1. Templates and taxonomy | Copy as is, with two small edits | `concept_model/parser.py` 870, `importer.py` 546, `bootstrap.py` 161, `filing_targets.py` 957, `taxonomy_semantics.py` 342, `definitions.py` 212, `dimensions.py` 146, `notes_parser.py` 93, `notes_importer.py` 56, `periods.py` 18, `sign_effect.py` 68, `statement_types.py` 293, `notes_types.py` 144, `tools/section_headers.py` 204, `tools/template_reader.py` 96, `notes/labels.py` 77, `scripts/generate_mpers_templates.py` 1,279. Data: 70 template workbooks (2.1 MB), `SSMxT_2022v1.0` (70 MB, 1,516 files), four JSON indexes (2.0 MB) | `test_concept_parser` 8, `test_concept_import` 2, `test_concept_bootstrap` 1, `test_filing_target_registry` 13, `test_filing_semantics_audit_snapshot` 1, `test_definition_lookup_tool` 5, `test_numeric_dimensions` 10 | openpyxl 3.1.5 (needs et_xmlfile 2.0.0) |
| 2. Figure storage and identity | Rebuild the store, copy the rules | `concept_model/facts_api.py` 1,171 (about 300 lines of rules worth keeping), `concept_model/cascade.py` 380, `concept_model/label_resolver.py` 144 | `test_facts_api` 12, `test_facts_read` 12, `test_cascade_recompute` 10 | fastapi 0.135.3 (only for its error type), pydantic 2.12.5 |
| 3. Checks | Copy with changes | `cross_checks/` 3,890 lines in 18 files | `test_cross_checks` 18, `test_cross_checks_impl` 36, `test_group_checks` 19, `test_socf_articulation` 5, `test_attribution_footing` 9, `test_cross_checks_mpers_socie` 6, `test_notes_numeric_footing` 6, `test_notes_face_tieouts` 16 | openpyxl 3.1.5 (only for the workbook half, which v2 drops) |
| 4. mTool fill | Copy the library; rebuild the glue and the readiness check | `mtool/offline_fill.py` 2,434, `column_detect.py` 720, `template_map.py` 947, `exporter.py` 398, `receipt.py` 339, `units.py` 99, `translation.py` 201, `sheet_selection.py` 69, `notes_exporter.py` 467, `notes_decorate.py` 1,289, `known_templates.json`. Not copied: `preflight.py` 448, `api/mtool.py` 1,593 | `test_mtool_offline_fill` 113, `test_mtool_column_detect` 31, `test_mtool_template_map` 12, `test_mtool_exporter` 14, `test_mtool_artifact_and_receipt` 25, `test_mtool_units` 17, `test_mtool_value_conventions` 4, `test_mtool_sheet_selection` 3, `test_mtool_notes_exporter` 32, `test_mtool_notes_decorate` 94, `test_mtool_filing_resolution` 14, `test_mtool_socie_input_totals` 3, `test_mtool_protected_inputs` 3, `test_mtool_formula_reconciliation` 10, `test_mtool_mpers_repair` 17 | None for the patcher (standard library only). beautifulsoup4 4.14.3 (needs soupsieve 2.8.3) for the notes half |
| 5. Human-file comparison | Copy with changes | `eval/human_file.py` 801, `eval/human_compare.py` 239, `api/human_file.py` 96 (rebuild) | `test_human_file_ingest` 18, `test_human_compare` 6 | beautifulsoup4 (through the notes sanitiser) |
| 6. Prior-year workbook import | Copy with changes, and one rule changes | `concept_model/prior_year.py` 858, `api/prior_year.py` 138 (rebuild), `docs/ROLLED-FORWARD-WORKBOOKS.md` | `test_prior_year_workbook` 21 | None beyond areas 1 and 4 |
| 7. Document handling | Word: not copied (owner, 18 November 2026: PDF uploads only). Page tools: copy with changes. Preparation: rebuild | `ingest/word_convert.py` 359, `docx_styles.py` 424, `docx_html.py` 236, `tools/pdf_viewer.py` 252, `page_cache.py` 266, `pdf_search.py` 323, `calculator.py` 131, `page_transcript.py` 345. Not copied: `ingest/document_preparation.py` 1,910, `ingest/pdf_sidecar.py` 451 | `test_word_convert` 22, `test_docx_styles` 11, `test_docx_html` 12, `test_pdf_viewer` 7, `test_page_cache` 12, `test_pdf_search` 25, `test_calculator_tool` 9, `test_document_preparation` 72 (rebuild) | PyMuPDF 1.27.2.2, mammoth 1.12.0 (needs cobble 0.1.4), beautifulsoup4 4.14.3. docx2pdf on Windows (not pinned in v1). LibreOffice on the Mac (a system program) |
| 8. Notes rendering | Copy with changes | `notes/render.py` 191, `table_layout.py` 387, `table_theme.py` 103, `html_sanitize.py` 591, `format_patch.py` 733, `format_verify.py` 174, `html_to_text.py` 352, plus `mtool/notes_decorate.py` (area 4), `notes/fonts/` (four Liberation Sans fonts, 1.6 MB, with licence) | `test_notes_render` 9, `test_notes_table_layout` 25, `test_notes_html_sanitize_css` 48, `test_notes_html_sanitize_trust_model` 10, `test_mtool_notes_decorate` 94 | PyMuPDF 1.27.2.2, beautifulsoup4 4.14.3, pydantic 2.12.5 |
| 9. Reports | Copy the registry and the report-field resolver; rebuild storage | `reports/registry.py` 85, `exporter.py` 143, `repository.py` 176 (rebuild), `agent.py` 314 (rebuild) | `test_reports` 20 | None beyond areas 1 and 4 |

Test function counts are `def test_` lines in each file. Parametrised tests run
more cases than that.

**Packages v2 does not yet list.** v2's `constraints.txt` has none of
openpyxl, et_xmlfile, PyMuPDF, beautifulsoup4, soupsieve, mammoth or cobble.
All seven are pinned in v1's `constraints.txt` at the versions above, so
AGENTS.md allows them without new approval. They must be added before step 1.
docx2pdf is not needed: the owner decided on 18 November 2026 that uploads
are PDF only, on every machine.

**A check that ran.** Four of the v1 test files above were run with v1's
virtual environment at commit `4bb9c6bf`: `test_mtool_offline_fill`,
`test_human_compare`, `test_notes_render` and `test_cross_checks_impl`.
168 passed in 4 seconds. No other v1 test was run.

---

## 2. Area by area

### 2.1 Templates and taxonomy

**What it does.** `parse_template` reads one template workbook with openpyxl
and returns a list of concepts with the sums that link them
(`concept_model/parser.py:133`). The equity statement takes a separate grid
parser (`parser.py:292`). Each concept then gets its SSM taxonomy element and a
"slot role" (input, formula, heading, unmapped) from the presentation linkbase
(`parser.py:180`, `taxonomy_semantics.py:320`). `bootstrap.py` does this for
every template at server start and writes the result to the database
(`bootstrap.py:44`, `:69`, `:111`).

The parse is fast. Parsing all 38 statement templates (both standards, both
levels, every layout) took under one second on the Mac and gave 6,520 concepts:
876 headings, 986 calculated totals, 3,400 inputs and 1,258 equity-grid cells.
6,506 of them carry a taxonomy element.

**Functions v2 would call**

| Function | What it does |
|---|---|
| `concept_model.parser.parse_template(path)` | Template workbook to a concept tree. No database |
| `concept_model.parser.derive_template_id(path)` | The template's ID, for example `mfrs-company-sofp-cunoncu-v1` |
| `concept_model.importer.import_template`, `import_company_targets`, `import_group_targets` | Write the tree and each concept's cell for each period and entity (`importer.py:40`, `:391`, `:480`) |
| `concept_model.filing_targets.persist_template_manifest(db, path)` | Write the taxonomy elements and the writable-slot list (`filing_targets.py:425`) |
| `concept_model.bootstrap.import_all_face_templates`, `import_all_notes_templates` | Do the above for every template |
| `concept_model.definitions.search`, `lookup_as_json` | Find a field's official definition by the words on the line (`definitions.py:124`, `:191`) |
| `concept_model.dimensions.dimension_key`, `instance_key`, `numeric_category_catalog` | Build the category part of a figure's identity and check it against the taxonomy (`dimensions.py:106`, `:124`, `:17`) |
| `concept_model.sign_effect.describe_overall_effect(conn, uuid, value)` | One sentence on whether a line is added or subtracted in the totals above it |
| `statement_types.template_path`, `VARIANTS`; `notes_types.notes_template_path` | Which template file serves a statement, layout, standard and level |

**What it depends on that v2 will not have**

- **v1's database tables.** The importer and the manifest writer insert into
  ten v1 tables: `concept_templates`, `concept_nodes`, `concept_edges`,
  `concept_targets`, `concept_render_aliases`, `concept_semantic_addresses`,
  `taxonomy_concepts`, `template_slots`, `template_manifest_exceptions` and
  `notes_nodes` (`db/schema.py:562`–`:719`, `:875`). Areas 2 to 6 all read
  these tables with SQL joins. Smallest change: create these ten tables in v2
  with the same columns. They are a read-only catalogue rebuilt at every start,
  so they carry no migration history. Section 3 lists them.
- **`utils.paths.safe_path` and `db.engine`.** v2 is copying `utils/` anyway.
  `db/engine.py` is 29 lines.
- **A generator script used at run time.** `taxonomy_semantics.py:198` and
  `reports/registry.py:50` import `scripts/generate_mpers_templates.py`
  (1,279 lines) to walk taxonomy roles. Smallest change: copy the script whole,
  or move its `walk_role_for_taxonomy` (`:477`) and `mpers_socie_components`
  (`:932`) into the concept package.
- **`notes.labels.normalize_label`** (77 lines, standard library). Copy it.
- **`run_periods` reads `runs.run_config_json`** (`periods.py:8`). Smallest
  change: pass the "first financial statements" flag in.

**Surprising or fragile**

- **A concept's ID is made from its label.** It is a UUID5 of template ID,
  sheet, row and label (`parser.py:767`). If v2 copies the templates and parser
  unchanged, v2's IDs equal v1's. That lets the step 1 scoring tool read v1's
  figures directly. Any edit to a template row label changes its ID.
- **The template ID is read from folder names.** `derive_template_id` marks a
  template MPERS if any folder in its full path contains "mpers", and Group if
  any folder is named "group" (`parser.py:432`). A v2 checkout under a folder
  with either word would get wrong IDs. Smallest change: read only the last two
  folders.
- **The two unit indexes are keyed by label, not by taxonomy element**
  (`concept_units_*.json`, read by `mtool/units.py:57`). A label shared by two
  elements with different units is marked ambiguous and treated as unknown.
- **The taxonomy reader opens every `.xsd` under `SSMxT_2022v1.0`**
  (`taxonomy_semantics.py:113`). Trimming the 70 MB folder was not tried. Copy
  it whole.
- **Do not copy** `concept_model/cell_resolver.py` (347). It maps a cell an
  agent wrote in a scratch Excel file back to a concept (`cell_resolver.py:1`).
  That is the direct-Excel path v2 drops. Also skip the template `backup`,
  `backup-originals` and `archive-*` folders unless v2 will run the generators,
  which need them for before-and-after snapshots.

### 2.2 How a figure is stored and identified

**What it does.** v1 stores one row per figure in `run_concept_facts`
(`db/schema.py:719`). Every write goes through `apply_fact`
(`facts_api.py:304`). It checks the write, saves it, and adds a before-and-after
row to `concept_fact_events` (`schema.py:742`).

**What identifies a figure.** The unique key is
`(run_id, concept_uuid, period, entity_scope, dimension_key)`
(`schema.py:734`).

- `period` is `CY` or `PY`. `entity_scope` is `Company` or `Group`
  (`facts_api.py:72`–`:73`).
- **The matrix column is inside the concept.** Each equity-grid cell is its own
  concept, with its column letter stored on the concept as `matrix_col`
  (`schema.py:585`). There is no separate column field on the figure.
- `dimension_key` is empty except for the categories in the share-capital and
  related-party notes. It is a sorted JSON object of taxonomy axis to member
  (`dimensions.py:106`). Only those two note sheets accept one
  (`dimensions.py:138`).
- The concept's own fixed category (the equity component on a grid cell) is
  stored on the concept, not repeated on the figure (`dimensions.py:124`).

**How calculated totals are handled.**

- An agent cannot write a value to a calculated total. The write is refused
  unless the agent marks the total "aggregate only", meaning the report gives
  no breakdown (`facts_api.py:189`–`:209`). Headings refuse every write
  (`facts_api.py:174`–`:184`).
- After each turn, `recompute_after_turn` adds up every total from its parts
  and **saves the sum as a figure** with `source='cascade'`
  (`cascade.py:64`, the insert at `cascade.py:318`–`:328`). The checks, the
  comparison and the mTool fill read those saved sums.
- If a total holds an observed value that differs from its parts, the
  difference is logged as a conflict (`run_concept_conflicts`, kind
  `partial_state`) and nothing is forced (`cascade.py:257`–`:300`).
- A total with no numeric part stays blank, never zero.
- So v1 never stores the total **as printed in the report** for an ordinary
  total. It stores only the sum of the parts.

**Rules worth copying, as code, into v2's save function**

| Rule | v1 location |
|---|---|
| A heading refuses a value, with a plain sentence | `facts_api.py:174` |
| A calculated total refuses an observed value unless marked aggregate only | `facts_api.py:189` |
| The "children" marker is only valid on a total | `facts_api.py:211` |
| Prior-year figures are refused when imported from a workbook | `facts_api.py:247` |
| Prior-year figures are refused for first financial statements | `facts_api.py:253` |
| A text field refuses a number ("save it as a note") | `facts_api.py:286` |
| A slot the manifest marks not writable refuses a value | `facts_api.py:299` |
| A parent marked aggregate only and a child with a value raise a conflict, in both directions | `facts_api.py:1038`, `:1106` |
| Totals are added at cent precision, with a cent tolerance | `cascade.py:39` |

**What it depends on that v2 will not have.** `facts_api.py` raises FastAPI's
`HTTPException` from library code (`facts_api.py:31`). Its notes branch pulls
in `notes/writer.py` (1,178 lines) and `db/repository.py` (3,920 lines)
(`facts_api.py:899`–`:903`). Smallest change: do not copy the file. Copy the
rules in the table above into v2's own save function, returning a plain
sentence instead of an HTTP error. Copy `cascade.py` as the "calculate totals"
step, changed to read and write v2's `figures` table.

**What v1 does not store at all.** v1 has no field for the label as printed,
the order on the page, a certainty or a one-line reason. The page is only
inside a free-text `evidence` column, or in `fact_source_terms.source_page`
when a prepared table was used (`schema.py:780`). These are new in v2.

### 2.3 Checks

**What it does.** Nine statement checks compare totals across statements: the
balance sheet balances, profit agrees between income statement and equity
statement, cash agrees between cash flow and balance sheet, and so on
(`framework.py:196`–`:229`). Each check has two versions: `run()` reads a
workbook file, and `run_facts()` reads saved figures. The figure version is the
default in v1 (`server.py:434`, `XBRL_FACT_BASED_CHECKS` defaults to on). Four
note checks run separately (`server.py:4403`–`:4571`).

**What each check needs as input.** The figure version takes a
`FactsContext`: an open SQLite connection, the run ID, a map of statement to
template ID, the filing level and the standard (`framework.py:233`). It finds
each line **by label**, through `label_resolver.resolve_label_candidates`,
which reads `concept_nodes` (`label_resolver.py:60`). It then reads the figure
from `run_concept_facts` through `read_run_facts` (`facts_api.py:502`).

**Can they run against a simple list of figures?** Not as written, but nearly.
They need two things: the concept catalogue (label, kind, sheet, row, matrix
column, template) and the figures keyed by concept, period and entity. Both are
plain lookups in `cross_checks/facts_util.py:45`–`:66` and
`label_resolver.py:60`–`:144`. Smallest change: give `FactsContext` two
functions, "concepts for this template" and "figures for this template", and
route those three SQL reads through them. Then a check runs from a list in
memory. That also makes the "re-run in under a second after an edit" target
likely, though it was not timed.

| Check | v1 file | Figure path? | Needs besides figures |
|---|---|---|---|
| Balance sheet balances | `sofp_balance.py` | Yes (`:72`) | none |
| Income statement profit to equity statement | `sopl_to_socie_profit.py` | Yes (`:99`) | equity-grid column letters by standard (`facts_util.py:113`) |
| Comprehensive income to equity statement | `soci_to_socie_tci.py` | Yes (`:92`) | same |
| Equity statement to balance sheet equity | `socie_to_sofp_equity.py` | Yes (`:130`) | same |
| Cash flow to balance sheet cash | `socf_to_sofp_cash.py` | Yes (`:94`) | none |
| Cash flow adds up | `socf_articulation.py` | Yes (`:302`) | none |
| Profit and comprehensive income split between owners and minority | `attribution_footing.py` | Yes (`:263`) | whether prior year was imported (`:265`, `concept_model.prior_year.is_preserved`) |
| Retained earnings statement to balance sheet (MPERS) | `sore_to_sofp_retained_earnings.py` | Yes (`:77`) | none |
| Share capital and related-party notes add up | `notes_numeric_footing.py` | Yes, by its own SQL (`:104`) | taxonomy category list |
| Note figure agrees with face figure | `notes_face_tieouts.py` | **No, workbook only** (`:92`) | a filled workbook |
| Note citations agree | `notes_consistency.py` | **No, workbook only** | a filled workbook |
| Cash flow line in the right section | `socf_section_placement.py` | **No, workbook only** | a filled workbook |

**Surprising or fragile**

- **Checks find lines by label text, with substring matching**
  (`label_resolver.py:91`–`:100`). The cash-flow duplicate "cash at end"
  rows only work because the search takes the top row first. v2 should keep
  the same template labels or switch the checks to taxonomy elements.
- **Three checks still need a workbook.** v2 drops the workbook. Smallest
  change: rewrite each one over figures. They are 149 to 429 lines.
- `cross_checks/util.py:14` imports `tools/verifier.py` (1,785 lines) for the
  workbook half. Drop the workbook `run()` methods and that import.
- **The main check test file tests the workbook half.**
  `test_cross_checks_impl.py` imports `openpyxl` and builds workbooks. The
  figure half is covered in `test_facts_read`, `test_cross_checks_e2e_parity`
  and `test_cross_checks_shadow`, which need v1's full database fixture. v2
  must rewrite these tests against figure lists.
- The result shape (`CrossCheckResult`, `Comparand`, `framework.py:77`–`:143`)
  can be copied as is. It already names both sides of each comparison.

### 2.4 mTool fill

**What it does.** Four steps, all without Excel.

1. `build_fill_doc` turns saved figures into fill instructions. Each carries
   the taxonomy element, categories, period and entity (`exporter.py:111`).
2. `inspect_template` identifies the uploaded workbook, and `resolve_filing_doc`
   finds the exact cell for each instruction (`template_map.py:109`, `:631`).
3. `fill_workbook` writes the numbers by editing only the sheet XML inside the
   file's zip, refuses formula cells, and reads every write back
   (`offline_fill.py:2037`). `fill_footnotes` writes prose notes into mTool's
   hidden note store (`offline_fill.py:1345`).
4. `write_fill_receipt` stores what was written, kept and skipped
   (`receipt.py:168`).

**The smallest set of files that reads and fills an mTool workbook**

| Job | Files | Lines |
|---|---|---|
| Read cells, inspect, patch numbers and notes, read back | `offline_fill.py` | 2,434 |
| Find label and year columns, fingerprint | `column_detect.py` | 720 |
| Find cells by taxonomy element | `template_map.py` | 947 |
| Known fingerprints | `known_templates.json` | data |
| **Minimum to read and fill numbers** | **the four above, plus `apply_column_map` from `exporter.py:355`** | **about 4,140** |
| Build instructions from v2's figures | `exporter.py` (adapted), `units.py`, `translation.py` | 698 |
| Notes into mTool | `notes_exporter.py`, `notes_decorate.py` | 1,756 |
| Receipt | `receipt.py` (adapted) | 339 |
| Sheet selection | `sheet_selection.py` | 69 |

`offline_fill.py` imports only the standard library and has no import from the
rest of v1. `column_detect.py` imports only `offline_fill`. Those two can be
copied unchanged. Their tests use openpyxl only to build test workbooks.

**What it depends on that v2 will not have**

- `template_map.py:27` imports `apply_column_map` from `exporter.py`, which
  imports `db.engine`, `receipt.py` and `notes.labels` at the top. Smallest
  change: move the 40-line `apply_column_map` into `template_map.py`. Then the
  read-and-fill core has no database import.
- `snapshot_facts` (`receipt.py:44`) is one SQL query over seven v1 tables:
  figures, concepts, templates, cell targets, taxonomy addresses, taxonomy
  elements, slots and sum links. `build_fill_doc` reads `run_periods` and
  `is_preserved` from `runs.run_config_json` (`exporter.py:148`–`:152`).
  Smallest change: v2 keeps the catalogue tables (section 3) and replaces the
  one query.
- `build_notes_fill_doc` reads `notes_cells`, `notes_nodes`, `template_slots`
  and `report_fields` (`notes_exporter.py:133`–`:165`).
- **Do not copy `preflight.py`.** It reads eight v1 tables that v2 drops:
  reviewer flags, notes review flags, notes integrity runs, notes coverage rows,
  run agents and more (`preflight.py:36`–`:170`). v2's readiness check is its
  own checks and open comments.
- **The fill steps are joined together inside an API route**, not a library
  function: `api/mtool.py:523`–`:1056` (about 530 lines) calls column
  detection, inspection, resolution, prior-year checks, the patcher, the notes
  patch, read-back, report fields, preservation checks and the receipt in
  order. v2 must rebuild this as one plain function. It is the main work of
  build step 7.
- The receipt table `mtool_fill_receipts` has 27 columns (`schema.py:1697`).
  Section 3 proposes fewer.

**Surprising or fragile**

- **The 30 "recognised templates" are v1's own repository templates, not
  mTool's.** Every one of the 30 entries in `known_templates.json` has
  `"source": "generated"`, layout `ours-A-labels-BC-values`, and is vouched for
  as "repo (generated from the SSM linkbase)". They fingerprint the files in
  `XBRL-template-MFRS` and `XBRL-template-MPERS`. A workbook exported from mTool
  is not on the list. It is handled by finding taxonomy element names inside it
  and is reported as `candidate-2.2`, meaning "probably compatible, not
  verified" (`template_map.py:183`–`:187`). A file with neither is reported
  `unverified` and filled by label as a fallback.
- **No real mTool workbook is in the repository.** The mTool tests fill v1's
  own templates (`tests/_human_file_fixture.py:20`, `mtool/README.md`, "Known
  limits"). The memory notes and README say the Windows acceptance run on a
  genuine mTool 2.2 file is still open.
- **Values pass through unchanged.** The exporter writes the stored value with
  no scaling and no sign change (`exporter.py:30`–`:66`, `translation.py`
  identity manifest). The stored sign must already be the sign the template's
  formula expects, for example dividends positive, cash-flow signs per row.
  v2's figures agent must keep the same sign rules, or the fill writes wrong
  signs.
- Notes are matched to mTool's note store by label within a sheet, and the
  first `fn_*` key wins (memory note on mTool text blocks; `offline_fill.py:879`,
  `:942`). A note over 32,767 characters after wrapping is skipped and flagged
  (`offline_fill.py:673`, `notes_exporter.py:389`).

### 2.5 Human-file comparison

**What it does.** `read_human_file` reads a person's filled mTool workbook
**by address**: it builds one dummy fill instruction for every fillable field
of the run's templates, finds each field's cell with the same resolver the fill
uses, and reads the cell (`eval/human_file.py:549`, `_slot_writes` at `:209`).
Typed numbers count. Formula cells are marked "calculated" and not scored.
Labels are never used to match figures (`human_file.py:14`–`:17`).
`load_comparison` then compares the stored human values with the run's current
figures on every read (`eval/human_compare.py:153`).

**Functions v2 would call**

| Function | What it does |
|---|---|
| `eval.human_file.read_human_file(conn, run_id, path, unit, shape=...)` | Read the workbook. Stores nothing |
| `eval.human_file.store_human_file`, `ingest_human_file`, `delete_rows` | Save or remove the human's values (`:738`, `:776`, `:768`) |
| `eval.human_compare.compare_figures(human, ai, ai_totals)` | Pure comparison of two dictionaries (`:70`) |
| `eval.human_compare.derive_totals(values, edges, keys)` | Add up the human's totals from the human's own inputs (`:38`) |
| `eval.human_compare.compare_notes(human, ai)` | Same field or not (`:137`) |

**What it depends on that v2 will not have**

- `run_filing_shape` reads `db.repository.fetch_run` and the `run_agents` table
  to learn which layouts ran (`human_file.py:110`–`:145`). Smallest change: v2
  passes the shape in. The function already accepts `config=`.
- The catalogue tables, through `_slot_writes`.
- Three storage tables, `human_files`, `human_file_facts`, `human_file_notes`
  (`schema.py:1734`–`:1775`). Section 3 keeps them.
- The API route uses `server._open_audit_conn` and helpers in `api/mtool.py`
  (`api/human_file.py:22`–`:27`). Rebuild the route.

**Surprising or fragile**

- **v1's numbers are not the plan's numbers.** v1 reports "Found" (both filled
  over human filled) and "Same value" (equal over both filled), per entity
  (`human_compare.py:6`–`:14`). There is no "complete and accurate" product,
  no "sign only" bucket and no per-cell "scale" bucket. v1 has one whole-file
  warning when the median ratio is about 1,000 (`human_file.py:434`). The plan's
  section 4.3 buckets are new code, on top of `compare_figures`.
- A human zero against a blank run value is left out of the score
  (`human_compare.py:116`–`:118`). The plan does not mention this rule.
- `load_comparison` reads every row of `concept_edges` and every calculated
  concept in the database on each call (`human_compare.py:176`, `:193`). This
  is fine at 6,520 concepts but not timed.
- Equal means exactly equal, allowing only float noise (`human_compare.py:33`).

### 2.6 Prior-year (rolled-forward) workbook import

**What it does.** `inspect_workbook` checks the uploaded workbook matches the
run's standard, level, layouts, dates and units, then reads its prior-year
inputs with the human-file reader (`prior_year.py:120`, the read at `:176`).
`import_workbook` saves them as figures with `source='prior_year_workbook'`,
the workbook hash and cell in the evidence, and a history row each
(`prior_year.py:238`). Typed subtotals are kept as "aggregate only" and a
disagreement with their parts becomes a conflict (`prior_year.py:39`).
`compare_value` lets an agent compare a printed comparative with the imported
one and names a sign-only difference with the line's overall sign
(`prior_year.py:446`, `:436`).

**Functions v2 would call**

| Function | What it does |
|---|---|
| `inspect_workbook(conn, config, path, unit)` | Check and read; returns inputs and a summary |
| `import_workbook(db, run_id, session_dir, config)` | Save the inputs before extraction |
| `is_preserved(conn, run_id)` | Was prior year imported for this run (`:351`) |
| `compare_value(...)` | Compare one printed comparative with the imported figure |
| `check_results(db, run_id)` | Comparative findings as check results (`:643`) |
| `stale_current_year_cells`, `validate_export_source`, `verify_preservation` | On fill: list typed current-year cells, check the workbook is the same one, prove imported cells were not changed (`:767`, `:775`, `:813`) |

**What it depends on that v2 will not have**

- `scout.infopack.Infopack` for reporting dates and suggested layouts
  (`prior_year.py:87`–`:118`, `api/prior_year.py:22`). Smallest change: pass
  the two dates and the confirmed layouts in. In v2 they come from setup.
- `runs.run_config_json` for the workbook token, the summary and the "is
  preserved" flag (`prior_year.py:327`–`:345`, `:351`). Smallest change: a
  `prior_workbook` record per run (section 3).
- `run_concept_conflicts` with kind `prior_year_comparative`. v2 stores these
  as check results.
- `register_comparison_tool` attaches a PydanticAI tool to a v1 agent
  (`prior_year.py:579`). Rebuild it as a v2 tool.
- It calls `export_run_to_xlsx` (`prior_year.py:427`–`:430`), part of the
  direct-Excel export v2 drops. Not traced further.

**Surprising or fragile**

- **v1 overwrites typed current-year figures on fill. v2 has decided the
  opposite.** v1: "This run's figure replaces a typed current-year number in
  the same field" (`docs/ROLLED-FORWARD-WORKBOOKS.md`, paragraph on Prepare
  mTool draft). The plan (section 4.5, decided 18 November) keeps typed
  current-year figures fixed and fills only gaps. The reader can already list
  typed current-year cells (`human_file.py:527`). The import, the save rules
  and the fill must all change. This is not a copy.
- Native mTool share-capital and related-party sheets hold current year only,
  so they normally import no prior year (`ROLLED-FORWARD-WORKBOOKS.md`).
- Only a person can close a sign-only difference (`ROLLED-FORWARD-WORKBOOKS.md`,
  "only a person can"). This matches plan section 4.5.

### 2.7 Document handling

**What it does**

- `convert_docx_to_pdf` turns Word into a text PDF, with Word on Windows or
  LibreOffice elsewhere, in a child process with a 180-second limit
  (`ingest/word_convert.py:323`, `:47`). No file path appears on a command
  line.
- `extract_style_maps` reads table borders, shading, alignment, padding and
  spacing straight from the Word XML (`ingest/docx_styles.py:284`).
  `extract_docx_html` turns the Word body into HTML with mammoth and adds those
  styles (`ingest/docx_html.py:79`, `:180`).
- `render_page_png` draws a page or a part of it as a picture
  (`tools/pdf_viewer.py:125`). `page_cache` keeps recent pictures in memory.
  `search_pdf_text` searches the PDF's text, or the prepared transcript when
  the PDF is a scan (`tools/pdf_search.py:179`). `calculate` does exact
  arithmetic without `eval` (`tools/calculator.py:21`).
- `prepare_document` is a model-driven reading of every page: it captures each
  page as HTML, checks tables, corrects rotation and links tables across pages
  (`ingest/document_preparation.py:1054`).

**How a prepared page is stored.** On disk, beside the PDF, not in the
database. A `preparation.json` holds the run's identity (file hashes, contract
version 18, model name), a `pages` list and a `blocks` list
(`document_preparation.py:48`, `:617`, `:626`). Each block has an ID,
a kind (heading, table, list, paragraph), its HTML and its page
(`document_preparation.py:670`). A combined HTML file and a rotation-corrected
PDF sit beside it. The file is only trusted when every hash still matches
(`document_preparation.py:626`–`:653`).

**What it depends on that v2 will not have**

- Preparation calls models through v1's `model_settings`, `usage_metrics`,
  `notes._rate_limit` and `ingest/pdf_sidecar.py` (`document_preparation.py:32`
  –`:36`, `:522`–`:525`). It is v2's Reader stage. Rebuild it. Its block shape
  (ID, kind, HTML, page) is a good model for v2's `pages` table.
- `page_transcript.py` reads `preparation.json` (`:50`) and imports PydanticAI's
  `RunContext` (`:30`). Smallest change: read v2's `pages` table instead.
- `page_cache.py` and `word_convert.py` read one setting each from the
  environment: `XBRL_PAGE_CACHE_MAX` (`page_cache.py:74`) and
  `XBRL_DOCX_CONVERTER` (`word_convert.py:278`). AGENTS.md puts settings in the
  database. Smallest change: pass them in, or use a fixed value.
- `word_convert.py` and `docx_html.py` are otherwise self-contained.
  `docx_styles.py` is standard library only.

**Surprising or fragile**

- LibreOffice must be installed on the Mac for Word input. It is not a Python
  package.
- docx2pdf is not pinned (section 1).
- `pdf_viewer.py` renders at the source scan's resolution, measured, not 200 DPI
  (`pdf_viewer.py:6`–`:36`). Keep this. It saves cost.

### 2.8 Notes rendering

**What it does.** `render_note_preview` decorates a note's HTML with the output
styling, then lays it out with PyMuPDF's HTML engine (`fitz.Story`) on mTool's
note page: A4 portrait, 20 mm margins, 170 mm of text width
(`notes/render.py:171`, `:38`–`:44`). Text is set in Liberation Sans, which has
Arial's letter widths, so lines wrap where Arial would (`render.py:1`–`:7`,
`:24`–`:33`). It returns PNG pictures and how many millimetres the widest table
runs over. `fitting_font_size` finds the largest table font, down to 8 pt, that
fits (`render.py:180`).

`table_layout.py` turns the formatter's description of a table (each column is
a label, amount, text or date; each row is a heading, item, subtotal or total;
where each rule sits) into inline styles by code (`table_layout.py:1`–`:13`,
`:317`). `html_sanitize.py` keeps only the allowed tags and table styles
(`html_sanitize.py:384`).

**What the renderer draws with.** PyMuPDF 1.27.2.2, BeautifulSoup with the
built-in `html.parser` (all 61 uses in the copy set), the four fonts in
`notes/fonts/`, and `mtool/notes_decorate.py` for the output styling.

**What it cannot draw**

- It is not mTool. The docstring says it shows "alignment, rules, bold,
  indents, column widths and wrapping, not mTool's exact pixels"
  (`render.py:5`–`:7`).
- The engine ignores percentage widths and treats pixel widths as absolute, so
  the code converts every table to point widths first (`render.py:70`–`:78`).
- Anything past the text area is clipped. A table too wide is drawn on a
  widened page and reported as overflow (`render.py:91`–`:94`, `:139`–`:145`).
- A note over 40 pages, or a table row taller than one page, cannot be drawn
  (`render.py:44`, `:107`–`:110`).
- One drawing at a time: PyMuPDF layout is not thread-safe (`render.py:47`).
- mTool itself does not honour hidden or absent borders. The decorator paints
  removed borders white so they vanish there (`notes_decorate.py:400`–`:419`).
  The preview shows the decorated result.
- Page breaks in mTool are not established (`mtool/README.md`, formatting
  table).

**What it depends on that v2 will not have**

- `table_theme.py` reads the firm's table style from two environment variables,
  `XBRL_NOTES_TABLE_STYLE` and `XBRL_NOTES_APPEARANCE_OVERRIDES`
  (`table_theme.py:32`–`:33`, `:57`). AGENTS.md puts settings in the database.
  Smallest change: pass the style dictionary in.
- `table_layout.py` needs `notes/format_patch.py` (733) and
  `notes/format_verify.py` (174), which need `html_sanitize.py` and
  `html_to_text.py`. The real copy set for the renderer and layout compiler is
  about 4,000 lines, counting `notes_decorate.py` (1,289), not the 680 lines of
  the four files the plan names.

**Surprising or fragile**

- **Everything speaks HTML.** The renderer, the decorator, the sanitiser, the
  layout compiler, the mTool note writer and the human-file note reader all
  take one HTML string per note field. The plan says v2 stores notes "as blocks
  with their look". To reuse this code, v2 must either store the note as HTML
  or compile its blocks to the same sanitised HTML before any of these steps.
- The sanitiser is not safe against hostile input. Its own docstring says so
  (`html_sanitize.py:9`–`:21`). It suits agent output and a user's own paste.

### 2.9 Reports

**What it does.** Three reports: directors' report, statement by directors,
auditors' report (`reports/registry.py:10`–`:14`). `fields(report, standard)`
lists each report's taxonomy fields and their kind (rich text, date, a choice
from a list, or plain text) from the taxonomy (`registry.py:46`).
`resolve_reports` finds each report field's cell in an uploaded workbook, and
only when the taxonomy element and the input type are certain
(`reports/exporter.py:49`). The rich-text parts are stored as notes; the other
fields are stored in `report_fields` (`reports/repository.py:75`,
`schema.py:259`).

**What it depends on that v2 will not have.** `registry.py` needs
`taxonomy_semantics` and `scripts/generate_mpers_templates` (`registry.py:49`
–`:50`). `repository.py` needs `db.repository`, `notes_cells` and openpyxl for
a diagnostic workbook. `agent.py` is a v1 agent loop. Smallest change: copy
`registry.py` and `exporter.py`; rebuild storage as a `report_fields` table
and the agent as part of v2's notes agent.

---

## 3. The data model v2 needs

Two groups of tables. The **catalogue** describes the templates and is the
same for every run. The **run tables** hold each run's work.

### 3.1 Catalogue tables (copy v1's columns exactly)

These are not in the plan's table list (section 3 of the plan). Without them,
the copied parser, checks, fill, comparison and prior-year import all fail,
because each one joins them in SQL. They are rebuilt from the template files at
every start, so they need no migrations. Keeping v1's column names lets the
copied SQL run unchanged.

| Table | Holds | v1 source |
|---|---|---|
| `concept_templates` | One row per template: ID, file path, shape (list or grid) | `schema.py:562` |
| `concept_nodes` | One row per concept: ID, template, parent, kind, label, sheet, row, column, grid column and its label | `schema.py:575` |
| `concept_edges` | The sums: parent, child, signed coefficient | `schema.py:665` |
| `concept_targets` | The cell for each concept, entity and period | `schema.py:679` |
| `concept_render_aliases` | A second cell for a concept that appears on two sheets | `schema.py:704` |
| `concept_semantic_addresses` | Taxonomy element and fixed categories per concept | `schema.py:596` |
| `taxonomy_concepts` | SSM element facts: type, period type, balance, abstract | `schema.py:610` |
| `template_slots` | Which cells are writable, and their value kind | `schema.py:628` |
| `template_manifest_exceptions` | Reviewed exceptions per template | `schema.py:653` |
| `notes_nodes` | The rows of the prose-note templates | `schema.py:875` |

If the owner prefers fewer tables, `concept_render_aliases` and
`template_manifest_exceptions` could fold into others, but every copied query
would then change. This map recommends keeping all ten.

### 3.2 Run tables

**`figures`** — one row per figure.

| Column | Meaning | Needed by |
|---|---|---|
| `id` | Row ID | all |
| `run_id` | The run | all |
| `concept_uuid` | The template field (includes the equity column for grid cells) | all |
| `period` | `CY` or `PY` | all |
| `entity_scope` | `Company` or `Group` | all |
| `dimension_key` | Category, as v1's sorted JSON, or empty | checks (note footing), fill, comparison, prior-year |
| `value` | The number, in the report's own unit and the template's sign. Blank means not found, never zero | all |
| `status` | `observed`, `explicit_zero`, `not_disclosed`, `user_override`, `conflict` (v1's set, `facts_api.py:43`) | checks, fill |
| `children_status` | For a total: `itemised`, `aggregate_only` or `partial` | calculation, fill |
| `origin` | `agent`, `person`, `calculated`, `prior_workbook`, `typed_in_workbook` | fill (skip calculated), prior-year lock, comparison |
| `locked` | 1 when imported from a workbook. Saves refuse it | section 4.5 of the plan |
| `stated_value` | For a total: the amount the report prints, when it differs from the calculated sum. Blank otherwise | Report view, "never forced to balance" |
| `certainty` | `sure` or `unsure` | review |
| `reason` | One line from the agent | review |
| `source_ref` | For an imported figure: workbook hash, sheet, cell | prior-year preservation check |
| `updated_by`, `updated_at` | Who and when | history |
| | Unique on `(run_id, concept_uuid, period, entity_scope, dimension_key)` | |

**`figure_lines`** — the printed lines behind a figure. One figure can come
from two or more printed lines added together, which v1 handles with
`fact_source_terms` (`schema.py:780`). The plan needs the printed label, its
order and its page for each figure; putting them here covers both the one-line
and the many-line case.

| Column | Meaning |
|---|---|
| `figure_id` | The figure |
| `printed_label` | The line as the report prints it |
| `print_order` | Its position in the statement as printed |
| `page` | Source page number |
| `amount` | The amount printed on that line |
| `coefficient` | +1 or −1 when lines are combined |

A save tool refuses a figure with no line and no page, which is one of the
plan's hard stops. If the owner wants one table only, the first three columns
can move onto `figures`, but then a figure made of two lines loses one label.

**`figure_history`** — before and after for every change, as v1's
`concept_fact_events` (`schema.py:742`): `figure_id` or the full key, `actor`,
`changed_at`, `before_json`, `after_json`, `round_id`.

**`notes`** — one row per note field.

| Column | Meaning |
|---|---|
| `run_id`, `id` | |
| `concept_uuid` | The note field (from `notes_nodes` or `template_slots`) |
| `sheet`, `row` | The template row, which the mTool note writer and comparison read |
| `label` | The template row label. The mTool note writer matches by it |
| `html` | The note as sanitised HTML, the form every copied note step takes |
| `blocks_json` | The stored blocks and their look, if v2 keeps blocks separately. `html` is compiled from it |
| `pages` | Source pages |
| `certainty`, `reason` | As figures |
| `format_status` | `previewed`, `not_previewed`, `check_formatting` |
| `revision`, `updated_by`, `updated_at` | Guards against two writers |
| | Unique on `(run_id, sheet, row)`, as v1 (`schema.py:856`) |

A `note_history` table mirrors `figure_history`.

**`report_fields`** — the non-rich-text report fields, as v1
(`schema.py:259`): `run_id`, `report`, `concept_id`, `value_kind`, `value`,
`status`, `pages`, `revision`.

**`check_results`** — rewritten each time figures change.

| Column | Meaning |
|---|---|
| `run_id`, `check_name` | |
| `status` | `passed`, `failed`, `warning`, `pending`, `blocked`, `not_applicable` (`framework.py:120`–`:131`) |
| `period`, `entity_scope` | Which pass failed |
| `expected`, `actual`, `diff`, `tolerance` | The numbers |
| `message` | One plain sentence |
| `comparands_json` | Both sides and their concepts, as v1 (`framework.py:77`) |
| `target_concept_uuid` | Where the review list jumps to |
| `computed_at` | |

Total-against-parts disagreements and prior-year comparative differences can
also land here, as `check_name = 'total_vs_parts'` and `'prior_year'`, instead
of a separate conflicts table.

**`fills`** — one row per mTool fill, a trimmed version of v1's 27-column
receipt (`schema.py:1697`).

| Column | Meaning |
|---|---|
| `id`, `run_id`, `created_by`, `created_at` | |
| `template_sha256`, `template_fingerprint`, `compatibility` | Which workbook, and `verified-generated`, `candidate-2.2` or `unverified` |
| `figures_digest`, `notes_digest` | Which revision of the figures and notes was filled |
| `column_map_json` | The layout used |
| `output_sha256`, `output_path` | The file handed back |
| `status` | `ok` or `needs review` |
| `report_json` | Written, kept, skipped, unresolved, mismatched, preserved |
| `downloaded_at` | |

**`prior_workbooks`** — one per run when a workbook is uploaded: `run_id`,
`filename`, `sha256`, `unit`, `layout_digest`, `confirmed_layout`,
`summary_json`. This replaces v1's keys inside `runs.run_config_json`.

**`human_files`, `human_file_figures`, `human_file_notes`** — as v1
(`schema.py:1734`–`:1775`), for scoring. Keys match `figures`.

**On `runs`.** The copied code reads three facts from the run: the standard,
the level, and whether these are first financial statements. It also needs the
confirmed layout for each statement and the unit. Store them as columns, not
inside a JSON blob.

---

## 4. Order of copying

Each line needs the lines above it.

1. **Utilities.** `utils/paths.py`, `utils/atomic_io.py`, `db/engine.py`,
   `notes/labels.py`. Add the seven packages from section 1 to v2's
   `constraints.txt`.
2. **Templates and taxonomy.** The 70 template files, `SSMxT_2022v1.0`, the
   four JSON indexes, `statement_types.py`, `notes_types.py`,
   `tools/section_headers.py`, `tools/template_reader.py`,
   `scripts/generate_mpers_templates.py`, then the concept package from area 1.
   Create the ten catalogue tables. Done when the bootstrap fills them and v1's
   parser tests pass.
3. **The figures table and the save rules** (area 2), with `cascade.py`
   adapted. Done when a total is calculated and saved, a heading refuses a
   value, and history rows appear.
4. **The mTool read-and-fill core.** `offline_fill.py` and `column_detect.py`
   unchanged, then `template_map.py` with `apply_column_map` moved in, then
   `units.py`, `translation.py`, and `exporter.py` adapted to v2's figures.
5. **Human-file reading and comparison** (area 5). This needs steps 2 to 4.
   It is what build step 1, the scoring tool, runs on. Build step 1 therefore
   needs steps 1 to 5 of this list before any agent exists.
6. **Checks** (area 3), changed to read from lists. Needs step 3.
7. **Document tools** (area 7). Independent of steps 2 to 6. Needed by build
   step 2.
8. **Notes rendering** (area 8) and the notes half of the mTool fill. Needs
   step 1. Needed by build step 5.
9. **Prior-year import** (area 6), with the changed current-year rule. Needs
   steps 2 to 5.
10. **Reports** (area 9). Needs steps 2 and 4.

---

## 5. Risks

**Things in the plan's section 8 that are wrong or incomplete**

- **"The list of 30 recognised templates" does not recognise mTool files.**
  The 30 are v1's own generated templates (section 2.4). A workbook exported
  from mTool is identified by taxonomy names inside it and is only ever
  "candidate". Build step 7's "done when" line ("each of the 30 recognised
  templates is read and trial-filled") would test v1's own files, not real
  mTool files. A real mTool 2.2 workbook needs to be obtained from the
  enterprise machine before step 7 can be judged.
- **"Template reading, field meanings, cell lookup by meaning: parts of
  `concept_model/`" leaves out the database.** The copied code needs ten
  catalogue tables that the plan's "about 20 tables" does not include
  (section 3.1).
- **"Checks: `cross_checks/`" is not a plain copy.** Nine checks work from
  saved figures. Three still need a filled workbook, which v2 drops. All of
  them read through SQL, not from a list.
- **"Human-file comparison and prior-year import" live mostly in `eval/`, not
  `concept_model/`.** `eval/human_file.py` and `eval/human_compare.py` are the
  core. The plan does not name the `eval/` folder.
- **The scoring tool (build step 1) is not small.** It needs the template
  catalogue, a figure store and the mTool reader working first (section 4,
  steps 1 to 5). About 6,000 lines of copied code sit under it.
- **The plan's scores are not v1's scores.** v1 has Found and Same value. It
  has no combined score, no sign-only bucket and no per-cell scale bucket
  (section 2.5). Comparing "v2 scores at least as well as v1" needs the v1
  baseline rescored with v2's definitions.
- **"Page viewing and the calculator: parts of `tools/`" is right, but the
  notes renderer is not "four files".** It pulls in about 4,000 lines
  (section 2.8).
- **"Model connections ... `model_settings.py`" and "Gateway check script" and
  "Login: `auth/`"** were not in this task and were not read.

**Things that are harder than they look**

- **The fill's control flow is inside a 530-line API route** (section 2.4).
  The library pieces copy; the order of steps and their error handling must be
  rebuilt.
- **v1 overwrites typed current-year figures; v2 keeps them.** The import,
  the save rules and the fill all change (section 2.6).
- **Tests are tied to v1's schema.** Most tests for areas 1 to 6 build v1's
  full database with `db.schema.init_db` (for example
  `tests/_human_file_fixture.py:11`, `:44`–`:48`). "Copy with tests" means
  rewriting their fixtures for v2's tables. The tests for `offline_fill`,
  `column_detect`, `notes_decorate`, `calculator`, `pdf_viewer`, `docx_styles`
  and `render` need no database and can copy nearly as they are.
- **Notes stored as blocks** must still produce one HTML string per field for
  the copied steps (section 2.8).
- **Signs.** The fill passes values through unchanged. v2's figures agent must
  store each value in the sign the template's formula expects, as v1's prompts
  do (`mtool/exporter.py:30`–`:66`). This lesson belongs in the shared agent
  principles.

**Things tied to what v2 is dropping**

- **Gemini.** None of the copied files depend on Gemini. One comment in
  `word_convert.py:112` names a Gemini key in a list of secrets kept out of a
  child process. Harmless.
- **v1's 78-table schema.** This worktree's `db/schema.py` has 75 distinct
  tables at schema version 56 (`schema.py:251`). The copy set needs ten
  catalogue tables plus the run tables in section 3. Everything else it reads
  (reviewer flags, notes integrity, coverage rows, run agents) is in
  `preflight.py` and the API routes, which are rebuilt.
- **The direct-Excel path.** `cell_resolver.py`, `concept_model/exporter.py`,
  the workbook half of every check, `tools/verifier.py` and
  `tools/fill_workbook.py` belong to it. Do not copy them.
  `prior_year.py:427` still calls the workbook export; that call must be
  replaced.
- **Settings from the environment.** `table_theme.py`, `page_cache.py` and
  `word_convert.py` read environment variables (sections 2.7, 2.8). v2 keeps
  settings in the database.

---

## 6. Not checked

- **Only v1 at commit `4bb9c6bf` was read.** The main v1 checkout is one merge
  behind (`8ba30614`). The notes renderer files differ between the two.
- **No real mTool workbook was opened.** None is in the repository. How the
  resolver behaves on a genuine mTool 2.2 export was not seen.
- **Only four v1 test files were run** (168 passed). The other test files named
  in section 1 were counted, not run.
- **Speed.** Parsing all statement templates took under a second. The bootstrap
  into a database, the checks, the comparison and a full fill were not timed.
- **Whether the taxonomy folder can be trimmed** was not tried.
- **`prior_year.py` lines 419–445 and 579–760** (seeding a scratch workbook,
  the agent tool, check results) were read only at the outline level.
- **`filing_targets.py` lines 127–425 and 651–957** (target building and
  coverage) were read only at the outline level.
- **`offline_fill.fill_footnotes` (`:1345`–`:1750`)**, the slot-creation path
  for notes, was read only at the docstring level.
- **`ingest/document_preparation.py`** beyond its storage format and outline
  was not read. It is marked for rebuild.
- **`reports/repository.py` and `reports/agent.py`** were read only at the
  outline level.
- **Which CSS features PyMuPDF's HTML engine drops** beyond those the code
  works around was not tested.
- **Windows.** Nothing here was run on the enterprise machine: Word
  conversion through docx2pdf, the Windows certificate store, and any mTool
  open, Validate or Generate step.
- **`auth/`, `model_settings.py`, `utils/` beyond the path helpers, and the
  Document Agent's `proxy_check.py`** were outside this task.
