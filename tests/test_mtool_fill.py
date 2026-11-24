"""Filling a genuine mTool template from a run (app/filing/), read back with
the scoring reader. The ten genuine templates under `templates/` are used."""
from __future__ import annotations

import hashlib
import re
import zipfile
from collections import Counter

import pytest

from app import db
from app.catalog import lookup
from app.catalog.fields import run_fields
from app.figures import store
from app.filing import identify as identity
from app.filing import receipts
from app.filing.fill import fill_workbook
from app.filing.plan import plan_figures
from app.scoring.workbook_read import read_filled_workbook
from app.workbook import mtool_map
from app.workbook.offline_fill import load_workbook_entries, write_patched_zip
from app.workbook.xlsx_cells import read_workbook, sheet_paths
from tests.mtool_fill_helpers import AGENT, GENUINE, matching_run, seed_input_figures, setup_of

COMPANY = GENUINE[0]   # MFRS Company, SOFP current/non-current, SOPL by function, SOCI before tax


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _figures(run_id: int) -> dict:
    with db.connect() as conn:
        return {(f["concept_uuid"], f["period"], f["entity_scope"], f["dimension_key"]): f
                for f in store.run_figures(conn, run_id)}


def _read(run_id: int, path):
    with db.connect() as conn:
        return read_filled_workbook(conn, lookup.run_family(conn, run_id), str(path))


def _key(line: dict) -> tuple:
    return line["concept_uuid"], line["period"], line["entity_scope"], line["dimension_key"]


def test_the_known_templates_file_matches_the_genuine_templates():
    expected = {}
    for template in GENUINE:
        expected.setdefault(identity.fingerprint(read_workbook(str(template))[1]), []).append(template.name)
    assert {k: v["files"] for k, v in identity.known_templates().items()} == expected
    assert sum(len(files) for files in expected.values()) == 10


@pytest.mark.parametrize("template", GENUINE, ids=lambda p: p.stem)
def test_a_genuine_template_is_filled_and_scoring_reads_the_run_back(tmp_path, template):
    run_id = matching_run(template)
    seed_input_figures(run_id)
    figures = _figures(run_id)
    before = _sha(template)
    out = tmp_path / "filled.xlsx"

    report = fill_workbook(run_id, template, out)

    assert report["template"]["compatibility"] == "known"
    assert template.name in identity.known_templates()[report["template"]["fingerprint"]]["files"]
    assert _sha(template) == before and report["output"]["sha256"] == _sha(out)
    assert report["mismatched"] == [] and len(report["written"]) > 300
    # Every figure is on the receipt once, with a reason.
    lines = [_key(x) for name in ("written", "kept", "skipped", "unresolved") for x in report[name]]
    assert Counter(lines) == Counter(figures.keys())
    assert all(x["reason"] and x["name"] for name in ("kept", "skipped", "unresolved") for x in report[name])
    assert not any(re.search(r"![A-Z]+\d", x["name"]) for x in report["unresolved"])   # named in words
    # Fill and read agree: scoring reads every written figure back, as stored.
    read = _read(run_id, out)
    for line in report["written"]:
        cell = read.cells[_key(line)]
        assert cell.value == figures[_key(line)]["value"] and f"{cell.workbook_cell}" == line["cell"], line
    # A calculated total is never typed over the template's formula. One whose SSM name sits on more
    # than one row (scoring lists it as ambiguous) is kept at its formula row and nothing is written.
    filled = read_workbook(str(out))[1]
    for line in report["kept"]:
        sheet, addr = line["cell"].split("!")
        col, row = re.fullmatch(r"([A-Z]+)(\d+)", addr).groups()
        assert line["code"] == "calculated" and filled[sheet][int(row)][col][0] == "F", line
        assert _key(line) not in read.cells or read.cells[_key(line)].is_formula
    assert not [x for x in report["unresolved"] if x["code"] == "ambiguous"]
    # mTool leaves the equity statement's across-the-row totals as inputs: those are written (v1).
    equity_totals = [x for x in report["written"]
                     if figures[_key(x)]["origin"] == "calculated" and x["statement"] == "SOCIE"]
    if setup_of(template)["standard"] == "MFRS":
        assert equity_totals
    assert all(read.cells[_key(x)].value == x["value"] for x in equity_totals)
    assert identity.identify(read_workbook(str(out))[1]).compatibility == "known"
    # The receipt: every line once, by a unique id; totals the template works out are neither listed nor counted.
    shown = receipts.receipt(report)
    assert len({x["id"] for x in shown["lines"]}) == len(shown["lines"])
    assert not [x for x in shown["lines"] if x["kind"] == "kept" or x["code"] == "calculated"]
    # Nor are the prior-year lines of notes that file the current year only: expected on every fill.
    assert not [x for x in shown["lines"] if x["code"] == "current_year_only"]
    assert shown["counts"]["not_written"] == sum(1 for k in ("skipped", "unresolved", "mismatched")
                                                 for x in report[k] if x["code"] != "current_year_only")


def test_values_go_in_as_stored_and_a_missing_figure_leaves_its_cell_empty(tmp_path):
    run_id = matching_run(COMPANY)
    with db.connect() as conn:
        family = lookup.run_family(conn, run_id)
        leaves = [f for f in run_fields(conn, family).values()
                  if f.sheet == "SOFP-Sub-CuNonCu" and not f.is_total and lookup.concept(conn, f.concept_uuid).writable]
        first, second = leaves[0], leaves[1]
        store.save_figures(conn, run_id, [
            store.FigureWrite(first.concept_uuid, "CY", "Company", -1234.56, [store.Line(first.plain_label, 4, -1234.56)]),
            store.FigureWrite(first.concept_uuid, "PY", "Company", 7000000, [store.Line(first.plain_label, 4, 7000000)]),
            store.FigureWrite(second.concept_uuid, "CY", "Company", 5, [store.Line(second.plain_label, 4, 5)])], AGENT)
        store.save_figures(conn, run_id, [store.FigureWrite(second.concept_uuid, "CY", "Company", None)],
                           store.Actor("person", "ana@firm.com"))
    out = tmp_path / "filled.xlsx"

    report = fill_workbook(run_id, COMPANY, out)

    written = {(x["concept_uuid"], x["period"]): x for x in report["written"]}
    assert written[(first.concept_uuid, "CY")]["value"] == -1234.56
    sheet, addr = written[(first.concept_uuid, "CY")]["cell"].split("!")
    col, row = re.fullmatch(r"([A-Z]+)(\d+)", addr).groups()
    cells = read_workbook(str(out))[1][sheet]
    assert cells[int(row)][col] == ("N", "-1234.56")
    assert cells[int(row)][chr(ord(col) + 1)] == ("N", "7000000")
    blank = next(x for x in report["skipped"] if x["concept_uuid"] == second.concept_uuid)
    assert blank["code"] == "no_value" and blank["reason"] == "No value in the source, so the cell is left empty."
    read = _read(run_id, out)
    assert read.cells[(second.concept_uuid, "CY", "Company", "")].value is None   # empty, not zero


def test_a_calculated_total_keeps_the_templates_formula(tmp_path):
    run_id = matching_run(COMPANY)
    seed_input_figures(run_id, every=7)
    out = tmp_path / "filled.xlsx"

    report = fill_workbook(run_id, COMPANY, out)

    assert report["kept"] and all(_figures(run_id)[_key(x)]["origin"] == "calculated" for x in report["kept"])
    assert not {_key(x) for x in report["written"]} & {_key(x) for x in report["kept"]}
    read = _read(run_id, out)
    assert all(read.cells[_key(x)].is_formula for x in report["kept"] if _key(x) in read.cells)


@pytest.mark.parametrize("lock_total", [False, True])
@pytest.mark.parametrize("total_marker", [0, "0:::abc::abc::abc"])
def test_equity_totals_across_the_row_are_mtool_inputs_and_are_written(tmp_path, lock_total, total_marker):
    """v1 tests/test_mtool_socie_input_totals.py: mTool leaves the equity statement's
    across-the-row totals unlocked and formula-free, and keeps down-the-column formulas."""
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Protection
    from tests.conftest import field_by_label

    run_id = matching_run(COMPANY)
    socie = "mfrs-company-socie-v1"
    opening = field_by_label(socie, "Equity at beginning of period", matrix_col="C")   # retained earnings
    with db.connect() as conn:
        store.save_figures(conn, run_id, [store.FigureWrite(opening, "CY", "Company", 1000.0,
                                                            [store.Line("Retained earnings", 6, 1000.0)])], AGENT)
    wb = Workbook()
    ws = wb.active
    ws.title = "SOCIE"
    prefix = "full_ifrs-cor_2022-03-24.xsd#"
    for col, member in (("E", "RetainedEarningsMember"), ("F", "EquityAttributableToOwnersOfParentMember")):
        ws[f"{col}2"] = "::".join(prefix + item for item in (
            "ifrs-full_StatementOfChangesInEquityTable", "ifrs-full_ComponentsOfEquityAxis", "ifrs-full_" + member))
    ws["G2"], ws["G4"] = total_marker, "Total"
    ws["C3"], ws["D3"], ws["C5"] = "#DOM#", "#PRIM#", "#ENDT#"
    for col in "EFG":
        ws[f"{col}5"] = "31/12/2026"
        ws[f"{col}7"].protection = Protection(locked=lock_total and col == "G")
        ws[f"{col}10"] = f"={col}7"
    ws["A7"], ws["D7"] = prefix + "ifrs-full_Equity", "*Equity at beginning of period"
    ws["A10"], ws["D10"] = prefix + "ifrs-full_Equity", "*Equity at end of period"
    ws.protection.sheet = True
    template, output = tmp_path / "mtool.xlsx", tmp_path / "filled.xlsx"
    wb.save(template)

    report = fill_workbook(run_id, template, output)

    written = {x["cell"]: x["value"] for x in report["written"]}
    assert written["SOCIE!E7"] == 1000 and written["SOCIE!F7"] == 1000
    filled = load_workbook(output)["SOCIE"]
    assert [filled[f"{col}10"].value for col in "EFG"] == ["=E7", "=F7", "=G7"]
    assert {x["cell"] for x in report["kept"]} >= {"SOCIE!E10", "SOCIE!F10", "SOCIE!G10"}
    if lock_total:
        assert "SOCIE!G7" not in written and filled["G7"].value is None
        assert any(x["cell"] == "SOCIE!G7" and x["code"] == "locked" for x in report["skipped"])
    else:
        assert written["SOCIE!G7"] == 1000 and filled["G7"].value == 1000


def test_the_template_itself_is_never_the_output(tmp_path):
    run_id = matching_run(COMPANY)
    copy = tmp_path / "template.xlsx"
    copy.write_bytes(COMPANY.read_bytes())
    with pytest.raises(ValueError):
        fill_workbook(run_id, copy, copy)
    assert copy.read_bytes() == COMPANY.read_bytes()


# Pure planning ------------------------------------------------------------------

def _plan(run_id, figures, *, locked=lambda sheet, addr: False, confirmed=None, cells=None):
    with db.connect() as conn:
        family = lookup.run_family(conn, run_id)
        fields = run_fields(conn, family)
    cells = cells or read_workbook(str(COMPANY))[1]
    placed = mtool_map.map_fields(cells, fields, family)
    return plan_figures(figures, fields, placed, cells, family, year=2025, locked=locked, confirmed=confirmed), \
        fields, placed


def _figure(concept, period="CY", value=100.0, origin="agent", dims=""):
    return {"concept_uuid": concept, "period": period, "entity_scope": "Company", "dimension_key": dims,
            "value": value, "origin": origin}


def test_a_locked_cell_a_formula_cell_and_a_first_statements_prior_year_are_not_written():
    run_id = matching_run(COMPANY)
    plan, fields, placed = _plan(run_id, [])
    single = {key: cell for cell, claims in placed.claims.items() if len(claims) == 1 for key, _ in claims}
    leaf = next(k for k in single if not fields[k[0]].is_total and k[1] == "CY")
    total = next(k for k in single if fields[k[0]].is_total and k[1] == "CY"
                 and read_workbook(str(COMPANY))[1][single[k][0]][single[k][1]][single[k][2]][0] == "F")
    plan, _, _ = _plan(run_id, [_figure(leaf[0]), _figure(total[0], origin="agent")], locked=lambda s, a: True)
    assert [x["code"] for x in plan.skipped] == ["locked", "formula"] and plan.writes == []
    first = matching_run(GENUINE[3])   # the Group first-time template
    with db.connect() as conn:
        family = lookup.run_family(conn, first)
    assert family.first_statements
    plan, _, _ = _plan(first, [_figure(leaf[0], period="PY")])
    assert plan.skipped[0]["code"] == "first_statements" and plan.writes == []


def test_a_confirmed_mapping_places_only_what_code_could_not_and_keeps_the_refusals():
    run_id = matching_run(COMPANY)
    plan, fields, placed = _plan(run_id, [])
    missed = next(k for k, (miss, _) in placed.missed.items() if miss.reason == "no_cell" and k[3] == "" and k[1] == "CY")
    taken = next(iter(placed.claims))
    plan, _, _ = _plan(run_id, [_figure(missed[0])])
    assert plan.unresolved[0]["code"] == "no_cell" and plan.unresolved[0]["reason"]
    free = ("SOFP-CuNonCu", 999, "E")
    plan, _, _ = _plan(run_id, [_figure(missed[0])], confirmed={missed: free})
    assert [w["cell"] for w in plan.writes] == ["SOFP-CuNonCu!E999"]
    plan, _, _ = _plan(run_id, [_figure(missed[0])], confirmed={missed: taken})
    assert plan.unresolved[0]["code"] == "shared_cell" and plan.writes == []

    # A person's cell also wins over the code's own cell for a figure the code placed (a read-back miss).
    placed_key = next(k for cell, claims in placed.claims.items() if len(claims) == 1 for k, _ in claims
                      if not fields[k[0]].is_total and k[3] == "")
    plan, _, _ = _plan(run_id, [_figure(placed_key[0], period=placed_key[1])], confirmed={placed_key: free})
    assert [w["cell"] for w in plan.writes] == ["SOFP-CuNonCu!E999"]


# Templates that are not known ---------------------------------------------------

def _altered(tmp_path, sheet: str, drop) -> str:
    """A copy of the Company template with some of one sheet's text cells emptied."""
    _, data, _ = load_workbook_entries(str(COMPANY))
    entry = sheet_paths(data)[sheet]
    strings = re.findall(rb"<si>.*?</si>", data["xl/sharedStrings.xml"], re.S)
    xml = data[entry].decode()

    def blank(m):
        text = strings[int(m.group(3))].decode()
        return f'<c r="{m.group(1)}"{m.group(2)}/>' if drop(text) else m.group(0)

    xml = re.sub(r'<c r="([A-Z]+\d+)"((?: s="\d+")?) t="s"><v>(\d+)</v></c>', blank, xml)
    path = tmp_path / "altered.xlsx"
    write_patched_zip(str(COMPANY), str(path), {entry: xml.encode()})
    return path


@pytest.mark.parametrize("sheet,drop,reason,code", [
    ("SOFP-CuNonCu", lambda t: ".xsd#" in t, "SOFP-CuNonCu marks a label column but carries no SSM names.", "no_cell"),
    ("SOFP-Sub-CuNonCu", lambda t: "#ENDT#" in t, "SOFP-Sub-CuNonCu holds amounts but does not mark its value columns.",
     "columns_not_marked"),
])
def test_an_altered_template_is_unknown_and_nothing_is_written_where_code_cannot_place_it(tmp_path, sheet, drop,
                                                                                          reason, code):
    run_id = matching_run(COMPANY)
    seed_input_figures(run_id, every=3)
    path = _altered(tmp_path, sheet, drop)

    report = fill_workbook(run_id, path, tmp_path / "filled.xlsx")

    assert report["template"]["compatibility"] == "unknown" and report["status"] == "needs review"
    assert reason in report["template"]["reasons"]
    assert not [x for x in report["written"] if x["cell"].startswith(sheet + "!")]
    with db.connect() as conn:
        on_sheet = {f.concept_uuid for f in run_fields(conn, lookup.run_family(conn, run_id)).values()
                    if f.sheet == sheet and not f.is_total}
    codes = {x["code"] for x in report["unresolved"] if x["concept_uuid"] in on_sheet}
    assert code in codes
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp_path / "filled.xlsx") as zout:
        entry = sheet_paths(load_workbook_entries(str(path))[1])[sheet]
        assert zin.read(entry) == zout.read(entry)


def test_a_workbook_with_no_mtool_layout_is_unknown(tmp_path):
    from app.catalog.statements import StatementType, template_path

    cells = read_workbook(str(template_path(StatementType.SOFP, "CuNonCu")))[1]
    found = identity.identify(cells)
    assert found.compatibility == "unknown" and found.reasons


def test_a_mismatched_line_keeps_its_own_reason_and_kept_totals_are_not_on_the_receipt():
    line = {"concept_uuid": "c1", "period": "CY", "entity_scope": "Company", "dimension_key": "", "name": "Revenue, 2025"}
    report = {"counts": {"written": 5, "kept": 40, "skipped": 1, "unresolved": 0, "mismatched": 1, "notes_written": 0},
              "kept": [{**line, "code": "calculated", "reason": "left to the template"}] * 40,
              "skipped": [{**line, "code": "no_value", "reason": "No value in the source, so the cell is left empty."}],
              "mismatched": [{**line, "code": "read_back", "reason": "The filled file does not hold the value written, "
                                                                    "so check this cell."}],
              "unresolved": [], "notes": {}, "template": {"compatibility": "known", "reasons": []}}
    shown = receipts.receipt(report)
    assert shown["counts"]["not_written"] == 2
    assert [(x["kind"], x["reason"]) for x in shown["lines"]] == [
        ("mismatched", "The filled file does not hold the value written, so check this cell."),
        ("skipped", "No value in the source, so the cell is left empty.")]
    assert shown["lines"][0]["id"] != shown["lines"][1]["id"]


def test_a_figure_that_is_not_a_field_is_named_in_words():
    run_id = matching_run(COMPANY)
    figure = _figure("not-a-field-uuid")
    plan, _, _ = _plan(run_id, [figure])
    assert plan.unresolved[0]["code"] == "not_a_field" and plan.unresolved[0]["name"] == "A figure not in the catalogue, 2025"
    with db.connect() as conn:
        family = lookup.run_family(conn, run_id)
        fields = run_fields(conn, family)
    cells = read_workbook(str(COMPANY))[1]
    placed = mtool_map.map_fields(cells, fields, family)
    plan = plan_figures([figure], fields, placed, cells, family, year=2025, locked=lambda s, a: False,
                        labels={"not-a-field-uuid": "*Deferred tax assets"})
    assert plan.unresolved[0]["name"] == "Deferred tax assets, 2025"
