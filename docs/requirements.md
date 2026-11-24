# XBRL Agent v2 — Requirements for the rewrite

Draft 3 · 17 November 2026 · Source: the current `xbrl-agent` repository at
commit `8ba30614` (main, after PR #64).

Draft 3 adds section 4.8: three proposed changes to the agent design. They
are proposals until the owner confirms them.

This document describes what the new app must do, what it should stop doing,
and the lessons from the current app that it must not lose. It is written to
be read before any code exists. The current repository was read, not changed.

---

## 1. Why we are rewriting

The app works, but it has become too hard to change safely. The owner named
six problems. The current code confirms each one.

| Problem | What the code shows |
|---|---|
| **Flows and agent coordination are too complex** | About 15 different AI agent roles. The main run is one function of about 3,400 lines inside a 9,500-line server file, changed in 190 commits. Reviewers, formatters and preparation each run on their own background threads with special rules to stop them clashing. |
| **The notes formatting pipeline breaks easily** | Notes pass through about ten steps that each touch formatting: page capture, page checking, a clean-up agent, a formatter agent, a visual review agent, a table re-copy loop, a cleaner, the editor, clipboard styling and mTool styling. These files have had about 140 commits. The notes review screen alone has had 92. |
| **Review screens do not help enough** | A run has six or seven tabs: Overview, Figures, Notes, Cross-checks, Activity, AI review and Values. The two largest screens are over 3,000 lines each. There is no way to sign off a review, so "processing finished" and "ready to file" are easy to confuse. |
| **Unused features add weight** | Repeat runs and benchmark evaluations are already switched off. They still leave about 12 database tables and their migration steps behind. |
| **Design is inconsistent** | There are three design documents (a design system, a prototype and an implementation matrix) plus your personal taste guide. They do not fully agree. For example, the app's main button is orange; your taste guide asks for black. |
| **(Found while reading) Rules are hard to keep track of** | A 3,800-line rules file of 31 numbered rules, 78 database tables after 56 schema versions, 33 advanced settings and about 5,200 automated tests. Each rule exists because something went wrong, but together they make every change slow. |

**The aim of v2:** the same results for accountants, from a design small
enough that one person can understand the whole run in an afternoon.

---

## 2. What the product must do

### 2.1 The job

An accountant uploads a company's audited financial statements, as a PDF or a
Word file. The app reads them and fills the SSM MBRS filing template, so the
accountant can check the result and file it through mTool. mTool is SSM's
Excel add-in that produces the final XBRL filing.

### 2.2 What it must cover (unchanged from today)

- **Two accounting standards:** MFRS (full) and MPERS (private entities).
- **Two filing levels:** Company, and Group (Group plus Company figures side
  by side).
- **Reporting periods:** current and prior year. "First financial statements"
  files the current year only.
- **Five main statements, with their layouts (variants):**
  - balance sheet (SOFP): current/non-current, or order of liquidity
  - profit or loss (SOPL): by function, or by nature
  - comprehensive income (SOCI): before tax, or net of tax
  - cash flows (SOCF): indirect, or direct
  - changes in equity (SOCIE), or retained earnings (SoRE) on MPERS only
  - the sub-schedules ("analysis" sheets) behind each statement
- **Five notes templates:** corporate information, accounting policies, list
  of notes (Sheet 12), issued capital and related parties.
- **Three reports:** directors' report, statement by directors and auditors'
  report, each with its text and its structured fields such as signers, dates
  and audit opinion.
- **Prior year from last year's mTool file (rolled-forward workbook):** read
  last year's figures from the workbook instead of the PDF. Recently built
  and merged.
- **Output:** a filled copy of the user's own mTool template, with a receipt
  that lists what was written, what was left out and why.
- **Accounts:** email and password login, admin-managed users, shared runs,
  an audit log and "Report an issue".
- **Where it runs:** Mac for development, the Windows enterprise machine
  through the company's AI service gateway (proxy), and later Azure.

### 2.3 Keep, change or drop

| Feature | Decision | Note |
|---|---|---|
| PDF upload | Keep | The backbone of everything. |
| Word upload | Drop | Decided 18 November 2026: uploads are PDF only on every machine. A Word file is refused with one sentence: save it as a PDF in Word, then upload that. |
| Page preparation (reading each page into structured text) | Keep, simplify | It is the right foundation. See section 4.3. |
| Scout (document map: where each statement and note is) | Keep, merge into preparation | One step builds the map, not a separate agent run. |
| Five statements and all variants | Keep | |
| Notes templates | Keep | Notes keep the source look through a much shorter formatting pipeline (section 4.4). |
| Reports | Keep | |
| Rolled-forward prior-year workbook | Keep | Recent, real customer need. |
| Cross-checks (balance sheet balances, profit flows to equity, cash ties) | Keep | Plain code, no AI. Proven and valuable. |
| AI reviewer | Keep one | One reviewer for figures and notes, started only by real failures. |
| Notes formatter agent, visual review agent, table re-copy loop | Drop | Formatting becomes code (section 4.4). |
| Notes clean-up agent | Drop | Page headers and footers are removed during preparation. |
| Clean-run "triage" review and focused investigations | Drop at first | Add back only if parity testing shows it catches real errors. |
| mTool fill (Excel-free file patching) and receipts | Keep, reuse code | Proven. Copy it across with its tests. |
| Old "download filled Excel" | Drop | Already replaced by mTool fill. |
| Human-file comparison (AI result vs the accountant's own mTool file) | **Decide** | Strong candidate to keep. It is how we prove v2 is as good as v1. |
| Repeat runs, benchmarks, evaluation suites | Drop | Already off. Nothing carries over. |
| Field-label editing page | **Decide** | Unclear whether anyone uses it. |
| Shared agent instructions (admin-written extra guidance) | Keep | Small and useful. |
| Per-company memory (hints from last year's run) | **Decide** | Rolled-forward workbooks may cover the same need. |
| Users, roles, audit log, issues | Keep | Rebuild as-is. |
| Detailed agent activity and traces | Keep, hide | Kept on disk for diagnosis. Not part of normal review. |
| 33 advanced settings | Cut to about 8 | Only settings a person actually changes. Everything else is fixed in code. |

---

## 3. Lessons we must carry over

These come from the 31 rules in the current `CLAUDE-REFERENCE.md`. Each one
cost a real failure to learn. They are written as plain requirements so v2
can meet them by design rather than by patching.

### 3.1 Numbers must be right, or visibly wrong

1. **Never force a total to balance.** The AI must not put a leftover amount
   into an "Other…" row to make totals agree. An imbalance stays visible.
2. **Section-heading rows never take a value.** Template rows that are only
   headings (XBRL "abstract" rows) refuse writes.
3. **A missing line is not zero.** A zero is stored only when the report
   prints a zero or a dash, and the source must be cited.
4. **Copy figures exactly as printed.** Never multiply or divide for
   thousands or millions. Units are declared once in setup.
5. **Store each figure once, by meaning.** Each figure is saved against its
   taxonomy concept, period and entity (Group or Company). Checks, review and
   export all read that one store. Today this is called the canonical concept
   model, and it is the right design.
6. **Template totals come from SSM's official calculation rules**
   (linkbase). They are generated by script and never typed by hand.
7. **Signs follow the template's formula.** For example, dividends are
   stored positive and the formula subtracts them. A sign-only difference
   against last year is left for a person to decide.
8. **Group filings are checked twice:** once for the Group columns and once
   for the Company columns.
9. **Company profit must be attributed to owners**, even when the report
   prints no split. Missing non-controlling interest stays blank.

### 3.2 The source document is the authority

10. **Map hints are advice only.** Agents may read any page. Nothing limits
    which pages they can see.
11. **Every figure and note cites its source page**, and the review screen
    opens that page.
12. **Notes content is copied from the source, never invented.** If capture
    is missing or broken, the app says so and leaves a visible gap.
13. **Notes matching is AI judgement**, not a dictionary of label synonyms.
    (This was decided on purpose, because report layouts vary widely.)
14. **An unfinished check is "unresolved", never "clean".** Applies to note
    coverage, source checks and review. False "all clear" results caused
    the worst incidents.

### 3.3 Runs must always finish properly

15. **Every run ends in a final status**: completed, completed with errors,
    failed or stopped. Never stuck on "running", even after a crash or
    restart.
16. **Saved work survives failure.** If a later step breaks or the user
    presses Stop, figures already extracted remain available.
17. **A retry of one statement stays inside its run.** It does not create a
    new run that loses the others.
18. **Agents stop on their own step limit** before the AI library's hidden
    limit of 50 calls, so a long document ends with a clear message, not a
    crash.

### 3.4 AI providers and the enterprise machine

19. **Each model needs its own connection settings.** GPT models must use
    OpenAI's Responses interface. Gemini cannot go through a remote proxy,
    because it loses required tool-call data. Gemini 3 needs temperature 1.0.
    Reasoning levels differ by model. Keep all of this in one model factory.
20. **Windows needs UTF-8 mode** (`PYTHONUTF8=1`) and the operating system's
    certificate store for the corporate network.
21. **Write files atomically** (write to a temporary file, then swap it in),
    so a reader never sees half a file.
22. **Keep full agent transcripts on disk**, including failed ones. Never put
    them in the database.

### 3.5 mTool output

23. **Find cells by taxonomy meaning, not position.** Never guess a cell.
    Ambiguous columns ask the user to confirm.
24. **Patch the mTool file directly** (zip and XML), without Excel, so it
    runs on a server. Read back every write to confirm it.
25. **mTool text-block limits are real** (about 32,767 characters per note).
    Note tables cannot contain merged cells in mTool's editor.
26. **Every fill writes a receipt** of what was written, skipped and changed.

### 3.6 Security

27. **Every API route needs login**, except login itself and the health
    check. Permissions are checked on the server, not just hidden in the
    screen.
28. **Production refuses to start in development login mode** or without a
    session secret.
29. **File access stays inside the app's own folders.** This was a Veracode
    finding.

---

## 4. How v2 should be built

### 4.1 Design principles

1. **Code does what code can do; AI does only judgement.** Reading a printed
   number off a page and deciding which template line it belongs to is
   judgement. Adding up, checking, formatting, styling and writing files are
   code.
2. **Few agents with clear jobs.** Target four agent roles, down from about
   15 (section 4.2).
3. **A run is a simple list of stages.** Each stage reads from the database,
   does its work and saves its result before the next starts. The screen
   reads progress from the database. One long function streaming events to
   the browser goes away.
4. **One way to do each thing.** One notes format, one review screen, one
   button style, one status vocabulary, one model factory.
5. **No feature switches for unfinished ideas.** A feature is either in the
   product or not built yet.
6. **Fresh database, no migration history.** v2 starts with a clean schema.
   Old runs stay readable in v1.

### 4.2 The four agents

| Agent | Job | Replaces today's |
|---|---|---|
| **Reader** | Turns each page into structured text and tables, with their look (section 4.4), then builds the document map: where each statement, note and report is. | Page capture, page checking, boundary repair, Scout, Scout vision, clean-up agent |
| **Statement extractor** | One per statement. Reads the pages and records each figure against its template line, citing the page. | Five face agents and their sub-sheet handling |
| **Notes placer** | Decides which source note goes to which notes template field, and pulls out the numbers for issued capital and related parties. It places source blocks; it does not rewrite them. | Five notes agents, Sheet 12 sub-agents, report agents |
| **Reviewer** | Runs only when a cross-check fails or a note is unplaced. Traces the cause to the page and proposes a fix, or flags it for a person. | Figures reviewer, triage, focused investigations, notes reviewer |

All four share one loop: one way to call a model, retry, stop, record usage
and save a transcript.

Section 4.8 proposes testing a smaller design: one extractor for all
statements, with the Reviewer used less often.

### 4.3 The run, stage by stage

1. **Upload.** Store the PDF. Uploads are PDF only; a Word file is refused.
2. **Prepare.** The Reader turns pages into structured content and builds the
   document map. It suggests the standard, level and variants.
3. **Confirm setup.** The user checks the suggestions and chooses what to
   extract. This is the only point where the user must act before
   extraction.
4. **Extract.** Statement extractors and the notes placer run in parallel.
5. **Check.** Cross-checks run as plain code, plus a notes coverage list.
6. **Review (AI).** Runs only when step 5 found problems.
7. **Human review.** One exceptions queue (section 4.5).
8. **Prepare filing.** Fill the user's mTool template and write a receipt.

Each stage has a status row in the database: waiting, working, done, failed
or stopped. Stopping or crashing at any stage leaves earlier stages intact.

### 4.4 Notes formatting: follow the source, through one short pipeline

**The goal:** notes look as close as possible to the source document. Where
the source is unclear, a default house style fills the gap.

**The problem today is the pipeline, not the AI's output.** A note's look
passes through about ten steps, each with its own rules: page capture, page
checking, a clean-up agent, a formatter agent, a visual review agent, a table
re-copy loop, an HTML cleaner, the editor, the clipboard styling and the
mTool styling. Each step can undo or contradict the one before, so a fix in
one place breaks another.

**v2: the look is captured once, stored once and drawn by one piece of code.**

1. **Capture the look once, at preparation.** When the Reader reads a page, it
   records each note as blocks (heading, paragraph, list, table) together with
   how they look in the source:
   - text: bold, italic, underline, heading level, indent, alignment
   - tables: rows and cells, merged cells, column widths, alignment, cell
     borders, double underlines under totals, shading and number formats
   - Uploads are PDF only, so the AI describes what it sees on the page in
     this fixed vocabulary. (Reading the look from a Word file's own styles
     was dropped with Word uploads on 18 November 2026.)
2. **Mark anything uncertain.** If the AI cannot tell (for example, whether a
   faint line is a border), it leaves that property as "not sure" rather than
   guessing.
3. **The default style fills only the gaps.** One house style, written in code
   and editable in Settings, supplies a value for anything the source did not
   show clearly. It never overrides what the source did show.
4. **One renderer draws every output.** The same code turns the stored look
   into the review view, the clipboard copy and the mTool text block, so they
   cannot drift apart. mTool's own limits are handled here only. For example,
   merged cells are split because mTool's editor cannot handle them, and size
   limits are checked before filling.
5. **Edits change the stored look**, not raw HTML. If a person fixes a
   border in review, every output shows the fix.
6. **One check, no repair loops.** After capture, one comparison against the
   page image flags differences for a person. It never rewrites the note on
   its own.

The notes placer (section 4.2) moves blocks with their look attached. It does
not restyle them.

This removes the formatter agent, visual review agent, table re-copy loop,
clean-up agent and most of the cleaner's rules. The app went partway in
October, when the formatter started describing table layouts and code
applied the styles. v2 makes that the only path and moves it to the start of
the pipeline.

### 4.5 Review: one exceptions queue

Today the user moves between tabs to find problems. In v2, review starts
from **one list of things that need a person**:

- failed cross-checks
- figures the reviewer changed or flagged
- notes not placed, or placed with low certainty
- differences from last year's figures
- mTool cells that could not be addressed

Each item shows the problem in one line, the source page beside it, and the
actions: accept, edit or dismiss with a reason. **Figures** and **Notes**
remain as browse-and-edit views for anyone who wants to look at everything.
Agent activity moves behind a "Technical detail" link.

**Review sign-off: dropped** (owner, 18 November 2026). There is no
"Reviewed" step. The mTool file can be prepared as soon as the run is not
busy.

### 4.6 One design system

- **One source of truth:** a single design document plus one theme file in
  code. Your taste guide (`~/.agents/taste/ui.md`) is the starting point.
- **One component per job:** one button family, one switch, one dropdown,
  one table, one status pill and one dialog. They are built first, before
  any screen.
- **Every screen answers three questions in five seconds:** where am I, what
  needs attention, and what can I do next? This is kept from today's design
  rules, which got this right.
- **Prototype first.** Each screen starts as an HTML prototype you approve.

### 4.7 Technology

Recommendation: **keep the same languages and main libraries.** That means
Python with PydanticAI and FastAPI behind, and React in front.

- The proven, self-contained parts can be **copied across with their tests**:
  the templates and taxonomy files, the template generators, the template
  parser, the cross-checks, the mTool patcher and its receipts, the page
  viewer, the login system and the model factory.
- The parts that carry the complexity are **rebuilt**: the run coordinator,
  the agents and prompts, notes storage and formatting, the review screens
  and the database schema.
- **Database:** SQLite to start (as today), designed so it can move to a
  server database on Azure. PR #64 recently made this change in v1.
- **Styling in the browser:** inline styles were chosen in v1 because
  Tailwind failed on Windows. v2 should use one approach that is tested on
  the Windows machine from the first screen.

### 4.8 Proposed changes to the agent design (17 November 2026)

**Status: proposed, not yet confirmed.**

Source: Anthropic's article "Building agents: When to fold subagents into
your main agent loop" (22 October 2026). Its main claim is that one agent
that sees everything often beats several specialists that pass summaries to
each other, on quality, cost and speed. It says separate agents are still
right for parallel, self-contained jobs that hand back a compact result.
The Reader is that kind of job, so it stays separate.

1. **Build the scoring set first.** Before any agent is designed, fix a set
   of test documents with known right answers, taken from the accountants'
   own mTool files. Ten documents are enough to start. Each document is run
   more than once, because one run can pass by chance. Every later design
   choice is judged against this set, and we look at which figures changed,
   not only the total score. This moves the human-file comparison from
   slice 7 into slice 0, as an internal tool.

2. **Test one extractor against five.** Section 4.2 keeps one extractor per
   statement. The statements depend on each other: profit flows into equity,
   and cash ties to the balance sheet. One extractor that sees all of them
   may make fewer of the mismatches that the cross-checks catch today. Five
   in parallel is faster and keeps each agent's reading load small. Build
   both in slice 2 and let the scoring set decide on accuracy, time and
   cost.

3. **Let the extractor run the cross-checks itself.** The cross-checks stay
   plain code, and they also become a tool the extractor can call before it
   finishes. If a check fails, the extractor sees the result with the page
   still in view and can correct the figure. It must still never force a
   balance (lesson 1): a failure it cannot explain from the page stays
   visible. The Reviewer then runs only on what is still failing, as a
   second opinion.

**Not proposed yet:** loading each statement's instructions only when needed
("skills"). A skill-first attempt in v1 was dropped on 2 November 2026. The
reason needs to be recorded before this is proposed again.

---

## 5. Build order and switch-over

Build in thin slices. Each slice works from upload to output before the next
one starts.

| Slice | Delivers | Done when |
|---|---|---|
| 0. Foundations | New repo, design system components, login, model factory, run stages, database | You can log in and see an empty run list on Mac and Windows |
| 1. One statement | Upload → prepare → SOFP, MFRS Company → checks → review queue → mTool fill | Doc 4 SOFP matches v1 or the human mTool file |
| 2. All statements | SOPL, SOCI, SOCF, SOCIE and all variants; Group level | Doc 1–3 face figures match or beat v1 |
| 3. Reviewer | One reviewer for failed checks | Fixes at least what v1 fixes on the test documents |
| 4. Notes | Structured notes, notes placer, house style, mTool text blocks | Notes pass mTool's limits and look right in mTool on Windows |
| 5. MPERS | Second standard, SoRE | MPERS test document matches v1 |
| 6. Reports and prior year | Reports and rolled-forward workbook | Feature parity with v1 |
| 7. Switch-over | Side-by-side runs, then retire v1 | Agreed parity on an agreed document set |

**How we prove v2 is good enough:** run the same documents through v1 and
v2 and compare both against the accountant's own mTool file. That is the
human-file comparison, which is why it should probably stay. v1 keeps
running until v2 passes.

---

## 6. Decisions needed from you

1. **Default style:** what should the fallback house style be? Today's
   accountant style (ruled tables, double underline under totals) is the
   obvious starting point. *Recommendation: start from today's style.*
2. **Human-file comparison:** keep it as a product feature, or only as an
   internal parity tool? *Recommendation: keep it, at least as an internal
   tool.*
3. **Old runs:** do v1 runs need to appear in v2, or is v1 kept read-only
   for history? *Recommendation: keep v1 read-only; import nothing.*
4. **Brand colour and primary button:** settled on 18 November 2026. Black
   primary button, with orange only as a marker. v1's theme file already
   works this way, so section 1's line about an orange main button was
   wrong.
5. **Field-label editing page and per-company memory:** keep or drop?
   *Recommendation: drop both until someone asks for them.*
6. **Review sign-off:** should "Reviewed" need a second person, or can the
   preparer sign off their own run?
7. **Repository:** create a new private GitHub repo now
   (`yeeliang94/xbrl-agent-v2`)?
8. **Agent design proposals (section 4.8):** confirm or reject each of the
   three. *Recommendation: confirm all three.* Proposal 1 needs about ten
   documents that have an accountant's own mTool file. Which documents can
   we use?

---

## 7. Not checked

- **Feature usage:** keep/drop decisions are based on the code and your
  description, not on usage data. Run history in v1's database could confirm
  which features are used, if you want that check.
- **Accuracy today:** no live runs were made for this document, so no claims
  are made about v1's current accuracy.
- **Windows and Azure:** the deployment needs in section 2.2 come from the
  rules file and memory notes, not from a test on those machines.

## Appendix: the current app in numbers

| Measure | Value |
|---|---|
| History | 837 commits since 7 April 2026 |
| Backend code (excluding tests) | about 111,000 lines of Python |
| Frontend code | about 73,000 lines of TypeScript |
| Largest file | `server.py`, 9,464 lines; the main run function is about 3,400 lines |
| AI agent roles | about 15, built in 13 files, with 30 prompt files |
| Database | 78 tables, schema version 56 |
| Settings | 33 advanced settings, plus the general settings |
| Tests | 496 backend test files (about 5,200 tests), 98 frontend test files |
| Rules file | 3,836 lines, 31 numbered rules |
