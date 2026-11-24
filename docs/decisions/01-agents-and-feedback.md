# Decision record 1 — Agents and feedback

18 November 2026 · From the brainstorm with the owner · Status: agreed unless
marked open.

## What we learned about users

- One person prepares and reviews a filing. They sign off their own run.
- They start a run, leave, and come back. Run time matters little.
- They skim everything. Experience tells them where to look harder.
- Most checking and fixing happens inside the mTool Excel template, not in
  our app.
- The biggest time cost is fixing notes formatting.
- Their own filed mTool files cannot leave the enterprise environment.

## Agreed

1. **Agent shape.** A Reader, one figures agent for all statements, one
   notes agent, and a Reviewer used only as a second opinion. The figures
   agent runs the cross-checks itself before it finishes. This is tested
   against five parallel extractors once a scoring set exists.
2. **Skills are not used.** The v1 attempt showed no material gain, because
   each agent already has one prompt.
3. **Notes target the mTool editor, not Word.** Notes match the source as far
   as mTool's editor can hold. Where it cannot, one fixed house rule applies.
   Example: a double underline becomes a thick bottom border. The stored look
   uses only what mTool's editor accepts.
4. **Notes formatting is built second**, straight after the first statement.
5. **Review supports skimming.** Nothing is hidden. Each item shows whether
   it is proven by arithmetic, a confident judgement or an unsure judgement,
   with the source page beside it.
6. **Users can correct the agent by talking to it.** After a run, the user
   says what is wrong and where it belongs. The agent fixes it, re-runs the
   checks and shows before and after. The user accepts or rejects.
7. **Users can record lessons for future runs.** After a correction, the app
   offers "remember this". The agent drafts a short lesson and the user
   approves it. Lessons are a visible, editable list.

## Open

- **Where corrections happen.** In our app before filling mTool, or in Excel
  with the corrected file uploaded back so the app learns from the
  differences. Depends on why users prefer Excel today.
- **Scope of a lesson.** One company, one user or the whole firm, and who
  approves a firm-wide lesson.
- **Scoring set.** The data folder has four source documents (Doc 1, Doc 2,
  Doc 3, Doc 4) and no accountant-filled file. Proposal: scoring runs inside
  the enterprise environment against filed mTool files there, and only
  counts and scores come out, never content. Needs the owner's confirmation
  that this is allowed.
- **mTool editor limits.** A full list of what the editor accepts is needed
  before the notes look is designed. v1's `docs/MTOOL-NOTES-AUTHORING.md` is
  the starting point; not yet re-read for this record.
