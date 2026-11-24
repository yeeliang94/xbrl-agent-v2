# XBRL Agent v2 — Backend plan

Draft 6 · 19 November 2026 · Status: for the owner's review. Nothing is built.

Draft 2 adds section 4.1 (models and the company gateway) and section 4.2
(a code workbench for the agents), and removes Gemini.

Draft 6 rewrites sections 7 and 8 after v1's code was read: the build
order changes and three earlier claims are corrected.

Draft 5 adds section 4.6 (principles and tools carried over from
v1's agents) and records six of the owner's decisions in section 9.

Draft 4 (same day) rewrites sections 4.1 and 4.2 after the owner's
corrections: the Mac calls OpenAI and Anthropic directly, the enterprise
machine follows v1, and the code workbench is a general tool.

Draft 3 adds section 4.3 (scoring against a workbook a person filled),
section 4.4 (reading and filling every template) and section 4.5 (starting
from a part-filled workbook).

This plan covers the server side only. It follows `requirements.md` (Draft 3),
decision records 1 and 2, and the prototype
`prototypes/review-prototype-v2.html`. The prototype is the list of things the
backend must be able to answer.

"v1" means the current `xbrl-agent` repository. v1 folders named here were
listed, not read line by line. Each one is read properly before it is copied.

---

## 1. What the screens need from the backend

| Screen behaviour | What the backend must provide |
|---|---|
| Run list with status | Runs, their owner and their current stage |
| Setup with suggested standard, level and layouts | A reading stage that finishes before extraction starts |
| Figures fill in while the agent works | Figures saved one by one, and a way for the browser to see new ones |
| Activity tab | A stored list of steps for each run |
| Report view and Template view | Each figure keeps its printed label, its order on the page and its template field |
| Source page beside a figure | Each figure and note keeps its page number |
| "Unsure" and the agent's reason | Each figure keeps a certainty and a one-line reason |
| Edit a figure, move it to another field | Direct changes by a person, with history |
| Comments on a figure, a line, a statement or part of a note | Stored comments with their target |
| Send comments in one batch | A correction round that one agent run works through |
| Changed, Not changed, Question; Accept and Undo | Each change records before and after, and can be reversed |
| Checks pass or fail, live after an edit | Checks are code and re-run in under a second |
| Notes preview, format toolbar, Redo from source | Notes stored as blocks with their look, and one renderer |
| Prepare mTool file, receipt | The fill and its receipt |
| Guidance for one company, firm guidance | Two stored lists, fed to the agents |
| A comment left by the agent | Agents can add comments, shown with the user's own |
| Compare with a workbook a person filled | A score and a list of differences for the run (section 4.3) |
| Upload any mTool template, including one that is part filled | Template recognition, reading by meaning, and a fill that keeps what is already there (sections 4.4 and 4.5) |

## 2. Overall shape

- **One server program** (Python, FastAPI), as today.
- **One database** (SQLite to start). The database is the only source of
  truth. The browser reads from it. Agents write to it.
- **A job queue inside the database.** Each stage of a run is a job. One
  worker loop picks up jobs and runs them. This replaces v1's single long
  function that streams to the browser.
- **Restart safety.** On start-up, any job marked "working" is marked
  "failed, can retry". No run stays stuck on "running".
- **Files on disk:** uploaded documents, page images, agent transcripts and
  filled mTool files. Written through the safe-path and atomic-write helpers.

**Live updates use polling.** While a run is working, the browser asks "what
changed since event number N" about once a second. It is plainer than v1's
streaming connection and survives a dropped connection or a restart. Runs
take minutes, so a one-second delay does not matter.

## 3. What is stored

About 20 tables, against 78 in v1.

| Group | Tables | Notes |
|---|---|---|
| People | users, sessions, audit log, issues | Copied in design from v1 |
| Companies | companies, company guidance, firm guidance | A run belongs to a company |
| Runs | runs, stages, jobs, events | A stage row per stage. Events feed the Activity tab |
| Document | documents, pages, document map | Pages hold the structured text from the Reader |
| Figures | figures, figure history | One row per concept, period and entity. Also printed label, print order, page, certainty, reason |
| Checks | check results | Rewritten whenever a figure changes |
| Notes | notes, note history | Blocks with their look, the field they are placed in, the page |
| Review | comments, rounds, changes | A change links to the comment that caused it and holds before and after |
| Filing | fills | The receipt for each mTool fill |
| Settings | settings | About 8 values |

**Two rules the design depends on:**

1. **Every write to a figure or a note adds a history row.** Undo restores
   the earlier row. Nothing is overwritten without a trace.
2. **Agents and people write through the same functions.** The functions
   refuse a write to a heading row, record the page, and re-run the checks.

## 4. The agents

Four roles. All use one shared loop for calling a model, retrying, stopping,
recording cost and saving a transcript.

| Agent | Starts when | Tools it has | Writes |
|---|---|---|---|
| **Reader** | After upload | View a page image | Pages, document map, suggested setup |
| **Figures agent** | After setup is confirmed | The code workbench (section 4.2), view a page, look up a template field's meaning, save a figure, run the checks | Figures |
| **Notes agent** | Same time as the figures agent | View a page, list the notes found, place a note in a field, save the numbers for issued capital and related parties | Notes |
| **Reviewer** | A check still fails, or the user sends comments | Everything the figures and notes agents have, plus answer a comment | Changes, answers to comments |

- The **figures agent** handles all statements in one run and runs the
  checks before it finishes. Whether one agent or five is better is tested
  on the scoring set (section 7, step 1).
- The **Reviewer** does not need the earlier agents' memory. It reads the
  saved figures, the pages and the comments. That is why a correction round
  works days later.
- **Guidance** for the company and the firm is added to each agent's
  instructions. It cannot switch off the write rules in section 3.
- **Hard limits live in the tools.** A tool that refuses returns a plain
  sentence the agent can read, such as "This row is a heading and cannot
  hold a value."

### 4.1 Models: direct on the Mac, the gateway on the enterprise machine

**Two set-ups. Each machine uses one.**

| Where | How models are reached |
|---|---|
| **Mac (development and tests)** | Straight to the providers. OpenAI with an OpenAI key. Anthropic with an Anthropic key. No gateway is involved |
| **Enterprise machine, and later Azure** | Exactly as v1 does today: one OpenAI-compatible gateway address and one key, with every model going through it |

The set-up is chosen by whether a gateway address is present in `.env`.
The Settings page shows which one is live.

**Both providers are first-class on the Mac**

- **One agent loop, two providers.** PydanticAI talks to OpenAI and to
  Anthropic natively. Both client libraries are already pinned in v1. No
  new dependency is needed.
- **Any model the key can use.** The Settings page lists the models each
  provider reports for the key, so a new Claude or GPT model can be chosen
  without a code change.
- **Default: `gpt-6-luna`.** `gpt-6.1-terra` can be selected for testing.
- **Tests cover both.** Step 0 is not done until a GPT call and a Claude
  call both succeed from the Mac.
- **Gemini is removed.** This drops the Google library and three v1
  special cases: the direct-call bypass, the lost tool-call data guard and
  the fixed temperature of 1.0.

**Model names found**

- **Terra:** OpenAI's documentation lists `gpt-6.1-terra`.
- **Luna:** `gpt-6-luna`, which is also v1's default. The owner confirmed
  on 18 November 2026 that there is no "Luna 6.1".
- On the enterprise machine the same models carry the gateway's own names,
  such as `openai.global.gpt-6-luna`. v1's naming is kept.

**Rules carried over from v1**

1. **GPT models use OpenAI's Responses interface** in both set-ups.
2. **On the gateway, Claude arrives looking like an OpenAI model.** The
   factory decides by the model's name, not by the connection type, so it
   never sends an OpenAI-only setting to Claude.
3. **Each model family has its own thinking levels.** The factory
   recognises a family from its name (Luna, Terra, Claude). A model from an
   unknown family gets safe defaults and a notice on the Settings page.
4. **One model factory.** No other file builds a model connection.
5. **The enterprise machine trusts the company's certificates** from the
   Windows certificate store, loaded before any connection is made.
   Certificate checking is never switched off.
6. **Company network proxy settings are respected** (`HTTPS_PROXY`).
7. **Windows runs in UTF-8 mode** (`PYTHONUTF8=1`).
8. **Agents stop on their own step limit** before the library's hidden
   limit, and keep `end_strategy="early"`.
9. **The agent library stays PydanticAI at v1's pinned version** (2.66.0).
10. **The gateway's region must match the model name.** The Document Agent
    notes that the EMEA address works with the `openai.eu.` name.
11. **Keys and the gateway address live in `.env` only.** Model choices
    live on the Settings page.

### 4.2 A code workbench for the agents (code interpreter)

**Why.** The article's advice is a light harness: give the agent a few
strong tools and let it choose how to do the job. A place to run code is
the strongest of these. The agent can add up a table, check a schedule,
search the document's text, compare this year with last year or look
inside a workbook, in whatever way suits the document in front of it.

**What it is.** The model provider runs Python in a short-lived sandbox
during a model call. The agent writes the code and reads the result.

**The split between freedom and control**

| The agent is free to | The harness still controls |
|---|---|
| Explore and calculate in the sandbox in any way | Saving a figure or a note: only through the save tools, with their rules |
| Read the files it was given | Writing the real mTool file: only the one patcher |
| Decide its own order of work | Step, time and cost limits |

The sandbox is a workbench. It is never the master copy of anything.

**What the agent is given in the sandbox**

- The document's pages as text and tables, from the Reader.
- The list of template fields with their meanings.
- A copy of the uploaded workbook, when there is one.
- The template toolkit scripts (section 4.4).

**Which model gets what**

| Set-up | GPT models | Claude models |
|---|---|---|
| **Mac, direct** | OpenAI's code interpreter | Anthropic's code execution tool |
| **Enterprise gateway** | OpenAI's code interpreter, if the gateway check passes | Local tools only. On the gateway Claude arrives as an OpenAI-style chat model, which cannot carry a provider tool |

- **Local tools always exist as well:** view a page, search the text, add
  up a table. A run works without any sandbox, with less freedom.
- **On or off from the Settings page.**
- **Code steps appear in the Activity tab** and in the transcript.

**How the Document Agent does it** (read from its code on the Desktop):

- It uses the same Responses interface, gateway address and key.
- It creates the sandbox itself, uploads files into it, downloads results
  and deletes it. A sandbox is deleted after 20 idle minutes.
- For the gateway it has two optional settings: a provider header, and
  naming the model when the sandbox is created.
- Its check script tests two ways: the app creates the sandbox ("Part A"),
  or OpenAI creates it on the first code call and files go in through the
  Files interface ("Part B"). Part A fails if the gateway blocks the
  sandbox routes.
- No recorded result from the enterprise machine was found in its
  documents. The owner reports that the code interpreter was tested there
  and worked. Which of the two ways passed is not recorded here, so step 0
  still runs the check script once.

v2 follows the same approach and adapts its check script. Giving the agent
files needs Part A or Part B to pass on the gateway. If neither does, the
agent still gets a sandbox for calculation, with numbers passed in the code.

**To be aware of**

- v1's review of 10 November 2026 recommended against adopting this then,
  and built the local adding-up tool instead. The owner has now chosen it
  for the reason above. The scoring set (step 1) will show its effect.
- The same review noted that data in Anthropic's sandbox is excluded from
  zero-retention. Decided on 18 November 2026: Claude's sandbox is used
  with test documents only. The app enforces this with a setting that is
  off by default.
- Document text and the workbook copy are uploaded to the provider's
  sandbox. For OpenAI this is settled: the owner confirmed on 18 November
  2026 that the firm's agreement with OpenAI covers data upload, on the
  enterprise gateway as well. No restriction applies to OpenAI's sandbox.

### 4.3 Scoring against a workbook a person filled

v1 already lets a user attach the mTool workbook a person filled for the
same document and compare it with the run. v2 keeps that and adds a score.

**Three numbers, per statement and for the whole run**

| Number | Meaning |
|---|---|
| **Completeness** | Of the cells the person filled, the share the app also filled |
| **Accuracy** | Of the cells both filled, the share where the values agree |
| **Complete and accurate** | Completeness times accuracy: the share of the person's cells the app got right |

**Listed beside the score, not hidden inside it**

- **Extra:** cells the app filled that the person left blank.
- **Sign only:** same amount, opposite sign.
- **Scale:** same digits, different units, such as thousands.
- **Notes:** whether each note sits in the same field. Note wording and
  formatting are not scored.

**Rules carried over from v1**

- The workbook is read by meaning, cell by cell, never by position alone.
- The comparison is worked out when it is opened, against the run's current
  figures. Editing a figure changes the score.
- First financial statements have no prior year, so prior-year cells are
  left out and not counted as zeros.
- Calculated totals are compared with what the template calculates.

**Two ways to use it**

- **In the app:** attach a filled workbook to a run. The run shows the three
  numbers and the list of differences. Clicking a difference opens that
  figure in review.
- **From the command line:** score many runs at once and print counts only.
  This is step 1 of the build order and is what runs inside the enterprise
  environment.

### 4.4 Reading and filling every template

**What v1 has, and v2 keeps**

- A list of 30 fingerprints for v1's own generated template files. A
  genuine mTool workbook is not on the list (section 8). Its cells are
  found by the official SSM field names inside it.
- Cells are found by taxonomy meaning. An ambiguous column asks the user.
- One patcher writes the mTool file directly, without Excel, and reads
  every write back. It uses only Python's standard library, because it also
  travels to the Windows machine as a single script.
- A receipt lists what was written, kept and skipped.

**What is new: a template toolkit the agent can use**

A folder holding a short instruction file and a set of scripts. Each script
does one thing and prints plain text:

| Script | What it does |
|---|---|
| Identify | Says which known template a workbook is, or that it is unknown |
| List | Lists the sheets, the fields and where each field's cells are |
| Find | Finds a field by its meaning or its label |
| Read | Reads the filled cells, by meaning |
| Trial fill | Fills a copy, never the original, and reads it back |
| Compare | Shows the differences between two workbooks |

- **Normal runs do not need an agent for this.** The same scripts are the
  code path for reading and filling a recognised template.
- **The agent uses the toolkit when code cannot finish the job:** an
  unrecognised template, a field that cannot be found, or a fill whose
  read-back does not match. It investigates with the scripts, then reports
  what it found and proposes a mapping.
- **A person confirms a new mapping.** It is then saved, so the template is
  recognised next time.
- **The agent never writes to the real file.** Only the one patcher does.
  A cell is never guessed. A cell that cannot be resolved is listed on the
  receipt.

**Where the scripts run.** In two places. On the app's own machine, the
agent picks a script and its inputs. In the code workbench (section 4.2),
the agent has the same scripts and a copy of the workbook, and can write its
own code to explore and debug. Neither place can change the real file.

**On the word "skill".** A skill-first design for the statement agents was
dropped on 2 November because each already had one prompt. This is a
different use: a rare, exploratory job with its own scripts.

### 4.5 Starting from a part-filled workbook

v1 already accepts last year's mTool workbook and uses it for the prior
year. v2 keeps those rules and treats it as the general case: the user may
upload a workbook that already holds some figures.

**What happens to what is already in the workbook**

| Already in the workbook | What the app does |
|---|---|
| Prior-year figures | Imported before extraction and locked. Agents cannot change them |
| Notes with numbers for the prior year | Imported the same way |
| Typed subtotals | Kept as the person's own totals. A disagreement with their parts stays visible |
| Current-year figures a person typed | Imported and kept fixed. The agent may comment on one, but cannot change it |
| Formulas and locked cells | Left alone |

**How the imported figures act as hints**

- **Field choice.** The fields used last year tell the agent where this
  company's lines belong. The agent follows them unless a line is gone or
  has changed in nature, and then it gives its reason.
- **Comparatives.** The agent compares the prior-year column printed in the
  document with the imported figures. Differences are shown for review.
- **Sign.** A difference in sign only is never settled by the agent. It
  stays open until a person decides.
- **Source.** Each imported figure is marked as coming from the workbook.

**Changed from v1, decided 18 November 2026.** Current-year figures a
person has already typed are imported and kept fixed. The app fills only
the gaps. If the agent thinks a typed figure needs review, it leaves a
comment on it and does not change it.

### 4.6 Principles and tools carried over from v1's agents

v2 has fewer agents, but each keeps what v1's agents were given. The tool
names below were read from v1's agent files.

**Principles**

1. **Look at the source.** Any page as a picture, a closer look at part of
   a page, the page's text, and a search across the document.
2. **Know what a field means before choosing it.** Look up the taxonomy
   definition.
3. **Check your own work before finishing.** The figures agent runs the
   totals and the checks. The notes agent looks at a picture of its own
   note beside the source page. The Reviewer re-checks after each fix.
4. **Account for everything.** Every line on a statement and every note in
   the document is either placed or reported as left out, with a reason.
5. **Say so when something is missing or unsure.** Report a gap, a missing
   mandatory field or "not disclosed". Never invent.
6. **Trace a wrong number to where it came from** before changing it.
7. **Raise a flag for a person** when the evidence does not settle it.

**Tools, and where each goes in v2**

| What v1's agents can do | v1 tools | In v2 |
|---|---|---|
| See pages | `view_pdf_pages`, `zoom_pdf_region`, `read_page_text`, `search_pdf_text` | All four agents |
| Understand the template | `read_template`, `lookup_definitions` | Figures agent, notes agent, Reviewer |
| Calculate | `calculator`, the table adding-up tool | The code workbench, with the local tools as fallback |
| Save work | `write_facts`, `save_result`, `write_note_from_source` | The gated save tools (section 3) |
| Check own figures | `verify_totals`, `submit_face_coverage` | Figures agent: run the checks, report coverage |
| Check own notes | `preview_layout`, `submit_batch_coverage`, `report_source_gap`, `report_missing_mandatory_field` | Notes agent: preview, report coverage and gaps |
| Find and fix | `list_facts`, `trace_cascade_source_tool`, `find_candidate_rows_tool`, `apply_fixes`, `verify_fixes`, `mark_not_disclosed` | Reviewer |
| Move and edit notes | `move_note_cell`, `edit_note_cells`, `clear_note_cells` | Reviewer |
| Ask a person | `raise_flag` | All agents. It appears in the review list |

**Formatting: the agent sees what it made**

- The notes agent has a **preview** tool. It draws the note as the one
  renderer will output it for mTool's page (A4 portrait, 20 mm margins) and
  returns a picture.
- The agent compares that picture with the source page and adjusts the
  stored look. It works on tables, headings, indents and rules.
- It has a fixed number of tries. If it cannot get close, it raises a flag
  and the note shows "Check formatting" in review.
- v1 gained this for tables in PR #65. v2 starts from that renderer.
- This replaces the line in `requirements.md` section 4.4 that said a note
  is never adjusted automatically. The agent may adjust a note while it is
  still working on it. After it finishes, a note changes only by a
  person's edit or a correction round.

**How the agents' instructions are written**

- Instructions state principles and leave the judgement to the agent. They
  do not hard-code a rule per label or per template row, because those
  break when a template or a report layout changes.
- The agent is trusted to explore the document, check its own work and fix
  what it finds, using the tools above and the code workbench.
- v1's statement instructions are read in full before v2's are written.
  Each lesson is kept once, as a shared principle that applies across
  statements. v1 began this in PR #55.
- A hard stop in code is kept only where a wrong write would corrupt the
  filing: a value in a heading row, a forced balance, a figure with no
  source page. Everything else is an instruction plus clear feedback.
- When an agent fails on a document, the fix is a better principle, tool
  or feedback. A document-specific rule is the last resort, with the
  reason written beside it.

**Agents can leave comments too.** When an agent thinks a person should
look at something it did not change, it leaves a comment on that figure or
note. This includes a figure a person typed that the agent believes is
wrong (section 4.5).

## 5. The stages of a run

| Stage | Done by | Ends when |
|---|---|---|
| 1. Upload | Code | The PDF is stored and each page is looked at once. Uploads are PDF only (section 9) |
| 2. Read | Reader | Pages and the document map are saved. Setup is suggested |
| 3. Setup | The user | The user confirms. This is the only required stop |
| 4. Extract | Figures agent and notes agent, side by side | Both have finished or failed |
| 5. Check | Code | Check results are saved |
| 6. Auto-review | Reviewer | Runs only if a check fails or a note is unplaced |
| 7. Human review | The user | Correction rounds repeat as often as needed |
| 9. Fill | Code | The mTool file and its receipt are written |

Run status is worked out from the stages. A stop or a failure at any stage
leaves the earlier stages' results in place. One statement can be redone
without a new run.

## 6. What the browser can ask for

Every request needs a login, except login itself and the health check.

| Area | Requests |
|---|---|
| Login | Log in, log out, who am I |
| Runs | List, create from an upload, open, stop, delete |
| Setup | Read the suggestions, confirm and start |
| Progress | Stages and events since a given number |
| Figures | One statement in Report or Template order, edit a figure, move a figure, confirm an unsure figure |
| Checks | Current results |
| Notes | List, open one, change its look, change its field, confirm, redo from source |
| Pages | A page image |
| Comments | Add, remove, send a round, accept, undo, reply |
| Filing | Upload the mTool template, fill, download, read the receipt |
| Guidance and settings | Read and change, with firm guidance and settings for admins only |
| Admin | Users, audit log, issues |

## 7. Build order

Revised on 19 November 2026 after v1's code was read (`v1-reuse-map.md`).
The scoring tool cannot run until the templates, the template catalogue and
the figure store exist, so those now come first.

Each step ends with something that can be checked. No step starts until the
one before it passes.

| Step | Build | Done when |
|---|---|---|
| **0. Skeleton** | New repository, database, login, job queue, the shared agent loop, the model factory, and a gateway check script | A user can log in. A test job runs, fails and retries. On Mac, a GPT call and a Claude call succeed directly, each with a code step. On the enterprise machine, the check script reports pass or fail for a GPT call, a Claude call and both ways of getting a sandbox |
| **1. Templates and figures** | Copy the templates and taxonomy. Read them into the template catalogue. The figure store with history and the gated save functions. The checks, working from saved figures. Report and Template views of a statement | All 38 statement templates load. Figures typed in by a test are saved, refused where they should be, and checked. The balance check fails on a wrong figure and passes when it is corrected |
| **2. Scoring tool** | Read a workbook a person filled. Compare it with a run. Completeness, accuracy and the combined number (section 4.3) | A workbook filled from known figures scores 100%. A workbook with seeded differences scores exactly what was seeded. v1's saved figures are scored with the same definitions, as the baseline |
| **3. Read** | PDF upload and page pictures, Reader, document map, setup. PDF only: a Word file is refused (section 9) | The four documents in v1's `data` folder are read. Statement pages and layouts are found correctly |
| **4. One statement** | Figures agent for the balance sheet, MFRS Company, with the code workbench | Scores at least as well as v1 on the balance sheet |
| **5. Review loop** | Edit, move, comments, rounds, Reviewer, accept, undo. Compare with a filled workbook inside the app. Added 22 November 2026 (decision record 3): scope questions at setup and during extraction, the "Needs you" list, Right or Wrong with a scope, the server's count of what a round changed, versioned guidance with a proposed line from a Company-scoped correction | A seeded wrong figure is corrected through a comment. Undo restores it. Attaching a filled workbook shows the score and the differences. A seeded scope contradiction stops extraction with a question, and each answer either carries on or restarts the stage |
| **6. Notes** | Notes agent, blocks with their look, one renderer, the preview tool, format changes, redo | Notes pass mTool's size limit. The preview picture matches the stored look. How notes look inside mTool is confirmed on Windows |
| **7. All statements** | The other four statements and their layouts. Group level. One agent tested against five | Scores at least as well as v1 on all statements |
| **8. mTool fill** | Fill and receipt, reusing v1's patcher. The template toolkit, and the agent's investigation of an unrecognised template (section 4.4) | A genuine mTool workbook is read and filled, and the filled file opens in mTool and matches the receipt. A deliberately altered template is reported as unknown, with nothing guessed (its investigation is step 12) |
| **9. MPERS** | Second standard, retained earnings statement | Scores at least as well as v1 on an MPERS document |
| **10. Reports and part-filled workbooks** | Three reports. Starting from a workbook that already holds figures (section 4.5) | Same coverage as v1. Imported figures survive the fill unchanged |
| **11. Switch-over** | Run v1 and v2 side by side | Agreed score on an agreed set of documents |
| **12. Template investigation** | The template toolkit and the agent's investigation of an unrecognised template (section 4.4), moved out of step 8 by the owner on 23 November 2026 | A deliberately altered template is investigated, placements are proposed with evidence, a person checks each on the approved screen, and nothing is guessed |

Notes are step 6, not last, because notes formatting is where users lose
the most time.

## 8. Reuse from v1

`v1-reuse-map.md` is the detailed record. It was written by reading the
code, and it corrects this section's first draft.

**Corrections to earlier drafts of this plan**

- **"30 recognised templates"** in section 4.4 are v1's own generated
  template files. A genuine mTool workbook is not on that list. v1 finds
  its cells by the official SSM field names and marks it "probably
  compatible, not verified". No genuine mTool workbook exists in v1's
  repository.
- **The database is larger than "about 20 tables".** The copied code reads
  about ten template-catalogue tables: the fields, their sums, their cells,
  the SSM field names and which cells can be written. They are rebuilt from
  the template files at every start, so they carry no history. They are
  copied with v1's columns.
- **v1 does not produce the plan's three scores.** It reports "Found" and
  "Same value". The combined score and the sign-only and scale lists are
  new work.

**What "copy" really means, area by area**

| Area | Verdict | What changes |
|---|---|---|
| Templates and taxonomy files | Copy as they are | Field identifiers come from the template labels, so v2's match v1's |
| Template reading and the catalogue | Copy with changes | Kept with v1's table columns |
| Figure store | Copy with changes | Adds the printed label, print order, page, certainty and reason |
| Checks | Nine copy with changes. Three are rebuilt | The three read a filled Excel workbook, which v2 does not have |
| mTool patcher and receipts | Copy as they are | The steps around them sit in a 530-line web route in v1. That part is rebuilt |
| Workbook comparison | Copy with changes | New scores added |
| Prior-year import | Copy with changes | v1 overwrites a typed current-year figure. v2 keeps it fixed |
| Notes renderer and mTool note writer | Copy with changes | Both take one HTML text per note. v2 stores blocks and turns them into that HTML |
| Word conversion, page viewing, calculator | Copy with changes | Three files read settings from `.env`. v2 moves those to the Settings page |
| Login, model connections, safe paths, atomic writes | Copy with changes | Done in step 0 |

**Rebuilt:** run coordination, the agents and their instructions, notes
storage, the review screens, and the rest of the database.

**Packages.** Seven that v1 pins are added when their step needs them:
openpyxl, et_xmlfile, PyMuPDF, beautifulsoup4, soupsieve, mammoth and
cobble. Uploads are PDF only (section 9), so v1's Word conversion is not
copied and `docx2pdf` is not needed. mammoth and cobble are only needed if
another use for them turns up.

**Tests.** The tests for the mTool patcher, notes styling, the renderer
and the calculator copy almost as they are. Most others build v1's full
database, so their set-up is rewritten.

**Which v1.** The Desktop checkout of v1 is one merge behind GitHub. The
build reads v1 from a reference copy at commit `4bb9c6bf`, kept in
`.v1-reference/` and not committed.

## 9. Decisions

**Decided on 18 November 2026**

| Question | Decision |
|---|---|
| Live updates | The screen asks for news about once a second. It must feel smooth. If it does not, switch to a held-open connection |
| Who edits a company's guidance | Anyone who can open that company's runs |
| Failed checks | The agent tries to fix its own failed checks before the user looks |
| Figures a person typed for this year | Kept fixed. The agent may comment on them |
| Score for notes | Same field only. Wording is not compared |
| New repository | Created: `yeeliang94/xbrl-agent-v2`, private |
| Scoring with real filed workbooks | Allowed. Getting results out is manual: the owner tests on the enterprise machine and sends screenshots. On the Mac, scoring uses test documents |
| Default model | `gpt-6-luna`. `gpt-6.1-terra` for testing |
| Claude's sandbox | Test documents only |
| OpenAI's sandbox | No restriction. Covered by the firm's agreement with OpenAI |
| Word files | Not accepted anywhere: Mac, the enterprise Windows machine and Azure take PDF only. A Word upload is refused with one plain sentence: save it as a PDF in Word, then upload that. No Word converter is copied from v1, and docx2pdf is not added. Azure App Service has neither Word nor LibreOffice, and one rule everywhere keeps runs alike |
| mTool templates in `templates/` | The ten `mTool_*.xlsx` workbooks the owner added on 18 November 2026 are genuine mTool templates and may be used as test files |
| Login idle timeout and lockout limits | Move from `.env` to the Settings page |
| The nine hard stops | Kept, all nine (owner, 18 November 2026, step 4). The cause they guarded against is fixed instead: the figures agent sees the template as an outline, each field with its own id, its place under its headings, and whether it is a heading, a line to fill or a total of named lines with their signs, and it saves by id, never by label. The nine stay as a safety net that should rarely fire |
| Share-capital and related-party Total column | Compared under totals, not scored, when a category beside it is filled. Scored when it is the only figure |
| Font | The computer's own font (Segoe UI on Windows, San Francisco on a Mac). No Geist, no Google Fonts link |
| Review depth | The full panel on every step |
| Steps side by side | Allowed (5 with 6, 7 with 8). Pausing for the usage limit is accepted |
| Records and logs | As complete as possible at every step, so anything can be debugged later (rule in `AGENTS.md`). Server logs are written to daily files kept 30 days |
| Sign-off | Dropped. There is no "Mark reviewed" step: once a run is not busy, "Prepare mTool file" is available straight away. The run's `reviewed` status goes when step 5 builds the run screen |
| Run header | The company name only, then the actions. No year, standard, level, status pill or clock in the header |
| Exports | "Download traces": one zip of a run's activity, model calls with tokens and cost, agent transcripts, page transcriptions, document map, figures with history, checks and comments; the uploaded PDF only when ticked. Settings: "Download server logs" (30 days) and "Download usage" (cost per run and per day). Who may download is left open for now: the existing open-run and admin checks apply. Server routes and Settings buttons in step 3; the run's "Download traces" is a quiet button in the run's header, beside the main action, and arrives with the run screen in step 5. It holds everything the agents did |

## 10. Not checked

- The v1 folders in section 8 were listed, not read. What can really be
  copied unchanged is confirmed step by step.
- No timing or cost estimate has been made for one agent handling all
  statements.
- Nothing here has been run on Windows or Azure. That includes Claude
  through the gateway and code calls through the gateway.
- `gpt-6.1-terra` comes from OpenAI's documentation as returned by a web
  search. `gpt-6-luna` comes from v1 and the owner.
- Listing a key's available models on the Settings page has not been tried
  against either provider.
- PydanticAI's built-in code tool was found in the installed library at
  version 2.9.0, for both OpenAI and Anthropic. It was not checked at the
  pinned 2.66.0, and it has not been called. Giving it files has not been
  tried.
- SQLite with one worker is assumed to be enough for the first users. The
  number of runs at the same time has not been asked.
