"""The one patcher (app/workbook/offline_fill.py): numbers, refusals, read-back.

Copied from v1 `tests/test_mtool_offline_fill.py` and
`tests/test_mtool_protected_inputs.py` for what v2 kept; every write names its
cell (v1's label writes are gone). openpyxl only builds fixtures and re-reads
output. The last tests use the genuine mTool templates.
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Protection

from app.workbook import offline_fill as patcher
from app.workbook.offline_fill import (PrefixedSheetError, col_to_idx, fill_workbook, format_value,
                                       get_sheet_paths, load_workbook_entries, main, patch_cell_in_sheet,
                                       set_full_calc_on_load, split_ref, validate_input, verify_values,
                                       write_patched_zip)
from tests.mtool_fill_helpers import GENUINE

SHEET = "SOFP-Sub-CuNonCu"
TOOL = Path(patcher.__file__)


@pytest.fixture
def template(tmp_path):
    """A small workbook in the mTool sub-sheet shape."""
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws["A4"] = "Freehold land"
    ws["B4"].number_format = "#,##0"   # styled empty
    ws["C4"].number_format = "#,##0"
    ws["A5"] = "Long term leasehold land"   # B5 absent
    ws["A6"] = "Motor vehicles"
    ws["B6"] = 999
    ws["A7"] = "*Land"
    ws["B7"] = "=SUM(B4:B6)"
    ws["A8"] = "Notes"
    ws["B8"] = "some text"
    wb.create_sheet("Other")["A1"] = "unrelated"
    path = tmp_path / "template.xlsx"
    wb.save(path)
    return str(path)


def run_fill(tmp_path, template, writes, extra_args=()):
    out, report_path, source = tmp_path / "filled.xlsx", tmp_path / "report.json", tmp_path / "fill.json"
    source.write_text(json.dumps({"writes": writes}), encoding="utf-8")
    code = main(["fill", "--workbook", template, "--input", str(source), "--output", str(out),
                 "--report", str(report_path), *extra_args])
    return code, json.loads(report_path.read_text(encoding="utf-8")), str(out)


def test_the_patcher_needs_nothing_but_the_standard_library(tmp_path):
    lone = tmp_path / "offline_fill.py"
    lone.write_bytes(TOOL.read_bytes())
    code = ("import sys; sys.path = [p for p in sys.path if 'site-packages' not in p]; "
            f"sys.argv = ['offline_fill', '--help']; exec(open({str(lone)!r}).read())")
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True)
    assert "usage: offline_fill" in result.stdout, result.stderr
    result = subprocess.run([sys.executable, str(lone), "--help"], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_a_value_is_written_into_an_existing_styled_or_missing_cell(tmp_path, template):
    code, report, out = run_fill(tmp_path, template, [
        {"sheet": SHEET, "cell": "B6", "value": 123},
        {"sheet": SHEET, "cell": "B4", "value": 1500000},
        {"sheet": SHEET, "cell": "C4", "value": -200.5},
        {"sheet": SHEET, "cell": "B5", "value": 820000},
        {"sheet": SHEET, "cell": "B100", "value": 42}])
    assert code == 0 and report["status"] == "ok"
    assert [w["action"] for w in report["written"]][-2:] == ["inserted_cell", "inserted_row"]
    ws = load_workbook(out)[SHEET]
    assert (ws["B6"].value, ws["B4"].value, ws["C4"].value, ws["B5"].value, ws["B100"].value) == \
        (123, 1500000, -200.5, 820000, 42)
    assert ws["B4"].number_format == "#,##0"


def test_untouched_members_are_byte_identical_and_the_template_is_unchanged(tmp_path, template):
    before = Path(template).read_bytes()
    code, _, out = run_fill(tmp_path, template, [{"sheet": SHEET, "cell": "B6", "value": 123}])
    assert code == 0 and Path(template).read_bytes() == before
    _, data, _ = load_workbook_entries(template)
    patched = get_sheet_paths(data)[SHEET]
    with zipfile.ZipFile(template) as zin, zipfile.ZipFile(out) as zout:
        assert zin.namelist() == zout.namelist()
        for name in zin.namelist():
            assert (zin.read(name) == zout.read(name)) == (name != patched), name


def test_a_formula_cell_is_never_written(tmp_path, template):
    code, report, out = run_fill(tmp_path, template, [{"sheet": SHEET, "cell": "B7", "value": 777}])
    assert code == 1 and report["status"] == "degraded"
    assert report["skipped_formula"][0]["cell"] == "B7" and not report["written"]
    assert load_workbook(out)[SHEET]["B7"].value == "=SUM(B4:B6)"


def test_a_text_cell_is_written_and_flagged_as_type_changed(tmp_path, template):
    code, report, out = run_fill(tmp_path, template, [{"sheet": SHEET, "cell": "B8", "value": 55}])
    assert code == 1 and report["type_changed"][0]["cell"] == "B8"
    assert load_workbook(out)[SHEET]["B8"].value == 55


def test_a_second_write_to_one_cell_and_an_unknown_sheet_are_errors(template):
    report = fill_workbook(template, {"writes": [{"sheet": SHEET, "cell": "B6", "value": 1},
                                                 {"sheet": SHEET, "cell": "B6", "value": 2},
                                                 {"sheet": "Nope", "cell": "B2", "value": 1}]}, dry_run=True)
    assert len(report["written"]) == 1
    assert ["duplicate write" in e["error"] or "not found" in e["error"] for e in report["errors"]] == [True, True]


def test_input_needs_a_cell_and_a_number_for_every_write():
    errors = validate_input({"writes": [
        {"sheet": SHEET, "cell": "B2", "value": "(200)"},
        {"sheet": SHEET, "cell": "B3", "value": True},
        {"sheet": SHEET, "label": "Freehold land", "column_role": "current_year", "value": 1},
        {"sheet": SHEET, "cell": "2B", "value": 1}]})
    assert len(errors) == 4
    assert any("every write names its cell" in e for e in errors)


def test_a_bom_input_is_read_and_a_bad_input_exits_2(tmp_path, template):
    source = tmp_path / "bom.json"
    source.write_bytes(b"\xef\xbb\xbf" + json.dumps({"writes": [{"sheet": SHEET, "cell": "B6", "value": 7}]})
                       .encode("utf-8"))
    out = tmp_path / "o.xlsx"
    assert main(["fill", "--workbook", template, "--input", str(source), "--output", str(out)]) == 0
    assert load_workbook(out)[SHEET]["B6"].value == 7
    source.write_text(json.dumps({"writes": [{"sheet": SHEET, "cell": "B2", "value": "nope"}]}))
    assert main(["fill", "--workbook", template, "--input", str(source), "--output", str(out)]) == 2


def test_the_input_workbook_is_never_patched_in_place(tmp_path, template):
    with pytest.raises(SystemExit):
        main(["fill", "--workbook", template, "--input", template, "--output", template])
    with pytest.raises(ValueError):
        write_patched_zip(template, template, {})
    before = Path(template).read_bytes()
    with pytest.raises(ValueError):
        fill_workbook(template, {"writes": [{"sheet": SHEET, "cell": "B6", "value": 1}]}, template)
    assert Path(template).read_bytes() == before


def test_values_are_written_exactly_as_given():
    assert format_value(1000) == "1000"
    assert format_value(-125000) == "-125000"
    assert format_value(1500000.0) == "1500000"
    assert format_value(43975.5) == "43975.5"
    assert format_value(-1234.56) == "-1234.56"
    assert format_value(1e21) == "1000000000000000000000"
    for bad in (True, float("nan"), float("inf"), "12"):
        with pytest.raises(ValueError):
            format_value(bad)


def test_cell_references():
    assert split_ref("B12") == ("B", 12)
    assert (col_to_idx("A"), col_to_idx("AA")) == (1, 27)
    with pytest.raises(ValueError):
        split_ref("12B")


def test_read_back_catches_a_missing_value_and_a_dry_run_writes_nothing(tmp_path, template):
    _, data, _ = load_workbook_entries(template)
    entry = get_sheet_paths(data)[SHEET]
    assert verify_values(template, [(entry, "B4", "123")]) == [
        {"entry": entry, "cell": "B4", "expected": "123", "found": None}]
    out = tmp_path / "never.xlsx"
    report = fill_workbook(template, {"writes": [{"sheet": SHEET, "cell": "B6", "value": 5}]}, str(out),
                           dry_run=True)
    assert report["written"] and not out.exists()


def test_force_recalc_sets_the_flag_on_the_existing_calc_settings(tmp_path, template):
    code, report, out = run_fill(tmp_path, template, [{"sheet": SHEET, "cell": "B6", "value": 5}],
                                 ["--force-recalc"])
    assert code == 0 and report["force_recalc"]["calcPr_found"] is True
    assert b'fullCalcOnLoad="1"' in load_workbook_entries(out)[1]["xl/workbook.xml"]


# Raw XML shapes Excel writes and openpyxl does not ---------------------------

WRAP = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>'


@pytest.mark.parametrize("cells,addr,action,expected", [
    ('<row r="2" spans="1:3"><c s="7" r="B2"><v>1</v></c></row>', "B2", "replaced", "<v>42</v>"),
    ('<row r="2"><c r="B2" s="5"/></row>', "B2", "expanded", '<c r="B2" s="5"><v>42</v></c>'),
    ('<row r="2"><c r="B2" s="3" t="s"><v>17</v></c></row>', "B2", "type_changed", '<c r="B2" s="3"><v>42</v></c>'),
    ('<row r="2" ht="15"/>', "B2", "inserted_cell", '<row r="2" ht="15"><c r="B2"><v>42</v></c></row>'),
    ('<row r="2"><c r="C2"><f>SUM(B9:B10)</f><v>0</v></c></row><row r="9"><c r="A9"/></row>', "B9",
     "inserted_cell", '<c r="B9"><v>42</v></c>'),
])
def test_excel_cell_shapes_are_patched_in_place(cells, addr, action, expected):
    out, found = patch_cell_in_sheet(WRAP % cells, addr, "42")
    assert found == action and expected in out
    assert "SUM(B9:B10)" in out or "SUM" not in cells


def test_cells_and_rows_are_inserted_in_order():
    out, action = patch_cell_in_sheet(WRAP % '<row r="2"><c r="A2"><v>1</v></c><c r="E2"><v>5</v></c></row>', "C2", "3")
    assert action == "inserted_cell" and out.index('r="A2"') < out.index('r="C2"') < out.index('r="E2"')
    out, action = patch_cell_in_sheet(WRAP % '<row r="1"><c r="A1"/></row><row r="9"><c r="A9"/></row>', "B5", "5")
    assert action == "inserted_row" and out.index('<row r="1">') < out.index('<row r="5">') < out.index('<row r="9">')
    out, action = patch_cell_in_sheet('<worksheet><sheetData/></worksheet>', "B2", "7")
    assert action == "inserted_row" and "<sheetData><row" in out


def test_a_self_closing_cell_does_not_swallow_the_cells_after_it():
    xml = WRAP % '<row r="2"><c r="B2" s="5"/><c r="C2"><f>B2*2</f><v>0</v></c></row>'
    out, action = patch_cell_in_sheet(xml, "B2", "4")
    assert action == "expanded" and "<f>B2*2</f>" in out


def test_a_namespace_prefixed_sheet_is_refused():
    with pytest.raises(PrefixedSheetError):
        patch_cell_in_sheet('<x:worksheet xmlns:x="m"><x:sheetData/></x:worksheet>', "B2", "7")


def test_full_calc_on_load_variants():
    out, found = set_full_calc_on_load('<workbook><calcPr calcId="1"/></workbook>')
    assert found and 'calcId="1" fullCalcOnLoad="1"/>' in out
    assert 'fullCalcOnLoad="1"' in set_full_calc_on_load('<workbook><calcPr fullCalcOnLoad="0"/></workbook>')[0]
    assert set_full_calc_on_load(out) == (out, True)
    assert set_full_calc_on_load("<workbook/>") == ("<workbook/>", False)


def test_inspect_lists_sheets_and_cell_kinds(template, capsys):
    assert main(["inspect", "--workbook", template]) == 0
    assert SHEET in capsys.readouterr().out
    assert main(["inspect", "--workbook", template, "--sheet", SHEET]) == 0
    out = capsys.readouterr().out
    assert "B:F" in out and "B:N" in out and "B:E" in out
    assert main(["inspect", "--workbook", template, "--sheet", "Nope"]) == 2


# Locked cells (v1 tests/test_mtool_protected_inputs.py) ---------------------

@pytest.mark.parametrize("custom_format,blocked", [
    ("", False), (' customFormat="0"', False), (' customFormat="1"', True), (' customFormat="true"', True)])
def test_a_row_style_locks_only_with_a_custom_format(tmp_path, custom_format, blocked):
    original, source = tmp_path / "original.xlsx", tmp_path / "source.xlsx"
    wb = Workbook()
    wb.active.protection.sheet = True
    wb.active.column_dimensions["D"].protection = Protection(locked=False)
    wb.save(original)
    with zipfile.ZipFile(original) as z:
        xml = z.read("xl/worksheets/sheet1.xml").decode()
    xml = xml.replace("<sheetData></sheetData>", f'<sheetData><row r="5" s="0"{custom_format}/></sheetData>')
    write_patched_zip(str(original), str(source), {"xl/worksheets/sheet1.xml": xml.encode()})
    report = fill_workbook(str(source), {"writes": [{"sheet": "Sheet", "cell": "D5", "value": 42}]}, dry_run=True)
    assert bool(report["locked"]) == blocked and bool(report["written"]) != blocked


def test_only_unlocked_inputs_change_and_the_sheet_protection_survives(tmp_path):
    source, output = tmp_path / "template.xlsx", tmp_path / "draft.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "SOCIE"
    ws.protection.sheet = True
    ws.protection.password = "fixture"
    ws["B1"] = 1
    ws["B1"].protection = Protection(locked=False)
    ws["B2"] = "=B1+1"
    ws["B3"] = 8
    ws["B4"].protection = Protection(locked=False)
    ws.column_dimensions["D"].protection = Protection(locked=False)
    wb.save(source)
    report = fill_workbook(str(source), {"writes": [{"sheet": "SOCIE", "cell": c, "value": 42}
                                                    for c in ("B1", "B2", "B3", "B4", "C5", "D5")]}, str(output))
    assert {x["cell"] for x in report["written"]} == {"B1", "B4", "D5"}
    assert {x["cell"] for x in report["skipped_formula"]} == {"B2"}
    assert {x["cell"] for x in report["locked"]} == {"B3", "C5"}
    result = load_workbook(output)
    assert result.active["B2"].value == "=B1+1" and result.active["B3"].value == 8
    assert result.active.protection.sheet and result.active.protection.password == ws.protection.password


# The genuine mTool templates ---------------------------------------------------

@pytest.mark.parametrize("template", GENUINE, ids=lambda p: p.stem)
def test_a_genuine_template_takes_a_value_and_reads_it_back(tmp_path, template):
    """An input cell of the balance-sheet sub-sheet: written, read back, and every other member unchanged."""
    from app.workbook.mtool_layout import sheet_layout
    from app.workbook.xlsx_cells import read_workbook

    _, cells = read_workbook(str(template))
    sheet = next(s for s in cells if s.startswith("SOFP-Sub"))
    layout = sheet_layout(cells[sheet], group="_Group_" in template.name)
    column = next(iter(layout.columns.values()))
    _, data, _ = load_workbook_entries(str(template))
    protection = patcher.protected_input_cells(data, get_sheet_paths(data))
    row = next(r for r, row_cells in sorted(cells[sheet].items()) if r > 25 and
               row_cells.get(column, ("", ""))[0] == "E" and
               not patcher.is_locked_input(protection, sheet, f"{column}{r}"))
    out = tmp_path / "filled.xlsx"
    report = fill_workbook(str(template), {"writes": [{"sheet": sheet, "cell": f"{column}{row}",
                                                       "value": -1234.56}]}, str(out))
    assert report["status"] == "ok" and report["mismatches"] == []
    assert read_workbook(str(out))[1][sheet][row][column] == ("N", "-1234.56")
    entry = get_sheet_paths(data)[sheet]
    with zipfile.ZipFile(template) as zin, zipfile.ZipFile(out) as zout:
        assert [n for n in zin.namelist() if zin.read(n) != zout.read(n)] == [entry]
