# What v2 can take from the Document Agent

22 November 2026 · Status: proposal for the owner. Nothing is built.

The Document Agent (`/Users/user/Desktop/Document Agent`) is a separate app:
one agent with a Python sandbox turns a folder of files into a workbook. It
has a working loop where a person reviews, corrects and guides the agent,
and the agent learns from it. This note compares that loop with v2's plan
(`backend-plan.md`, decision records 1 and 2, `review-prototype-v2.html`)
and proposes what v2 should take, mostly in step 5.

## 1. What v2 already has or plans

v2's prototype is already ahead on some points. Keep these as they are.

- Comments on a figure, a line, a statement or part of a note, sent as one
  round.
- A per-comment outcome from the agent: Changed, Not changed, Question, with
  Accept, Undo and Reply. The Document Agent has no per-comment answer at
  all; it only reports what changed.
- A source page beside every figure, and "Unsure" with a reason.
- An Activity tab that fills while the agent works.
- Live checks after every edit, and history on every write.
- Guidance per company and firm guidance.
- Agents can leave comments and raise flags (planned, not built).

## 2. What v2 lacks, and should take

In order of value. "Where" says which step it fits.

### 2.1 The server, not the agent, says what changed (step 5)

After every save in a round, the Document Agent's server compares the files
with a copy taken when the round was sent. It tells the agent, and the
person, three things per comment: "was X, is now Y", "not changed, because
…", and **what changed elsewhere that nobody asked for**
(`app/feedback.py:441-502`).

For v2: build this from figure history, which already exists. For each
round, list per comment the figures it touched (before and after), and
separately every other figure the round changed. Feed it back to the agent
in the save tool's reply, and show "Changed elsewhere" in the review list.
Why: the agent's own claim "Changed" is not proof, and an unasked change to
a total or another statement is the mistake a reviewer misses when
skimming.

### 2.2 Questions only about the run's scope (step 5)

The Document Agent's `ask_user` tool shows a card: the question, the
evidence (value, file, where), up to four choices with one marked
"Suggested", a free-text box and "Let the agent decide". It allows three
questions per run (`app/engine/agent.py:458-485`).

**Owner's direction (22 November 2026):** v2 does not ask about single
figures. The agent decides, and the person reviews and comments in the
review screen. A question is only for a fact that changes the whole run:
the scope.

Scope means what the setup screen holds: the standard (MFRS or MPERS), the
level (Company or Group), the year end, the unit (RM or RM'000), which
statements are printed and their layouts. A wrong answer there makes every
later figure wrong, so it is worth stopping for.

There are two moments for such a question:

1. **At setup.** This stop already exists. The Reader marks each suggestion
   it is unsure of. For those, the setup screen shows the question card
   (5.1) instead of a plain field.
2. **During extraction.** An agent finds evidence against what was
   confirmed: MPERS wording in a run set up as MFRS, Group columns in a
   Company run, a unit that differs from the one confirmed. It raises a
   scope question with its evidence. That stage stops and keeps its work.
   The run shows "Needs you". The answer either confirms the setup (the
   stage carries on) or changes it (the affected stages start again).

Everything else goes to the review screen: Unsure figures with the agent's
reason, its comments and its flags.

### 2.3 Comment on a spot on the source page (step 5)

In the Document Agent a person can click any point on a PDF page and
comment; the server draws a numbered pin on the page picture and sends that
picture to the agent (`feedback.py:252-313`).

v2's comments attach only to things the agent already saved. A line the
agent missed has nowhere to attach. For v2: allow a comment on a point of a
source page ("this line is missing"), sent with the pinned page picture.
Why: missing lines are a common v1 failure, and today the reviewer would
have to describe the place in words.

### 2.4 Send a message while the agent works (step 5 or 7)

The Document Agent lets a person type to the agent while it runs. The
message is delivered between turns, so no tool call is cut off, and it is
kept so a resumed run still follows it (`app/engine/service.py:118-149`).

For v2: an "Add guidance for this run" box during extraction ("the
statement of cash flows starts on page 14"). Why: today the only choice is
to wait for the run to finish, then send a correction round.

### 2.5 Rounds that survive retries and restarts (step 5)

The Document Agent gives each round an id from the browser, so a retry does
not send the round twice. A round moves from saving to sent to delivered to
done. It keeps a copy of the outputs taken when the round was sent. Comment
text and file values reach the agent quoted, so a comment cannot pass for an
instruction (`feedback.py:206-237`). The message also says: apply a
rule-like comment everywhere the same thing occurs.

For v2: copy these four habits into the rounds table and the Reviewer's
message. They are small and prevent double rounds and lost rounds.

### 2.6 Past corrections become tests (after step 5, before step 7)

Each lesson in the Document Agent keeps a test: the run's files, the spot
corrected and the value accepted. At most 20 per playbook. When the
instructions change, the tests are re-run and the screen shows "Past
corrections: 14 of 15 still right" (`app/cases.py`, `app/replay.py`).

For v2 this fits better than it does there. v2 already scores a run against
an answer key (step 2). Every accepted correction is one more answer-key
line: document, field, period, value. Collected over time, they become a
growing test set built from real reviews. Re-run it before any change to
the agents' instructions. Why: it answers the owner's overfitting concern
with evidence. A prompt change that fixes Doc 1 and breaks an earlier
correction on Doc 2 shows up before it ships.

### 2.7 Guidance with versions and Undo (step 5)

Every save of a Document Agent playbook is a new version. A save based on an
old version is refused, so two people cannot overwrite each other. Any
version can be restored (`app/playbooks.py:136-186`).

For v2: company and firm guidance keep versions the same way, with Undo.
Each run records which version it used. Why: when a run goes wrong, the
first question is "what guidance did it have?".

### 2.8 Last year's run of the same company as a reference (step 7 or 10)

The Document Agent offers the last three finished runs of the same kind of
work. The agent opens one when it helps with layout and conventions. It is
told never to copy values (`app/engine/pastruns.py`).

For v2: offer the same company's last reviewed run. The agent can see which
field each line was filed in last year, and what the reviewer corrected.
Values still come only from this year's document. Why: the hard choices
are field choices, and the company's own past answer is the best guide.

### 2.9 Smaller items

- **Self-describing steps.** Each agent step carries a one-line description
  that the Activity tab shows as it is. Clearer than tool names.
- **A daily spend limit** on the Settings page. The run pauses and says why
  when it is reached.

## 3. A decision for the owner: learning from corrections

On 18 November the owner decided: no "remember this" feature; guidance is
per company, plus firm guidance for admins.

The Document Agent went further. The agent that made a fix writes the
lesson itself with a `remember` tool. A lesson is kept only if the run then
passes its checks and the commented spot really changed. It appears with an
Undo. Each lesson keeps a test (2.6), and a tidy of the instructions is
saved only if every test still passes. Measured result there: the agent
judged well in 3 of 4 live tests, on very few runs.

A middle way for v2 that keeps the owner's rule:

- After a round, the agent may **propose** a line of company guidance from
  a correction. The person adds it with one click or ignores it. Nothing is
  added by itself.
- Firm guidance stays admin-only and typed by a person.
- Every guidance line keeps the correction it came from as a test (2.6).

Options: keep the decision as it is; take the middle way; or take the
Document Agent's approach in full.

## 4. What not to take

- **Skills and programs inside skills.** v2 decided against skills (decision
  record 1).
- **Automatic tidying and the curator model call.** Useful only once
  guidance grows long. Revisit when it does.
- **Questions about single figures.** The agent decides; the person
  reviews (2.2). Only a scope question stops a stage.
- **The cell-by-cell comparison.** It shows an inserted row as many
  changes. v2 stores figures by meaning, so compare by field and period.
- **A comment with no answer.** v2's Changed / Not changed / Question is
  better; keep it.

## 5. Screen and interaction lessons

Sources: the running app, and three approved or proposed prototypes in the
Document Agent: `prototype/question-card/`, `prototype/live-steps/` and
`docs/local/prototypes/playbooks-review-queue.html`. Each item says how it
would look in v2.

**Prototype:** `prototypes/review-prototype-v3.html` (22 November 2026, not
yet approved). It is v2's prototype plus 5.1 to 5.3, 5.6 and 5.7. The bar
at the foot has two new states, "Setup question" and "Scope question". The
scope choices are labelled Figure, Run and Company to fit the side panel.
`review-prototype-v2.html` is unchanged, for comparison.

### 5.1 The question card

When the agent is unsure, it shows a card, not a sentence.

- **The question is the heading.** "Which start date should I use for Aina
  Rahman?"
- **The evidence sits under it.** Each line is a value and where it came
  from, and the source is a button that opens it. "17 Nov 2026 ·
  Joiner_AinaRahman.pdf", "3 Nov 2026 · Payroll_Input.xlsx, row 48".
- **Up to four choices.** Each has a short label and one line saying what
  follows from it ("Pays 14 days in November"). The agent's best choice is
  marked "Suggested".
- **"Something else"** is a text box inside the card, in the same list as
  the choices. The page's own message box hides while the card is open, so
  there is one place to answer.
- **"Let the agent decide"** is a quiet link at the foot.
- **Keys 1 to 5** pick a choice. Picking folds the card into one line: the
  question, then the answer.
- **A question with no choices** ("What account number should I use?") shows
  only the text box.

In v2 the card is used only for scope (section 2.2). For example, during
extraction:

> **This looks like an MPERS filing. Which standard applies?**
> "Malaysian Private Entities Reporting Standard" · page 3, auditor's report
> "Statement of income and retained earnings" · page 7
> 1 MPERS · Suggested · *Restarts extraction with the MPERS templates*
> 2 MFRS, as set up · *Carries on; the wording is noted*
> 3 Something else …

At setup, the same card replaces a plain field wherever the Reader is
unsure.

### 5.2 One "Needs you" list

The review-queue prototype gathers everything that needs a person into one
list. Each item carries a short reason: "Sources disagree", "Check failed",
"12 alike". Items that are alike are answered once: "Accept all 12", "Leave
all 12 out", "Show me each one". The list ends with a count of what passed:
"214 other values passed their checks".

In v2 today these are spread out: Unsure figures, failed checks, unplaced
notes, comments and (planned) agent flags. There are no questions about
single figures (section 2.2), so this list is where the agent's doubts
reach the person. One "Needs you" tab with a count
gives the skimming reviewer a single place to start, and the closing count
tells them what they may skip. Each item opens its figure with the source
page beside it.

### 5.3 Right or Wrong, with a scope

Clicking a value opens a small panel:

- **Where it came from.** The source line as text, with the matched number
  highlighted, and a button to open the page.
- **Right / Wrong.** Right confirms the value. Wrong opens a note box,
  already focused.
- **Apply to: This value · This run · Always.** One row of choices under the
  note.

This replaces a separate "remember this" button. It also fits v2: "This
figure" fixes one cell, "This run" asks the agent to apply the same fix
wherever it occurs, and "This company" proposes a line of company guidance.

### 5.4 A proposed lesson shows what it would change

When a correction is scoped "Always", the prototype shows the lesson as a
card: "Save as a lesson?" with the wording, where it will be saved, and a
re-check against earlier runs. Either "2 good examples unchanged", or
"Would change Oct 2026 payroll: E1061 Basic pay 2,750.00 → 2,566.67". The
buttons are "This run only" and "Save lesson". After saving, the line reads
"Lesson saved, version 4" with Undo.

For v2: before a company guidance line is saved, re-run it against that
company's earlier corrections (section 2.6) and show any figure it would
change. The reviewer sees the consequence before agreeing.

### 5.5 Guidance beside the run

A drawer opens the playbook beside the run, and a lesson waiting for
approval appears in the place it would be saved, with Accept, Edit and
Reject. The run header shows which version the run used.

For v2: the company's guidance opens from the run, with the version the
run used. A proposed line shows in place.

### 5.6 Watching the agent work

- **Steps are plain sentences in the agent's own words.** "Read the new
  joiner forms", "Checked allowances against the approved claims".
- **Each step's files are buttons** that open the file. In v2 they would be
  page numbers.
- **One live line** shows the current step with a pulsing dot and a timer.
- **Finished steps fold** into "Worked through 7 files · 2m 24s". A step
  that failed is marked, and the folded group shows "1 problem".

v2's Activity tab lists steps. It would gain the agent's own wording,
clickable pages and folding.

### 5.7 The agent's reply to a round

After a round, the conversation shows the person's comment, a folded
"Corrected 4 cells · 12 s", then one plain sentence from the agent: "Fixed
Raj Kumar. Mei Chen joined on 3 Nov, so I applied the same rule to her."
The app adds "Changed 2 of 2 commented spots. 2 other changes in the
files". Changed cells turn green in the viewer.

v2 already gives each comment Changed, Not changed or Question. Add the
one-sentence summary of the round and the app's own count, including
"other changes" (section 2.1). In the grid, mark the figures the round
changed until they are accepted.

### 5.8 Commenting

- **Click any cell, line or point on a page** and a small box opens. Its
  title is the spot ("One-time Payment, cell D6"), with one field, "What
  should change?".
- **A draft survives a click elsewhere.** Nothing typed is lost.
- **Numbered pins** mark each comment on the page.
- **A strip under the viewer** reads "3 comments on 2 files" with **Send to
  agent**.
- **Clicking a row** shows "Row 6 came from" with its source files. Opening
  one gives a Back button to the row.

v2 keeps its quick chips ("Recheck", "Wrong field", "Wrong sign"). It adds
drafts that survive, numbered pins on the source page (section 2.3), and a
Back button after jumping to a source.

### 5.9 Smaller touches

- **Name a page while typing.** Type @ to point at a file in a message to
  the agent. In v2, "@page 14".
- **Keep as good example.** One button marks a finished run as a reference
  for the next one (section 2.8).

### 5.10 What not to copy on screen

- **Tinted status pills** ("Checked", "Passed"). v2's rule is a dot and a
  word.
- **The conversation as the main view.** v2 is grid first, with the source
  page beside it, and that suits figures. The conversation belongs in the
  Activity tab.
- **A status pill in the run header.** The owner removed it from v2 on 18
  November. "Needs you" belongs in the run list and the tab count.

## 6. Not checked

- The running Document Agent was opened in a browser: the run screen, the
  output viewer, the comment box and row sources were seen. No open
  question and no saved lesson existed on this machine, so the question
  card, the "Needs you" list and the lesson flow were read from the
  prototypes and code only.
- Its live results come from one to three runs per feature.
