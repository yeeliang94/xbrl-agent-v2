# Decision record 4 — Notes (step 6)

23 November 2026 · Owner · Status: agreed. The owner accepted every
recommendation in `docs/step-6-plan.md` section 7 and approved the live
notes runs.

## Agreed

1. **The notes agent captures the look, not the Reader.** The Reader keeps
   transcribing words. The notes agent sets the look and checks it against
   the page with the preview tool. This replaces `requirements.md` 4.4
   point 1, where the Reader recorded the look.
2. **Merged cells are split when a note is made**, the text in the first
   cell, so the review shows what mTool gets. Every amount stays in its
   column.
3. **A double underline is a thick bottom border**, the Settings default.
   How it shows in mTool is confirmed on Windows.
4. **Notes reach mTool by a Copy button and a paste** until the mTool fill
   in step 8. The Copy button needs a prototype change first.
5. **No agent changes a note's words.** A wrong word is a gap report or
   "Redo from source". Word editing by a person is not built now.
6. **The worker runs at most two jobs at once**, from different stages, so
   figures and notes run side by side.
7. **Notes placement keys are drafted from v1's runs and a blind reading.**
   The owner confirms the unsure ones. The keys are not committed.
8. **Six live notes runs** (Doc 1 to 3, twice each), about $0.60 to $1.80,
   once the notes agent and the review loop pass their scripted tests.
9. **Three previews a note**, as in v1. After that the agent flags the note
   and it shows "Check formatting".
10. **The three reports stay in step 10.** Setup's Reports switch does
    nothing until then.

## Also settled by this record

- The look sits on a whole block, row or cell, never on part of a text: the
  Reader transcribes no inline styling, so there is nothing finer to copy.
- The agent's preview picture stays in the run's traces, not on the review
  screen (plan section 5, item 9).
- `requirements.md` 4.4 point 6 ("one check, never rewrites") gives way to
  the preview loop in `backend-plan.md`: the agent may adjust a note's look
  while it works; after it finishes, only a person or a round changes it.

## Screens

23 November 2026: the owner approved `prototypes/review-prototype-v4.html`
for the notes screens (Copy for mTool, too long, "not sure" rings with
"Check formatting", figures under the numeric notes, split notes, undo of a
person's look change, gaps and missing fields). It supersedes v3 for notes
only. The owner also approved copying v1's six prose-note presentation files
(roles 710000 to 730000) into `templates/`.

## The "note citations agree" check

23 November 2026: the owner dropped this check for now. Each note sits in
one field, so a policy note and its disclosure are on different pages and
comparing them would warn on almost every run. It stays "not assessed"
with that reason (`app/checks/placement_checks.py`). It replaces step 6
plan 6e's "assessed once notes exist".
