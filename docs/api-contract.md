# API contract

What the browser and the server say to each other. Both sides are built from
this file. A change here is made before the code that depends on it.

All bodies are JSON. All routes need a session cookie unless marked open.
Errors return `{"detail": "<one plain sentence>"}` with a 4xx or 5xx status.

## Ports

- The server listens on port 8100 by default (`PORT` in `.env` changes it).
- In development the browser app runs on port 5174 and passes `/api`
  requests to `http://localhost:8100`.
- In normal use the server also serves the built browser app from
  `web/dist`, so there is one address.

## Step 0

### Health and login

| Route | Body | Returns |
|---|---|---|
| `GET /api/health` (open) | | `{"status":"ok","version":"<string>","commit":"<string>"\|null,"database_copy"?:{"last_saved_at":"<iso>"\|null,"saving":<bool>,"stale":<bool>}}`. `commit` is the deployed commit (null from a checkout). `database_copy` appears on Azure only |
| `POST /api/auth/login/password` (open) | `{"email","password"}` | 200 `{"user": User}` and sets the session cookie. 401 on a wrong email or password. 429 when locked out |
| `GET /api/auth/me` | | `{"user": User}`, or 401 |
| `POST /api/auth/logout` | | 204, clears the cookie |
| `POST /api/auth/change-password` | `{"current_password","new_password"}` | 204 |

`User` is `{"email","name","is_admin","must_change_password"}`.

The route names follow v1's `auth/routes.py`.

### Users and the audit log (admin only)

Brought across from v1's `auth/routes.py`. The Settings page's Users and Audit log sections use them
(see "Go-live A1, A2 and A7" at the end of this file for the exact shapes).

| Route | Body | Returns |
|---|---|---|
| `GET /api/admin/users` | | `{"users": AdminUser[]}` |
| `POST /api/admin/users` | `{"email","name"}` | `{"user": AdminUser, "temporary_password"}`. The password is shown once |
| `POST /api/admin/users/{email}/disable` | | `{"user": AdminUser}`. Ends that person's sessions |
| `POST /api/admin/users/{email}/enable` | | `{"user": AdminUser}` |
| `POST /api/admin/users/{email}/reset-password` | | `{"user": AdminUser, "temporary_password"}` |
| `POST /api/admin/users/{email}/admin` | `{"is_admin"}` | `{"user": AdminUser}`. The last admin cannot be demoted |
| `GET /api/admin/audit` | | `{"entries": AuditEntry[]}`, newest first |

`AdminUser` is `User` plus `{"disabled","has_password","created_at"}`.
The exact field names are those the server returns; the browser types are
written from the server when the Users screen is built.

A person signed in with a temporary password can use only the
`/api/auth/*` routes until they change it.

### Runs

| Route | Returns |
|---|---|
| `GET /api/runs` | `{"runs": Run[]}`, newest first |

`Run` is `{"id","company","year","standard","level","status","updated_at","owner_name","owner_email"}`.

- "Mine" in the run list means `owner_email` equals the signed-in user's email.

- `standard` is `"MFRS"` or `"MPERS"`. `level` is `"Company"` or `"Group"`.
- `status` is one of `"reading"`, `"setup"`, `"ready"`, `"extracting"`,
  `"in_review"`, `"correcting"`, `"filed"`, `"failed"`, `"stopped"`.
  `"ready"` (step 3c) means the setup is confirmed and the run waits for
  extraction. `"reviewed"` was removed in step 3c: the owner dropped
  sign-off, and nothing had used it.

In step 0 the list is empty.

### Settings

| Route | Body | Returns |
|---|---|---|
| `GET /api/settings` | | `Settings` |
| `PUT /api/settings` (admin) | any subset of the changeable fields | `Settings` |
| `GET /api/models` | | `{"models": Model[]}` |

`Settings` is:

```json
{
  "route": "direct",
  "models": {"reading": "gpt-6-luna", "extraction": "gpt-6-luna", "review": "gpt-6-luna"},
  "code_workbench": true,
  "claude_sandbox_real_documents": false,
  "house_style": {
    "body_text": "justified",
    "table_font_pt": 10,
    "smallest_table_font_pt": 8,
    "double_underline": "thick_bottom_border",
    "bold_totals": false
  }
}
```

- `body_text` is `"justified"` or `"left"`.
- `table_font_pt` is 9, 10 or 11. `smallest_table_font_pt` is 8 or 9.
- `double_underline` is `"thick_bottom_border"` or `"single_bottom_border"`.
- A `PUT` with a value outside these is refused with a 422.
- `route` is `"direct"` or `"gateway"`. It is read-only: it follows whether
  a gateway address is set in `.env`.
- Everything else is changeable by an admin.

`Model` is `{"id","provider","family","label","available"}`.

- `provider` is `"openai"` or `"anthropic"`.
- `family` is `"luna"`, `"terra"`, `"claude"` or `"other"`.
- `available` is false when the provider's key is missing.
- The list comes from the provider when a key is present. It always
  includes `gpt-6-luna` and `gpt-6.1-terra`.

## Step 1

Figures, statements, checks and activity for one run. Every route needs a
session. The server checks that the signed-in person may open the run: runs
are shared, as in v1, so any signed-in person may open any run. A run that
does not exist returns 404 `{"detail": "There is no such run."}`.

A write the figure store refuses returns 422 with `{"detail": "<one plain
sentence>"}` and saves nothing. The refusals are listed below.

### Statements

| Route | Returns |
|---|---|
| `GET /api/runs/{run_id}/statements/{statement}?order=report` | `Statement` in report order |
| `GET /api/runs/{run_id}/statements/{statement}?order=template` | `Statement` in template order |

- `statement` is `SOFP`, `SOPL`, `SOCI`, `SOCF` or `SOCIE` (`SOCIE` also
  serves the MPERS statement of retained earnings). A statement that is
  not part of the run returns 404.
- `order` defaults to `report`.

`Statement` is:

```json
{
  "run_id": 1, "statement": "SOFP", "variant": "CuNonCu",
  "template_id": "mfrs-company-sofp-cunoncu-v1", "order": "report",
  "columns": [Column], "rows": [Row]
}
```

`Column` is `{"key", "label", "entity_scope", "period", "matrix_col"}`.

- Ordinary statements: one column per entity and period, keyed
  `"Company:CY"`, `"Company:PY"`, and on a Group run also `"Group:CY"`,
  `"Group:PY"`. `matrix_col` is null. Labels are `"This year"` and
  `"Last year"`, or `"Group, this year"` and so on for a Group run.
- The equity statement: one column per equity component, keyed by its
  template column letter (`"C"` is retained earnings), with the component
  name as `label`. `entity_scope` and `period` are null; each block of rows
  carries them instead. Report order shows only components that hold a
  figure; template order shows all.

`Row` is:

```json
{
  "kind": "line",
  "label": "Other payables and accruals",
  "field_label": "Other current non-trade payables",
  "printed_label": "Other payables and accruals",
  "concept_uuid": "…", "sheet": "SOFP-Sub-CuNonCu", "row": 434,
  "page": 7, "print_order": 31,
  "cells": {"Company:CY": Cell, "Company:PY": Cell},
  "status": null, "certainty": "sure", "reason": "", "edited": false
}
```

- `kind` is `"heading"`, `"line"` or `"total"`. A heading has no cells.
- `label` is what the grid shows first: the printed line in report order,
  the template field in template order. `field_label` is always the
  template field. `printed_label` is null when nothing was printed.
- In report order there is one row per printed line, sorted by page and
  `print_order`. A heading row is added where the printed section changes.
  A figure saved from two printed lines shows as two rows.
- In template order every template line is a row, the face sheet first,
  then its sub-sheet, including lines with no figure.
- Equity statement rows also carry `entity_scope` and `period`; each block
  starts with a heading row such as `"This year"`.
- `status` is null or one of, in this priority: `"does_not_tally"` (a
  failed check points at this line), `"differs_from_report"` (a total the
  report prints, or a total saved with no breakdown, differs by more than
  RM 1 from the sum of the lines saved under it), `"unsure"`, `"edited"`
  (a person changed it).
- `certainty` is `"unsure"` when any figure on the row is unsure, and
  `reason` is that figure's one-line reason.

`Statement` also carries `source_kind`: `"pdf"`, `"word"` or `"excel"`,
what the run started from (go-live plan C6). On a Word or Excel run every
`page` is a page of the reading copy the server laid out, not of the
printed report. On an Excel run each row on a sheet's pages also carries
`source`: `{"sheet": "SOFP", "row": 7}`, with `row` null when the line
cannot be told apart on the sheet; and each cell whose amount is found on
that row carries `source_cell`, such as `"B7"`. Both are worked out when the
statement is shown, from the figure's page, printed label and amount, so a
figure a person typed is found the same way.

`Cell` is:

```json
{
  "figure_id": 12, "concept_uuid": "…", "value": 389200, "printed": 389200,
  "stated": null, "certainty": "sure", "reason": "", "edited": false,
  "origin": "agent", "writable": true, "agent_writable": true, "lines_sum": null,
  "sign_question": false, "comparison": null
}
```

- `value` is the saved figure, or null when the line is missing. A missing
  line is never shown as zero.
- `printed` is the amount on the printed line (report order and the equity
  statement), else null. `stated` is a total as the report prints it.
- `origin` is `"agent"`, `"person"`, `"calculated"`, `"prior_workbook"`,
  `"typed_in_workbook"`, or null when there is no figure.
- `writable` is false for headings, totals and figures kept from last
  year's workbook. A total the report gives with no breakdown is
  writable, and an edit keeps it as such. `figure_id` is null when no
  figure is saved.
- `comparison` is, for a last-year figure kept from the starting workbook,
  the report's comparative as the figures agent last read it
  (`{"report_value", "page", "open"}`), else null. `open` is true while the
  reading differs from the kept figure and no person has confirmed the
  figure since (the comparatives check's rule). `sign_question` is true
  while the reading differs in sign only. A person settles either by
  confirming the figure (step 10e).
- `agent_writable` is `writable`, and also false for a figure a person typed
  into the workbook (`origin` `"typed_in_workbook"`): an agent may only
  comment on it.
- `lines_sum` is, for a total saved with no breakdown, what the lines saved
  under it add up to (null when none holds a number). It is null on every
  other cell. The total keeps its own value; the grid marks the difference.

### Figures

| Route | Body | Returns |
|---|---|---|
| `POST /api/runs/{run_id}/figures` | `{"concept_uuid","period","entity_scope","value","dimensions"?,"page"?,"printed_label"?,"reason"?}` | `{"figure": Figure}`. A person's edit of one figure. `value: null` clears it. A new figure needs `page` (step 5, "Final review fixes") |
| `POST /api/runs/{run_id}/figures/{figure_id}/move` | `{"to_concept_uuid","whole_row"?}` | `{"figures": Figure[]}`, the figures now in the target field |
| `POST /api/runs/{run_id}/figures/{figure_id}/confirm` | | `{"figure": Figure}` |
| `GET /api/runs/{run_id}/figures/{figure_id}/history` | | `{"history": HistoryEntry[]}`, oldest first |
| `POST /api/runs/{run_id}/figures/{figure_id}/restore` | `{"history_id"}` | `{"figure": Figure}` |

- An edit finds the figure by its whole key, `dimensions` included. It
  keeps the figure's printed lines. On a one-line figure the printed amount
  follows the corrected value, and a sent `page` or `printed_label`
  corrects that line while the part not sent is kept. A figure with more
  than one line keeps its lines as they are. A new figure needs `page` and
  `printed_label`. An edit marks the figure sure and edited.
- A `value` that is not an ordinary number (infinity or NaN) is refused with
  422 "The value must be an ordinary number."
- `period` is `"CY"` or `"PY"`. `entity_scope` is `"Company"` or `"Group"`.
  `dimensions` is a category for the share-capital and related-party
  notes only, as `{"<taxonomy axis>": "<member>"}`.
- A move adds the figure to the target field's figure for the same period,
  with both sets of printed lines, and clears the source. `whole_row: true`
  moves every period of that field and entity. Moving a blank figure is
  refused: "This figure is blank, so there is nothing to move."
- Confirm marks an unsure figure sure. Only a person can confirm a figure
  with an open sign-only difference with last year's workbook.
- Restore puts the figure back to how it was after that history entry:
  its value and printed lines and, on a total, the printed amount and
  whether it is added up from its lines or given with no breakdown. The
  totals are then added up again.
- Every change re-adds the totals and re-runs the checks before the route
  returns.

`Figure` is:

```json
{
  "id": 12, "concept_uuid": "…", "period": "PY", "entity_scope": "Company",
  "dimension_key": "", "value": 389200, "status": "observed",
  "children_status": null, "origin": "agent", "stated_value": null,
  "locked": false, "certainty": "sure", "reason": "",
  "sign_question": false, "person_edited": false, "revision": 1,
  "updated_by": "seed", "updated_at": "…",
  "lines": [{"printed_label": "Other payables and accruals", "page": 7,
             "amount": 389200, "print_order": 31, "coefficient": 1,
             "section": "Current liabilities"}]
}
```

- `status` is `"observed"`, `"explicit_zero"`, `"not_disclosed"` or
  `"user_override"`. `children_status` is set on totals: `"itemised"`
  (added up from its lines) or `"aggregate_only"` (the report gives the
  total with no breakdown).

`HistoryEntry` is `{"id","action","actor_kind","actor_name","changed_at","before","after"}`.
`action` is `"save"`, `"edit"`, `"move"`, `"confirm"`, `"restore"`,
`"calculate"`, `"flag"` or `"import"`. `before` is null for a new figure; `before` and
`after` hold the figure's fields and printed lines.

**Refusals.** These nine are the only hard stops (agent-lessons section 7,
for the owner to confirm; the ninth is the owner's decision). Each is the
whole `detail`:

1. A value in a heading: "`<field>` is a heading and cannot hold a value, so save the figure on a line under it."
2. A typed value on a calculated total: "`<field>` is added up from the lines under it, so save those lines, or save this total as printed or as a total with no breakdown."
3. A total with no breakdown whose saved lines add to another amount: "The lines under `<field>` already add up to `<amount>`, so correct or clear them before saving this total with no breakdown."
4. A zero that no printed amount backs (agents only): "Give the printed amount of the line that shows this zero, such as 0 or a dash, because a zero needs a printed source like any other figure." A zero whose printed lines add to zero is accepted.
5. A value that is not the sum of its printed lines (agents only). A line given with no amount: "Give the printed amount of each line given for this figure, so the value can be checked against them." Lines that add to another number: "The printed lines given add up to `<amount>` but the value given is `<amount>`, so check the sign of each line and whether a line is missing, because a value must be the sum of its printed lines and not a number found by subtraction."
6. No source: "Give the page and the line as printed for this figure, because every figure needs its source."
7. Prior year on first financial statements: "These are the company's first financial statements, so there is no prior year to save." A figure kept from last year's workbook: "This prior-year figure is kept as filed in last year's workbook, so leave a comment if the report shows a different amount."
8. A sign-only difference with last year, by an agent: "Only a person can settle a sign-only difference with last year's workbook, so leave a comment for the reviewer."
9. A figure a person typed into the workbook, by an agent (save, clear or move): "A person typed this figure into the workbook, so leave a comment for the reviewer rather than changing it."

A total saved with no breakdown is not forced to agree with lines saved
under it later: the printed-totals check reports the difference as a
warning, and the row's status is `"differs_from_report"`.

Requests that do not fit the run are also refused with 422, for example
"That field is not in this run's templates.", "This run saves figures for
the Company only." (or "This run saves figures for Group and Company." on
a Group run), "`<field>` holds text, so save it as a note rather than a
figure.", "The value must be an ordinary number.", "The amount of each
printed line must be an ordinary number." or "Keep each printed label to
300 characters or fewer, as the line is printed."

### Checks

| Route | Returns |
|---|---|
| `GET /api/runs/{run_id}/checks` | `{"checks": Check[]}` |

`Check` is:

```json
{
  "name": "sofp_balance", "title": "Total assets equal total equity and liabilities",
  "entity_scope": "Company", "status": "failed", "period": "PY",
  "expected": 10038100, "actual": 10029100, "diff": 9000, "tolerance": 1,
  "message": "For the Company, this year, Total assets and Total equity and liabilities agree at 11,272,400. For the Company, last year, Total assets is 10,038,100 and Total equity and liabilities is 10,029,100, a difference of 9,000.",
  "comparands": [{"label","sheet","value","role","statement","row","period","tolerance"}],
  "target_concept_uuid": "…", "computed_at": "…"
}
```

- `status` is `"passed"`, `"failed"`, `"warning"` (advisory),
  `"not_applicable"` (nothing to check in this run's layouts) or
  `"not_assessed"` (it could not be judged, for example no figures yet). A
  check that could not be assessed is never shown as passed.
- A Group run has two of each check: `entity_scope` `"Group"` and
  `"Company"`. Group comes first.
- `period`, `expected`, `actual` and `diff` describe the first failing
  period, else the first passing one. `target_concept_uuid` is the line
  the review list jumps to, or null.
- `message` is plain sentences, one per period. A blank side names the
  line: "Total assets is blank for the Company, this year."
- `printed_totals` (a warning, never a failure) lists each total the
  report prints that differs from its saved lines, and each total saved
  with no breakdown whose saved lines add up to another amount, with both
  amounts and the difference. Differences up to RM 1 are not listed.
- Results are recomputed whenever a figure in the run changes.

### Activity

| Route | Returns |
|---|---|
| `GET /api/runs/{run_id}/events?after_id=0&limit=100` | `{"events": Event[], "last_id", "has_more"}` |
| `GET /api/runs/{run_id}/events/{event_id}` | `{"event": EventDetail}` |

- Events come oldest first, after `after_id`. `limit` is 1 to 500, default
  100. To page forward, pass `last_id` as the next `after_id`; `has_more`
  says whether more rows are waiting. While a run works, the browser asks
  with the last `last_id` about once a second.
- `Event` is `{"id","job_id","source","kind","message","created_at","has_data"}`.
  The data payload is left out of the list. `EventDetail` adds `"data"`.

### Run list change

`GET /api/runs` is unchanged. It now reads owner names through the login
module's store.

## Step 2

Scoring a run against a workbook a person filled for the same document
(`backend-plan.md` section 4.3). Same rules as Step 1: every route needs a
session, any signed-in person may use any run, a run that does not exist
returns 404 `{"detail": "There is no such run."}`.

### The filled workbook

| Route | Body | Returns |
|---|---|---|
| `POST /api/runs/{run_id}/filled-workbook` | multipart form, one field `file` (`.xlsx` or `.xlsm`) | `{"workbook": FilledWorkbook}`. Replaces any workbook already attached |
| `GET /api/runs/{run_id}/filled-workbook` | | `{"workbook": FilledWorkbook}`, or `{"workbook": null}` |
| `DELETE /api/runs/{run_id}/filled-workbook` | | 204. 404 `{"detail": "This run has no filled workbook."}` when none is attached |

- One workbook per run. The file is kept in the run's folder and its cells
  are read when it is attached. A replacement is read in full before the
  old one is removed, so a refused upload keeps the old workbook.
- The workbook is read by meaning: the run's own template fields, found by
  their official SSM field names (an mTool workbook) or by the template's
  own field labels (a workbook in the app's template layout). A cell is
  never matched by position alone.
- Refusals, 422 unless noted: "Choose an .xlsx or .xlsm workbook.", "This
  file is empty.", "This file is over 25 MB." (413), "This file could not be
  read as an Excel workbook.", "Nothing in this workbook matches the run's
  templates, so check that it was filled for this run's statements."

`FilledWorkbook` is:

```json
{
  "filename": "Seri Maju 2025 mTool.xlsx", "sha256": "…",
  "layout": "mtool", "uploaded_by": "ana@firm.com", "uploaded_at": "…",
  "cells_read": 214, "not_assessed": 3
}
```

- `layout` is `"mtool"` (it carries SSM field names) or `"template"` (the
  app's own template layout).
- `cells_read` counts the fields the workbook holds a cell for.
  `not_assessed` counts the cells that hold something but could not be read
  or matched to a field (see `NotAssessed` below).

### The comparison

| Route | Returns |
|---|---|
| `GET /api/runs/{run_id}/comparison` | `{"comparison": Comparison}`. 404 `{"detail": "This run has no filled workbook."}` |

Worked out on every read, against the run's current figures, so an edit
changes it at once. The comparison itself is not stored. The workbook's
stored read is refreshed when the run's templates have changed since the
workbook was read (a statement's layout confirmed again).

`Comparison` is:

```json
{
  "workbook": FilledWorkbook,
  "tolerance": 1,
  "overall": Score,
  "statements": [{"statement": "SOFP", "score": Score}],
  "differences": [Difference],
  "totals": {"counts": Counts, "differences": [Difference]},
  "notes": NotesComparison,
  "not_assessed": [NotAssessed]
}
```

`Score` is:

```json
{
  "person_filled": 120, "both_filled": 114, "agree": 110,
  "completeness": 0.95, "accuracy": 0.9649, "complete_and_accurate": 0.9167,
  "counts": Counts
}
```

`Counts` is `{"agree","extra","sign_only","scale","different","missing","zero_left_blank","not_assessed"}`.

What counts:

- **Only data-entry fields are scored**: template lines a value is typed
  into. Headings never hold a value. Calculated totals are compared
  separately under `totals`, so one wrong line is not counted again in
  every total above it. Notes are compared on their own, under `notes`
  (see "Notes in the workbook" below), and never enter these figure scores.
- A cell is one field, period, entity and category (and, on the equity
  statement, the equity column).
- `person_filled`: data-entry cells the person filled with a number.
  `both_filled`: of those, the ones the run also holds. `agree`: of those,
  the ones within `tolerance` (RM 1, the checks' tolerance).
- `completeness` is `both_filled / person_filled`, `accuracy` is
  `agree / both_filled`, `complete_and_accurate` is their product
  (`agree / person_filled`). Each is null when its denominator is zero,
  never 0 or 1.
- The kinds of difference, each a count in `Counts` and a row in
  `differences`:
  - `extra`: the run holds the cell, the person left it blank.
  - `sign_only`: same amount, opposite sign.
  - `scale`: same digits at a different scale: one amount, divided by
    1,000 or 1,000,000, is within RM 1 of the other, with the same sign.
  - `different`: any other disagreement.
  - `missing`: the person filled the cell, the run left it blank.
  - `zero_left_blank`: the person typed a zero, the run left it blank.
    Listed, but left out of `person_filled` (as v1).
- A figure the run marks "not disclosed" is blank, never zero.
- First financial statements: prior-year cells are left out on both sides.
  A prior-year cell the person filled anyway is listed in `not_assessed`.
- `not_assessed` in `Counts` is the number of `NotAssessed` rows for that
  statement. They never count as agreeing and never count towards a score.

`totals` compares each calculated total: on each side, the amount typed in
place of the formula if one was typed (the run's total saved with no
breakdown or typed into a workbook, or a number the person typed over the
template's formula),
otherwise what the template calculates from that side's own lines. Its
`Counts` uses the same kinds; `not_assessed` is 0 there. A total the
person's cell could not be read for, or whose lines include such a cell, is
not compared: it is a `NotAssessed` row of its statement instead.

On the share-capital and related-party sheets, the Total column (the field
with no category, `dimension_key` `""`) is compared under `totals` whenever
either side filled a category beside it, so one wrong class is not counted
twice. On each side it is the amount typed in the Total column, else the
sum of that side's categories (the run uses its categories' sum when it has
any). Where neither side filled a category, the Total column is the only
figure and is scored as a data-entry cell. A Total beside a category that
could not be read is a `NotAssessed` row (`line_not_read`).

#### Notes in the workbook

`notes` is null when the workbook holds no notes. Otherwise `NotesComparison` is:

```json
{
  "score": 0.8684,
  "in_workbook": 38, "same_field": 33, "different_field": 3, "missing": 2,
  "differences": [NoteDifference],
  "only_in_run": [{"number": "9", "title": "Inventories", "run_fields": [{"field_id": "…", "label": "…"}]}]
}
```

`NoteDifference` is:

```json
{
  "kind": "different_field", "number": "24", "title": "Related party disclosures",
  "run_fields": [{"field_id": "…", "label": "Disclosure of other related party transactions"}],
  "workbook_fields": [{"field_id": "…", "label": "Disclosure of related party"}],
  "note_id": 12, "pages": [31, 32]
}
```

- **"Same field" only. Wording is not compared.** The workbook's note fields
  are read when it is attached: on an mTool workbook, the field's row is
  found by its SSM name and its text is read from mTool's note store (or
  from the text-block cell itself, when text was typed there); on the app's
  template layout, the text is column B of the row whose label is the
  field's label. Only the text's short lines are kept, to find a note's
  printed heading.
- The workbook is turned into an answer key and scored by the notes scoring
  that answer keys use (`app/scoring/notes.py`). A note of the run is
  counted in a workbook field when the run placed it in a field the
  workbook filled, or when a line of that field's text is exactly the note's
  printed number and title ("5. Trade and other receivables", with or
  without "Note"). A title with no number never names a note this way.
- `same_field`: every part of the note sits in a field the workbook filled,
  and in each field where the workbook names it. `different_field`: the run
  placed the note, but a part sits in a field the workbook left empty, or
  not in the field where the workbook names it. `missing`: the run did not
  place it. `in_workbook` is their sum and `score` is
  `same_field / in_workbook`.
- A filled workbook field that no note of the run sits in or is named in is
  a `missing` row with `number` `""`, titled by the field's label: the
  workbook has a note there and the run has nothing to match it.
- `note_id` and `pages` are the run's note when it stored one (`note_id`
  null otherwise), so the screen can open it.
- `only_in_run`: notes the run placed that match nothing in the workbook.
  Listed, never counted.
- Worked out on every read against the run's current notes. A workbook
  attached before notes were read is read again on its next comparison.

`Difference` carries what the review screen needs to open the figure:

```json
{
  "kind": "sign_only", "statement": "SOFP", "concept_uuid": "…",
  "field_label": "Trade payables", "sheet": "SOFP-Sub-CuNonCu", "row": 404,
  "period": "CY", "entity_scope": "Company", "dimension_key": "",
  "matrix_col": null, "run_value": -1628400, "person_value": 1628400,
  "figure_id": 31, "workbook_cell": "SOFP-Sub-CuNonCu!B404"
}
```

- `figure_id` is null when the run holds no figure for the cell.
- `workbook_cell` is where the person's value was read, or null when the
  workbook has no cell for the field.

`NotAssessed` is:

```json
{
  "statement": "SOFP", "reason": "not_a_number", "sentence": "SOFP-Sub-CuNonCu!B139 holds text, not a number.",
  "workbook_cell": "SOFP-Sub-CuNonCu!B139", "concept_uuid": "…", "period": "CY",
  "entity_scope": "Company", "dimension_key": "", "figure_id": null
}
```

`reason` is one of:

| `reason` | Meaning |
|---|---|
| `not_a_number` | A field's cell holds text that is not a number |
| `formula_not_worked_out` | A field's cell holds a formula the reader cannot work out |
| `no_field` | A cell holds a number but no field of the run's templates sits there (a heading, an unknown row, another column) |
| `label_mismatch` | Template layout: the row's label is not the field's label, so the cell is not trusted |
| `repeats_a_total` | Template layout: a number typed on a face line that only repeats a total kept on another sheet |
| `ambiguous` | mTool layout: more than one cell carries the field's SSM name for this period and entity |
| `columns_not_marked` | mTool layout: the sheet carries the field, but does not mark which column is which year or, on a Group run, which is the Group and which the Company. Columns are never assigned by position |
| `no_cell` | The run holds a figure, but the workbook has no cell for that field |
| `line_not_read` | A calculated total that was not compared, because a line under it could not be read |
| `prior_year_first_statements` | A prior-year cell on first financial statements |

`statement` is null when the cell sits outside every statement of the run.

## Step 3

Reading a document (`backend-plan.md` section 5, stages 1 and 2). Step 3a
is the upload and the page pictures; the Reader (3b) and the setup screen
(3c) add to this section. Same rules as Step 1: every route needs a
session, any signed-in person may open any run, a run that does not exist
returns 404 `{"detail": "There is no such run."}`.

### A new run from an upload

| Route | Body | Returns |
|---|---|---|
| `POST /api/runs` | multipart form, one field `file`: a PDF, a Word document (`.docx`) or an Excel workbook (`.xlsx`) | `{"run": Run, "document": Document}` |

- The run starts with status `"reading"`. Its company, year, standard and
  level are not known yet, so `company`, `year`, `standard` and `level`
  are null until the Reader suggests them and the person confirms setup.
  A reading run has no statements: its statement routes return 404 and
  its checks list is empty.
- The signed-in person is the run's owner.
- A run starts from one file (owner, 25 November 2026). Its kind is
  decided from the file's content. Nothing is converted with Word or
  LibreOffice: for a Word or Excel file the server lays out a reading copy
  itself (Word through `mammoth` and PyMuPDF's Story, Excel through
  `openpyxl`), and the run reads that copy's pages as it would a PDF's. Its
  page numbers are its own. The uploaded file is kept beside it, and the
  file's own headings, paragraphs and table rows (an Excel sheet's cells
  with their saved values) are stored in `file_lines`, for the agents' file
  tools (`app/agents/file_tools.py`).
- Excel: a formula is read by the result Excel saved with it. One saved
  without a result reads as empty, and an event tells the person: "The
  sheet <name> has <n> formula(s) saved without a result, so they read as
  empty. Open the workbook in Excel, save it and upload it again." Hidden
  sheets are left out until brought in (below).
- The PDF, or the reading copy, is kept in the run's folder. Each page is
  looked at once, here: its size, its rotation and whether it has a real
  text layer.
- Several files at once: the new-run page sends one `POST /api/runs` per
  file, at most two at a time. Each becomes its own run.
- Refusals name the file, 422 unless noted: "<file> is in the old Word
  format. Save it as .docx and upload that." (`.doc`), "<file> is in the old
  Excel format. Save it as .xlsx and upload that." (`.xls`), "<file> is
  protected by a password. Remove the password and upload it again.",
  "<file> is not a .docx file. Save it as .docx and upload that." (a macro
  or template Word file; the same for `.xlsx`), "<file> is not a PDF, a Word
  document (.docx) or an Excel workbook (.xlsx).", "<file> could not be read
  as a Word file." (or "as an Excel workbook"), "<file> holds no text,
  tables or pictures to read." (a file of pictures alone is read from its
  pages, as a scanned PDF is; a picture in a format the reading copy cannot
  draw, such as EMF, shows as a sentence saying so on its page, and the run
  gets an upload notice), "<file> holds only pictures saved in a format the
  reading copy cannot draw. Paste the pictures in again as PNG or JPEG and
  upload it again.", "<file> keeps more than 500,000 rows and cells,
  counting the empty ones Excel saved, so upload the financial statements
  on their own." (counted across every sheet the workbook links, before it
  is loaded), "<file> has no sheet with anything on it to read.",
  "<file> makes more than 500 pages, so upload the financial statements on
  their own.", "<file> unpacks to more than 300 MB, so upload the financial
  statements on their own." (checked before the file is parsed), "This file is empty.", "<file> is <n> MB. The largest file a
  run can take is 100 MB." (413),
  "This file could not be read as a PDF." (a PDF header, but PyMuPDF cannot
  open it or it has no pages), "This PDF has more than 500 pages, so
  upload the financial statements on their own.", "Page <n> is larger than
  A0 paper, so upload a PDF with ordinary page sizes." (checked before any
  page is drawn).

`Run` gains one field, `filename`: the uploaded document's file name, or
null for a run made without one (the demo run). The run list returns it
too, so a reading run can be told apart before its company is known.

### The document

| Route | Returns |
|---|---|
| `GET /api/runs/{run_id}/document` | `{"document": Document}`. 404 `{"detail": "This run has no document."}` |

`Document` is:

```json
{
  "filename": "Doc 1.pdf", "kind": "pdf", "sha256": "…", "size_bytes": 2512344,
  "page_count": 36, "scanned_pages": 36,
  "uploaded_by": "ana@firm.com", "uploaded_at": "…",
  "pages": [Page]
}
```

`Page` is `{"page": 1, "width": 595.0, "height": 842.0, "rotation": 0, "has_text_layer": false}`.

- `page` is the PDF page number, from 1.
- `width` and `height` are in points (1/72 inch), as the page shows after
  its rotation. `rotation` is the rotation stored in the PDF: 0, 90, 180
  or 270.
- `has_text_layer` is decided page by page. A page whose words cover only a
  little of it while one picture covers most of it is a scan, even when a
  stamp or a certification line adds a few words of real text. A scan
  that carries a full searchable text layer counts as text.
- `scanned_pages` counts the pages with no text layer.
- `kind` is `"pdf"`, `"word"` or `"excel"`. `filename`, `sha256` and
  `size_bytes` are the uploaded file's; `page_count` and `pages` are the
  reading copy's for a Word or Excel run.
- An Excel run's `Document` also has `sheets`, in the workbook's order:
  `{"name", "hidden", "used", "first_page", "last_page", "rows", "pictures",
  "pictures_not_drawn", "empty_formulas", "notice"}`. `used` says the sheet
  is laid out in the reading copy, on `first_page` to `last_page`;
  `pictures` counts every picture placed on it, `pictures_not_drawn` those
  saved in a format the reading copy cannot draw (EMF, WMF), which show
  there as a sentence saying so; `notice` is the sentence about formulas
  saved without a result and pictures not drawn, or null.

### An Excel run's sheets

| Route | Body | Returns |
|---|---|---|
| `GET /api/runs/{run_id}/sheets/{name}` | | `{"sheet": {"name", "position", "count", "columns", "first_page", "last_page", "pictures", "rows": [{"row", "cells": {"B": "1,284,300"}}]}}`: a used sheet's filled cells as shown, and how many pictures sit on it (they are drawn only on its reading-copy pages). 404 "This run has no sheet called <name>." |
| `POST /api/runs/{run_id}/sheets/bring-in` | `{"sheet"}` | `{"run": Run, "document": Document}`. A hidden sheet is laid out after the pages already read, the run goes back to `reading`, only the new pages are transcribed and the Reader maps the whole workbook again, then the run waits at setup |

- Bring-in refusals, 409: "A sheet can be brought in only while the run
  waits at setup.", "The workbook has no sheet called <name>.", "The sheet
  <name> is already in use.", "The sheet <name> has nothing on it.", "This
  run did not start from an Excel workbook.", "The workbook changed while
  this sheet was laid out, so try again." The workbook is laid out again
  outside the database's write lock; only the final write takes it.
- At setup a statement's sheet is its `pages`: each sheet sits on pages of
  its own, so choosing a sheet sets the statement's pages to that sheet's.
  A spare sheet given to the notes joins the notes list as one note with no
  number, titled with the sheet's name, on the sheet's pages.

### Page pictures

| Route | Returns |
|---|---|
| `GET /api/runs/{run_id}/pages/{page}/image` | the page as a PNG picture |
| `GET /api/runs/{run_id}/pages/{page}/image?clip=x0,y0,x1,y1` | one region of the page, as a PNG |

- A scanned page is drawn at the scan's own resolution (a 150 DPI scan at
  150 DPI), never above it, and never above 200 DPI. Any other page is
  drawn at 200 DPI.
- `clip` is four page fractions from 0 to 1, left, top, right, bottom,
  with left below right and top below bottom. A region keeps the page's
  pixel density; it only covers less of the page.
- No picture is bigger than 40 million pixels: a page or region that would
  be is drawn at a lower resolution instead.
- 404 `{"detail": "This run has no document."}`, 404 `{"detail": "This
  document has no page <n>."}`, 422 `{"detail": "Give the region as four
  page fractions from 0 to 1: left, top, right, bottom."}`

### Reading (step 3b)

Reading starts by itself after an upload. It has two parts, run as one job
of the run's `read` stage: every page is transcribed once (the page's
structured text, kept for every later agent), then the Reader agent writes
the document map. Pages already transcribed are never transcribed again: a
retry reads only the pages still missing. On success the run moves to
`"setup"`. On failure the `read` stage is `"failed"` with one plain
sentence, the run's status is `"failed"`, and finished pages are kept.

Progress is the `read` stage plus the run's events (`GET
/api/runs/{run_id}/events`, Step 1). Reading writes events such as
"Reading 38 pages.", "Read page 21 of 38.", "Page 2 is blank.", "Page 7
could not be read: <reason>", the Reader's own steps and tools, then one
event per statement found ("Financial position on page 13.",
"Comprehensive income is not printed.") and "The document map is saved."

| Route | Body | Returns |
|---|---|---|
| `GET /api/runs/{run_id}/read` | | `{"read": ReadProgress}` |
| `POST /api/runs/{run_id}/read/retry` | | 202 `{"read": ReadProgress}`. 409 `{"detail": "Reading has not failed, so there is nothing to try again."}` |
| `GET /api/runs/{run_id}/map` | | `{"map": DocumentMap}`. 404 `{"detail": "The document has not been mapped yet."}` |
| `GET /api/runs/{run_id}/setup` | | `{"setup": SuggestedSetup}`. 404 as for the map |

- A retry reuses the same `read` stage row and starts a new job for it.
  Pages that failed last time count as `waiting` again, since they are
  read again.
- All three `GET` routes return 404 `{"detail": "This run has no document."}`
  for a run made without an upload.

`ReadProgress` is:

```json
{
  "status": "working", "started_at": "…", "finished_at": null, "error": null,
  "pages": {"total": 38, "read": 21, "blank": 1, "failed": 0, "waiting": 16},
  "map_saved": false
}
```

- `status` is the stage's: `"waiting"`, `"working"`, `"done"` or `"failed"`.
  `error` is the plain sentence of a failed stage, else null.

`DocumentMap` is:

```json
{
  "saved_at": "…",
  "company": Finding, "year_end": Finding, "standard": Finding,
  "level": Finding, "unit": Finding,
  "statements": [StatementFinding],
  "notes": [Note],
  "other_sections": [Section],
  "note_gaps": [{"note": "7", "reason": "The document numbers its notes 1 to 6, then 8."}],
  "open_points": ["Note 12 is cited on page 13 but is not in the notes list; find it or say why it is absent."],
  "pages": [MapPage]
}
```

`Finding` is `{"value", "pages", "reason", "unsure"}`:

| Field | `value` |
|---|---|
| `company` | the company's name as printed |
| `year_end` | the financial year end, `"YYYY-MM-DD"` |
| `standard` | `"MFRS"`, `"MPERS"` or `"unknown"` (the basis-of-preparation note names neither, or both) |
| `level` | `"Company"`, or `"Group"` when Group and Company columns are printed |
| `unit` | `"RM"` or `"RM'000"`, from the statements' column headings. Figures are never rescaled |

- `pages` are the PDF pages the finding was read from (PDF page numbers,
  never printed folios). `reason` is one sentence. `unsure` is true when
  the Reader could not settle it from the page; `reason` then says why.
- `value` is null when the document does not show it (for example a name
  that cannot be read on a scan).

`StatementFinding` is:

```json
{
  "statement": "SOFP", "found": true, "pages": [13], "title": "Statement of financial position",
  "layout": "CuNonCu", "reason": "Assets and liabilities are split into current and non-current sections.",
  "unsure": false
}
```

- There are always five, in the order `SOFP`, `SOPL`, `SOCI`, `SOCF`, `SOCIE`.
- `found` false means the statement is not printed. `pages` is then empty and
  `layout` is null.
- `layout` is one of the statement's layouts: `SOFP` `"CuNonCu"` or
  `"OrderOfLiquidity"`; `SOPL` `"Function"` or `"Nature"`; `SOCI`
  `"BeforeTax"` or `"NetOfTax"`; `SOCF` `"Indirect"` or `"Direct"`; `SOCIE`
  `"Default"`, or `"SoRE"` (the statement of retained earnings, MPERS only).
- Profit or loss and comprehensive income printed on one page both point at
  that page.
- `unsure` true: the page does not show enough to decide the layout; the
  Reader chose the likelier one and `reason` says what is missing.

`Note` is:

```json
{
  "number": "4", "title": "Property, plant and equipment", "first_page": 22, "last_page": 23,
  "sub_notes": [{"number": "4.1", "title": "Right-of-use assets", "page": 23}]
}
```

- `first_page` and `last_page` are the PDF pages the note sits on, from its
  heading to its last line. Step 6 checks that every note is accounted for
  against them.
- `number` is as printed, or `""` when it cannot be read on a scan.
- A heading repeated with "continued" is part of the same note, not a new one.

`note_gaps` are numbers missing from the notes list that the Reader has
explained. `open_points` are what the code found to check in the notes list
and the unit when the map was last saved, and the Reader left unanswered:
a missing number, a note cited on a statement but not listed, a note
heading on the pages beyond the end of the list, a number listed twice, or
a unit backed by one page only. Neither stops the setup.

`Section` is `{"kind", "title", "first_page", "last_page"}`. `kind` is
`"directors_report"`, `"statement_by_directors"`, `"statutory_declaration"`
or `"auditors_report"`.

`MapPage` is:

```json
{"page": 16, "folio": "14", "rotation": 90, "kind": "notes", "title": "Property, plant and equipment",
 "status": "read", "reason": null}
```

- `folio` is the page number as printed, or null when none is printed.
- `rotation` is the turn, clockwise, that makes the page upright, beyond the
  rotation stored in the PDF: 0, 90, 180 or 270. Agents see the page turned.
  The model does not give the angle: it names the edge the top of the
  letters points to (`text_top`), and code turns that into `rotation`. A
  turned page is looked at once more, turned, and the turn corrected when it
  is still not upright (`turn_corrected_from` keeps the first answer).
- `kind` is `"cover"`, `"contents"`, `"directors_report"`,
  `"statement_by_directors"`, `"statutory_declaration"`, `"auditors_report"`,
  `"statement"`, `"notes"`, `"other"` or `"blank"`.
- `status` is `"read"`, `"blank"` (no model call is made), `"failed"`, with
  `reason` the plain sentence, or `"waiting"` (not read yet). A page that is
  not read has `kind` null.

`SuggestedSetup` is what the setup screen (step 3c) starts from:

```json
{
  "company": Finding, "year_end": Finding, "year": 2021, "standard": Finding,
  "level": Finding, "unit": Finding,
  "statements": [{"statement": "SOCI", "found": false, "pages": [], "layout": "NotPrepared",
                  "layouts": {"MFRS": [{"value": "BeforeTax", "label": "Before tax"},
                                       {"value": "NetOfTax", "label": "Net of tax"},
                                       {"value": "NotPrepared", "label": "Not printed"}],
                              "MPERS": [...]},
                  "reason": "No statement of comprehensive income is printed.", "unsure": false}]
}
```

- `year` is the year of `year_end`, or null.
- A comprehensive income statement that is not printed has layout
  `"NotPrepared"`. Any other statement that is not printed keeps a null
  layout.
- `layouts` lists, for each standard, the layouts a person may choose for
  the statement, each with the label the setup screen shows. The browser
  shows exactly these; the server's statement catalogue
  (`app/catalog/statements.VARIANTS`) is the only list. Retained earnings
  (`SoRE`) appears only under MPERS.

### Confirming the setup (step 3c)

| Route | Body | Returns |
|---|---|---|
| `POST /api/runs/{run_id}/setup` | `ConfirmedSetup` | `{"run": Run, "company": {"id", "name", "existing"}}` |

`ConfirmedSetup` is:

```json
{
  "company": "Kemuncak Logistik Sdn. Bhd.", "year_end": "2024-12-31",
  "standard": "MFRS", "level": "Company", "unit": "RM",
  "statements": [{"statement": "SOFP", "layout": "CuNonCu", "included": true, "pages": [13]}],
  "notes_included": true,
  "notes": [{"number": "4", "title": "Revenue", "first_page": 23, "last_page": 23}]
}
```

- `statements` holds all five statements once each. `layout` is one of
  the statement's layouts for the chosen standard (`SuggestedSetup`), and
  `"NotPrepared"` for a comprehensive income statement that is not
  printed. A not-printed statement is not included. `SoRE` is MPERS only.
- `pages` are the statement's PDF pages as the person confirmed them (the
  Reader's pages, or others chosen with "Other page"): up to 10 pages of
  the document. An included statement needs at least one. They are stored
  with the statement's layout.
- `unit` is `"RM"` or `"RM'000"`. Figures are never rescaled.
- `notes` is the edited notes list, in order. `number` may be `""` for a
  note whose number cannot be read; every other number appears once.
  `first_page` and `last_page` are PDF pages of the document, first not
  after last.
- The company is matched to an existing company whose name is the same
  apart from case, spacing and the punctuation `.` `,` `(` `)`; otherwise a
  new company is made. `existing` says which happened, and `name` is the
  stored name (an existing company keeps its own spelling).
- On success the run moves to `"ready"`, the `setup` stage is `"done"`,
  the confirmed values are saved (company, year from `year_end`, standard,
  level, unit, each statement's layout and whether it is included, whether
  notes are included, and the notes list), the checks start as "not
  assessed", and an event "Setup confirmed." is written. Extraction (step
  4) starts from one place, `app/runs/extraction.py::start_extraction`;
  see "Step 4" for what it does.
- Refusals, 422 unless noted, one sentence each: "Reading is not finished,
  so the setup cannot be confirmed yet." (409, a run still reading),
  "This run's setup is already confirmed." (409), "Reading failed, so try
  again before confirming the setup." (409), "Enter the company's name.",
  "The company's name is too long.", "Enter the year end as a date.",
  "Choose MFRS or MPERS.", "Choose Company or Group.", "Choose whether
  amounts are in RM or RM thousands.", "Give each of the five statements
  once.", "The <layout> layout of <statement> does not exist for <standard>
  filings, so choose another layout.", "<Statement> is marked not printed,
  so switch it off or choose a layout.", "Switch on at least one
  statement.", "Give the page <statement> is printed on, or switch it
  off.", "The pages of <statement> must be within the document's <N>
  pages.", "Give the pages of <statement> as up to 10 page numbers.",
  "Each note needs a title.", "Keep each note title to 200 characters or
  fewer.", "Note <n> is listed twice.",
  "Note <n>'s pages must be within the document's <N> pages, first page
  first.", "The notes list holds more than 500 notes."

`GET /api/runs/{run_id}/pages/{page}/image` now draws the page upright:
it turns the page by the map's `rotation` for that page (`MapPage`),
beyond the rotation stored in the PDF. A page not yet read is drawn as
stored. A `clip` is then given on the upright page.

`Run.company` is null until setup is confirmed; the run list then shows
`filename`.

### Deleting a run (the setup screen's Replace)

| Route | Returns |
|---|---|
| `DELETE /api/runs/{run_id}` | 204, no body |

- Only a run waiting at setup (`"setup"`) or one whose reading failed
  (`"failed"`) can be deleted; otherwise 409 `{"detail": "Only a run
  waiting at setup, or one whose reading failed, can be deleted."}`. A run
  with a job still queued or working: 409 `{"detail": "This run still has
  work in progress, so it cannot be deleted yet."}`.
- Anyone who may open the run may delete it (the open-run check).
- Its rows (document, pages, stages, jobs, events, map, model calls, setup)
  and its folders (the uploaded PDF, page records, transcripts) are
  removed. Folders come from the run's number alone; links are not followed.
- Replace on the setup page (ready, or reading failed; never while reading)
  uploads the new PDF with `POST /api/runs`, then deletes the old run, then
  opens the new run's setup page.

### Traces (step 3c)

| Route | Returns |
|---|---|
| `GET /api/runs/{run_id}/traces` | one zip of everything recorded for the run |
| `GET /api/runs/{run_id}/traces?include_pdf=1` | the same, with the uploaded PDF (and any attached filled workbook) |

- Any signed-in person who may open the run may download it (the open-run
  check, `backend-plan.md` section 9).
- The zip is named `run-<id>-traces.zip` and holds:
  `manifest.json` (what is inside, when it was made, and what is not
  recorded yet), `run.json` (the run, its company, setup, statements,
  notes list, stages and jobs), `events.json` (every event with its data),
  `model_calls.json` and `model_calls.csv`, `pages.json` (each page's
  facts and transcription, or its read error), `document.json`,
  `document_map.json` (with its open points), `figures.json` (figures,
  their printed lines and history), `checks.json`, `server-log.txt` (the
  server-log lines for the run, with their tracebacks), `transcripts/`
  (every agent transcript), `records/` (the run folder's own records, such
  as the reading records: raw model answers and corrections), and, only
  with `include_pdf=1`, `uploaded/`.
- Comments and rounds are in `comments.json` and `rounds.json` (step 5a).
- Every text in the zip is masked: the exact value of each secret in the
  environment (keys, the gateway address, the session secret) and anything
  shaped like a key or an authorisation header becomes `[masked]`. Only the
  uploaded files go in as they are.
- Nothing from the database or the request becomes a file path: folders
  come from the run's number, every file is checked to sit inside them,
  and symbolic links are skipped. The zip is built in a temporary file and
  streamed, then removed.
- There is no button for it yet. The run screen's "Download traces"
  arrives with step 5.

### Records on the Settings page (step 3c)

| Route | Returns |
|---|---|
| `GET /api/settings/records/logs` (admin) | `server-logs.zip`: the server log files of the last 30 days |
| `GET /api/settings/records/usage` (admin) | `usage.csv`: model calls, tokens and cost by day, run and model |

- The server writes its log to `logs/server-YYYY-MM-DD.log` in the output
  folder, one file a day, UTF-8, kept 30 days, as well as to the console.
  A line that concerns a run carries `run=<id>`; other lines carry
  `run=-`. Document text, keys and passwords are never logged, and every
  line is masked as the traces are. A successful poll for reading news
  (`GET .../read` and `GET .../events`) is not written to the file; a
  failed one is. A model call's stored `error` is masked the same way.
- `usage.csv` columns: `day`, `run_id`, `run`, `model`, `calls`,
  `failed_calls`, `input_tokens`, `cached_tokens`, `output_tokens`,
  `cost_usd`. `run` is the company, else the file name. Calls with no run
  have an empty `run_id`. `cost_usd` is the estimate of the priced calls.
- A person who is not an admin gets 403 `{"detail": "Only an admin can do
  this."}`.

### Login limits on the Settings page (step 3c)

`Settings` gains `login`, changeable by an admin:

```json
"login": {"idle_timeout_minutes": 60, "max_attempts": 5, "lockout_minutes": 15}
```

- `idle_timeout_minutes`: 5 to 1440. A session idle longer is signed out.
- `max_attempts`: 3 to 20 wrong passwords before the email is locked out
  from that address.
- `lockout_minutes`: 1 to 1440.
- A `PUT` may send any subset of the three. A value outside its range, or
  not a whole number, is refused with a 422 sentence such as "Sign out
  after idle must be a whole number of minutes from 5 to 1440."
- These were `AUTH_IDLE_TIMEOUT_S`, `AUTH_LOGIN_MAX_ATTEMPTS` and
  `AUTH_LOGIN_LOCKOUT_S` in `.env`. Those names are no longer read.

## Step 4

No new routes. The browser sees extraction through what it already reads:
the run's `status`, its stages and its Activity events.

### Extraction after setup

- Confirming the setup queues the `extract` job in the same transaction, with
  an `extract` stage (`"waiting"`). Every included statement is extracted
  (step 7), in the order SOFP, SOPL, SOCI, SOCIE, SOCF, by one agent run per
  entity that fills all of its statements; on a Group run the Group's run
  comes first, then the Company's. `working_on` names the first statement
  of the run in progress. A setup with no statement is not queued; an event says "Nothing is
  extracted: no statement is part of this run."
- `Run.status`: `"ready"` while the job waits, `"extracting"` while the
  figures agent works, `"in_review"` when the stage is done, `"failed"`
  when it fails. The run list shows these with its existing words
  ("Ready", "Extracting", "In review", "Failed").
- The stage is `"done"` when every entity's agent saved figures, also when
  one stopped at its step or time limit or did not cover a statement (an
  event then says that statement is partly filled). A failed agent does not
  stop the next entity's. The stage is `"failed"`, with `error` one plain
  sentence per failed agent naming the statements it left unfinished:
  "The <statements> could not be filled: no figure was saved. <reason>"
  (with " (Group figures)" after the statements on a Group run). Every
  figure saved is kept. One attempt: a failure waits for a person. A
  statement is finished when the agent's accepted finish covers it (its
  `finished` event names it); a retry, a restart or a scope answer fills
  only the statements not finished, and a setup change drops the marks of
  the statements whose figures it cleared.
- A run whose extraction failed cannot be deleted: `DELETE /api/runs/{id}`
  answers 409 "Only a run waiting at setup, or one whose reading failed, can
  be deleted." (Changed in step 5a: it can now be deleted.)
- Figures are written by the agent through the figure store (actor kind
  `"agent"`, name `"figures"`), so every write has a history row and the
  checks re-run, as for a person's edit. `GET .../statements/SOFP` shows
  them as they arrive.

### Events (source `extraction` or `figures`)

| kind | message, for example | data |
|---|---|---|
| `queued` | "Extraction is queued: the statement of financial position and statement of profit or loss." ("... for the Group and the Company columns." on a Group run) | none |
| `statement` | "Working on the statement of profit or loss." ("... (Group figures)." on a Group run) | `{"statement", "statements", "entity"}` |
| `workbench` | "The code workbench is on." or the reason it is off | `{"on"}` |
| `started`, `step`, `tool` | the shared agent loop's rows | as in step 3 |
| `code` | "Ran a code step in the sandbox." | `{"code_chars", "language"}`; the code itself is kept in the transcript only |
| `saved` | "Saved 12 figure(s), 1 refused." | `{"saved": ["FP-s28 CY", ...], "points"}` |
| `cleared` | "Cleared 2 figure(s)." | none |
| `checked` | "Checks: 1 need action, 2 passed." | `{"action", "passed", "blank_required"}` |
| `coverage` | "Coverage: 10 printed line(s) written, 8 skipped, 0 still open." | `{"written", "skipped", "open"}` |
| `finished` or `notice` | "The statement of financial position is filled, with 1 point(s) left open." | statement, statements, entity, status, steps, seconds, unresolved count, code steps, calls, tokens, `cost_usd` |
| `notice` | "The statement of cash flows could not be filled: <reason>" or "The statement of cash flows is partly filled. <reason>" | `{"statements", "entity"}` |
| `done` | "Extraction is finished. The run is ready for review." | the run's calls, tokens and `cost_usd` |
| `failed` | "Extraction stopped: <sentence>" | the run's calls, tokens and `cost_usd` |

Event data holds field ids, counts, tokens and cost, never document text.
The agent's own words (its finish summary and open points) and its coverage
report are kept in `runs/run-<id>/extraction-<statements>.json` (the statements
joined by `+`, `-Group` added for the Group's run, with that run's own usage)
and the transcript,
both in the traces zip. Each model call is a `model_calls` row with source
`figures`, tokens, cost, duration and any error.

## Step 5a

The review loop on the server (decision record 3, `backend-plan.md` step 5):
comments, correction rounds worked by the Reviewer, the server's count of
what a round changed, Accept and Undo, agent comments, the "Needs you" list
and a retry of a failed extraction. Same rules as Step 1: every route needs a
session, any signed-in person may open any run, a run that does not exist
returns 404 `{"detail": "There is no such run."}`. A refusal is `{"detail":
"<one plain sentence>"}`: 404 for something that does not exist, 409 for
something the run's state does not allow now, 422 for a request that is
wrong in itself.

### Comments

| Route | Body | Returns |
|---|---|---|
| `GET /api/runs/{run_id}/comments?status=<status>` | | `{"comments": Comment[]}`, oldest first. `status` is optional and may be given more than once |
| `POST /api/runs/{run_id}/comments` | `NewComment` | 201 `{"comment": Comment}` |
| `DELETE /api/runs/{run_id}/comments/{comment_id}` | | 204 |
| `POST /api/runs/{run_id}/comments/{comment_id}/reply` | `{"text"}` | `{"comment": Comment}`, open again |
| `POST /api/runs/{run_id}/comments/{comment_id}/accept` | | `{"comment": Comment}` |
| `POST /api/runs/{run_id}/comments/{comment_id}/undo` | | `{"comments": Comment[], "figures": Figure[]}` |
| `POST /api/runs/{run_id}/comments/{comment_id}/done` | | `{"comment": Comment}`, for an agent comment |
| `POST /api/runs/{run_id}/comments/accept-all` | | `{"comments": Comment[]}`, the ones accepted |

`NewComment` is:

```json
{"target": Target, "text": "Page 7 prints 398,200 for last year.", "scope": "figure"}
```

`Target` is one of:

```json
{"kind": "figure", "statement": "SOFP", "concept_uuid": "…", "period": "PY", "entity_scope": "Company", "dimension_key": ""}
{"kind": "figure", "figure_id": 31}
{"kind": "line", "statement": "SOFP", "concept_uuid": "…", "entity_scope": "Company"}
{"kind": "statement", "statement": "SOFP"}
```

- `figure` is one value. `figure_id` may stand in for the key; the server
  fills the key from it. A figure comment may point at a line with no figure
  yet (a missing line).
- `line` is every period of one template field, for one entity.
- `statement` is the whole statement.
- `note` is kept for step 6: "Comments on notes arrive with the notes, in a
  later step."
- `entity_scope` defaults to `"Company"`, `dimension_key` to `""`.
- `scope` is `"figure"` (the default), `"run"` (fix the same thing wherever
  it occurs) or `"company"` (also propose a line of company guidance). Only
  a person's comment on a figure or a line may carry `"run"` or `"company"`.

`Comment` is:

```json
{
  "id": 4, "run_id": 1, "author_kind": "person", "author_name": "ana@firm.com",
  "target": {"kind": "figure", "statement": "SOFP", "concept_uuid": "…", "period": "PY",
             "entity_scope": "Company", "dimension_key": "", "field_label": "Other payables",
             "figure_id": 31},
  "text": "Page 7 prints 398,200 for last year.", "scope": "figure",
  "status": "answered", "outcome": "changed", "answer": "Used 398,200 as page 7 prints.",
  "proposed_guidance": null, "round_id": 2,
  "thread": [{"kind": "answer", "round_id": 1, "outcome": "question", "answer": "Which year?", "at": "…"},
             {"kind": "reply", "author_name": "ana@firm.com", "text": "Last year.", "at": "…"}],
  "created_at": "…", "updated_at": "…"
}
```

- `target.field_label` is the template field, null on a statement
  comment. `target.figure_id` is the figure saved there now, or null.
- `status` for a person's comment: `"open"` (not sent) → `"sent"` (in a
  round) → `"answered"` → `"accepted"` or `"undone"`. A reply makes it
  `"open"` again, for the next round. An agent's comment is `"open"` until a
  person marks it `"done"`.
- `outcome` is `"changed"`, `"not_changed"` or `"question"`, with `answer`
  the agent's one sentence; both are null until answered and again after a
  reply. The earlier answers and the replies are kept in `thread`, oldest
  first.
- `proposed_guidance` is a line of company guidance the Reviewer proposes
  for a `"company"`-scoped comment it changed, or null. It is stored only;
  adding it to the company's guidance arrives with step 5b.
- `round_id` is the round that last carried the comment, or null.

Refusals: "Write what the comment should say." (422), "Keep a comment to
2,000 characters or fewer." (422), "A comment points at a figure, a line or
a statement." (422), "Comments on notes arrive with the notes, in a later
step." (422), "That statement is not part of this run." (422), "That field
is not in this statement's template." (422), "The period is CY (this year)
or PY (last year)." (422), "This run has no prior year." (422), "This run
saves figures for the Company only." (422), "There is no such figure in
this run." (404), "A comment applies to the figure, the run or the
company." (422), "Only a comment on a figure or a line can apply to the run
or the company." (422), "Comments can be added once extraction has
finished." (409), "There is no such comment in this run." (404), "Only an
open comment can be removed." (409), "An agent's comment is marked done,
not removed." (409), "This comment is being worked on, so reply when the
round ends." (409), "Only an answered comment can be replied to." (409; an
accepted or undone comment can be replied to as well),
"Reply to an agent's comment by adding a comment of your own." (409), "Only
an answered comment can be accepted." (409), "Only an answered comment can
be undone." (409), "Nothing changed for this comment, so there is nothing
to undo." (409), "A correction round is running, so undo when it ends."
(409), "<field> was changed outside this round after the round first wrote it, so restore it from its
history instead." (409), "Only an agent's comment is marked done." (409).

**Undo** puts back, exactly, every figure the round changed for the
comment: each to its state just before the round (value, printed lines,
certainty, reason and, on a total, its printed amount and how it is added
up). A figure the round added is cleared. It goes through the figure
store's restore path, so each figure gets a history row (`"restore"`, by the
person) and the totals and checks are worked out again. When a figure was
also changed for another comment of the same round, that comment is undone
with it; the response lists every comment undone. Changes the round made
for no comment ("other") are not undone by a comment's Undo.

**Accept all** accepts the answered comments of the latest round whose
outcome is `"changed"` or `"not_changed"`. A `"question"` waits for a reply.

### Correction rounds

| Route | Body | Returns |
|---|---|---|
| `POST /api/runs/{run_id}/rounds` | `{"client_id"?}` | 202 `{"round": Round}` |
| `GET /api/runs/{run_id}/rounds` | | `{"rounds": Round[]}`, oldest first |
| `GET /api/runs/{run_id}/rounds/{round_id}` | | `{"round": Round, "report": RoundReport}` |
| `POST /api/runs/{run_id}/rounds/{round_id}/stop` | | `{"round": Round}` |

- Sending takes every open comment a person wrote and sends them as one
  round, in one step: the round, its comments and its job are saved
  together or not at all. The run moves to `"correcting"` and back to
  `"in_review"` when the round ends, however it ends.
- `client_id` is optional, up to 100 characters, made by the browser for
  one press of "Send". The same `client_id` again returns the round already
  made instead of a second one, so a retried request never sends twice.
- Refusals: "A correction round is already running." (409), "Extraction is
  still running, so send the comments when it finishes." (409), "Comments
  can be sent once extraction has finished." (409), "There are no open
  comments to send." (422), "There is no such round in this run." (404).
- Stop asks the Reviewer to stop before its next step. A round still
  waiting is stopped at once. Stopping a round that has ended: 409 "This
  round has already ended."
- A round always ends `"done"`, `"failed"` or `"stopped"`. A failure, a
  stop, the step or time limit, or a server restart while it works (start-up
  marks it `"failed"`, never retried) keeps every answer and change made so
  far; comments not yet answered go back to `"open"`.

`Round` is:

```json
{
  "id": 2, "run_id": 1, "number": 2, "status": "done", "sent_by": "ana@firm.com",
  "sent_at": "…", "started_at": "…", "finished_at": "…",
  "summary": "Moved the director's balance to related parties and used page 7's payables.",
  "error": null, "stop_requested": false, "comment_ids": [4, 5]
}
```

- `status` is `"sent"` (waiting), `"working"`, `"done"`, `"failed"` or
  `"stopped"`. `summary` is the Reviewer's one sentence, null until it
  finishes. `error` is the plain sentence of a round that did not finish.

`RoundReport` is the server's own count of what the round changed, worked
out from figure history (every write in a round carries the round's id and
the comments it served). It is the same text the Reviewer is shown after each
save, clear or move:

```json
{
  "round_id": 2,
  "comments": [{"comment_id": 4, "outcome": "changed", "answer": "…", "changed": true, "verified": true,
                "figures": [Change]}],
  "other": [Change],
  "totals_recalculated": [Change],
  "counts": {"comments": 2, "changed": 1, "other": 1, "totals_recalculated": 3},
  "checks": {"before": {"failed": 1, "passed": 3}, "now": {"failed": 0, "passed": 4},
             "newly_failing": [], "assessed": true}
}
```

`Change` is:

```json
{"figure_id": 31, "statement": "SOFP", "concept_uuid": "…", "field_label": "Other payables",
 "period": "PY", "entity_scope": "Company", "dimension_key": "",
 "was": 389200, "is_now": 398200, "changed": true, "differences": ["value 389,200 → 398,200"], "served": [4]}
```

- `comments[].figures`: a figure comment's own figure, a line comment's
  figures (every period), and any other figure written for the comment.
  `was` is the value before the round (null when blank or new), `is_now`
  the value now. `changed` is true when the value, the printed amount or the
  printed lines differ from before the round.
- `comments[].changed` is true when anything changed for that comment.
  `verified` is true only when the outcome is `"changed"` and the server sees
  a change. `"not_changed"` and `"question"` are never verified.
- `other`: figures the round changed that are no comment's own target.
  `served` names the comments a write said it was for (empty when none).
- `totals_recalculated`: totals the template added up again as a result.
- `checks`: counts by status when the round was sent and now;
  `newly_failing` lists the checks (name, entity, title) that passed before
  the round and do not pass now; `assessed` is false when no check could be
  assessed, which is never shown as passed.

### The Reviewer

Runs as the job `review_round`, through the shared agent loop, with the
model in Settings `models.review`. It reads the saved figures, the pages and
the round's comments; it needs no earlier agent's memory. Its writes go
through the figure store as actor kind `"agent"`, name `"reviewer"`, so
every hard stop applies and every write has a history row. It may finish
only when every comment of the round has an answer, the checks ran after its
last change, and no check that passed before the round fails now (unless it
states, with the reason, that the report makes it unfixable).

### Events (source `review`)

| kind | message, for example | data |
|---|---|---|
| `queued` | "Correction round 2 is queued: 2 comment(s)." | `{"round_id", "comments"}` |
| `started`, `step`, `tool` | the shared agent loop's rows | as in step 3 |
| `saved`, `cleared`, `moved` | "Saved 1 figure(s)." | field ids and periods, never document text |
| `answered` | "Answered comment 4: changed." | `{"comment_id", "outcome"}` |
| `comment` | "Left a comment on Other payables, last year." | `{"comment_id"}` |
| `checked` | "Checks: 0 need action, 4 passed." | `{"action", "passed", "assessed", "newly_failing"}` |
| `notice` | "The finish was sent back: answer comment 5." | none |
| `done` | "Correction round 2 is finished: 1 of 2 comment(s) changed." | counts, tokens and `cost_usd` |
| `failed` or `stopped` | "Correction round 2 stopped: <sentence>" | tokens and `cost_usd` |

Each model call is a `model_calls` row with source `review`. The figures
agent writes `comment` events too (source `figures`) when it leaves a comment.

### Agent comments

The figures agent and the Reviewer have a `leave_comment` tool for
something a person should look at that the agent did not change (the
`raise_flag` of `backend-plan.md` 4.6). It saves a `Comment` with
`author_kind` `"agent"`, `scope` `"figure"` and status `"open"`, on a figure,
a line or the statement.

### Needs you

| Route | Returns |
|---|---|
| `GET /api/runs/{run_id}/needs-you` | `{"items": NeedsYouItem[], "passed": 214}` |
| `POST /api/runs/{run_id}/needs-you/alike/accept` | the same, after the alike lines are confirmed |

Items come in this order: failed checks, Unsure figures, open agent
comments, (notes to check and unplaced notes, from step 6), then one alike
group. `passed` is the number of figures holding a value that no item names.

`NeedsYouItem` is:

```json
{"kind": "failed_check", "title": "Total assets equal total equity and liabilities",
 "message": "For the Company, last year, …", "check": "sofp_balance",
 "statement": "SOFP", "concept_uuid": "…", "period": "PY", "entity_scope": "Company", "figure_id": 12}
{"kind": "unsure", "title": "Other receivables, last year", "message": "<the agent's reason>",
 "statement": "SOFP", "concept_uuid": "…", "period": "PY", "entity_scope": "Company", "figure_id": 18}
{"kind": "agent_comment", "title": "Other payables, last year", "message": "<the comment>", "comment_id": 9,
 "statement": "SOFP", "concept_uuid": "…", "period": "PY", "entity_scope": "Company", "figure_id": 31}
{"kind": "alike", "title": "12 lines filed under a different name",
 "message": "For example “Cash and bank balances” filed as Cash and cash equivalents.", "count": 12,
 "lines": [{"figure_id": 7, "printed_label": "Cash and bank balances", "field_label": "Cash and cash equivalents",
            "statement": "SOFP", "concept_uuid": "…", "period": "CY", "entity_scope": "Company"}]}
```

- A failed check is one whose status is `"failed"`. Its figure is the one
  at the check's `target_concept_uuid` for its period, or null.
- An Unsure figure is one whose certainty is unsure.
- The alike group lists figures saved from a printed line whose label is
  not the template field's, apart from case, spacing and punctuation, and
  that no person has confirmed since their last change. It is left out when
  there are none. Accepting it confirms each of them (a `"confirm"` history
  row each), so they leave the list.
- `"note_to_check"` and `"unplaced_note"` are kept for step 6.

### Retrying a failed extraction

| Route | Returns |
|---|---|
| `POST /api/runs/{run_id}/extract/retry` | 202 `{"run": Run}`. 409 `{"detail": "Extraction has not failed, so there is nothing to try again."}` |

- It reuses the `extract` stage row and queues a new job for it. The run
  goes back to `"ready"`, then `"extracting"`. Nothing is cleared: figures
  already saved, a person's edits among them, are kept, and the agent starts
  from them.

### Run list change

`Run` gains `failed_stage`: `"read"` or `"extract"` when the run's status is
`"failed"`, else null, so the run list can tell a failed reading from a
failed extraction.

`DELETE /api/runs/{run_id}` now also deletes a run whose extraction failed.
The refusal becomes "Only a run waiting at setup, or one whose reading or
extraction failed, can be deleted." Its comments and rounds go with it.

### Server log change

A successful poll for a round (`GET .../rounds/{round_id}`) is left out of the
server log file, like the reading and events polls; a failed one is written.
Each round writes a line when it starts and when it ends, and a full
traceback when it fails on an unexpected error.

### Traces change

The traces zip gains `comments.json` (every comment with its thread) and
`rounds.json` (every round with the comments it carried and its report).
Each round's record (`review-round-<n>.json`: the Reviewer's finish, its
answers and the report) is under `records/`. The manifest's "not recorded
yet" line about comments is gone.

## Step 5b

Scope questions and guidance on the server (decision record 3, items 1 to 3
and 6; `backend-plan.md` section 9). Same rules as Step 5a: every route needs
a session, a run that does not exist returns 404 `{"detail": "There is no
such run."}`, and a refusal is `{"detail": "<one plain sentence>"}`: 404 for
something that does not exist, 409 for something the state does not allow
now, 422 for a request that is wrong in itself.

### Run and stage status change

- `Run.status` gains `"needs_answer"`: the figures agent stopped to ask a
  scope question and waits for a person. The run list shows it as "Needs
  your answer". It moves back to `"ready"` when the question is answered,
  then `"extracting"` as before.
- The `extract` stage gains the status `"asking"` while the question is
  open. It always reaches `"done"` or `"failed"` after the answer.
- While a run needs an answer, sending comments is refused: 409 "Extraction
  is waiting for your answer to its question, so send the comments after it
  finishes." Adding a comment is refused as before ("Comments can be added
  once extraction has finished.").

### Scope questions during extraction

The figures agent asks only about scope: the standard, the level, the year
end, the unit, or a statement's layout (or whether it is printed). It asks
only when the document contradicts the confirmed setup. Everything else it
settles itself and shows as an Unsure figure, an agent comment or a flag.

| Route | Body | Returns |
|---|---|---|
| `GET /api/runs/{run_id}/question` | | `{"question": ScopeQuestion}` for the open question, or `{"question": null}` |
| `GET /api/runs/{run_id}/questions` | | `{"questions": ScopeQuestion[]}`, every question of the run, oldest first |
| `POST /api/runs/{run_id}/question/answer` | `{"choice": 0}` or `{"text": "…"}`, optional `"question_id"` | `{"question": ScopeQuestion, "run": Run}` |

`ScopeQuestion` is:

```json
{
  "id": 3, "run_id": 1, "stage": "extract", "asked_by": "figures",
  "field": "standard", "statement": null,
  "question": "This looks like an MPERS filing. Which standard applies?",
  "evidence": [{"text": "“…in accordance with the Malaysian Private Entities Reporting Standard…”", "page": 3},
               {"text": "“…prepared in accordance with Malaysian Financial Reporting Standards…”", "page": 13}],
  "choices": [{"label": "MPERS", "value": "MPERS", "effect": "Restarts extraction with the MPERS templates", "suggested": true},
              {"label": "MFRS, as set up", "value": "MFRS", "effect": "Carries on", "suggested": false}],
  "setup_value": "MFRS", "status": "open", "asked_at": "…",
  "answer": null
}
```

- `field` is `"standard"`, `"level"`, `"year_end"`, `"unit"` or `"layout"`.
  `statement` is the statement of a `"layout"` question, else null.
- `value` of a choice is a setup value: `"MFRS"` or `"MPERS"`; `"Company"` or
  `"Group"`; `"RM"` or `"RM'000"`; a date `"YYYY-MM-DD"`; or a layout of the
  statement (as in `SuggestedSetup.layouts`), or `"NotPrepared"` for a
  statement not printed (any statement; the answer switches it off).
- There are two to four choices, exactly one `suggested`, and one of them is
  always the confirmed setup (`setup_value`), so the person can keep it.
- `evidence` lines each carry their PDF page, for a page link.
- `status` is `"open"` or `"answered"`. `answer` is null while open, then
  `{"choice", "text", "value", "setup_changed", "cleared", "by", "at"}`:
  the index of the choice taken (or null), the person's own words (or
  null), the setup value chosen (or null), whether the setup changed, how
  many of the agent's figures were cleared, who answered and when.
- One open question per run at a time. A question still open when the
  server restarts stays open: the stage keeps waiting and no model is called.

When the agent asks (its `ask_scope` tool), in one step: the question is
saved, the `extract` stage becomes `"asking"` and the run `"needs_answer"`.
The agent stops before its next step. Every figure saved so far is kept.
The tool refuses, with one sentence the agent can act on, a field that is
not scope ("Ask only about the scope: …"), a layout question with no
statement, a question longer than one sentence of 300 characters, evidence
without a page or outside the document, fewer than two or more than four
choices, not exactly one suggested choice, a value the field cannot take,
two choices with the same value, choices that leave out the confirmed
setup, a second open question, and a question about a field the person
already answered in this run.

**Answering:**

- With the choice that is the confirmed setup, or with the person's own
  words: the setup is kept and extraction is queued again. Its first
  message gives the agent the question and the answer as a fact from the
  person, and lists the figures already saved; nothing is cleared.
- With another choice: the setup changes through the same check as
  confirming the setup (Step 3c), and the figures the agent saved where
  the change refiles them are cleared: every statement for the standard,
  the level, the year end or the unit; one statement for its layout. A
  figure a person typed or edited, or one imported from last year's
  workbook, is never cleared. Each cleared figure gets a `"clear"` history
  row naming the person. The totals and checks are worked out again for
  the new templates, and extraction is queued again. A statement switched
  on by the answer takes the evidence pages as its pages.
- If no statement this version extracts is left (the balance sheet was
  switched off), the stage is `"done"` and the run `"in_review"`.
- A job already queued for the run (one handed back after a restart) takes
  the answer instead of a second job being queued.
- Refusals: "Choose one of the choices or write your own answer, not
  both." (422, also for neither), "There is no such choice." (422), "Keep
  the answer to 1,000 characters or fewer." (422), "This run has no open
  question to answer." (409), "This question is already answered." (409,
  when `question_id` names an answered one), "There is no such question in
  this run." (404), "The <layout> layout of the <statement> does not exist
  for <standard> filings, so start a new run with the right setup." (409),
  "This answer cannot be applied to the setup: <the setup check's
  sentence>" (409). A refused answer changes nothing.

### Setup question cards

`SuggestedSetup` (`GET /api/runs/{run_id}/setup`) gains `questions`, one
card for each unsure suggestion of the standard, the level, the unit or a
statement's layout:

```json
"questions": [
  {"field": "unit", "statement": null, "question": "Are the amounts in RM or RM thousands?",
   "reason": "No unit is printed above the statements.", "pages": [7],
   "choices": [{"value": "RM", "label": "RM", "effect": "Figures are filed as printed, in RM", "suggested": true},
               {"value": "RM'000", "label": "RM thousands", "effect": "Figures are filed as printed, in RM thousands", "suggested": false}]},
  {"field": "layout", "statement": "SOPL", "question": "Which layout does the statement of profit or loss use?",
   "reason": "…", "pages": [8],
   "choices": [{"value": "Function", "label": "By function", "layout": "Function", "included": true, "effect": "…", "suggested": true},
               {"value": "Nature", "label": "By nature", "layout": "Nature", "included": true, "effect": "…", "suggested": false},
               {"value": null, "label": "Not printed", "layout": "Function", "included": false, "effect": "…", "suggested": false}]}
]
```

- `reason` and `pages` are the Reader's, as in `Finding`; the browser shows
  the reason with a page link for each page.
- A layout card offers exactly what `POST .../setup` accepts for that
  statement under the suggested standard (MFRS when the standard is
  unknown). Each layout choice says what it sets: `layout` and `included`.
  Comprehensive income's "Not printed" is its layout `"NotPrepared"`
  (`included` false). Any other statement's "Not printed" has `value`
  null and sets `included` false, keeping its `layout`. The suggested choice is the
  Reader's value; when the Reader's standard is `"unknown"`, no standard
  choice is suggested. The year end and the company's name are typed, so
  they have no card.
- Choosing a card's answer only fills the setup form; the setup is still
  confirmed with `POST /api/runs/{run_id}/setup`.

### Events (source `extraction` or `figures`)

| kind | message, for example | data |
|---|---|---|
| `asked` (figures) | "Stopped to ask about the standard." | `{"question_id", "field", "statement"}` |
| `stopped` (figures) | "Stopped to ask a person about the scope." | the shared agent loop's counts |
| `answered` | "ana@firm.com answered the question about the standard with MPERS." | `{"question_id", "choice", "own_text", "setup_changed", "by"}` |
| `setup_changed` | "Setup changed: the standard is now MPERS; 12 figure(s) the agent saved were cleared." | `{"question_id", "field", "statement", "from", "to", "cleared", "by"}` |

### Guidance

Guidance is the conventions people keep for the agents: the firm's, for
every company, and each company's own. It is a list of lines, saved as whole
versions. It is added only by a person.

| Route | Body | Returns |
|---|---|---|
| `GET /api/companies/{company_id}/guidance` | | `{"company": {"id", "name"}, "guidance": Guidance, "versions": Version[]}` |
| `GET /api/companies/{company_id}/guidance/versions/{n}` | | `{"guidance": Guidance}` |
| `PUT /api/companies/{company_id}/guidance` | `{"based_on": 2, "lines": ["…"]}` | as the `GET` |
| `POST /api/companies/{company_id}/guidance/restore` | `{"version": 1, "based_on": 2}` | as the `GET` |
| `GET /api/guidance/firm` | | `{"guidance": Guidance, "versions": Version[]}` |
| `GET /api/guidance/firm/versions/{n}` | | `{"guidance": Guidance}` |
| `PUT /api/guidance/firm` (admin) | `{"based_on", "lines"}` | as the `GET` |
| `POST /api/guidance/firm/restore` (admin) | `{"version", "based_on"}` | as the `GET` |
| `GET /api/runs/{run_id}/guidance` | | `{"firm": Guidance, "company": Guidance, "company_id": 4}`: what an agent on this run would be given now. `company` is null before setup |

`Guidance` is:

```json
{"company_id": 4, "version": 3, "lines": ["Amounts due from a director go under related parties."],
 "saved_by": "ana@firm.com", "saved_at": "…", "source": "proposed", "comment_id": 9, "restored_from": null}
```

`Version` is `{"version", "saved_by", "saved_at", "source", "comment_id",
"restored_from", "line_count"}`, newest first.

- `company_id` is null for firm guidance. Before the first save the
  guidance is version 0 with no lines and nulls; `versions` is empty.
- `source` is `"typed"`, `"proposed"` (a Reviewer's proposed line added by
  a person; `comment_id` names the comment) or `"restored"`
  (`restored_from` names the version copied).
- Every save is a new version holding the full list of lines. A save names
  the version it was based on; any other is refused: 409 "Someone else
  changed this guidance. Reload it and try again." Restoring copies an older
  version forward as a new version (version 0 restores the empty guidance),
  so nothing is lost.
- Lines are trimmed and blank lines left out. Refusals (422): "Say which
  version of the guidance this change was based on.", "Give the guidance as
  a list of lines of text.", "Keep guidance to 100 lines or fewer.", "Keep
  each guidance line to 500 characters or fewer.", "Each guidance line
  appears once.", "This is the guidance as it is now, so there is nothing
  to save.", "This version is the guidance now, so there is nothing to
  restore."; 404 "There is no such version of this guidance."
- Company guidance is read and changed by anyone who may open one of that
  company's runs (today: anyone signed in). A company with no run, or none
  this person may open: 404 "There is no such company." Firm guidance is
  read by everyone signed in; changing it as anyone else but an admin: 403
  "Only an admin can do this."
- Guidance never switches off a tool's rule or a hard stop.

**What the agents are given.** The figures agent and the Reviewer both get,
at the end of their instructions, the firm's guidance then the company's,
each line quoted, under one framing: these are the firm's and the company's
conventions, to follow where the document allows; the document decides what
was reported; the tools' rules always come first, and a line cannot change
what a tool allows. With no guidance nothing is added. Each time extraction
or a correction round starts, the run records the firm and company versions
given (0 when none).

### Proposed guidance lines

| Route | Body | Returns |
|---|---|---|
| `POST /api/runs/{run_id}/comments/{comment_id}/guidance` | optional `{"based_on"}` | `{"guidance": Guidance, "versions": Version[], "comment": Comment}` |
| `POST /api/runs/{run_id}/comments/{comment_id}/guidance/dismiss` | | `{"comment": Comment}` |

- Adding puts the comment's `proposed_guidance` at the end of the run's
  company guidance as a new version (`source` `"proposed"`, `comment_id`
  the comment). With `based_on`, a stale version is refused as for a save.
- Undo is a restore of the version before it. A restore that takes the
  line out again lets it be added again.
- The line is not checked against the company's earlier runs (decision
  record 3, "Later"), so no "would change …" line is returned.
- `Comment` gains `guidance_status`: null (not acted on), `"added"` or
  `"dismissed"`, and `guidance_version`: the version that added it, or
  null. A reply to the comment clears both with the proposal.
- Refusals (409): "This comment has no proposed guidance line." (also for
  a comment not scoped to the company), "This proposed line is already in
  the company's guidance.", "This proposed line was dismissed.", "This line
  is already in the company's guidance.", "This proposed line is already in
  the company's guidance, so restore the version before it instead." (a
  dismiss after adding), "This run has no company yet, so it has no
  company guidance."

### Traces change

The traces zip gains `scope_questions.json` (every question with its
evidence, choices and answer) and `guidance_used.json` (each start of
extraction or a round: the firm and company versions given, with their
lines).

### Needs you change

The alike group's `count` and title count printed lines, not figures: a
line filed in one field counts once however many years it holds ("22 lines
filed under a different name" for 44 figures). `lines` still lists every
figure.

### Step 5c server additions

Added for the run screen. Same rules as above.

**One run**

| Route | Returns |
|---|---|
| `GET /api/runs/{run_id}` | `{"run": RunDetail}` |

`RunDetail` is every field of the run-list `Run`, plus:

```json
{
  "statements": [{"statement": "SOFP", "name": "statement of financial position", "layout": "CuNonCu",
                  "layout_label": "Current and non-current", "pages": [2]}],
  "failure": {"stage": "extract", "sentence": "No figure was saved. …"},
  "working_on": "SOFP",
  "open_question_id": 3,
  "stages": [{"name": "read", "status": "done", "started_at": "…", "finished_at": "…", "error": null}]
}
```

- `statements` are the confirmed statements that are switched on, in the
  order SOFP, SOPL, SOCI, SOCF, SOCIE; empty before setup.
- `failure` is null unless the run's status is `"failed"`; then it names
  the failed stage (`"read"` or `"extract"`) and its plain sentence.
- `working_on` is the statement the `extract` stage is on while it works,
  else null. `open_question_id` is the open scope question's id, or null.
- `stages` lists the run's stages, oldest first.
- Access is the open-run check.

**Pages on events.** Every event (`GET .../events`, `.../events/{id}`)
gains `pages`: the PDF pages its step concerns, in order, once each, or
`[]`. `message` stays one plain sentence. Pages are given for: an agent's
page tools (`read_pages`, `view_pages`, `zoom_page`; the pages it named, on
the `looked` row: see "Review fixes" below),
a statement's start (event `statement` from source `extraction`, "Working
on the statement of financial position.", with the statement's confirmed
pages), saved figures (the pages of the printed lines saved), checks (the
printed pages of the figures that checks needing action point at), the
Reader's findings (a statement's pages; the notes list's first and last
page) and scope questions (`asked`, `answered`, `setup_changed`: the
evidence pages). The activity feed also gains `question_id` on every row:
the scope question an `asked`, `answered` or `setup_changed` event is
about, else null. It also gains `agent` on every row: the name of the
agent that wrote it when several run side by side (the notes agent's
sessions, such as "Placing the notes" or "Formatting the notes, 2 of 3"),
else null. The Activity tab shows one block per agent when a run has more
than one.

**Stopping extraction**

| Route | Returns |
|---|---|
| `POST /api/runs/{run_id}/extract/stop` | 202 `{"run": Run}`. 409 `{"detail": "Extraction is not running, so there is nothing to stop."}` |

- Allowed while the run is `"ready"` or `"extracting"` with its `extract`
  stage waiting or working.
- A job still waiting to start is stopped at once. A working agent stops
  before its next step (the shared loop's stop check), so the response may
  still show `"extracting"`; poll the run.
- Stopping keeps every figure saved. The stage ends `"stopped"` with
  `error` "Stopped on request; the figures saved so far are kept." The run
  goes to `"in_review"` when it holds figures, else to `"stopped"`. An
  event says "Extraction stopped on request. The figures saved so far are
  kept." (or "… before it started.").
- `POST .../extract/retry` now also works from a stopped stage (run
  `"stopped"`, or `"in_review"` with the `extract` stage `"stopped"`). It
  queues extraction again and the agent starts from the figures saved. Its
  refusal sentence is unchanged.

**Page pictures of a run with no document.** `GET
/api/runs/{run_id}/pages/{page}/image` for a run made without an upload
(the demo run) answers 404 `{"detail": "This run has no document."}`, as
for the document route. This was already so; it is now tested.

**Guidance at setup.** `GET /api/runs/{run_id}/guidance` gains
`company_from_suggestion`. Before setup is confirmed the run has no
company; if the Reader's suggested company name matches an existing
company (the same match as confirming setup: case, spacing and `. , ( )`
ignored), `company_id` and `company` are that company's and
`company_from_suggestion` is true. Otherwise they are null and it is
false. No company is made before setup is confirmed.

**Where a printed line sits on its page: not built.** The transcription
holds a page's text and tables but no positions (only stamps and
signatures carry a region), and most documents are scans with no text
layer, so there is nothing cheap to clip by. It needs the transcription
to return a region per block, a change to the Reader's output; left for
the owner to decide.

### Review fixes (step 5 review panel)

Changes from the step 5 review. They change some sentences above; this
list is the authority where they differ.

**Moves are all or nothing.** A Reviewer move that is refused for one year
after another year was written saves nothing of that move, history rows
included. The tool says "<field>: not moved, and nothing of this move was
saved. <reason>"; the count of moves and figures changed stays right.

**Undo.**

- Undo refuses, with 409 "This would also reverse comment <n>'s change,
  which is already accepted, so restore the figure from its history
  instead.", when another comment of the round shares a changed figure and
  is no longer answered (accepted, open again after a reply, in a round, or
  done). It never reverses a change under a comment that still claims it.
- "Changed since" is checked from the round's first write on the figure,
  so a person's edit made while the round worked is never wiped. The
  sentence becomes "<field> was changed outside this round after the round
  first wrote it, so restore it from its history instead." (409).
- A figure the round added is put back as blank and stays the agent's: it
  is not marked as a person's edit, and its origin is kept.

**Proposed guidance of an undone change.** Adding a proposed line needs the
comment to be answered or accepted; otherwise 409 "This change was undone,
so its guidance line cannot be added."

**Scope questions.** For any field but `layout`, the statement is ignored,
so a question answered about the standard, the level, the year end or the
unit is never asked again.

**A round always ends.** A failure while a round's result is recorded ends
the round `"failed"` ("The round stopped on an unexpected error; the
answers and changes so far are kept.") and the run goes back to
`"in_review"`.

**Recording the guidance given.** If the run cannot record which guidance
versions an agent was given, the server log keeps the full error and the
agent still starts with its guidance.

**What a round changed.** `Change.changed` is true for any difference a
person sees, not only the value: the value, how it reads (blank, not
disclosed, zero), the printed amount, the certainty, the reason and the
printed lines. `Change` gains `differences`, the plain list of what moved,
for example `["certainty sure → unsure", "reason changed"]`. The
Reviewer's report text adds them after the value: "Trade payables CY was
250, is now 250 (certainty sure → unsure, reason changed)".

**Newly failing checks.** `RoundReport.checks.newly_failing` and the
Reviewer's own list are the checks on the statements it works on that
passed when the round was sent and now fail or warn. A check that can no
longer be assessed, or no longer applies, is not newly failing; `assessed`
false still says no check could be assessed, which is never shown as
passed. The Reviewer treats a newly failing check as a lead to trace:
either its change was wrong (fix or undo it) or the change exposed another
wrong figure (fix that). The finish field `not_fixable` is renamed
`explained`: `[{"check", "reason"}]`, a check it traced and leaves
failing, with why.

**Activity in the agents' own words** (decision record 3, item 8).

- The page tools of every agent (`read_pages`, `view_pages`, `zoom_page`,
  `search_pages`), the figures agent's `save_figures` and `clear_figures`,
  and the Reviewer's `save_figures`, `clear_figures`, `move_figures` and
  `answer_comment` take an optional `note`: one sentence, in the agent's
  own words, on what it is doing and why. Both agents are told to give it
  on each step. A note is kept to 300 characters on one line.
- Each page tool call writes a visible row of kind `looked`, with `pages`
  (the pages it named) and the note as `message`, or "Looked at pages 2,
  3." / "Searched the pages." when there is no note. The `tool` row of the
  same call no longer carries pages.
- A `saved`, `cleared`, `moved` or `answered` row takes the note as its
  `message` when one is given (for `answered`, the first answer of the
  call).
- Kinds for the browser to show: every kind except `step` and `tool`,
  which are the shared loop's own bookkeeping. `GET
  /api/runs/{run_id}/events?hide_internal=true` leaves those two kinds out;
  `last_id` and `has_more` page as before.

**Accept all.** `GET /api/runs/{run_id}/rounds` also returns
`"accept_all": {"round_id": 2, "comment_ids": [4, 5]}`: the latest round
and exactly the comments `POST .../comments/accept-all` would accept now
(answered `"changed"` or `"not_changed"`). `round_id` is null before any
round.

### Final review fixes

Changes from the final review. Where they differ from the sentences above,
these hold.

- **Alike lines.** An Unsure figure, or one with an open sign question, is
  never in the alike group: it stays its own Needs-you item. Accepting the
  alike group records a person's `"confirm"` on each line and changes
  nothing else: certainty and sign questions stay as they were.
- **Group figures.** A comment on a Group figure or line is accepted (step
  7). The Reviewer's packet names the entity of every comment ("Group
  figures" or "Company figures"), and each write changes the columns of the
  comments it answers; a round may hold comments on both. The Reviewer works
  on the statements its comments are on.
- **A round at its limit.** A round that reaches its step or time limit
  after every comment is answered, with the checks run after its last
  change, ends `"done"`. Its `summary` is the limit sentence, for example
  "Stopped at the step limit of 40 before finishing." Otherwise it ends
  `"failed"` as before.
- **The "changed" refusal** of `answer_comment` now says how to fix it:
  save the correction "naming this comment in comment_ids on the write
  that corrects it".
- **Undo.**
  - It needs the run to be in review: otherwise 409 "Undo once the run is
    back in review." (for example while extraction runs again after Try
    again).
  - Its response gains `guidance_line_kept`: one
    `{"comment_id", "company_id", "version"}` for each undone comment
    whose proposed line was added to company guidance. The line stays; the
    person can take it out by restoring the version before it. The list is
    empty otherwise.
- **A scope answer that switches the balance sheet off.** An extraction job
  still queued (one handed back after a restart) has its statements worked
  out again from the new setup. When none is left, that job is finished,
  the `extract` stage is `"done"` and the run goes to `"in_review"`, with
  the event "Nothing is extracted: the balance sheet is not part of this
  run." An extraction job that starts with statements no longer in the
  setup does the same instead of failing.
- **A person's figure in a blank field.** `POST /api/runs/{run_id}/figures`
  for a field with no figure and no printed line yet needs `page`: the PDF
  page the amount is printed on. `printed_label` is optional and defaults
  to the field's label. Refusals (422): "Give the page this amount is
  printed on." and "The page must be within the document's <N> pages."
  A field that takes no figure (a heading, for example) keeps its own
  refusal. An existing figure keeps its lines, as before.

### Field names in what a person reads

The agents work with field ids (`FP-s141`, `CE-6-B`), but a person never
reads one. Everything an agent writes for a person is stored with each id
the template outline knows turned into the field's name: agent comments,
answers and proposed guidance lines, a round's `summary`, a figure's
`reason`, a scope question's question, evidence text and choice labels and
effects, and every activity `message`. Nothing is refused for using an id.

- The name is the field's label (a total shown on the face uses its face
  label). An equity-statement column adds its column: "Equity at beginning
  of period (Retained earnings)". When that name repeats among the
  statement's non-heading fields, its nearest heading goes in front:
  "Current trade payables › Trade payables".
- A word that only looks like an id ("MFRS-9") is left as it is.
- When an activity `message` was rewritten, the agent's own wording is
  kept in the event's `data.raw`.
- "Left a comment on …" names the field and year the same way.

## Step 6b

The note store (`docs/step-6-plan.md` 6b, decision record 4). A note is a
list of blocks (`app/notes/blocks.py`) copied by code from the Reader's
page content, with the look beside the words. Agents and people change a
note through the same store functions. Same rules as Step 5a: every route
needs a session, any signed-in person may open any run, a run that does not
exist returns 404 `{"detail": "There is no such run."}`, and a refusal is
`{"detail": "<one plain sentence>"}`.

### Notes

| Route | Body | Returns |
|---|---|---|
| `GET /api/runs/{run_id}/notes` | | `{"notes": NoteSummary[]}`, by template, field, position, then id |
| `GET /api/runs/{run_id}/notes/{note_id}` | | `{"note": Note}` |
| `POST /api/runs/{run_id}/notes/{note_id}/look` | `{"blocks": NoteBlock[], "format_state"?, "reason"?}` | `{"note": Note}` |
| `POST /api/runs/{run_id}/notes/{note_id}/field` | `{"node_uuid": "…" \| null, "position"?}` | `{"note": Note, "history_id"}` |
| `POST /api/runs/{run_id}/notes/{note_id}/field/confirm` | | `{"note": Note, "history_id"}` |
| `POST /api/runs/{run_id}/notes/{note_id}/confirm` | | `{"note": Note}` |
| `POST /api/runs/{run_id}/notes/{note_id}/undo` | `{"history_id"?}` | `{"note": Note}` |
| `POST /api/runs/{run_id}/notes/{note_id}/redo` | `{"reason"?}` | `{"note": Note}` |
| `GET /api/runs/{run_id}/notes/{note_id}/history` | | `{"history": NoteHistoryEntry[]}`, oldest first |

- **Look.** `blocks` is the note's whole block list with the new look. Only
  the look may differ: the same blocks in the same order, the same words,
  the same table shape. Otherwise 422 "A look change cannot change the
  note's words or blocks, so change only its look." A look the block model
  does not hold is refused with the model's own sentence, for example "Row
  2's line names column 5, but the columns are 0 to 3."
  `format_state` is `"fine"` or `"check_formatting"`; when it is left out
  the note keeps its state. A note with any "not sure" look shows
  `"not_sure"` until that look is set.
- **Field.** `node_uuid` is a note field of the template catalogue
  (`notes_nodes`); `null` takes the note out of its field ("Not placed").
  The note goes last in the new field unless `position` is given. An
  unknown field: 422 "There is no such note field." A person who moves a
  note to another field has chosen it, so the move also confirms the
  placement (`confirmed_by`, certainty sure); its formatting and gaps stay
  as they are (owner, 24 November 2026). `history_id` is the row Undo takes.
- **Field is right** (`field/confirm`) confirms the placement only, the same
  way. A note in no field: 422 "The note is in no field, so there is no
  field to confirm."
- **Confirm** records who checked the note and makes its placement sure.
- **Undo** puts the note back exactly as it was before one change of its
  history, by default its latest change. Undoing the placement itself
  leaves the note in the list as not placed, with its blocks. Undo is a
  change too: undoing an undo puts the change back.
- **Redo** copies the note's blocks again from the pages they came from,
  with the plain look, and keeps the note's field.
- Every change adds one history row and one activity event (source
  `notes`) before the route returns.

`NoteSummary` is `Note` without `blocks`. `Note` is:

```json
{
  "id": 7, "number": "4", "title": "Revenue", "pages": [23, 24],
  "template_id": "…", "field": {"node_uuid": "…", "label": "Disclosure of revenue"},
  "part": 1, "parts": 1, "part_title": "", "position": 0,
  "format_state": "fine", "format_reason": "", "has_unsure": false,
  "certainty": "sure", "certainty_reason": "",
  "confirmed_by": null, "confirmed_at": null,
  "revision": 3, "updated_by": "ana@firm.com", "updated_at": "…",
  "blocks": [NoteBlock]
}
```

- `field` is null when the note is not placed; `template_id` is then null.
- `part` of `parts`: a note split at a first-level sub-section across
  fields ("part 1 of 2"). An unsplit note is part 1 of 1. `part_title` is
  a part's own first heading without its numbering ("Borrowing costs"),
  empty for a whole note or a part with no heading of its own.
- `pages` are the PDF pages its blocks were copied from.
- `format_state` is `"fine"`, `"check_formatting"` (with `format_reason`,
  one sentence on what still differs) or `"not_sure"`.

`NoteBlock` is one of the block model's four kinds, as JSON:

```json
{"kind": "heading", "id": "p23b0", "source": {"page": 23, "block": 0}, "level": 2, "text": "4. Revenue",
 "look": {"bold": true, "italic": false, "underline": false, "align": null, "indent": 0, "unsure": []}}
{"kind": "paragraph", "id": "p23b1", "source": {"page": 23, "block": 1}, "text": "…", "look": {…}}
{"kind": "list", "id": "p23b2", "source": {"page": 23, "block": 2},
 "items": [{"text": "(a) Sale of goods", "level": 0}], "look": {…}}
{"kind": "table", "id": "p23b3", "source": {"page": 23, "block": 3},
 "columns": [{"role": "label", "width": null, "align": null, "unsure": []},
             {"role": "amount", "width": null, "align": null, "unsure": []}],
 "rows": [{"role": "heading", "cells": [{"text": "", "look": {…}}, {"text": "2025 RM", "look": {…}}],
           "indent": 0, "bold": false, "shaded": false, "line_below": null, "unsure": []}],
 "frame": "none", "font_pt": null, "unsure": []}
```

- `source` is the PDF page and the block's position in that page's
  content (`MapPage` content, from 0). `id` is `p<page>b<block>`.
- A table's merged cells are split when the note is made: the text sits in
  the first cell of the merge, the others are empty, and every amount keeps
  its column.
- `line_below.columns` are 0-based column numbers; empty means every
  column. `line_below.style` is `"single"` or `"double"`.

`NoteHistoryEntry` is `{"id","action","actor_kind","actor_name","changed_at","round_id","comment_ids","reason","before","after"}`.
`action` is `"place"`, `"look"`, `"move"`, `"clear"`, `"confirm"`,
`"redo"` or `"restore"`. `before` is null for a newly placed note; `before`
and `after` hold the note's field, part, position, blocks, states and
confirmation.

**Refusals.** Three hard stops, each the whole `detail` (422):

1. A note in a heading field: "`<field>` is a heading, so place the note in a field under it."
2. A block that is not from a page of this run: "Page `<n>` of this run has no block `<m>`, so place blocks shown on this run's pages."
3. A write to another run: "That note belongs to another run, so change it from that run."

A note that does not exist: 404 "There is no such note in this run." A
change history entry that is not this note's: 404 "There is no such change
in this note's history."

### Events (source `notes`)

One per change, `kind` the history action, `pages` the note's pages, a
plain `message` naming the note and the field by its label ("Moved note 4
Revenue from Other notes to Disclosure of revenue."). `data` holds
`note_id`, `history_id` and `action`.

## Step 6d

The notes agent (`docs/step-6-plan.md` 6d and section 4). No new routes. The
browser sees it through the run's `status`, its stages, its notes (Step 6b
routes) and its Activity events.

### Two stages after setup

- Confirming the setup queues two jobs in the same transaction: `extract`
  (stage `extract`, as before) and `notes` (stage `notes`, `"waiting"`).
  With `notes_included` false no notes job or stage is made, and an event
  (source `notes`, kind `notice`) says "The notes are switched off at
  setup, so the notes agent does not run."
- The worker runs at most two jobs at once, never two of the same kind, so
  the figures agent and the notes agent work side by side.
- While a run has a `notes` stage, `Run.status` follows both stages:
  `"extracting"` while either works (also when one is done and the other
  still waits or works), `"needs_answer"` while either is `"asking"`,
  then, once both have ended: `"failed"` when the `extract` stage failed
  (or the `notes` stage failed and there is no `extract` stage),
  `"stopped"` when a stage was stopped and the run holds no figure and no
  note, else `"in_review"`. A failed notes stage alone leaves the run
  `"in_review"`, with the stage's `error` its plain sentence.
- `Run.failed_stage` may be `"notes"` (only when it is the run's only
  failed agent stage). `RunDetail.failure` names the extract stage first.
- The `notes` stage's `working_on` names the sessions running now, comma
  separated, such as `"placing, numeric"` or `"look-1, look-2, numeric"`.
  `RunDetail.working_on` is still the extract stage's.
- The notes stage is `"done"` when its sessions ended, also at a step or
  time limit (an event says the session is partly done). It is `"failed"`
  with one plain sentence when the model failed ("<reason>; the notes placed
  so far are kept.") or nothing at all was placed or reported ("No note was
  placed or reported."). Notes already placed are always kept.

### Stop, retry and scope questions

- `POST .../extract/stop` stops both agents. It is allowed while either
  stage waits or works. A waiting notes job stops at once ("The notes agent
  stopped on request before it started."); a working one stops before its
  next step. The notes stage ends `"stopped"` with `error` "Stopped on
  request; the notes placed so far are kept."
- `POST .../extract/retry` queues again whichever stage failed or was
  stopped (extract as before; notes when its stage is `"failed"` or
  `"stopped"` and the run is `"failed"`, `"stopped"` or `"in_review"`).
  Nothing is cleared; the notes agent starts from the notes placed.
- The notes agent asks scope questions with the same tool and rules as the
  figures agent. `ScopeQuestion.stage` is `"notes"` and `asked_by`
  `"notes"` for its questions. A question from either agent stops both:
  each stage becomes `"asking"` and keeps its work. Answering queues both
  again.

### Events (source `notes`)

| kind | message, for example | data |
|---|---|---|
| `queued` | "The notes agent is queued." | none |
| `session` | "Working on the list of notes." | `{"session"}` |
| `place`, `look`, `move` | as Step 6b | as Step 6b |
| `previewed` | "Previewed Disclosure of borrowings as mTool gets it." | `{"node_uuid", "note_ids", "tier", "chars", "overflow_mm", "pictures"}` |
| `flagged` | "Marked note 5 Trade and other receivables for a formatting check: …" | `{"note_id"}` |
| `reported` | "Reported a capture problem for note 7." | `{"report_id", "kind", "note_number"}` |
| `coverage` | "Coverage: 18 note(s) placed, 2 report(s), 0 still open." | `{"placed", "reports", "open"}` |
| `saved`, `cleared` | share capital and related-party figures, as Step 4 | `{"saved"}` |
| `finished` or `notice` | "The list of notes: done." or "…: partly done. <reason>" | session, status, steps, seconds, unresolved count |
| `done` | "The notes are placed: 18 of 20 listed note(s) placed, 2 report(s), 0 point(s) open." | coverage counts, calls, tokens, `cost_usd` |
| `failed`, `stopped` | "The notes agent stopped: <sentence>" | the notes agent's calls, tokens and `cost_usd` |

The shared loop's rows (`started`, `step`, `tool`, `looked`) come from
source `notes` too. Messages name fields by label and pages by number,
never by id. Each model call is a `model_calls` row with source `notes`.
The extract stage's `done` event says "The run is ready for review once the
notes agent ends." while the notes agent still works.

### Traces change

The traces zip gains `notes.json` (every note with its blocks and history)
and `note_reports.json`. Under `records/`: `notes.json` (each session's
finish, open points, previews used and transcript name, and the final
coverage) and `note-previews/*.png` (every preview picture the agent saw).
The notes agent's transcripts are `transcripts/notes-*.json`, one per
session.

## Step 6e

Notes in the review loop (`docs/step-6-plan.md` 6e), and the routes the notes
screens need. Same rules as Step 6b: every route needs a session, any
signed-in person may open any run, a run that does not exist returns 404
`{"detail": "There is no such run."}`, and a refusal is `{"detail": "<one
plain sentence>"}`.

### Note fields

| Route | Returns |
|---|---|
| `GET /api/runs/{run_id}/notes/fields` | `{"fields": NoteField[]}` |

`NoteField` is one field a note can go in, headings included and marked, in
template order, top to bottom:

```json
{"field_id": "…", "template": "LIST_OF_NOTES", "template_name": "List of notes",
 "template_id": "mfrs-company-notes-listofnotes-v1", "label": "Disclosure of revenue",
 "path": ["Notes to the financial statements"], "heading": false, "mandatory": false, "catch_all": false}
```

- `field_id` is the `node_uuid` a note's `field` and `POST …/field` use.
- The list holds the three prose-note templates and the text field of each
  numeric note (`template` `"ISSUED_CAPITAL"` or `"RELATED_PARTY"`). A note
  can be placed in a numeric note's text field like any other field, so
  share capital sits in its two allowed fields (fixes 6d's open item).
- Empty before the setup is confirmed.

### Reports

| Route | Returns |
|---|---|
| `GET /api/runs/{run_id}/notes/reports` | `{"reports": NoteReport[]}`, oldest first |
| `POST /api/runs/{run_id}/notes/reports/{report_id}/leave-empty` | `{"report": NoteReport}` |
| `POST /api/runs/{run_id}/notes/reports/{report_id}/reopen` | `{"report": NoteReport}` |

`NoteReport` is what the notes agent reported:

```json
{"id": 31, "kind": "source_gap", "note_id": 3, "note_number": "5", "node_uuid": null, "field_label": null,
 "template_id": null, "pages": [24], "reason": "…", "after_block": "p24b2",
 "status": "open", "settled_by": null, "settled_at": null, "created_at": "…"}
```

- `kind` is `"source_gap"`, `"missing_mandatory_field"` or `"routed_elsewhere"`.
- `note_id` is the run's note with the report's note number (its first
  part), or null. `node_uuid`, `field_label` and `template_id` name the
  field of a missing mandatory field, else null.
- `after_block` is the block of the note after which a source gap falls,
  when the agent named one (`report_gap` gains `after_block`), else null.
- `status` is `"open"` or `"settled"`. A person settles a source gap by
  confirming its note (any part of it, matched by the printed number) or
  with `leave-empty` (accepting it as it is, also for a gap whose note was
  never placed), and a missing field by leaving it empty. `reopen` makes a
  report open again.
- `leave-empty` is for a missing mandatory field or a source gap: 422 "Only
  a missing required field or a capture problem can be settled." A report
  that does not exist: 404 "There is no such report in this run."
- Each settle and reopen writes an event (source `notes`, kind `report`),
  for example "Left Significant accounting judgements empty."

### The note as review draws it

| Route | Returns |
|---|---|
| `GET /api/runs/{run_id}/notes/{note_id}/review` | `{"review": {"note_id": 7, "node_uuid": "…", "revision": "…", "tier": "full", "html": "…", "double_underline": "…"}}` |

- The field's prepared text (below) at the tier mTool's text landed on,
  with marks for the screen: the note and block on each block, the row and
  column on each table cell. The server refuses to send it unless removing
  the marks gives back exactly the prepared text, so review, Copy and mTool
  show one text. A note that is not placed is drawn alone through the same
  renderer (`node_uuid` null). `double_underline` is the house style's
  setting.

### The field's prepared text

| Route | Returns |
|---|---|
| `GET /api/runs/{run_id}/notes/{note_id}/prepared` | `{"prepared": PreparedNote}` |

```json
{"node_uuid": "…", "revision": "<sha256 of html>", "html": "…", "tier": "full", "chars": 5210, "limit": 32767}
```

- The whole text of the note's field (every note placed there, in order),
  as `app/notes/render.prepare` makes it with the Settings house style: the
  same text the preview, the review page and mTool get. `tier` is `"full"`,
  `"compact"`, `"lite"`, `"flat"` or `"too_long"`.
- A note that is not placed: 409 "This note is not placed, so there is no
  field text to copy."

### Note changes

- `NoteSummary` and `Note` gain `fit`: `{"tier", "chars", "limit"}` of the
  note's field's whole text, or null when the note is not placed.
- `Note` gains `figures`: for a note placed in a numeric note's text field,
  the figures of that numeric note as `{"columns", "rows", "unsure"}`.
  `columns` and `rows` have the Statement shapes (Step 1), one row per field
  and category holding a figure, in template order; a category row's
  `label` names its category. `unsure` counts the figures marked Unsure.
  Null for every other note.
- **Confirm** also sets `format_state` to `"fine"` (its reason cleared) and
  settles the note's open source gaps.

### Comments on notes

`Target` gains:

```json
{"kind": "note", "note_id": 7, "note_part": null}
{"kind": "note", "note_id": 7, "note_part": {"block": "p23b4", "scope": "row", "row": 4, "column": null}}
```

- `note_part` null is the whole note. Otherwise `block` is a block id of the
  note and `scope` is `"block"` (a heading, paragraph or list), or for a
  table `"table"`, `"row"`, `"column"` or `"cell"`. `row` and `column` are
  0-based: `row` for a row or cell, `column` for a column or cell, else null.
- A note comment's `scope` is `"figure"`.
- `Comment.target` of a note comment is `{"kind": "note", "note_id",
  "note_part", "field_label", "statement": null, "concept_uuid": null,
  "period": null, "entity_scope": null, "dimension_key": "", "figure_id":
  null}`. `field_label` names the note and the part, as the browser names a
  selection: "Note 5 Trade and other receivables", "… › Row: Total", "… ›
  Column: 2025 RM", "… › Total, 2025 RM", "… › Table", "… › Paragraph".
- Refusals replace "Comments on notes arrive with the notes, in a later
  step.": "There is no such note in this run." (404), "A note comment names
  the note by its id." (422), "Note 5 Trade and other receivables has no block
  p23b9." (422), "A comment on part of a note is on a block, a table, a row,
  a column or a cell." (422), "A paragraph has no rows or columns, so
  comment on the whole block." (422), "The table has 5 rows, so row 9 does
  not exist." (422), "The table has 4 columns, so column 6 does not exist."
  (422), "Name the row for a row or cell comment." (422), "Name the column
  for a column or cell comment." (422).
- A comment on a share capital or related-party figure (`{"kind": "figure",
  "figure_id"}`) is filed under its numeric note: `target.statement` is
  `"ISSUED_CAPITAL"` or `"RELATED_PARTY"`, and `target.note_id` is the note
  placed in that note's text field (whose page shows the figures), or null.
  Needs you items on these figures carry the same `statement` and `note_id`,
  and a round's `Change.statement` names the note the same way. A figure in
  no statement or numeric note of the run: 422 "That figure is in no
  statement or numeric note of this run."
- A round with such comments gives the Reviewer the two numeric notes'
  outlines and categories, `save_note_figures` and `clear_note_figures`
  (the notes agent's figure tools, each write naming the comments it
  answers), and the numeric notes' checks in `run_checks`. Undo puts the
  figures back as for any figure.

### The Reviewer and notes

The Reviewer gains note tools, all tagged with the round and the comments
each write answers: `show_notes` (a note's blocks with ids, rows and columns
numbered from 1, and the look), `find_note_fields`, `move_notes` (to another
note field, or out of its field), `set_note_look` (the notes agent's look
vocabulary), `preview_notes` (the field drawn as mTool gets it, three per
note in a round) and `redo_notes` ("Redo from source": the note copied again
from its pages with the plain look; it keeps its field). Taking a note out
of its last placement is done, and the tool says plainly that the note is
now placed nowhere (v1's lesson, as feedback). Each write's result ends with
the server's count of what the round has changed, notes included. A note
write counts as a change for the finish: the Reviewer runs the checks after
its last change, notes included.

`RoundReport` gains:

```json
{"comments": [{"comment_id": 4, "…": "…", "notes": [NoteChange]}],
 "notes_other": [NoteChange],
 "counts": {"…": "…", "notes": 2}}
```

`NoteChange` is:

```json
{"note_id": 7, "number": "5", "title": "Trade and other receivables",
 "field_was": {"node_uuid": "…", "label": "Disclosure of borrowings"},
 "field_now": {"node_uuid": "…", "label": "Disclosure of trade and other receivables"},
 "changed": true, "differences": ["field Disclosure of borrowings → Disclosure of trade and other receivables",
                                  "look changed"], "served": [4]}
```

- Worked out from `note_history` rows carrying the round's id: the note
  before the round's first write on it, and now. `differences` may hold
  "field … → …", "position changed", "look changed", "copied again from its
  pages", "formatting <state> → <state>" and "confirmed".
- `comments[].notes`: a note comment's own note, and any note written for
  the comment. `comments[].changed` counts note changes too.
- `notes_other`: notes the round changed that no comment points at.
  `counts.notes` is the number of notes the round changed.

**Undo** of a comment also puts back, exactly, every note the round changed
for it, each to its state just before the round, through the note store (a
`"restore"` history row each). Comments sharing a note are undone together.
A note changed outside the round after the round first wrote it (a
person's confirm included, since it settles the note's gaps): 409
"`<note>` was changed outside this round after the round first wrote it, so
restore it from its history instead." The response gains `"notes": Note[]`.

### Needs you change

After the open agent comments, in this order:

```json
{"kind": "note_too_long", "title": "Disclosure of borrowings", "message": "40,210 of 32,767 characters…", "note_id": 9, "node_uuid": "…"}
{"kind": "note_to_check", "title": "Note 5 Trade and other receivables", "message": "<the reason>", "note_id": 7}
{"kind": "unplaced_note", "title": "Note 8 Contingent liabilities", "message": "…", "note_id": 8}
{"kind": "note_gap", "title": "Note 5 Trade and other receivables", "message": "<the reason>", "note_id": 7, "report_id": 31}
{"kind": "missing_field", "title": "Significant accounting judgements", "message": "<the reason>", "report_id": 32}
```

- `note_too_long`: one per field whose whole text is too long for mTool at
  every tier; `note_id` is the field's first note. Clears when it fits.
- `note_to_check`: a placed note whose `format_state` is not `"fine"` or
  whose placement is unsure. Clears on Confirm, or a look change that
  leaves it fine.
- `unplaced_note`: a note in no field. Clears when it is placed.
- `note_gap`: an open source gap. Clears when its note is confirmed.
- `missing_field`: an open missing mandatory field that no note fills.
  Clears when a note is placed there or a person leaves it empty.
- Every other field of these items (`statement`, `concept_uuid`, `period`,
  `entity_scope`, `figure_id`) is null.

### Checks change

"Policy and disclosure notes cite the same pages"
(`notes_citation_consistency`) stays `"not_assessed"`, now with the reason:
"Each note is placed once, so a policy note and its disclosure note have no
shared citation to compare." v1 placed the same policy text in two cells,
so their citations had to agree; v2 places each note once, so a policy note
and its disclosure note sit on their own pages and comparing their pages
would warn on nearly every run. An owner decision is needed on what this
check should compare in v2.

### Schema change

`comments` gains `note_id` and `note_part_json` (replacing the unused
`note_ref`, which stays in older databases); `note_reports` gains `status`,
`settled_by`, `settled_at` and `after_block`. An existing database gains the
columns at start-up.

### Step 6 review fixes

- **Look response.** `POST /api/runs/{run_id}/notes/{note_id}/look` returns
  `{"note": Note, "history_id": 412}`. `history_id` is the history row this
  look change added: pass it to `/undo` as `{"history_id": 412}` to undo
  exactly this change.
- **Confirm by a person** also marks every "not sure" look of the note done
  (every block's, row's, column's and cell's `unsure` list is emptied), in
  the same history row, so `has_unsure` is false and a later look change
  stays `"fine"`. Undo of that confirm brings the not-sure looks back and
  opens again the source gaps the confirm settled.
- **A comment on the notes as a whole.** The notes agent files a comment on
  the notes in general as a `"statement"` comment with `"statement":
  "NOTES"`. Its Needs-you item is:

  ```json
  {"kind": "agent_comment", "title": "The notes", "message": "<the comment>", "comment_id": 9,
   "statement": "NOTES", "target_kind": "notes",
   "concept_uuid": null, "period": null, "entity_scope": null, "figure_id": null}
  ```

  `target_kind` `"notes"` means: open the notes list, not a statement.
  Other items have no `target_kind`.
- **A person's comment on the notes.** `NewComment.target` may be
  `{"kind": "statement", "statement": "NOTES"}` (the notes as a whole) or
  `{"kind": "statement", "statement": "NOTES", "report_id": 32}` (one of the
  notes agent's reports, such as a required field no note fills; the
  missing-field panel's comment box sends this). Scope is `"figure"` (the
  run's own comment). A run that leaves the notes out: 422 "This run leaves
  the notes out, so there are no notes to comment on." An unknown report:
  404 "There is no such report in this run." In `Comment.target`,
  `report_id` is the report's id or null, and `field_label` is the report's
  field label (else "Note 5", else "The notes"), or "The notes" for the
  notes as a whole. Send puts these comments in the round like any other:
  the Reviewer reads the report (its field, kind and reason) and may place
  a note in that field or answer why it stays empty.
- `note_history` gains `settled_reports_json`: the gap reports a person's
  confirm settled; `comments` gains `report_id`. An existing database gains
  the columns at start-up.

## Step 8

Filling the run's mTool template (`step-8-plan.md` part 8e). Same rules as
Step 1: every route needs a session (401 without one), any signed-in person
may use any run, a run that does not exist returns 404 `{"detail": "There
is no such run."}`.

### mTool fills

| Route | Body | Returns |
|---|---|---|
| `POST /api/runs/{run_id}/fills` | multipart form, one field `file` (`.xlsx` or `.xlsm`) | 202 `{"fill": Fill}`. Keeps the template and queues its fill |
| `GET /api/runs/{run_id}/fills` | | `{"fills": Fill[]}`, oldest first, without receipts |
| `GET /api/runs/{run_id}/fills/{fill_id}` | | `{"fill": Fill}` with `receipt` |
| `GET /api/runs/{run_id}/fills/{fill_id}/file` | | the filled workbook, named "<template name> filled.xlsx". Sets `downloaded_at` |

- The uploaded template is kept in the run's folder and never changed. The
  fill writes a new file beside it, atomically. Both go in the traces
  export only with `include_pdf=1` (as `uploaded/fill-<id> …`); every fill
  row with its full report goes in `fills.json`.
- The fill runs as the job `fill`, one attempt. The browser asks for the
  fill about once a second until `job_status` is `"ready"` or `"failed"`.
- Refusals, 409 unless noted: "Choose an .xlsx or .xlsm mTool template."
  (422), "This file is empty." (422), "This file is over 25 MB." (413),
  "Confirm the run's setup before preparing the mTool file.", "The run is
  still working, so prepare the mTool file when it finishes." (reading,
  extraction, a scope question or a correction round is queued or
  working), "A fill is already running for this run.", "There is no such
  fill in this run." (404), "This mTool file is not ready yet." (download
  before ready), "The filled file is no longer on the server, so fill the
  template again." (410).

`Fill` is:

```json
{
  "id": 4, "run_id": 1, "job_status": "ready", "error": null,
  "template_filename": "SeriMaju_MFRS_Company_2025.xlsx", "template_sha256": "…",
  "compatibility": "known", "status": "needs review", "output_sha256": "…",
  "created_by": "ana@firm.com", "created_at": "…", "started_at": "…", "finished_at": "…",
  "downloaded_at": null,
  "receipt": FillReceipt
}
```

- `job_status` is `"queued"`, `"filling"`, `"ready"` or `"failed"`.
  `error` is the plain sentence of a fill that failed, for example "This
  file could not be read as an Excel workbook."
- `status` is the receipt's: `"ok"`, or `"needs review"` when anything is
  unresolved or mismatched, a note was left out (too long, or a formula
  cell), or the template is not a known one. Null until
  ready. `compatibility` is `"known"`, `"probably_compatible"` or
  `"unknown"`.

`FillReceipt` is null until the fill is ready:

```json
{
  "counts": {"written": 214, "not_written": 3, "notes": 11, "notes_not_written": 1},
  "lines": [
    {"id": "skipped|8806…|CY|Company|", "name": "Other comprehensive income, Company, 2025",
     "reason": "No value in the source, so the cell is left empty.", "code": "no_value", "kind": "skipped"}
  ],
  "template": {"name": "MFRS Company …", "compatibility": "known", "reasons": []}
}
```

- `lines` lists every figure and note the fill did not write: `kind` is
  `"unresolved"`, `"mismatched"`, `"skipped"`, `"note_unresolved"`,
  `"note_mismatched"` or `"note_skipped"`, in that order. `id` is stable and
  unique within the receipt (the kind and the figure's concept, period,
  entity and category, or the note field). `name` is the figure or note in
  words, never a cell address or an id; `reason` is one plain sentence, a
  mismatched line's own. `counts.not_written` counts the figure lines
  (skipped, unresolved and mismatched).
- A total the template works out with its own formula is expected: it is
  neither listed nor counted (it stays in the full report as `kept`).
- The patcher's own error for a line is kept in the full report as
  `detail`, never on the receipt.
- The dialog's title is "mTool file ready" when `status` is `"ok"`. When
  `status` is `"needs review"` or `template.compatibility` is not
  `"known"`, the title is "mTool file needs a check" and each of
  `template.reasons` is shown as a line before the figure lines. Download
  stays available either way.
- A correction round is refused while a fill is queued or filling: "The
  mTool file is being prepared, so send the comments when it is ready."
  (409), since the fill reads the figures as they stand when it starts.
- No file path leaves the server.

### Events (source `fill`)

| kind | message, for example | data |
|---|---|---|
| `queued` | "The mTool fill is queued." | `{"fill_id"}` |
| `started` | "Filling the mTool template." | `{"fill_id", "template_sha256"}` |
| `done` | "The mTool file is ready: 214 figure(s) written, 3 not written, 11 note(s) written." | `{"fill_id", "status"}` and the counts |
| `failed` | "The mTool fill failed: <sentence>" | `{"fill_id"}` |

The server log has a line when a fill is queued, starts, ends and is
downloaded, and a full traceback for every failure.

### Schema change

New table `fills` (one row per fill: the template, the job's status and
error, the receipt's digests, status and report, `downloaded_at`). An
existing database gains it at start-up.

## Later steps

Added here before each step is built.

## Step 10d: a starting workbook

A part-filled mTool workbook (most often last year's file, rolled forward to
this year) attached at setup. Its figures are imported when the setup is
confirmed, before extraction starts.

| Route | Body | Returns |
|---|---|---|
| `POST /api/runs/{run_id}/starting-workbook` | multipart `file` (.xlsx or .xlsm, up to 25 MB) | `{"starting_workbook": StartingWorkbook}`. At setup only. Attaching again replaces the file and the record |
| `GET /api/runs/{run_id}/starting-workbook` | | `{"starting_workbook": StartingWorkbook \| null}` |
| `DELETE /api/runs/{run_id}/starting-workbook` | | 204. At setup only |

`StartingWorkbook` is:

```json
{
  "filename": "last.xlsx", "sha256": "…", "uploaded_by": "ana@firm.com", "uploaded_at": "…",
  "workbook": {"standard": "MFRS", "level": "Company", "unit": "RM", "year_end": "2021-12-31"},
  "imported_at": null,
  "imported": null
}
```

- `workbook` is what the file's Filing Information sheet says of itself,
  each value null when it says nothing the app knows. The setup screen may
  show it beside the setup.
- `imported` is null until the setup is confirmed, then
  `{"prior_year", "typed_this_year", "typed_totals", "not_imported": [{"cell", "period", "entity_scope", "sentence"}], "formulas_left": ["Sheet!E28"], "loose": [{"workbook_cell", "sentence", …}], "workbook": {…}}`.
  `not_imported` lists cells that held something but were not read or were
  refused, each with its reason; `formulas_left` this year's input cells that
  hold a formula (not typed, so left alone); `loose` numbers no field claims.

**What is imported.** Last year's figures as `origin` `"prior_workbook"`,
locked for everyone. This year's figures a person typed as
`"typed_in_workbook"`, kept fixed against agents (a person may still edit
one). A total typed over its formula as a total with no breakdown
(`children_status` `"aggregate_only"`), whatever its lines add up to: the
printed-totals check shows the difference. A blank cell is never imported,
so it is never zero; a typed 0 or dash is imported as 0. A total left to its
formula is not imported. Group and Company columns are imported apart. Each
imported figure has an `"import"` history row, and its `source_ref` holds
`{"sha256", "cell"}`.

**Refusals**, each the whole `detail` (422), on attach or on the setup
confirm:

- "This is not an mTool workbook, so attach last year's mTool file rolled forward to this year." (attach)
- "These are the company's first financial statements, so there is no last year's workbook to start from."
- "The workbook is an `<standard>` filing but this run files `<standard>`, so attach a workbook for the same standard."
- "The workbook is a `<level>` filing but this run is a `<level>` filing, so attach a workbook for the same level."
- "The workbook is in `<unit>` but the report is in `<unit>`, so attach a workbook in the same unit." (units read `RM` or `RM'000 (thousands)`)
- "The workbook does not say its level of rounding, so its unit cannot be checked against the report; set it in the workbook's filing information."
- "The workbook does not say its year end, so it cannot be checked against the report; set it in the workbook's filing information." (the year end may be typed as day/month/year or held as a date)
- "The workbook is set for the year ending `<date>` but the report's year ends `<date>`, so roll the workbook forward to this year in mTool first."
- "The workbook has no sheet for the `<statement>` in the `<layout>` layout this run uses, so attach a workbook made for the same layouts."
- "The workbook has no last-year column, so it was set up for first financial statements; attach one rolled forward from last year's filing."
- "The workbook holds no figures for this run's statements, so there is nothing to start from."
- "The starting workbook changed or is missing since it was attached, so attach it again."

A refused confirm keeps nothing: the run stays at setup, and the person can
correct the setup or remove the workbook. After the confirm, attaching
answers 409 "A starting workbook is attached at setup, and this run's setup
is already confirmed." and removing answers 409 "The starting workbook's
figures are already in this run, so it stays attached." So a removal never
has imported figures to undo.

With a starting workbook, a scope answer that would change the standard,
level, unit, year end or a layout is refused 409: "This run starts from a
workbook made for its current setup, so <the field> cannot change here;
start a new run with the right setup and a workbook that fits it." A
this-year figure imported from the workbook stays fixed against agents after
a person edits it too (hard stop 9).

### Last year's comparatives (step 10e)

The figures agent saves last year's column as printed, as before. On a field
whose last-year figure was kept from the workbook, the save records the
report's comparative instead of saving it, and answers in plain sentences:
it agrees, it differs (by how much), or it is the same amount with the
opposite sign. A sign-only difference marks the figure `sign_question: true`
and unsure; only a person settles it, by confirming the figure. The kept
figure never changes.

New check `prior_year_comparatives` ("Last year's figures agree with the
report"), once per entity: `not_applicable` with no kept figures,
`not_assessed` when none is compared yet, `warning` for each open
difference or while some kept figures are not compared, `passed` otherwise.
A difference a person confirmed after the reading counts as accepted.
Only face-statement figures with no category count (a numeric note's
figures are never compared). The figures agent's `run_checks` asks for the
kept figures of its own fields not compared yet, and shows open differences
as information only: a person decides them, so they never hold up its
finish. The Reviewer sees the check. A save that only records comparatives
counts as work, and a statement wholly imported from the workbook starts
with its imported figures counted.

### Events (source `setup` and `figures`)

`starting_workbook` (attached, replaced or removed), `workbook_imported`
(the counts), and `comparative` (source `figures`, one per reading).

### Schema change

New tables `starting_workbooks` (the file, its hash, what it says of itself,
the import's summary) and `prior_year_comparisons` (the agent's reading of
each kept figure's comparative). The traces zip gains
`starting_workbook.json`; the file itself goes in only with the uploads.

## Step 10a-c: reports

The directors' report, the statement by directors and the auditors' report
(`step-10-plan.md` parts 10a to 10c). Same rules as Step 1: every route
needs a session (401 without one), any signed-in person may use any run, a
run that does not exist returns 404 `{"detail": "There is no such run."}`.
The screens wait on an owner-approved prototype (10f).

### Report fields

| Route | Body | Returns |
|---|---|---|
| `GET /api/runs/{run_id}/reports` | | `{"stage": {"status", "error"} \| null, "reports": Report[]}`: all three reports, every field in template order |
| `PATCH /api/runs/{run_id}/reports/{report}/{field}` | `{"revision", "status"?, "value"?, "blocks"?, "pages"?, "reason"?}` | `{"field": ReportField}` with `history_id` |
| `POST /api/runs/{run_id}/reports/{report}/{field}/clear` | `{"revision", "reason"?}` | `{"field": ReportField}` with `history_id` |
| `GET /api/runs/{run_id}/reports/{report}/{field}/history` | | `{"history": ReportFieldChange[]}`, oldest first |

- `report` is `DIRECTORS_REPORT`, `STATEMENT_BY_DIRECTORS` or
  `AUDITORS_REPORT`. `field` is the taxonomy element
  (`ssmt_NameOfAuditFirm`) or the short id (`AUD-15`: the report's code and
  the template row).
- `revision` is the revision the person saw (0 for a field not assessed
  yet). A different one is refused 409: "<Label> changed since you opened
  it, so reload it before saving."
- `status` is `"filled"` (the default), `"not_shown"` or `"unsure"`. A
  filled short field takes `value`; the narrative takes `blocks`, block ids
  or ranges from the run's pages (`["p5b0-p5b2"]`), whose words code copies,
  as for notes. An empty field needs `reason`.
- Clear empties a field on purpose (`status` `"cleared"`): the fill leaves
  its cell blank. Only a person clears.
- Every write adds a history row and an event. A person's write is kept:
  the reports agent cannot change it.
- Refusals, 422 unless noted, one sentence each: "<Label> takes one of:
  <the list>.", "<Label> is a date, so write it as YYYY-MM-DD, for example
  2025-04-30.", "<Label> is longer than 4,096 characters, so shorten it to
  what is printed.", "Give a value for <Label>, or leave it empty with a
  reason.", "<Label>: say in the reason why the field is left empty.",
  "Page <n> is not a page of this document; give PDF page numbers.", "Page
  <n> of this run has no block <b>, so place blocks shown on this run's
  pages.", "The run's setup is not confirmed, so it has no reports yet.",
  "The <report> has no field <field>." (404), "There is no such report; …"
  (404).

`Report` is `{"report", "name", "sheet", "fields": ReportField[], "assessed",
"total"}`. `ReportField` is:

```json
{
  "report": "AUDITORS_REPORT", "field_id": "AUD-11", "element_id": "ssmt_LicenseNumberOfAuditor",
  "label": "License number of auditor", "kind": "text", "choices": [], "row": 11,
  "status": "filled", "value": "03339/12/2025 J", "reason": "", "pages": [5],
  "revision": 1, "updated_by": "reports", "actor_kind": "agent", "updated_at": "…"
}
```

- `kind` is `"html"` (the narrative), `"date"`, `"choice"` (with
  `choices`, the taxonomy's list) or `"text"`. Identity, licence and
  registration numbers are text, kept exactly as printed.
- `status` is `"not_assessed"` for a field with no assessment yet (then
  `revision` 0 and `value` null), else `"filled"`, `"not_shown"`,
  `"unsure"` or `"cleared"`. A field left empty has `value` null, never a
  word such as "none".
- The narrative field also has `html` (its text through the note renderer
  with the house style, as mTool gets it) and `fit` (`{"tier", "chars",
  "limit"}`), both null until it is filled.

`ReportFieldChange` is `{"id", "action" ("save", "edit" or "clear"),
"actor_kind", "actor_name", "changed_at", "before", "after"}`; `before` is
null for a field's first assessment.

### The reports stage

- Confirming the setup queues the job `reports` (stage `reports`,
  `"waiting"`) beside `extract` and `notes` when the document map names a
  directors' report, statement by directors or auditors' report section.
  Otherwise no job or stage is made and an event (source `reports`, kind
  `notice`) says "The Reader found no directors' report, statement by
  directors or auditors' report, so the reports agent does not run." There
  is no setup switch.
- While the stage waits or works the run is `"extracting"`; the run goes to
  review once the extract, notes and reports stages have all ended. A
  failed reports stage never fails the run.
- The stage is `"done"` when the agent finished, also at a step or time
  limit. It is `"failed"` with one sentence when the model failed ("<reason>;
  the report fields saved so far are kept.") or nothing was saved ("No report
  field was saved."). `POST .../extract/stop` stops it too ("Stopped on
  request; the report fields saved so far are kept."); `POST
  .../extract/retry` queues it again when it failed or was stopped.
- The model is the Settings page's extraction model.

### Events (source `reports`)

| kind | message, for example | data |
|---|---|---|
| `queued` | "The reports agent is queued." | none |
| `notice` | no report section; "The finish was sent back: 3 field(s) are not assessed yet." | none |
| `save`, `edit`, `clear` | "Saved Name of audit firm in the auditors' report." or "Left … empty: <reason>" | `{"report", "field_id", "element_id", "status", "history_id", "by"}` |
| `done` | "The reports are filled." or "The reports are partly filled, 4 field(s) not assessed. …" | status, `not_assessed`, `unresolved`, calls, tokens, `cost_usd` |
| `failed`, `stopped` | "The reports agent stopped: <sentence>" | calls, tokens and `cost_usd` |

The shared loop's rows (`started`, `step`, `tool`, `looked`) come from
source `reports` too. Each model call is a `model_calls` row with source
`reports`. The run's record is `runs/run-<id>/reports.json`.

### Schema change

New tables `report_fields` (one row per assessed field: status, value or
narrative blocks, reason, pages, revision, who) and `report_field_history`.
The traces zip gains `reports.json` (every field with its history). The
catalogue loads each report template's narrative row into `notes_nodes`.

## Step 10g: the fill keeps the starting workbook and writes the reports

Changes to the Step 8 fill (`step-10-plan.md` part 10g). Same routes and
rules as Step 8.

### Filling a run's starting workbook

| Route | Body | Returns |
|---|---|---|
| `POST /api/runs/{run_id}/fills` | no body, for a run with a starting workbook | 202 `{"fill": Fill}`. Queues the fill of the starting workbook |

- A run with a starting workbook (Step 10d) is filled into a copy of that
  workbook, never into a template a person uploads. Its `Fill` names the
  starting workbook: `template_filename` and `template_sha256` are the
  attached file's. The download is "<starting workbook name> filled.xlsx"
  (or `.xlsm`).
- Refusals, besides Step 8's: an upload for a run with a starting workbook,
  409 "This run fills the workbook attached at setup, so prepare the mTool
  file without uploading a template."; no upload for a run without one, 422
  "Choose an .xlsx or .xlsm mTool template."
- The fill fails, and no file is released, with one of these sentences as
  the fill's `error`:
  - "The starting workbook changed or is missing since it was attached, so attach it again."
  - "A figure imported from the starting workbook changed during the fill (<cell>), so no file was released."
  - "A cell of the starting workbook changed during the fill (<cell>), so no file was released."
  - "Last year's figure in <cell> is a formula that uses this year's cells, so filling this year would change it and no file was released. Type its value over the formula in the workbook and start a new run with it."
  - "The fill changed the starting workbook's sheets, so no file was released."
  - "<why the workbook does not fit>, so this run's setup no longer fits the starting workbook and no file was made; start a new run with it." (the fill checks the workbook against the run's setup again, as the import did)

**What the fill does with the starting workbook.** A figure imported from it
(last year's, or this year's typed) is not written: kept as in the workbook,
counted on the receipt (`counts.kept_in_workbook`), not listed. A typed
figure a person then changed in the app is written with the person's value
and listed (`kind` `"replaced"`). A typed figure a person cleared stays in
the workbook and is listed. A cell on a field's row that holds a value the
run did not import (a cell the import could not read, a formula a person put
in this year's column) is kept and listed, and no figure is written over it.
Any listed workbook value makes the receipt `"needs review"`.
An imported figure whose run value differs from its cell for any other
reason is not written and is listed as unresolved (`code` `"run_differs"`).
A last-year figure written on a field the workbook left blank is written and
listed (`kind` `"prior_year_added"`, "Last year's filing had no figure
here, …"), and makes the receipt `"needs review"`.

**The release check.** Before the file is released, every cell the fill did
not plan to write is compared with the starting workbook: the same cell XML
and the same value. Every imported cell that is a formula must still work
out to the same amount. Anything else fails the fill as above.

### Report fields in the fill

Every fill (template or starting workbook) also writes the three reports:

- The narratives go into mTool's note store like a note, at the text-block
  cell of the report's sheet (the sheet that carries the narrative's SSM
  name: DirectorsRep, StatOfDirectors, AuditReport or Auditorsreport). They
  are lines of the receipt's notes.
- A short field goes in the one unlocked cell on the row of its SSM name, or
  for the auditor's details, the one unlocked typing cell under the table's
  column. Text goes in exactly as saved, identity numbers included. The
  auditor's licence goes in only as four digits, and the audit firm's number
  only as AF and four digits (taken from the saved text when it holds
  exactly one AF number); anything else is listed, never shortened. A choice
  goes in only when the cell's own list offers it, and a date only when the
  cell checks for a date, as Excel's day number. A cleared field empties its
  cell.
- On the genuine mTool templates the choices, the dates, the types of
  identification and the auditor's state are locked cells mTool sets with
  its own picker: they are listed, "mTool sets this field with its own
  picker, so choose it in mTool."
- A field the document does not show, or nobody read, leaves its cell as it
  is and is listed. A report nobody read is one line. In a starting workbook
  a field left so whose cell holds last year's value is listed: "The run has
  no value for this, so the workbook's own value was kept as in the
  workbook. Check it."

### Receipt change

`FillReceipt.counts` gains `reports`, `reports_not_written`,
`kept_in_workbook` and `workbook_kept`. `lines` gains, after the note lines,
`"report_unresolved"`, `"report_mismatched"` and `"report_skipped"` (named
"<field label>, <report>"), then `"workbook_kept"` (named "<row label>,
<sheet> sheet") and `"replaced"`. `report_unresolved`, `report_mismatched`
and `workbook_kept` make the status `"needs review"`; `report_skipped` and
`replaced` do not. `counts.not_written` still counts figure lines only. The
full report (`report_json`) gains `reports` (`written`, `skipped`,
`unresolved`, `mismatched`) and `starting` (null, or the workbook's
`filename`, `sha256`, `imported_kept`, `cells_checked`, `kept_in_workbook`,
`replaced` and `workbook_kept`).

The `done` event's message reads "… <n> note(s) and <n> report field(s)
written." and its data gains the new counts. The fill's `queued` event for a
starting workbook reads "The mTool fill of the starting workbook is queued."

## Step 12

Template investigation (`docs/step-8-plan.md` 8f, owner's approved
`prototypes/fill-placements-prototype.html`). When a fill leaves figures
with no single cell (receipt codes `no_cell`, `no_sheet`, `ambiguous`,
`columns_not_marked`, `shared_cell`, `not_written`) or a figure that did
not read back (`read_back`), the fill job queues the `investigate` job for
the figures no finished investigation of the same template has looked at,
so a skipped place is not proposed twice and a failed investigation blocks
nothing. Totals are left out: the template works them out. The
investigating agent reads a copy of the template with the template toolkit
(`app/workbook/toolkit/`) and proposes a cell per figure with its evidence.
It never writes a workbook or a mapping. A person chooses Use or Skip; the
used places are saved for the template's fingerprint, which makes the
template known, and the template is filled again.

`Fill` gains:

```json
{"investigation": "queued" | "working" | "done" | "failed" | null,
 "investigation_error": "…" | null,
 "placements_open": 2}
```

`placements_open` is present when one fill is read
(`GET /api/runs/{run_id}/fills/{fill_id}`). Once the investigation is
done, a receipt line for a figure the agent looked at and found no place
for reads "No place found in this template."; a figure it did not reach
keeps its own reason. The agent's reason for each is kept with the fill.

A saved place keeps its row's words. A later fill of the same template
uses it only while that row still holds them; otherwise the figure is
placed as if nothing were saved. A saved place wins over the code's own
cell for that figure, unless another figure holds the cell.

| Route | Body | Answer |
|---|---|---|
| `GET /api/runs/{run_id}/fills/{fill_id}/placements` | | `{"investigation", "error", "placements": Placement[]}` |
| `POST /api/runs/{run_id}/fills/{fill_id}/placements` | `{"use": [id]}` | 202 `{"fill": Fill, "used": n}`: the new fill, or this fill unchanged when nothing was used |

`Placement` is `{"id", "figure", "place", "evidence", "status"}`: the
figure and the cell in words (sheet, row label, column heading), never a
bare cell address on its own; `status` is `open`, `used` or `skipped`.

Refusals, one sentence each: before the investigation is done, 409 "The
places are not ready yet."; when no place is open, 409 "These places were
already checked."; an id that is not an open place of this fill, 422
"Choose places from this fill's list."; a busy run or a fill already
running, as `POST /fills`.

The agent's own refusals (`propose_places`), each one sentence it can act
on: a cell that holds a formula, a locked cell, a cell that already holds a
value, a cell the fill wrote, a cell proposed for another figure, and a
proposal with no evidence.

## Go-live A1, A2 and A7

Settings sections: Account and General for everyone; System, Users, Audit log and Issues for admins.
Every route marked admin answers 403 `{"detail": "Only an admin can do this."}` to anyone else.

### Users (admin)

| Route | Body | Returns |
|---|---|---|
| `GET /api/admin/users` | | `{"users": AdminUser[]}`, by email |
| `POST /api/admin/users` | `{"email","name","is_admin"?}` | `{"user": AdminUser, "temporary_password"}`. 409 when the email exists |
| `POST /api/admin/users/{email}/disable` | | `{"ok": true, "user": AdminUser}`. Ends that person's sessions |
| `POST /api/admin/users/{email}/enable` | | `{"ok": true, "user": AdminUser}` |
| `POST /api/admin/users/{email}/reset-password` | | `{"user": AdminUser, "temporary_password"}`. 409 for the admin's own account |
| `POST /api/admin/users/{email}/admin` | `{"is_admin"}` | `{"user": AdminUser}` |

`AdminUser` is `User` plus `{"disabled","has_password","created_at","password_set_at","last_sign_in_at"}`.
The only enabled admin cannot be disabled or made a non-admin: 409
`"<name> is the only admin. Make someone else an admin first."`

`POST /api/auth/change-password` (everyone) is unchanged, and now writes the audit row `password_changed`.

### Audit log (admin)

`GET /api/admin/audit?actor=<email>&group=<group>&offset=<n>&limit=<n>` returns
`{"events": AuditEntry[], "total": <int>, "has_more": <bool>, "people": [{"email","name"}]}`, newest first.
`limit` is 1 to 200 (default 50). `total` counts every row that matches the filters. `people` is everyone
with a row in the log. The older `before=<id>` paging still works.

`AuditEntry` is `{"id","at","actor_email","actor_name","action","target","target_name","detail"}`.
`group` selects actions by how their name starts:

| Group | Actions start with | Actions written today |
|---|---|---|
| `users` | `user_`, `password_`, `role_` | `user_added`, `user_disabled`, `user_enabled`, `password_reset`, `password_changed`, `role_changed` |
| `settings` | `setting_` | `setting_changed`: target `<group>.<name>`, detail `{"setting","from","to"}` in plain words |
| `runs` | `run_`, `drafts_` | `run_deleted`, `drafts_cleared` |
| `issues` | `issue_` | `issue_updated`, `issue_closed`, `issue_reopened`, `issue_deleted`, `issue_traces_downloaded` (target is the issue number) |

`PUT /api/settings` writes one `setting_changed` row for each value that actually changed.

### Report an issue

| Route | Body | Returns |
|---|---|---|
| `POST /api/issues` | multipart: `text`, optional `run_id`, optional `file` | `{"issue": Issue}`. 422 with no text or a file that is not a PNG, JPEG, GIF or WebP picture; 413 over 10 MB; 404 for a run the person may not open |
| `GET /api/issues?status=open\|closed\|all` (admin) | | `{"issues": Issue[]}`, newest first |
| `PATCH /api/issues/{id}` (admin) | `{"status"?: "open"\|"closed", "note"?}` | `{"issue": Issue}` |
| `DELETE /api/issues/{id}` (admin) | | 204. Removes the report and its screenshot; the run is kept |
| `GET /api/issues/{id}/file` (admin) | | the screenshot, as a download |
| `GET /api/issues/{id}/traces` (admin) | | the traces zip of the issue's run, as `GET /api/runs/{id}/traces` builds it without the PDF. 404 when the issue has no run or the run was deleted |

`Issue` is `{"id","created_at","updated_at","reporter_email","reporter_name","text","run_id","run_label",
"status","note","file_name"}`. `run_label` is the run's name when it was reported and is kept when the run is
deleted (`run_id` then becomes null).

### Housekeeping

There is no automatic clean-up (owner, 26 November 2026): runs, their files and their traces are removed
only by hand, by deleting a run or clearing abandoned drafts (Go-live A4).

| Route | Returns |
|---|---|
| `POST /api/admin/connection-test` (admin) | `{"results": [{"model","ok","seconds","sentence"}]}`, one per distinct model set for reading, extraction and review |

The connection test sends one made-up word to each model through the app's own model connection and records
each call in `model_calls` with source `connection_test`.

### Version

`GET /api/health` already returns `version`; the shell shows it. The traces zip gains `version.txt` (the
version, then the deployed commit when there is one) and `manifest.json` gains `app_version` and `commit`.

## Go-live A4: run list search, filters, paging and delete

Replaces `GET /api/runs` and `DELETE /api/runs/{run_id}` above.

| Route | Body | Returns |
|---|---|---|
| `GET /api/runs?q=&status=&standard=&updated_since=&mine=&page=0&per_page=25` | | `{"runs": Run[], "total", "page", "per_page"}`, newest first |
| `GET /api/runs/{run_id}/deletion` | | `{"allowed", "refused": {"code", "detail"} \| null, "figures", "notes", "filled_workbook"}` |
| `DELETE /api/runs/{run_id}` | | 204, no body |
| `GET /api/admin/drafts?older_than_days=30` | | `{"older_than_days", "count"}`. Admin only |
| `POST /api/admin/drafts/clear` | `{"older_than_days"}` | `{"older_than_days", "cleared"}`. Admin only |

- `q` looks in the company's name and the file's name, in any case.
  `status` is one run status, or `"working"` (reading, extracting,
  correcting). `standard` is `"MFRS"` or `"MPERS"`. `updated_since` is an
  ISO time; runs updated at or after it. `mine=true` keeps the signed-in
  person's own runs. `per_page` is 1 to 100.
- A filter the list does not have is refused, 422, one sentence: "Choose a
  status from the list.", "Choose MFRS or MPERS.", "Give the earliest update
  time as a date and time."
- A page past the end gives the last page; `page` in the answer says which.
- Delete: the run's owner or an admin, checked on the server, else 403
  "Only the run's owner or an admin can delete this run.". A run that is
  working (reading, extracting, correcting, or with a job queued or
  running) is refused, 409 "This run is still working, so stop it or wait
  until it finishes, then delete it.". Any other status may be deleted.
- A delete removes the run's rows (figures, notes, comments, rounds, fills,
  traces) and then its folders on disk, and writes an audit row
  `run_deleted` with the run's number, company, file, status and owner.
- `deletion` names what a delete would remove, for the confirm dialog.
  `figures` leaves out totals the app adds up. `code` is `"owner"` or
  `"working"`.
- Clearing drafts deletes every run still at setup, untouched for
  `older_than_days` days or more (1 to 3650) and with no job queued, with
  its files, and writes one audit row `drafts_cleared` naming them. A
  wrong age: 422 "Give the age as a whole number of days from 1 to 3650.".

## Go-live A3: reporting period and amounts in millions

- `ConfirmedSetup` gains `first_statements` (boolean, default false): true
  is "This year only", the company's first financial statements. It is
  saved in `run_setup.first_statements`; anything but true or false is
  refused, 422 "Say whether the report covers this year and last year, or
  this year only.".
- `unit` may now also be `"RM'000,000"` (RM millions), in the setup, the
  document map's `unit` finding and a setup question's choices. A wrong
  unit: 422 "Choose whether amounts are in RM, RM thousands or RM
  millions.". Figures are still stored and filed as printed.
- `DocumentMap` and `SuggestedSetup` gain `first_statements`: a `Finding`
  whose value is `"yes"` when the Reader saw no prior-year figures, `"no"`
  otherwise, or null for a map read before the Reader looked.
- When it is `"yes"`, the setup's `questions` include one card with
  `field: "period"` and choices `"only"` (suggested) and `"both"`. The
  person answers it before the run can start.
- The fill's `template.reasons` gains one sentence, and the fill needs
  review, when the template's own level of rounding is not the run's unit:
  "The template is in RM thousands but the report is in RM millions, so
  mTool would read every amount in the wrong unit; make the template in
  mTool with the same level of rounding and fill it again.".

## Run controls (go-live A5, B1): redo one statement, stop reading, cost

All routes need a session. A run this person may not open answers 404.

### Redo one statement

| Route | Returns |
|---|---|
| `GET /api/runs/{run_id}/statements/{statement}/redo` | `{"redo": RedoPreview}`. 404 "That statement is not part of this run." |
| `POST /api/runs/{run_id}/statements/{statement}/redo` | Body `{"keep_mine": true}` (the default). 202 `{"run": Run, "cleared": 12, "kept": 3}`. 404 as above. 409 with one sentence |

```json
{"statement": "SOFP", "name": "statement of financial position", "refusal": null,
 "kept": [{"concept_uuid": "…", "entity_scope": "Company", "label": "Share capital", "how": "confirmed"}]}
```

- `kept` lists the statement's lines a person edited (`"edited"`) or
  confirmed as they stand now (`"confirmed"`), one per field and entity. A
  confirm counts until the figure is changed again.
- Allowed while the run is `"in_review"` and none of its jobs is queued or
  working. Otherwise `refusal` (and the POST's 409) says "A statement can be
  redone once the run is in review and no agent is working on it." or "This
  run still has work in progress, so wait for it to finish before redoing a
  statement."
- The POST clears the statement's figures, each with a history row naming
  the person, so any of them can be restored. With `keep_mine` true the
  kept lines are not cleared, and the figures agent's save and clear tools
  leave them as they are and tell the agent why. With `keep_mine` false they
  are cleared too. Figures imported from a starting workbook are never
  cleared.
- It then queues the figures agent for that statement alone. The run goes
  to `"ready"`, then `"extracting"`, then back to `"in_review"`. The other
  statements' figures are not touched; the notes and reports stages do not
  run again. Stop is `POST .../extract/stop`; a stopped redo is tried again
  with `POST .../extract/retry`.
- Events (source `extraction`): `redo` "Started redoing the statement of
  financial position.", a `notice` "Kept 3 lines a person edited or
  confirmed.", and at the end `finished` "The statement of financial
  position is redone."
- `RunDetail` gains `redo`: `{"statement": "SOFP", "kept": [12, 15]}` (the
  ids of the kept figures) from the POST until the statement is finished
  again, else null.

### Stop reading

| Route | Returns |
|---|---|
| `POST /api/runs/{run_id}/read/stop` | 202 `{"read": ReadProgress}`. 409 `{"detail": "Reading is not running, so there is nothing to stop."}` |

- Allowed while the `read` stage waits or works. A job still waiting stops
  at once. A working one starts no further page and the Reader takes no
  further step, so it stops once the model calls under way have finished;
  poll `GET .../read`.
- `ReadProgress` gains `stop_requested` and its `status` may be
  `"stopped"`, with `error` "Stopped on request; the pages read so far are
  kept." The run's status is `"stopped"`, and its run-list row's
  `failed_stage` is `"read"` (null for a stopped extraction), so the list
  opens it at setup. An event says "Reading stopped on
  request. The pages read so far are kept." (or "… before it started.").
- `POST .../read/retry` now also works from a stopped reading and reads
  only the pages not yet read. A run whose reading was stopped can be
  deleted (`DELETE /api/runs/{run_id}`), as one whose reading failed.

### Cost and time

| Route | Returns |
|---|---|
| `GET /api/runs/{run_id}/cost` | `{"cost": RunCost}` |

```json
{"agents": [{"agent": "Reading the document", "seconds": 130, "calls": 62, "cost_usd": 0.18, "unpriced": 0}],
 "total": {"seconds": 130, "calls": 62, "cost_usd": 0.18, "unpriced": 0}}
```

- One row per agent that made a model call, in working order: "Reading the
  document" (transcription and the Reader), the figures agent, the notes
  agents, "Reports", "Corrections", "Finding places in the template". An
  agent run that names itself has a row of its own, in the order it
  started: one per figures run ("Statement of financial position", and
  "Statement of financial position, redone" after a redo) and one per notes
  session ("Placing the notes"). Calls recorded before the agent's name was
  kept fall back to "Figures" or "Notes".
- `seconds` is the time the agent spent waiting on the model; calls made
  side by side count once. The total adds the rows.
- `cost_usd` is the estimate recorded with each call. It is null when none
  of the calls has a known price; `unpriced` counts the calls with none.
  The screen leaves a null cost blank and shows a partly priced one as
  "$0.94+".
- A redo is refused while a stopped redo of another statement is still
  open: "The redo of the statement of financial position was stopped
  before it finished, so try it again before redoing another statement."
  The lines a redo keeps are worked out again each time the agent starts,
  so a line a person corrects after a stopped redo is kept through the
  retry too.

### Agents are told when a limit is near (go-live B5)

No route changes. Once 70% and again once 90% of an agent's time limit is
used, the next tool result ends with one sentence, such as "[Time: 21 of 30
minutes used, about 9 minutes left. …]", as it already did for steps. The
Reader's tool results now carry both notes too. Nothing is refused and the
limits are unchanged.
