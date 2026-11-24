# Answer keys

The correct answers for the four test documents, used to judge the agents.
Written 18 November 2026.

## Where they are

- **Pages and layouts** (step 3, the Reader): inside
  `tests/test_reading_live.py`. Committed, because it holds page numbers
  and layout names only.
- **Figures** (steps 4 and 7, the figures agent): one JSON file per
  document in `test-data/answer-keys/` (`Doc_1.json`, `Doc_2.json`,
  `Doc_3.json`, `Doc_4.json`). **Not committed**: `test-data/` is in
  `.gitignore`, as v1 keeps its `data/` folder out of git, because the
  figures come from client documents. Copy the folder by hand to a new
  machine.

The documents themselves stay where they are: v1's
`/Users/user/Desktop/xbrl-agent/data/` (Doc 1, Doc 2, Doc 3) and the plain
Doc 4 PDF in `test-data/`. The stamped copy is not used.

## How the figure keys were made

1. Two independent readings of every statement page: the GPT-6 Luna
   transcription the Reader saved, and a separate reading by Claude from
   the page pictures, done first and blind. Every disagreement was settled
   by zooming in on the page.
2. Arithmetic checks for both years: every subtotal and total, the balance
   sheet balancing, profit flowing to comprehensive income and equity,
   closing equity and closing cash agreeing with the balance sheet.
3. The balance sheet lines were matched to the MBRS template (MFRS,
   Company, current/non-current): the face row, and the data-entry
   cell(s) on the sub-sheet where each amount is typed, split from the
   notes where the face row is a formula. Each mapping has a confidence
   and a reason.

The two readings agreed on every amount in all four documents. Every
check passes, except where the document itself is wrong, which is
recorded, not corrected (for example Doc 4's line printed "Total
liabilities" leaves out the non-current lease liability).

## What is certain and what is judgement

- **Certain:** every printed line, its amounts for both years, and the
  arithmetic.
- **Judgement:** which template field a line belongs in, and splits taken
  from the notes. Each carries `confidence` and `reason`. Medium and low
  ones are listed under `open_points` for a person to confirm. When an
  agent disagrees with a medium-confidence mapping, look at the reason
  before calling the agent wrong.

## Shape of a file

```
document, source_path, company, year_end, standard, level, unit, periods
statements:
  SOFP: pages, lines[ label, note, kind (heading|line|subtotal|total),
                     cy, py, printed_cy, printed_py, readings, resolution,
                     face_field, entry[ concept_uuid, label, sheet, cy, py,
                                        source, confidence, reason ] ]
  SOPL, SOCI, SOCIE (rows with columns per equity component), SOCF
checks[ check, cy, py ]
open_points[ one sentence each ]
key_version, sofp_entry_total_check
```

Amounts are as printed, in the document's own unit (Doc 1 is RM
thousands). Brackets are negative. A printed dash is 0; a blank is null.

## Notes placements (step 6g)

Each of Doc 1, Doc 2 and Doc 3 has a `notes` section in its key file
(Doc 4 is set aside). Written 23 November 2026.

- **What it holds:** each note in the document's notes list, by number
  and title as printed, with the fields it may go in (field ids from
  `app/catalog/note_fields.run_note_fields`, MFRS Company), a confidence
  and a one-sentence reason. `required` marks a field that must hold part
  of the note; the others are an allowed split at a first-level
  sub-section, or the allowed share-capital double. The opening paragraph
  without a number is under `unnumbered`: judged, not counted.
- **How it was made:** v1's placements across its runs and a blind
  reading of each note against the field list, compared; every
  difference settled from the page. Medium and low ones are in the
  section's `open_points` for the owner to confirm.
- **Confirmed by the owner, 23 November 2026:** every proposed placement
  stands, including the medium and low ones, and a copy of the
  related-party note in "other notes to accounts" counts as wrong (a note
  sits in one field; the plan's allowed doubles are share capital only).
- **Counts:** Doc 1, 13 notes (12 high, 1 medium); Doc 2, 14 (12 high, 2
  medium); Doc 3, 20 (12 high, 7 medium, 1 low).

### The score

`app/scoring/notes.py`, "same field" only; the words are not compared
(owner, 18 November 2026). Per note: right (every placement in a listed
field, and every required field used), elsewhere, or not placed; and the
run's notes the key does not have. The number is right / notes in the key.
It reads a v2 run from its `notes` table and a v1 run from v1's database.

### v1 baseline

`venv/bin/python scripts/score_notes_v1.py` (add `--detail` for each miss),
23 November 2026:

| Document | v1 runs | Average |
|---|---|---|
| Doc 1 | 318, 319, 330 | 0.923 |
| Doc 2 | 324, 326, 333, 338 | 0.893 |
| Doc 3 | 325, 328, 329, 331, 340 | 0.820 |

Most of v1's misses are one habit: it copied the related-party note into
"Disclosure of other notes to accounts" as well as the related-party
field, which the key counts as elsewhere (owner, 23 November 2026: the copy
is wrong). The bar stays 0.923, 0.893 and 0.820. Run 328 (Doc 3) failed part
way and left six notes unplaced.

## Statement placements (step 7e)

Profit or loss, comprehensive income, changes in equity and cash flows
were placed in the keys of Doc 1, Doc 2 and Doc 3 on 23 November 2026
(`key_version` 3; the step 6 copies are kept as `<doc>.step6.json`).
Doc 4 is set aside.

- **How:** the same method as the balance sheet. Each printed line was
  matched to its data-entry cells from the notes and the official
  definitions. v1's five most recent runs were a second opinion, and every
  disagreement was settled from the page. A run that saves exactly the key
  scores 1.0 on each statement, and the template's totals equal the
  printed totals for both years, except where the document disagrees with
  itself (recorded in `open_points`).
- **Equity:** each printed row and column maps to a grid cell
  `CE-<row>-<column>`. The Total column has no entry. Keys whose equity
  statement was written as `rows` gained a `lines` list in the common
  shape.
- **For the owner to confirm** (medium placements, all in `open_points`):
  - Profit, or total comprehensive income, attributable to owners is
    accepted filled or blank when the page prints no split, in all three
    keys.
  - Doc 1: interest paid is lease interest; the general field is also
    accepted.
  - Doc 1: other income stays whole; a split is also accepted.
  - Doc 2: 2024 other income is split into exchange gains from note 10;
    v1's whole amount is also accepted.
  - Doc 2: the low-value lease memo line has no entry.
  - Doc 3: closing cash goes in two data-entry cells, because neither is a
    formula in this template.

### v1 baseline per statement

Complete and accurate, averaged over the same v1 runs as the balance sheet
(Doc 3's equity and cash flows from runs 347 and 348 only):

| Document | Profit or loss | Comprehensive income | Equity | Cash flows |
|---|---|---|---|---|
| Doc 1 | 0.844 | 1.0 | 1.0 | 1.0 |
| Doc 2 | 0.943 | 1.0 | 1.0 | 1.0 |
| Doc 3 | 1.0 | 1.0 | 1.0 | 1.0 |

v1's misses on profit or loss are revenue and cost of sales put in "Other"
fields where a dedicated field fits.
