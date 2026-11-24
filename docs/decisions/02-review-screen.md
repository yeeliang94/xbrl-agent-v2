# Decision record 2 — Review screen

18 November 2026 · From the brainstorm with the owner · Status: proposed in
the prototype `prototypes/review-prototype-v2.html`. Extended and approved
on 22 November 2026 as `review-prototype-v3.html` (decision record 3).

## The review grid does not copy the Excel template

**Checked:** the real MFRS Company templates are far larger than what one
company uses. The balance sheet has 73 rows on its main sheet and 450 on its
analysis sheet. Profit or loss has 38 and 136. Cash flows has 135. A typical
company fills a small share of these.

**No technical problem.** Figures are stored by meaning, and the mTool fill
finds cells by meaning. The order on screen does not affect the filing.

**Proposed:**

- **Report view (default).** Lines appear as the company's own statement
  prints them, in that order. This matches the source page beside the grid.
  A line whose template field has a different name shows "Filed as …" under
  it. These are the judgement calls the user checks.
- **Template view.** The same figures in template order, with unused
  template fields shown greyed. This is for finding a line in Excel.
- **Template wording is kept exactly**, so a field can be searched for in
  the Excel file.

**Risk:** users finish in Excel. If they cannot find a line there, the Report
view costs them time. The Template view is the answer to that. It needs
testing with a real user.

## Comments attach at four levels

A figure, a whole line (all its periods), a whole statement, or part of a
note. A comment on a line asks the agent to recheck every figure on it.

## One screen for the whole life of a run

The same screen shows a run while it extracts, in review, while it corrects
and after sign-off. While the agent works:

- figures fill into the grid as they are extracted
- an Activity tab lists each step, with the current step animated
- the sidebar marks the statement in progress
- a clock shows elapsed time

This replaces the separate progress page in the first prototype.

## Look

Black sidebar for navigation. Figures in a monospaced font. Tinted bands for
section headings. Totals in medium weight with a rule above. Motion is short
and only marks a change of state. It is switched off when the user's system
asks for reduced motion.

**Colours.** Black, white, cool greys and one orange. The values come from
v1's theme file (`web/src/lib/theme.ts`), which uses black and orange.

**Status.** No tinted pills. A status is a small dot and a word: a black dot
for finished, an orange dot for needs attention, a grey ring for neutral. A
failure is the one filled label, in dark orange with white text.

**Markers.** A comment is marked by a small orange dot. No coloured edge
lines anywhere.
