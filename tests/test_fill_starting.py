"""The fill into a run's starting workbook (step 10g).

Ported from v1 `tests/test_prior_year_workbook.py` `:254` (upload, import and
this year's fill) and `:654` (a last-year formula this year's fill would
change is refused), with the owner's rule of 18 November 2026: this year's
figures typed in the workbook are kept, never overwritten. The workbooks are
the genuine `templates/mTool_*.xlsx`, filled by the fill from a run. No model.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile

import pytest

from app import db
from app.figures import store
from app.filing import receipts, starting_fill
from app.filing.fill import FillError, fill_workbook
from app.jobs import worker
from app.starting import store as starting
from app.workbook import report_cells
from app.workbook.xlsx_cells import load_entries, read_workbook, sheet_paths
from tests.conftest import OWNER, login, make_run
from tests.mtool_fill_helpers import AGENT
from tests.test_starting_workbook import COMPANY_RM, OTHER_PPE, ROU, _f, _import

PERSON = store.Actor("person", OWNER)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _save(run_id, figures, actor=AGENT):
    with db.connect() as conn:
        results = store.save_figures(conn, run_id, [
            store.FigureWrite(_f(where), period, "Company", value, [store.Line("A line", 3, value)])
            for where, period, value in figures], actor)
    assert all(r["ok"] for r in results), results


def _last_year(tmp_path, figures) -> tuple:
    """A genuine mTool workbook filled from a run holding `figures` [(where, period, value)], and the cell of
    each {(where, period): "Sheet!E25"}."""
    source = make_run([("SOFP", "CuNonCu")])
    _save(source, figures)
    path = tmp_path / "last.xlsx"
    report = fill_workbook(source, COMPANY_RM, path)
    uuids = {_f(where): where for where, _p, _v in figures}
    return path, {(uuids[x["concept_uuid"]], x["period"]): x["cell"] for x in report["written"]
                  if x["concept_uuid"] in uuids}


def _set_cell(path, ref: str, inner: str) -> None:
    """Replace one cell's content in the file, as a person does in Excel: `inner` is the cell's XML body."""
    sheet, cell = ref.rsplit("!", 1)
    with zipfile.ZipFile(path) as zf:
        data = {n: zf.read(n) for n in zf.namelist()}
    member = sheet_paths(data)[sheet]
    pattern = re.compile(rf'<c r="{cell}"([^>]*?)(?:/>|>.*?</c>)', re.S)
    xml = data[member].decode("utf-8")
    assert pattern.search(xml), ref
    kind = ' t="inlineStr"' if inner.startswith("<is>") else ""
    data[member] = pattern.sub(lambda m: f'<c r="{cell}"{re.sub(r" t=\"[^\"]*\"", "", m.group(1))}{kind}>{inner}</c>',
                               xml, count=1).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in data.items():
            zf.writestr(name, payload)
    path.write_bytes(buffer.getvalue())


def _cell_xml(path, ref: str) -> str:
    sheet, cell = ref.rsplit("!", 1)
    data = load_entries(str(path))
    found = re.search(rf'<c r="{cell}"[^>]*?(?:/>|>.*?</c>)', data[sheet_paths(data)[sheet]].decode("utf-8"), re.S)
    return found.group(0) if found else ""


def _value(path, ref: str):
    sheet, cell = ref.rsplit("!", 1)
    col, row = re.fullmatch(r"([A-Z]+)(\d+)", cell).groups()
    return read_workbook(str(path))[1][sheet].get(int(row), {}).get(col)


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _key(line) -> tuple:
    return line["concept_uuid"], line["period"]


def test_the_fill_writes_into_the_starting_workbook_and_every_imported_cell_stays_byte_identical(tmp_path):
    """v1 :254, with this year's typed figure kept (owner, 18 November 2026)."""
    path, cell = _last_year(tmp_path, [(OTHER_PPE, "PY", 900), (OTHER_PPE, "CY", 1100), (ROU, "PY", 0)])
    run = make_run([("SOFP", "CuNonCu")])
    _import(run, path)
    _save(run, [(ROU, "CY", 250)])
    with db.connect() as conn:
        imported = starting.imported_cells(conn, run)
        kept_file = starting.path_of(conn, run)
    before = _sha(kept_file)
    out = tmp_path / "filled.xlsx"

    report = fill_workbook(run, None, out)

    assert _sha(kept_file) == before                           # the kept workbook is never changed
    assert len(imported) == 3
    for entry in imported:
        assert _cell_xml(out, entry["cell"]) == _cell_xml(kept_file, entry["cell"]) != "", entry["cell"]
    assert {_key(x) for x in report["starting"]["kept_in_workbook"]} == {
        (_f(OTHER_PPE), "PY"), (_f(OTHER_PPE), "CY"), (_f(ROU), "PY")}
    assert all(x["reason"] == "Kept as in the workbook." for x in report["starting"]["kept_in_workbook"])
    # This year's new figure is written beside them, in the attached workbook's own cell.
    written = next(x for x in report["written"] if _key(x) == (_f(ROU), "CY"))
    assert _value(out, written["cell"]) == ("N", "250")
    assert report["starting"]["imported_kept"] == 3 and report["starting"]["filename"] == "last.xlsx"
    shown = receipts.receipt(report)
    assert shown["counts"]["kept_in_workbook"] == 3
    assert not [x for x in shown["lines"] if x["code"] == "in_workbook"]    # counted, not listed
    assert not report["starting"]["workbook_kept"] and not report["starting"]["replaced"]

    # Another template cannot be filled for this run.
    with pytest.raises(FillError, match="fills the workbook attached at setup"):
        fill_workbook(run, COMPANY_RM, tmp_path / "other.xlsx")


def test_typed_cells_with_no_figure_are_kept_and_listed_and_a_persons_edit_replaces_its_typed_figure(tmp_path):
    path, cell = _last_year(tmp_path, [(OTHER_PPE, "PY", 900), (ROU, "PY", 40), (ROU, "CY", 300)])
    formula_cell = cell[(OTHER_PPE, "PY")].replace("!F", "!E")          # this year's cell of the same line
    _set_cell(path, formula_cell, "<f>100+1</f><v>101</v>")              # a person's own formula
    run = make_run([("SOFP", "CuNonCu")])
    summary = _import(run, path)
    assert summary["formulas_left"] == [formula_cell]
    with db.connect() as conn:
        typed = next(f for f in starting.imported_cells(conn, run) if f["key"][:2] == (_f(ROU), "CY"))
    _save(run, [(ROU, "CY", 350)], PERSON)                               # the person's own edit in the app
    _save(run, [(OTHER_PPE, "CY", 77)])                                  # the run's figure for the formula's line
    out = tmp_path / "filled.xlsx"

    report = fill_workbook(run, None, out)

    assert _value(out, typed["cell"]) == ("N", "350")
    replaced = report["starting"]["replaced"]
    assert [(_key(x), x["code"]) for x in replaced] == [((_f(ROU), "CY"), "person_edit")]
    assert _cell_xml(out, formula_cell) == _cell_xml(path, formula_cell)  # the formula is kept
    assert [x["code"] for x in report["starting"]["workbook_kept"]] == ["formula_left"]
    assert next(x for x in report["skipped"] if _key(x) == (_f(OTHER_PPE), "CY"))["code"] == "formula"
    assert report["status"] == "needs review"
    shown = receipts.receipt(report)
    kinds = {x["kind"] for x in shown["lines"]}
    assert {"workbook_kept", "replaced"} <= kinds
    assert all("!" not in x["name"] and x["reason"] for x in shown["lines"])
    assert any("kept as in the workbook" in x["reason"] for x in shown["lines"] if x["kind"] == "workbook_kept")


def test_a_tampered_imported_cell_refuses_release(tmp_path, monkeypatch):
    path, cell = _last_year(tmp_path, [(OTHER_PPE, "PY", 900), (OTHER_PPE, "CY", 1100)])
    run = make_run([("SOFP", "CuNonCu")])
    _import(run, path)
    real = report_cells.fill_report_fields

    def tampering(source, doc, output):            # a fault that changes last year's figure on the way out
        result = real(source, doc, output)
        _set_cell(type(path)(output), cell[(OTHER_PPE, "PY")], "<v>901</v>")
        return result

    monkeypatch.setattr(report_cells, "fill_report_fields", tampering)
    out = tmp_path / "filled.xlsx"
    with pytest.raises(FillError, match="A figure imported from the starting workbook changed during the fill"):
        fill_workbook(run, None, out)
    assert not out.exists()                        # no file is released

    # The check on its own: an unchanged copy passes, a changed cell does not.
    with db.connect() as conn:
        start = starting_fill.load(conn, run)
    assert starting_fill.verify(path, path, set(), start)["imported_kept"] == 2
    copy = tmp_path / "copy.xlsx"
    copy.write_bytes(path.read_bytes())
    _set_cell(copy, cell[(OTHER_PPE, "CY")], "<v>1</v>")
    with pytest.raises(starting_fill.ReleaseRefused, match="imported"):
        starting_fill.verify(path, copy, set(), start)


def test_a_last_year_formula_that_this_years_fill_would_change_is_refused(tmp_path):
    """v1 :654."""
    path, cell = _last_year(tmp_path, [(OTHER_PPE, "PY", 900)])
    this_year = cell[(OTHER_PPE, "PY")].replace("!F", "!E")
    _set_cell(path, cell[(OTHER_PPE, "PY")], f"<f>900+{this_year.rsplit('!', 1)[1]}</f><v>900</v>")
    run = make_run([("SOFP", "CuNonCu")])
    assert _import(run, path)["prior_year"] == 1
    _save(run, [(OTHER_PPE, "CY", 50)])
    out = tmp_path / "filled.xlsx"
    with pytest.raises(FillError, match="formula that uses this year's cells"):
        fill_workbook(run, None, out)
    assert not out.exists()


def test_a_starting_workbook_changed_on_disk_is_refused(tmp_path):
    path, _cell = _last_year(tmp_path, [(OTHER_PPE, "PY", 900)])
    run = make_run([("SOFP", "CuNonCu")])
    _import(run, path)
    with db.connect() as conn:
        kept_file = starting.path_of(conn, run)
    kept_file.write_bytes(kept_file.read_bytes() + b"x")
    with pytest.raises(FillError, match="changed or is missing since it was attached"):
        fill_workbook(run, None, tmp_path / "filled.xlsx")


async def test_the_route_fills_the_starting_workbook_without_an_upload(client, tmp_path):
    path, _cell = _last_year(tmp_path, [(OTHER_PPE, "PY", 900)])
    run = make_run([("SOFP", "CuNonCu")])
    _import(run, path)
    with db.connect() as conn:
        conn.execute("UPDATE runs SET status = 'in_review' WHERE id = ?", (run,))
    assert login(client, OWNER).status_code == 200
    url = f"/api/runs/{run}/fills"

    upload = client.post(url, files={"file": ("other.xlsx", COMPANY_RM.read_bytes(), XLSX)})
    assert upload.status_code == 409 and upload.json()["detail"] == receipts.HAS_STARTING
    started = client.post(url)
    assert started.status_code == 202
    fill = started.json()["fill"]
    assert fill["template_filename"] == "last.xlsx" and fill["template_sha256"] == _sha(path)
    assert await worker.run_once()
    got = client.get(f"{url}/{fill['id']}").json()["fill"]
    assert got["job_status"] == "ready", got
    assert got["receipt"]["counts"]["kept_in_workbook"] == 1
    download = client.get(f"{url}/{fill['id']}/file")
    assert download.status_code == 200 and "last%20filled.xlsx" in download.headers["content-disposition"]

    plain = make_run([("SOFP", "CuNonCu")])
    with db.connect() as conn:
        conn.execute("UPDATE runs SET status = 'in_review' WHERE id = ?", (plain,))
    refused = client.post(f"/api/runs/{plain}/fills")
    assert refused.status_code == 422 and refused.json()["detail"] == receipts.WRONG_TYPE


def test_a_typed_figure_a_person_cleared_is_kept_and_listed(tmp_path):
    path, cell = _last_year(tmp_path, [(OTHER_PPE, "PY", 900), (OTHER_PPE, "CY", 1100)])
    run = make_run([("SOFP", "CuNonCu")])
    _import(run, path)
    _save(run, [(OTHER_PPE, "CY", None)], PERSON)
    out = tmp_path / "filled.xlsx"
    report = fill_workbook(run, None, out)
    assert _cell_xml(out, cell[(OTHER_PPE, "CY")]) == _cell_xml(path, cell[(OTHER_PPE, "CY")])
    assert [x["code"] for x in report["starting"]["workbook_kept"]] == ["person_cleared"]
    assert report["status"] == "needs review"


def test_a_report_field_this_run_has_no_value_for_keeps_last_years_value_and_lists_it(tmp_path):
    from app.reports import store as reports
    from tests.report_helpers import reports_run

    path, _cell = _last_year(tmp_path, [(OTHER_PPE, "PY", 900)])
    _set_cell(path, "DirectorsRep!E20", '<is><t>Last Year Director</t></is>')
    _set_cell(path, "DirectorsRep!E17", '<is><t>Last Year Director</t></is>')
    run = reports_run()
    with db.connect() as conn:
        conn.execute("UPDATE runs SET status = 'setup' WHERE id = ?", (run,))
        conn.execute("UPDATE run_setup SET year_end = NULL WHERE run_id = ?", (run,))
    _import(run, path)
    with db.connect(immediate=True) as conn:
        agent = reports.Actor("agent", "reports")
        reports.save_field(conn, run, "DIRECTORS_REPORT", "ssmt_NameOfFirstDirectorWhoSignedDirectorsReport",
                           reports.FieldWrite("filled", "Tan Ah Kow", pages=[3]), agent)
        reports.save_field(conn, run, "DIRECTORS_REPORT", "ssmt_NameOfSecondDirectorWhoSignedDirectorsReport",
                           reports.FieldWrite("not_shown", reason="Only one director signed."), agent)
    out = tmp_path / "filled.xlsx"
    report = fill_workbook(run, None, out)
    assert _value(out, "DirectorsRep!E17") == ("S", "Tan Ah Kow")             # this year's report replaces it
    assert _value(out, "DirectorsRep!E20") == ("S", "Last Year Director")      # kept, and listed for a check
    second = next(x for x in report["reports"]["unresolved"]
                  if x["element_id"] == "ssmt_NameOfSecondDirectorWhoSignedDirectorsReport")
    assert second["code"] == "kept_workbook_value" and "kept as in the workbook" in second["reason"]
