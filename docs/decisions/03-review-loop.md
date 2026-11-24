# Decision record 3 — Review loop after the Document Agent comparison

22 November 2026 · Owner · Status: agreed. The look is approved in
`prototypes/review-prototype-v3.html`, which supersedes
`review-prototype-v2.html` for the run screen and setup.

Background: `docs/document-agent-lessons.md`.

## Agreed

1. **The agent asks only about scope.** Scope is what setup holds: the
   standard, the level, the year end, the unit, which statements are printed
   and their layouts. Every other doubt the agent settles itself and shows
   for review: an Unsure figure with its reason, an agent comment or a flag.
2. **A scope question has two moments.** At setup, an unsure suggestion is
   shown as a question card. During extraction, an agent that finds
   evidence against the confirmed setup stops its stage, keeps its work and
   asks. The answer either confirms the setup (the stage carries on) or
   changes it (the affected stages start again).
3. **The question card:** the question as the heading, the evidence with a
   page link for each line, up to four choices with one line on what
   follows, one marked Suggested, a "Something else" box, keys 1 to n. No
   "Let the agent decide" on a scope question.
4. **One "Needs you" list** in the run screen: failed checks, Unsure
   figures, agent comments, notes to check, unplaced notes, and alike items
   answered once. It ends with the count of figures that passed.
5. **Right or Wrong on a figure.** Wrong opens the comment box with "Apply
   to: Figure, Run, Company". Run asks the agent to fix the same thing
   wherever it occurs. Company also proposes a line of company guidance.
6. **Guidance is added only by a person.** The agent may propose a company
   guidance line from a Company-scoped correction; the person adds it with
   one click or leaves it. This keeps the 18 November rule (no automatic
   "remember this"). Firm guidance stays admin-only and typed.
7. **The server counts what a round changed,** from figure history: per
   comment, before and after; and every other figure the round changed. The
   agent sees it after each save; the person sees it under the agent's
   one-sentence reply.
8. **Activity steps** are written in the agent's own words, carry page
   links, and fold into one line when the run finishes.

## Later, not in step 5

- Checking a proposed guidance line against the company's earlier runs
  ("would change …"). It needs the past-corrections test set
  (`document-agent-lessons.md` 2.6). Until then the proposal shows no
  check line.
- A comment pinned to a spot on a source page, a message to the agent while
  it works, and last year's run as a reference.
