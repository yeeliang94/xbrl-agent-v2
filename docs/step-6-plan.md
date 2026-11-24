# Step 6 plan — Notes

Written 23 November 2026 on branch `step-6-notes`. A plan only: nothing is built. Read with
`backend-plan.md` (4.6, 7, 8), `requirements.md` 4.4, decision records 1 to 3, `agent-lessons.md`
sections 4 and 5, `v1-reuse-map.md` 2.1, 2.4 and 2.8, and `prototypes/review-prototype-v3.html`.

## 1. What step 6 delivers

The notes agent places each note in a template field, copying the source's words, and makes it
look as close to the source as mTool's note editor can hold. The look is stored once, as blocks in
a fixed vocabulary. One renderer draws the review page, the clipboard copy, the mTool text and the
agent's preview picture. A person can change a note's look, move it, confirm it, comment on part of
it and ask for it to be redone from the source.

**Done when** (from `backend-plan.md` section 7, made checkable):

1. Every note in the confirmed notes list is placed, routed to another template where it is really
   placed, or reported with a reason.
2. Every field's mTool text is within mTool's limit of 32,767 characters, counted on the wrapped
   text as v1's patcher counts it. Nothing is cut. A field that cannot fit shows as too long.
3. The preview picture, the review page and the clipboard copy come from the same prepared text at
   the same revision. A test proves the texts are identical.
4. A person's look change, field change, confirm and redo each add a history row. Undo restores.
5. Live on Doc 1, Doc 2 and Doc 3, placement scores at least v1's average (section 6).
6. Server tests, the browser build and browser tests pass.

**Only Windows can confirm** how a note looks in mTool's note editor (TX27) after a paste, a save
and a full reopen: the thick bottom border, white edges, widths in percent, text underline and
justified prose. The mTool file fill is step 8, so step 6's Windows check is a paste (question 4).

## 2. The parts, in build order

Each part ends with its own checks. New routes go into `api-contract.md` before they are coded.

### 6a. Prose-note templates in the catalogue

- **Builds:** Corporate information, Accounting policies and List of notes (MFRS and MPERS, Company
  and Group) read into `notes_nodes`. Each field has an id, its path under its headings, heading or
  fillable, mandatory (the `*` prefix) and a catch-all mark, all as data. v1 found the catch-all by
  searching labels in four files (`agent-lessons.md` section 7). The numeric notes' text fields join
  the list.
- **Files:** `app/catalog/notes_parser.py`, `statements.py`, `loader.py`, `taxonomy.py` (prose
  roles), and `app/catalog/note_fields.py` (the list agents and screens read).
- **Copied from v1:** `concept_model/notes_parser.py` (93 lines), `notes_importer.py` (56), the prose
  half of `notes_types.py` (144), `notes/labels.py` (77), with `test_notes_types.py` (5) and
  `test_notes_registry_import.py` (10), their set-up rewritten for v2's database.
- **Tests:** all 12 prose templates load; ids stay the same across restarts; MPERS has no
  capital-management field; one catch-all per template; headings are marked.
- **Done when:** every prose-note template loads and a run's field list comes back in one call.

### 6b. Note blocks and the note store

- **Builds:** the block model (section 3), the `notes`, `note_history` and `note_reports` tables,
  and one set of write functions for agents and people: place, set look, move, clear, confirm,
  restore. Each write adds a history row and re-runs the checks. Routes: list, open one, change
  look, change field, confirm, undo.
- **Files:** `app/notes/blocks.py` (model and plain-sentence validation), `store.py`, `copy.py`
  (blocks from the Reader's page content, by block id), `routes.py`, `app/db/schema.sql`.
- **Copied from v1:** nothing. v1 stored one HTML text per field (`notes_cells`).
- **Hard stops, one sentence each, and only these:** a note in a heading field; a block that is not
  from a page of this run; a write to another run. The look tools take no text, so they cannot
  change words: copying holds by construction, not by a rule.
- **Tests:** copying keeps every word and table cell; a look change leaves the text identical; one
  history row per write; undo restores exactly; the three refusals; split cells keep every amount
  in its column, on every table in Doc 1 to 3's transcriptions.
- **Done when:** a test places three notes, changes their look, moves one, undoes it, and reads the
  history back in order.

### 6c. The one renderer

- **Builds:** blocks to HTML, then mTool styling, the size tiers and the preview picture. The house
  style comes from the Settings page. The server sends the prepared HTML to the browser, so there is
  no second decorator (v1 kept a TypeScript copy in `web/src/lib/clipboard.ts`).
- **Files:** `app/notes/render/html.py`, `decorate*.py` (split to stay under about 400 lines a
  file), `fit.py` (tiers and the 32,767 count), `picture.py`, and `app/notes/fonts/`.
- **Copied from v1:** `mtool/notes_decorate.py` (1,289 lines, less its Word-table and legacy-theme
  paths); `notes/render.py` (191) with the four Liberation Sans fonts and licence;
  `prepare_note_output` and `_resolve_note_html` from `mtool/notes_exporter.py` (lines 72-94 and
  344-467, without database reads); `wrap_footnote_html` and `EXCEL_CELL_CHAR_LIMIT` from
  `mtool/offline_fill.py` (lines 660-710); `content_structure` from `notes/format_verify.py:155`.
  Tests: `test_mtool_notes_decorate.py` (94), `test_notes_render.py` (9), the tier tests of
  `test_mtool_notes_exporter.py` (32 in all), `test_notes_char_limit.py` (5).
- **Rebuilt:** the table-look compiler. v1's `table_layout.py` (387) and `format_patch.py` (733)
  patched stored HTML; v2's blocks carry the look. Vocabulary and refusal wording come from
  `table_layout.py` lines 35-114. Not copied: `html_sanitize.py`, `html_to_text.py` (v2 writes its
  own HTML; nothing hostile is parsed).
- **Package:** beautifulsoup4 4.14.3 and soupsieve 2.8.3, both pinned in v1's `constraints.txt`.
- **Tests:** one note gives identical HTML for review, clipboard and mTool; a bold total and its
  rule show in the picture (pixel test, as v1's); a wide table reports its overflow and the font that
  fits, never below the Settings minimum; an over-limit field steps down the tiers and keeps every
  word; a field with several notes is counted as one text.
- **Done when:** the three outputs are proven identical, and the tiers hold on a 200-row table.

### 6d. The notes agent

- **Builds:** the agent, its tools and instructions, its own stage and job, its run beside the
  figures agent (section 4). Share-capital and related-party numbers go through the figure store.
- **Files:** `app/notes/agent.py`, `tools.py`, `look_tools.py`, `coverage.py`, `instructions.py`,
  `job.py`, `state.py`; `app/jobs/worker.py` (question 6); `app/runs/status.py`.
- **Copied from v1:** the preview limits and messages (`notes/formatting_agent.py` lines 225-296:
  three previews per note, 12 pictures a call, "fits at N pt"). The lessons, as principles.
- **Rebuilt:** the rest, on the `app/extraction/` pattern: fields by id, saves by id, budget notes on
  every tool, a finish check in code, the shared loop.
- **Tests:** a scripted model places, previews, flags one and finishes; the finish is refused while
  a note is unaccounted for; a fourth preview is refused in one sentence; a stopped run keeps its
  notes; every model call, transcript and preview picture is recorded.
- **Done when:** a scripted run leaves every note placed or reported, with history, events and
  transcript.

### 6e. Notes in the review loop

- **Builds:** comments on a note, a block, or a table's row, column or cell; the Reviewer's note
  tools (move, set look, preview, redo from source); the Needs you kinds `note_to_check` and
  `unplaced_note` (kept for step 6 in `app/review/needs_you.py`); a round's count of note changes,
  from `note_history`; Undo of a note change; "note citations agree" assessed once notes exist.
- **Files:** `app/review/comments.py` (drop the "notes arrive later" refusal), `note_tools.py`
  (new), `changes.py`, `undo.py`, `needs_you.py`, `instructions.py`; `app/checks/placement_checks.py`.
- **Copied from v1:** "never clear a note's last placement" (`notes/reviewer_agent.py` lines
  449-460), as tool feedback, not a stop.
- **Done when:** a scripted round fixes a seeded wrong field and a seeded wrong border, the server's
  count shows both, and Undo restores each; "Redo from source" rebuilds a note and Undo restores it.

### 6f. The notes screens

- **Builds:** everything in section 5's first list, with the existing components.
- **Files:** `web/src/pages/run/NoteWork.tsx`, `NoteToolbar.tsx`, `NoteSide.tsx`, `noteModel.ts`,
  `RunNav.tsx`, `NeedsYouTab.tsx`, `web/src/api/`.
- **Tests:** Vitest for selection scope, a look change sent and redrawn, field change, Confirm, the
  empty and still-working states.
- **Done when:** every state in that list is checked in a browser against a seeded run.

### 6g. Judging notes

- **Builds:** notes placement keys for Doc 1 to 3, the "same field" score in
  `app/scoring/notes.py`, a v1 baseline from v1's database, and `tests/test_notes_live.py` (`live`).
- **Done when:** the score runs on a v2 run and on v1's runs, and the live result is in the build log.

### Which parts can be built side by side

| Together | Why they do not collide |
|---|---|
| 6a and 6c | `app/catalog/` against `app/notes/render/`. The orchestrator writes `app/notes/blocks.py` first; both read it, neither changes it |
| 6b and 6c | 6b owns `store.py`, `copy.py`, `routes.py` and the schema; 6c owns `render/` |
| 6f with 6d and 6e | Once the routes are in `api-contract.md`, the browser agent works only in `web/`, on fixtures |
| 6g keys | The orchestrator drafts them at any time; the score code waits for 6b |

6d waits for 6a to 6c. 6e waits for 6d. Two agents never share a file.

## 3. The data shape

### Note blocks

A note is a list of blocks. The words come only from the Reader's page content, copied by code.
The look sits beside the words. A text run is `{text, bold, italic, underline}`.

| Block | Holds | Look it can carry |
|---|---|---|
| Heading | Level 1 to 3, text runs | Bold, italic, underline, alignment |
| Paragraph | Text runs | Alignment, indent 0 to 4 |
| List | Ordered or bulleted items, level 0 to 2 | Indent; numbering kept as printed |
| Table | Columns: role (label, amount, text, date), width in percent. Rows: role (heading, item, subtotal, total). Cells: text runs | Row indent 0 to 3, bold, shading; cell alignment and vertical alignment; lines below a row across named columns, single or double; frame none or grid (grid only when the source boxes every cell); font 8 to 14 pt, only when too wide |

**Each look value is set, "not sure" or absent.** Absent means the source shows the plain look.
"Not sure" means the agent could not tell. Both are drawn in the house style from Settings, and a
note with a "not sure" value is shown for checking. The house style never overrides a set value.

### Mapped to what mTool's note editor accepts

| Stored look | Sent to mTool | Basis |
|---|---|---|
| Bold, italic | `strong`, `em` | v1 tested |
| Underline | `u` | Not certified in mTool (Windows) |
| Heading | Bold heading, level kept | v1 tested |
| Alignment, indent | Inline `text-align`; indent in 2em steps | v1 tested |
| Line, single | 0.75px solid bottom border on the spanned cells | v1 tested |
| Line, double | House style: thick bottom border, or single | Decision record 1; Windows check |
| No line | White border: mTool draws hidden borders grey | v1 recon, 6 July 2026 |
| Column widths | Width attributes in percent | mTool may change them on save |
| Font size | Inline size, never below the Settings minimum | v1 |
| Shading | Cell fill, only where the source shades | v1 |
| Merged cells | Not stored: split into ordinary cells, text in the first | mTool's editor cannot resize them (question 2) |
| Page breaks, pictures, logos | Not supported | Reported for a person |

**Size.** mTool holds one text per field, and a catch-all field holds several notes, so the limit
applies to the field's whole text. The tiers are v1's: full, compact, lite, flat. A field still over
is "too long for mTool" and nothing is cut. Splitting it is a content decision.

### Database tables

- **`notes`:** run, note number and title as printed, source pages, template, field
  (`notes_nodes.node_uuid`, empty when not placed), part (1 of n, for a first-level split), position
  in the field, blocks (JSON), formatting state (fine, check formatting, not sure) with a reason,
  placement certainty with a reason, confirmed by, times.
- **`note_history`:** note, run, action (place, look, move, clear, confirm, redo, restore), before
  and after (JSON), who (agent or person, and name), round, comment, reason, time.
- **`note_reports`:** run, kind (source gap, missing mandatory field, routed elsewhere), note
  number, field, pages, reason. The coverage record.
- **`comments`:** `note_id` and `note_part` (block, row, column, scope) replace `note_ref`.
- **Unchanged:** share-capital and related-party numbers stay in `figures` with their categories;
  the five house-style values stay in Settings. Preview pictures are PNG files in the run's folder
  and its export.

## 4. The notes agent

### Tools

| Tool | What it does |
|---|---|
| `view_pages`, `zoom_page`, `read_pages`, `search_pages` | The shared page tools |
| `list_notes` | The confirmed notes list, sub-notes, and what is placed so far |
| `show_note_source` | A note's source blocks with ids, across its pages, on to the next note heading |
| `find_note_fields`, `show_note_fields`, `lookup_definitions` | Fields by id with path, mandatory and catch-all marks; taxonomy meanings |
| `place_note` | Places whole source blocks, or one first-level sub-section, in a field by id. Code copies the words. Says so when the blocks are already placed elsewhere, naming the two allowed doubles |
| `set_look` | Look values only. Refuses a row, column or cell that does not exist, in one sentence |
| `preview_note` | Draws the field as mTool gets it on mTool's page (A4, 20 mm margins): pictures, character count against the limit, tier, overflow and the font that fits. Three tries a note; it says how many are left |
| `flag_formatting` | "Check formatting", with one sentence on what still differs |
| `save_figures`, `clear_figures` | The figure store, on the share-capital and related-party outlines |
| `report_gap`, `report_missing_field`, `report_coverage` | A capture problem; a mandatory field the source does not support; code checks every note and the numbering for holes |
| `leave_comment`, `ask_scope` | Shared with the figures agent |

### What its instructions carry from v1, as principles

Each lesson in `agent-lessons.md` sections 4 and 5 is kept once and worded generally:

1. Place a note by its printed heading and main subject. Know a field's meaning before choosing it.
   Use the catch-all when no field fits the whole note. Never drop a real note. Tell policies from
   disclosures by their form.
2. One note, one field. Split only at a first-level sub-section, for materially different topics,
   with the parts holding the whole note (owner, 5 August 2026). Nothing appears twice, except share
   capital in its two fields; related-party text lives only in the related-party template.
3. Copy, never invent: place source blocks, add no total, caption or padding. Account for every
   note and check the numbering for holes. Report a capture problem and carry on.
4. Numeric notes: read a field with its parents, cover every share class, judge each related-party
   category from the entity's side, keep amounts positive, copy a count printed in thousands as
   printed and flag it (owner, 18 November).
5. Look: the source decides which distinctions matter (headings, totals, column roles, real lines,
   shading); the house style decides how they look. Amounts align right. Place a line by its row
   label and both years' amounts. Zoom once on what you cannot read, then mark it "not sure" rather
   than guess. Where mTool cannot draw something, use the nearest house form and say so.
6. Check your own work: preview, compare with the source page, judge what the picture shows, fix
   only what differs. Match this year's and last year's tables by their year line.

Labels, row numbers and note numbers from v1's prompts are dropped (`agent-lessons.md` section 8).

### How it runs beside the figures agent

- Confirming setup queues two jobs, extract and notes, each with its own stage, so one can fail,
  stop or retry alone. The run is ready for review when both have finished or failed.
- The worker runs at most two jobs at once, from different stages (question 6). Writes stay short;
  the renderer keeps v1's one-drawing-at-a-time lock.
- One notes agent, run in sessions as the figures agent runs per statement: corporate information
  and policies, the list of notes, the two numeric notes. Code checks coverage across sessions.
- It uses the "extraction" model on the Settings page. A scope question from either agent stops
  both stages and keeps their work. After it finishes, a note changes only by a person or a round.

## 5. Review screen changes

### Already in the approved prototype (`review-prototype-v3.html`)

- Notes in the left list, grouped by template, with counts; the note on an A4 page, with a skeleton
  while notes are being placed; the source page beside it.
- The toolbar: bold, italic, underline, three alignments, indent in and out, top, bottom, thick
  bottom and no borders; Cell, Row, Column or Table for a table.
- The field dropdown with "Not placed"; Confirm; the "Check formatting" and "Not placed" labels;
  "Double underline shown as thick border" under a selected total.
- Comments on a note or a part, with the five chips and "Redo from source"; the two Needs you kinds.
- Settings, "Notes house style", five values (already built).

### Needs a prototype change, approved before app code

1. **Copy for mTool:** a button that copies the prepared note (question 4).
2. **Too long for mTool:** how an over-limit field and a reduced tier show.
3. **"Not sure" look:** as "Check formatting", or its own mark on the uncertain cells.
4. **Share-capital and related-party numbers:** the prototype shows these notes as text only.
5. **A split note:** one note in two fields ("part 1 of 2").
6. **Undo of a person's own look change** on the note page.
7. **Gaps and missing mandatory fields** the agent reported.
8. **Editing a note's words,** if the owner wants it (question 5).
9. **The agent's preview picture** in review, if wanted. The default keeps it in the traces.

## 6. How notes are judged

- **The answer keys hold no notes placements.** `test-data/answer-keys/` covers the five
  statements; "note" there is the note-reference column. The reading key counts notes for Doc 4 only.
- **v1 has placements to compare with:** Doc 1 runs 318, 319, 330; Doc 2 runs 324, 326, 333, 338;
  Doc 3 runs 325, 328, 329, 331, 340 (18 to 32 notes a run, in v1's `output/xbrl_agent.db`).
- **Proposed keys:** a `notes` section in each answer-key file: each note's field (or fields, for an
  allowed split or double), with a confidence and a reason. Made as the figure keys were: v1's
  placements and a blind reading compared, each difference settled from the page, medium and low
  ones listed for the owner. Not committed (client data).
- **Score:** same field only; wording is not compared (owner, 18 November). Reported as right,
  elsewhere, not placed, and placed but not in the key. The look is judged by a person, plus one
  test: every field within the limit. **Bar:** v1's average over its runs above.
- **Live test:** Doc 1 to 3, two runs each, notes only. On GPT-6 Luna ($0.10 in, $0.01 cached, $0.50
  out a million tokens): about 4 to 6 million input tokens a run, mostly cached, up to 150,000 out,
  pictures the largest part. About 10 to 30 cents a run, **$0.60 to $1.80 in all**. The $5 cap has
  about $4 left. The owner is told before it runs.

## 7. Questions for the owner

| # | Question | Recommended answer |
|---|---|---|
| 1 | Who captures the look: the Reader on every page (`requirements.md` 4.4) or the notes agent (`backend-plan.md` 4.6)? | The notes agent. The Reader keeps the words; the agent adds the look and checks it by preview. No extra reading cost; one place sets the look |
| 2 | Merged cells: kept and split only for mTool, or split when the note is made? | Split when made, so review shows what mTool gets (decision record 1) |
| 3 | Double underline: thick bottom border (Settings default) or v1's single 0.75px line? | Keep the Settings choice, default thick; confirm on Windows |
| 4 | Step 6 needs a way into mTool before step 8's fill. A Copy button and a paste? | Yes. Add Copy (prototype change) |
| 5 | May anyone change a note's words? | Agents never type words: a wrong word is a gap report or a "Redo from source". A person's word edit only if the owner wants it |
| 6 | May the worker run two jobs at once (figures and notes)? | Yes, at most two, from different stages |
| 7 | May the placement keys be drafted from v1's runs and a blind reading, the owner confirming the unsure ones? | Yes |
| 8 | Approve $0.60 to $1.80 for six live notes runs? | Yes, once 6d and 6e pass their scripted tests |
| 9 | Three previews a note, as in v1? | Yes |
| 10 | The three reports stay in step 10? | Yes. Setup's Reports switch does nothing until then |

## 8. Risks

- **The preview is not mTool.** PyMuPDF draws like a browser, not like TX27, and mTool changes
  widths on save. Only Windows shows the truth.
- **Styling makes text large.** v1 saw it grow a note thirteen times; a busy catch-all field can
  pass the limit. The tiers drop styling before content.
- **Pictures cost tokens and steps.** Three previews on 30 notes can exhaust a session. Sessions by
  template and the 12-picture limit hold it; the live test measures it.
- **The Reader's tables carry spans and no look.** Splitting merged cells must not move an amount to
  another column (tested in 6b).
- **Two agents on SQLite.** Short writes; a locked database is retried once, then reported to the
  agent as a sentence.
- **Trimming a 1,289-line decorator** may break a tested case. Its 94 tests are copied and pass
  before anything is trimmed.
- **Keys are judgement.** Several fields can fit one note. Read the key's reason before calling the
  agent wrong, and judge over several runs (the owner's overfitting concern).

## Contradictions found in the existing documents

1. `requirements.md` 4.4: the Reader captures the look, merged cells are stored, one check never
   rewrites a note. `backend-plan.md` 4.6 has a preview loop; decision record 1 stores only what
   mTool accepts (questions 1 and 2).
2. Double underline: decision record 1 and Settings say thick bottom border; v1's
   `MTOOL-NOTES-AUTHORING.md` says v1 writes a 0.75px single line; v1's recon says a 3px double line
   survived at file level (question 3).
3. Step 6's "done when" asks for the look inside mTool, but the fill is step 8 (question 4).
4. `AGENTS.md` and `HANDOFF.md` still point to `review-prototype-v2.html`; decision record 3 says v3
   supersedes it.
5. `HANDOFF.md` says step 5 is not merged; `main` holds it. Its first line says written 19 November,
   updated 18 November.
6. Decision record 1 item 7 ("remember this") was overruled on 18 November and by decision record 3;
   the record is not marked.
