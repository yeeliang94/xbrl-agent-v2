"""Reading and filling mTool workbooks, without Excel (backend-plan section 4.4).

`xlsx_cells`, `xlsx_formulas`, `mtool_layout` and `mtool_address` read a
workbook with Python's standard library only, as v1's `mtool/offline_fill.py`
does, and import nothing from the rest of the app. `mtool_map` places a run's
fields on a genuine mTool workbook with them; scoring reads through it and the
fill writes through it, so read and fill agree. `offline_fill` is the one
patcher that writes a workbook; `report_cells` beside it writes the reports'
short fields with its helpers, standard library only too.
"""
