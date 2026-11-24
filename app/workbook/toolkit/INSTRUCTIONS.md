# Template toolkit

Six scripts, each doing one job and printing plain text. None changes the workbook:
`trial_fill` writes a temporary copy, reads it back and deletes it.

| Script | Job | Example |
|---|---|---|
| `identify` | Which known template the workbook is, or why it is not one | `venv/bin/python -m app.workbook.toolkit.identify book.xlsx` |
| `list_rows` | The sheets, or one sheet's rows: label, SSM name and each value cell | `... list_rows book.xlsx SOFP-CuNonCu --start 1 --rows 60` |
| `find` | Rows whose label or SSM name holds all the words | `... find book.xlsx trade receivables` |
| `read` | What some cells hold: number, text, formula, empty; and whether locked | `... read book.xlsx "SOFP-CuNonCu!C12" "SOFP-CuNonCu!D12"` |
| `trial_fill` | Write values into a copy and say what read back | `... trial_fill book.xlsx "SOFP-CuNonCu!C12=1200"` |
| `compare` | The cells that differ between two workbooks | `... compare a.xlsx b.xlsx --sheet SOFP-CuNonCu` |

How to look at a template the fill could not place a figure in:

1. `identify` says what is wrong with it.
2. `list_rows` with no sheet shows every sheet; with a sheet, its top rows show which column is which year.
3. `find` the figure's line by its words, then `read` the cells beside it.
4. `trial_fill` the value into a copy to see it read back.

A cell is never guessed. A cell that holds a formula, is locked, or holds another figure is not an input cell.
