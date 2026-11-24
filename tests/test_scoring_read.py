"""Reading a workbook a person filled, by meaning (app/scoring/workbook_read.py).

The template-layout cases fill a copy of the app's own template. The mTool
cases build the smallest mTool-shaped sheets, as v1's tests do
(`tests/test_mtool_template_map.py::_save_semantic_marker_workbook`,
`tests/test_human_file_ingest.py`): XSD references, `#PRIM#`, `#ENDT#` and
`#DOM#` markers. No genuine mTool workbook is used.
"""
from __future__ import annotations

import pytest
from openpyxl import Workbook, load_workbook

from app import db
from app.catalog.lookup import run_family
from app.catalog.statements import StatementType, template_path
from app.scoring import workbook_read
from app.scoring.workbook_read import NothingMatches, read_filled_workbook
from app.workbook.xlsx_cells import WorkbookUnreadable
from app.workbook.xlsx_formulas import FormulaNotWorkedOut, WorkBudget, calculated_value
from tests.conftest import field, make_run

SOFP = "mfrs-company-sofp-cunoncu-v1"
XSD = "full_ifrs-cor_2022-03-24.xsd#"


def _read(run_id: int, path):
    with db.connect() as conn:
        return read_filled_workbook(conn, run_family(conn, run_id), str(path))


def _template_copy(tmp_path, statement="SOFP", variant="CuNonCu", level="company", standard="mfrs"):
    path = tmp_path / "filled.xlsx"
    wb = load_workbook(template_path(StatementType(statement), variant, level, standard))
    return wb, path


def _target(concept: str, period="CY", entity="Company") -> tuple[str, str]:
    with db.connect() as conn:
        sheet, row, col = conn.execute("SELECT target_sheet, target_row, target_col FROM concept_targets "
                                       "WHERE concept_uuid = ? AND period = ? AND entity_scope = ?",
                                       (concept, period, entity)).fetchone()
    return sheet, f"{col}{row}"


# The app's own template layout -------------------------------------------

@pytest.mark.parametrize("typed,expected", [
    (1250, 1250), ("=1000+250", 1250), (" (2,653,465.00) ", -2653465), ("+1,000.50", 1000.5), ("0", 0),
    ("-", 0), ("—", 0), (" Nil ", 0),
])
def test_a_data_entry_cell_is_read_as_typed_text_or_a_formula(tmp_path, typed, expected):
    run_id = make_run()
    concept = field(SOFP, "SOFP-CuNonCu", 20)   # Deferred tax assets
    wb, path = _template_copy(tmp_path)
    sheet, cell = _target(concept)
    wb[sheet][cell] = typed
    wb.save(path)

    read = _read(run_id, path)

    assert read.layout == "template"
    assert read.cells[(concept, "CY", "Company", "")].value == expected
    assert read.unread == {} and read.loose == []


@pytest.mark.parametrize("typed,reason", [("about 5 million", "not_a_number"), ("=INDIRECT(\"B5\")",
                                                                                "formula_not_worked_out")])
def test_a_cell_that_cannot_be_read_is_reported_not_dropped(tmp_path, typed, reason):
    run_id = make_run()
    concept = field(SOFP, "SOFP-CuNonCu", 20)
    wb, path = _template_copy(tmp_path)
    sheet, cell = _target(concept)
    wb[sheet][cell] = typed
    wb.save(path)

    read = _read(run_id, path)

    key = (concept, "CY", "Company", "")
    assert key not in read.cells
    assert read.unread[key].reason == reason and read.unread[key].holds_value
    assert read.unread[key].workbook_cell == f"{sheet}!{cell}"


def test_formula_work_has_one_budget_per_read_and_running_out_is_not_assessed(tmp_path, monkeypatch):
    monkeypatch.setattr(workbook_read, "FORMULA_WORK", 30)
    run_id = make_run()
    first, second = field(SOFP, "SOFP-CuNonCu", 20), field(SOFP, "SOFP-CuNonCu", 11)
    wb, path = _template_copy(tmp_path)
    for concept in (first, second):
        sheet, cell = _target(concept)
        wb[sheet][cell] = "=SUM(Z1:Z20)"   # 21 cells each: the first fits the budget, the second does not
    wb.save(path)

    read = _read(run_id, path)

    keys = [(concept, "CY", "Company", "") for concept in (first, second)]
    assert [read.cells[k].value for k in keys if k in read.cells] == [0]
    problem, = [read.unread[k] for k in keys if k in read.unread]
    assert problem.reason == "formula_not_worked_out" and problem.holds_value
    assert "more work than one reading allows" in problem.sentence


def test_a_long_formula_is_refused_before_its_ranges_are_added_up():
    cells = {"S": {1: {"A": ("F", "SUM(B1:B9000)+" + "+".join(["1"] * 8000))}}}
    budget = WorkBudget(100)
    with pytest.raises(FormulaNotWorkedOut, match="too long"):
        calculated_value(cells, "S", "A1", budget=budget)
    assert budget.left == 99   # only the formula's own cell was visited


def test_a_number_in_a_heading_row_is_listed_as_matching_no_field(tmp_path):
    run_id = make_run()
    wb, path = _template_copy(tmp_path)
    with db.connect() as conn:
        row = conn.execute("SELECT render_row FROM concept_nodes WHERE template_id = ? AND kind = 'ABSTRACT' "
                           "AND render_sheet = 'SOFP-CuNonCu' ORDER BY render_row LIMIT 1", (SOFP,)).fetchone()[0]
    wb["SOFP-CuNonCu"][f"B{row}"] = 77
    wb.save(path)

    read = _read(run_id, path)

    assert [(n["reason"], n["workbook_cell"]) for n in read.loose] == [("no_field", f"SOFP-CuNonCu!B{row}")]


def test_a_row_whose_label_is_not_the_fields_label_is_not_trusted(tmp_path):
    run_id = make_run()
    concept = field(SOFP, "SOFP-CuNonCu", 20)
    wb, path = _template_copy(tmp_path)
    sheet, cell = _target(concept)
    wb[sheet][cell] = 500
    wb[sheet][f"A{cell[1:]}"] = "Deferred tax, net"
    wb.save(path)

    read = _read(run_id, path)

    assert read.unread[(concept, "CY", "Company", "")].reason == "label_mismatch"


def test_a_total_keeps_its_formula_and_a_typed_total_is_read(tmp_path):
    run_id = make_run()
    ppe = field(SOFP, "SOFP-Sub-CuNonCu", 39)        # Property, plant and equipment, a total
    total_assets = field(SOFP, "SOFP-CuNonCu", 37)
    wb, path = _template_copy(tmp_path)
    sheet, cell = _target(ppe)
    wb[sheet][cell] = 4812300
    wb.save(path)

    read = _read(run_id, path)

    assert read.cells[(ppe, "CY", "Company", "")].value == 4812300
    assert not read.cells[(ppe, "CY", "Company", "")].is_formula
    assert read.cells[(total_assets, "CY", "Company", "")].is_formula
    assert read.cells[(total_assets, "CY", "Company", "")].value is None


def test_first_statements_leave_out_the_prior_year_and_list_a_filled_one(tmp_path):
    run_id = make_run(first_statements=True)
    concept = field(SOFP, "SOFP-CuNonCu", 20)
    wb, path = _template_copy(tmp_path)
    for period, value in (("CY", 10), ("PY", 9)):
        sheet, cell = _target(concept, period)
        wb[sheet][cell] = value
    wb.save(path)

    read = _read(run_id, path)

    assert read.cells[(concept, "CY", "Company", "")].value == 10
    assert (concept, "PY", "Company", "") not in read.cells
    assert read.unread[(concept, "PY", "Company", "")].reason == "prior_year_first_statements"


def test_group_and_equity_statement_cells_are_found_by_entity_period_and_column(tmp_path):
    run_id = make_run((("SOCIE", "Default"),), level="Group")
    template = "mfrs-group-socie-v1"
    with db.connect() as conn:
        concept = conn.execute("SELECT concept_uuid FROM concept_nodes WHERE template_id = ? AND matrix_col = 'C' "
                               "AND LTRIM(canonical_label, '*') = 'Profit (loss)'", (template,)).fetchone()[0]
    wb, path = _template_copy(tmp_path, "SOCIE", "Default", "group")
    for n, (entity, period) in enumerate([("Group", "CY"), ("Group", "PY"), ("Company", "CY"), ("Company", "PY")]):
        sheet, cell = _target(concept, period, entity)
        wb[sheet][cell] = 1000 + n
    wb.save(path)

    read = _read(run_id, path)

    assert {k[1:3]: c.value for k, c in read.cells.items() if k[0] == concept and c.value is not None} == {
        ("CY", "Group"): 1000, ("PY", "Group"): 1001, ("CY", "Company"): 1002, ("PY", "Company"): 1003}


def test_a_file_that_is_not_a_workbook_or_matches_nothing_is_refused(tmp_path):
    run_id = make_run()
    junk = tmp_path / "junk.xlsx"
    junk.write_bytes(b"not a zip")
    with pytest.raises(WorkbookUnreadable):
        _read(run_id, junk)
    other = tmp_path / "other.xlsx"
    wb = Workbook()
    wb.active.title = "Budget"
    wb.active["B2"] = 5
    wb.save(other)
    with pytest.raises(NothingMatches):
        _read(run_id, other)


# A genuine mTool layout (built in the test) ------------------------------

def _socie_marker_workbook(path, *, two_periods=True, sheet_name="SOCIE"):
    """v1's smallest mTool-shaped equity sheet: one equity column per period block."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name

    def add_block(header_row, marker_row, end_row, primary_row, end_date):
        ws.cell(header_row, 5).value = (f"{XSD}ifrs-full_StatementOfChangesInEquityTable::"
                                        f"{XSD}ifrs-full_ComponentsOfEquityAxis::{XSD}ifrs-full_IssuedCapitalMember")
        ws.cell(marker_row, 3).value = "#DOM#"
        ws.cell(marker_row, 4).value = "#PRIM#"
        ws.cell(end_row, 3).value = "#ENDT#"
        ws.cell(end_row, 5).value = end_date
        ws.cell(primary_row, 1).value = f"{XSD}ifrs-full_ProfitLoss@http://www.xbrl.org/2003/role/label"
        ws.cell(primary_row, 4).value = "Profit (loss)"

    add_block(2, 3, 4, 5, "31/12/2024")
    if two_periods:
        add_block(10, 11, 12, 13, "31/12/2023")
    return wb, ws


def _socie_profit(column="B") -> str:
    with db.connect() as conn:
        return conn.execute("SELECT concept_uuid FROM concept_nodes WHERE template_id = 'mfrs-company-socie-v1' "
                            "AND matrix_col = ? AND LTRIM(canonical_label, '*') = 'Profit (loss)'",
                            (column,)).fetchone()[0]


def test_mtool_period_blocks_tell_this_year_from_last_year(tmp_path):
    run_id = make_run((("SOCIE", "Default"),))
    wb, ws = _socie_marker_workbook(tmp_path)
    ws["E5"], ws["E13"] = 100, 90
    path = tmp_path / "mtool.xlsx"
    wb.save(path)

    read = _read(run_id, path)

    concept = _socie_profit("B")   # issued capital column
    assert read.layout == "mtool"
    assert read.cells[(concept, "CY", "Company", "")].value == 100
    assert read.cells[(concept, "PY", "Company", "")].value == 90
    assert read.cells[(concept, "CY", "Company", "")].workbook_cell == "SOCIE!E5"
    assert read.loose == []


def test_mtool_sheet_with_no_prior_year_section_reads_no_prior_year(tmp_path):
    run_id = make_run((("SOCIE", "Default"),))
    wb, ws = _socie_marker_workbook(tmp_path, two_periods=False)
    ws["E5"] = 100
    path = tmp_path / "mtool.xlsx"
    wb.save(path)

    read = _read(run_id, path)

    concept = _socie_profit("B")
    assert read.cells[(concept, "CY", "Company", "")].value == 100
    assert (concept, "PY", "Company", "") not in read.cells


def test_mtool_field_on_another_sheet_is_not_read(tmp_path):
    run_id = make_run((("SOCIE", "Default"),))
    wb, ws = _socie_marker_workbook(tmp_path, sheet_name="Other-Sheet")
    ws["E5"] = 100
    path = tmp_path / "mtool.xlsx"
    wb.save(path)

    with pytest.raises(NothingMatches):
        _read(run_id, path)


def test_mtool_repeated_rows_are_told_apart_by_exact_label_or_reported(tmp_path):
    run_id = make_run((("SOCIE", "Default"),))
    wb, ws = _socie_marker_workbook(tmp_path, two_periods=False)
    ws["A6"] = ws["A5"].value
    ws["D6"] = "Profit (loss)"
    ws["E5"], ws["E6"] = 100, 200
    path = tmp_path / "mtool.xlsx"
    wb.save(path)

    read = _read(run_id, path)

    key = (_socie_profit("B"), "CY", "Company", "")
    assert read.unread[key].reason == "ambiguous" and read.unread[key].holds_value
    assert read.loose == []   # listed once, under the field, not again as "no field sits there"

    ws["D5"] = "Profit (loss) from discontinued operations"
    wb.save(path)
    read = _read(run_id, path)
    assert read.cells[key].value == 200


def _ordinary_mtool_sheet(path, *, group=False, scope_markers=True, reversed_columns=False):
    """An ordinary mTool sheet: a `#PRIM#` label column and dated value columns."""
    wb = Workbook()
    ws = wb.active
    ws.title = "SOFP-CuNonCu"
    ws["C3"], ws["D3"] = "#ENDT#", "#PRIM#"
    dates = ["31/12/2024", "31/12/2023"]
    columns = ["E", "F"] if not group else ["E", "F", "G", "H"]
    if reversed_columns:
        dates.reverse()
    if group:
        dates = dates * 2
        if scope_markers:
            ws["B2"] = f"{XSD}ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis"
            ws["C2"] = "#DOM#"
            ws["E2"], ws["F2"], ws["G2"], ws["H2"] = "Consolidated", "Consolidated", "Separate", "Separate"
    for col, date in zip(columns, dates):
        ws[f"{col}3"] = date
    ws["A7"] = f"{XSD}ifrs-full_DeferredTaxAssets"
    ws["D7"] = "Deferred tax assets"
    for n, col in enumerate(columns):
        ws[f"{col}7"] = 1000 + n
    wb.save(path)


@pytest.mark.parametrize("reversed_columns", [False, True])
def test_mtool_dates_decide_this_year_not_column_order(tmp_path, reversed_columns):
    run_id = make_run()
    path = tmp_path / "mtool.xlsx"
    _ordinary_mtool_sheet(path, reversed_columns=reversed_columns)

    read = _read(run_id, path)

    concept = field(SOFP, "SOFP-CuNonCu", 20)
    cy, py = (1001, 1000) if reversed_columns else (1000, 1001)
    assert read.cells[(concept, "CY", "Company", "")].value == cy
    assert read.cells[(concept, "PY", "Company", "")].value == py


def test_mtool_group_columns_come_from_the_consolidation_markers_only(tmp_path):
    run_id = make_run(level="Group")
    concept = field("mfrs-group-sofp-cunoncu-v1", "SOFP-CuNonCu", 20)
    path = tmp_path / "mtool.xlsx"
    _ordinary_mtool_sheet(path, group=True)

    read = _read(run_id, path)

    assert {k[1:3]: c.value for k, c in read.cells.items() if k[0] == concept} == {
        ("CY", "Group"): 1000, ("PY", "Group"): 1001, ("CY", "Company"): 1002, ("PY", "Company"): 1003}

    _ordinary_mtool_sheet(path, group=True, scope_markers=False)
    read = _read(run_id, path)   # never assigned by position
    assert not any(k[0] == concept for k in read.cells)
    unread = {k[1:3]: u for k, u in read.unread.items() if k[0] == concept}
    assert len(unread) == 4 and all(u.reason == "columns_not_marked" and u.holds_value for u in unread.values())
    assert read.loose == []   # each number listed once, under the field


def test_mtool_share_capital_total_column_is_the_field_without_a_category(tmp_path):
    run_id = make_run()
    wb = Workbook()
    ws = wb.active
    ws.title = "Notes-Issuedcapital"
    ws["E18"] = (f"{XSD}ifrs-full_DisclosureOfClassesOfShareCapitalTable::{XSD}ifrs-full_ClassesOfShareCapitalAxis::"
                 f"{XSD}ifrs-full_OrdinarySharesMember")
    ws["F18"] = 0   # mTool's marker: the all-classes total sits in this column
    ws["C19"], ws["D19"] = "#LAYOUTSCSR#", "#PRIM#"
    ws["C20"], ws["E20"], ws["F20"] = "#DOM#", "Ordinary shares", "Total"
    ws["C24"], ws["E24"], ws["F24"] = "#ENDT#", "31/12/2025", "31/12/2025"
    ws["A31"] = f"{XSD}ifrs-full_NumberOfSharesIssuedAndFullyPaid"
    ws["D31"] = "*Number of shares issued and fully paid"
    ws["E31"], ws["F31"] = 1000, 1000
    path = tmp_path / "capital.xlsx"
    wb.save(path)

    read = _read(run_id, path)

    concept = field("mfrs-company-notes-issuedcapital-v1", "Notes-Issuedcapital", 8)
    ordinary = '{"ifrs-full_ClassesOfShareCapitalAxis":"ifrs-full_OrdinarySharesMember"}'
    assert {(k[1], k[3], c.value) for k, c in read.cells.items() if k[0] == concept and c.value is not None} == {
        ("CY", ordinary, 1000.0), ("CY", "", 1000.0)}


@pytest.mark.parametrize("typed", [123, "=100+23", "123"])
def test_mpers_native_share_capital_sheet_keeps_its_category(tmp_path, typed):
    run_id = make_run(standard="MPERS")
    axis, member, table = ("ifrs-smes_ClassesOfShareCapitalAxis", "ssmt-mpers_OrdinarySharesMember",
                           "ifrs-smes_DisclosureOfClassesOfShareCapitalTable")
    with db.connect() as conn:
        concept, primary = conn.execute(
            "SELECT n.concept_uuid, a.primary_concept FROM concept_nodes n JOIN concept_semantic_addresses a "
            "USING (concept_uuid) WHERE n.template_id = 'mpers-company-notes-issuedcapital-v1' AND n.kind = 'LEAF' "
            "AND LTRIM(n.canonical_label, '* ') = 'Number of shares issued and fully paid'").fetchone()
    wb = Workbook()
    ws = wb.active
    ws.title = "Notes-IssuedCap"
    ws["E2"] = "::".join("native.xsd#" + i for i in (table, axis, member))
    ws["B3"], ws["C3"], ws["D3"], ws["E3"] = "native.xsd#" + axis, "#DOM#", "#PRIM#", "Ordinary shares"
    ws["C4"], ws["E4"] = "#ENDT#", "31/12/2026"
    ws["A7"], ws["D7"], ws["E7"] = "native.xsd#" + primary, "Number of shares issued and fully paid", typed
    path = tmp_path / "native-note.xlsx"
    wb.save(path)

    read = _read(run_id, path)

    values = [(k, c) for k, c in read.cells.items() if k[0] == concept and c.value is not None]
    assert [(k[3], c.value) for k, c in values] == [(f'{{"{axis}":"{member}"}}', 123)]
