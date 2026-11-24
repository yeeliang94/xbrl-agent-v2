"""Filling an mTool template from a run (backend-plan section 4.4, step 8).

`fill.fill_workbook` is the entry point. `identify` says which template a
workbook is, `plan` turns figures into cell writes and `notes` turns note
fields into note-store writes; both plans are pure. Only
`app/workbook/offline_fill.py` writes the file.
"""
