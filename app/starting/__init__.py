"""A part-filled workbook a person attaches at setup: most often last year's
mTool file, rolled forward to this year (step 10d, `docs/backend-plan.md`
section 4.5).

- `workbook.py` reads the file, says what it is (standard, level, unit, year
  end) and plans the import, refusing one that does not fit the run.
- `store.py` keeps the file and its record, and imports its figures when the
  setup is confirmed, before extraction starts.
- `comparatives.py` records the report's comparative when an agent reads a
  prior-year figure the workbook already holds (step 10e).
- `routes.py`: attach, read and remove it (`docs/api-contract.md`).

Rebuilt from v1 `concept_model/prior_year.py`, with the owner's change of
18 November 2026: this year's figures a person typed are imported and kept
fixed, never overwritten.
"""
