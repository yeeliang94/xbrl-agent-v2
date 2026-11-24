# Step 7 plan — All statements

Written 23 November 2026 on branch `step-7-statements`. The owner said to build and test. Read with
`backend-plan.md` (4, 7), `build-log.md` step 4, decision records 1 and 3, and `agent-lessons.md`.

## 1. What step 7 delivers

The figures agent fills all five statements: the balance sheet (done in step 4), profit or loss,
comprehensive income, changes in equity and cash flows. On a Group run it fills the Group columns
as well as the Company columns. One agent for all five is tested against one agent per statement,
and the better one stays.

**Done when** (from `backend-plan.md` section 7, made checkable):

1. A confirmed setup with all five statements extracts all five. Each statement's agent ends with
   its checks run and its printed lines accounted for.
2. Live on Doc 1, Doc 2 and Doc 3, each statement scores at least v1's average for that statement
   on the same answer key (section 4). Doc 4 stays set aside.
3. A Group run fills the Group and the Company columns, and checks each. Proven with fake models
   only: no test document is a Group filing, and v1 never ran one.
4. One agent for all five and one agent per statement are compared live on score, cost and time.
   The result and the choice are written in the build log.
5. Server tests, the browser build and browser tests pass.

## 2. What is already there

- The outline, the save tools, the figure store, the checks and the scoring work for any statement.
  The review screen shows every statement and both entity columns.
- The job extracts the balance sheet only (`app/extraction/job.py`, `STATEMENTS`), and the agent
  fills the Company columns only (`FiguresDeps.entity`).
- A comment on a Group figure is refused until this step (`app/review/comments.py`, `GROUP_LATER`).
- The equity statement's outline is not usable: each row shows only its total column, so the agent
  cannot see the component columns. Found while planning.
- The answer keys hold field placements for the balance sheet only. The other four statements have
  their printed lines and amounts (certain), but no placements.

## 3. The parts, in build order

### 7a. The equity statement as a grid

- **Builds:** the outline view of the equity statement as rows and columns. The columns are listed
  once (letter, label, and which are totals of which), the rows once (label, line or total, and
  what a total row adds up). A cell's id stays `CE-<row>-<column>`. `show_section` on a row or a
  column shows its cells with what is saved; `find_fields` finds a row label or a column label.
- **Checks:** a fake agent that saves the key's equity cells gets every row and column total right,
  and the outline text names every column.

### 7b. All five statements in the job

- **Builds:** the job extracts every included statement, in the order balance sheet, profit or
  loss, comprehensive income, changes in equity, cash flows. One figures agent fills all of an
  entity's statements (see 7d). The first message and the events name the statements being filled,
  never "the balance sheet" alone.
- The agent's `run_checks` includes the checks across the statements it fills, and across the
  statements finished before it. So it sees profit agree with profit or loss and closing equity
  agree with the balance sheet. Which statements count never depends on the order.
- A statement is finished when the agent's accepted finish covers it: coverage reported for it, and
  the checks run after the last change. Each finished statement gets a mark.
- A failed agent marks nothing finished. The next entity's agent still runs. The stage ends failed
  in one sentence that names the statements left unfinished, even when there is only one. Every
  figure is kept.
- A retry fills only the statements not yet finished. A setup change drops the marks of the
  statements whose figures it cleared.
- **Checks:** a fake agent fills five statements in one stage; a failed agent is named with its
  statements and the next entity still runs; a retry skips a finished statement.

### 7c. Group columns

- **Builds:** on a Group run each statement is filled twice, once for the Group figures and once for
  the Company figures, each run told which columns it fills. The checks run per entity, as they do
  now. A comment on a Group figure is accepted and the Reviewer saves to the entity of the comment.
  The notes agent stays on the Company (the numeric notes for the Group wait for a Group document).
- **Checks:** with fake models, a Group run saves to both entities and checks each; a comment on a
  Group figure is answered by the Reviewer with a Group save.

### 7d. One agent for all five, against one per statement

- **Builds:** the figures agent takes a set of statements rather than one. One statement is the
  case already built. With all five it sees all five outlines and reports coverage per statement.
  Each coverage line's statement comes from its field ids, so one line can serve two statements. It
  finishes only when each statement is covered.
- **Decided (live, six runs):** one agent for all of an entity's statements met or beat v1 on every
  statement of Doc 1 to Doc 3. It was faster (about 400 against 550 seconds) and cost about the same.
  It is the job's only mode.
- **Checks:** a fake agent fills two statements in one run and is refused a finish while one is not
  covered.

### 7e. Answer keys and v1's baseline

- **Builds:** field placements for profit or loss, comprehensive income, changes in equity and cash
  flows in the keys of Doc 1, Doc 2 and Doc 3, made as the balance sheet's were: each line's field,
  a confidence and a reason, medium and low ones listed in `open_points` for the owner. v1's five
  most recent runs per document are a second opinion; every disagreement is settled from the page.
  Then v1's average per statement, scored with the same keys.
- **Checks:** a run that saves exactly the key scores 1.0 on each statement and its template totals
  match the printed totals.

### 7f. Live

- The live test fills all five statements per document and scores each against v1's average for
  that statement. First one run of each mode on each document, then a second run of the better mode.
- **Spend:** about $1.20 to $1.80 estimated against the $2.90 left of the $5 cap. Stop and report if
  it nears the cap.

## 4. Not in this step

- A Group test document. Until the owner gives one, the Group columns are proven with fakes only.
- MPERS (step 9) and the mTool fill (step 8).
- The browser needs no change: the review screen already shows every statement and both columns. If
  a change turns out to be needed, it starts as a prototype for the owner.
