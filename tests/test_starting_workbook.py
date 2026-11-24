"""A part-filled workbook attached at setup (step 10d) and the hints and
comparatives the agents get from it (step 10e).

Ported from v1 `tests/test_prior_year_workbook.py` (`:62`, `:236`, `:521`,
`:887`, `:989`, `:1141`, `:1211`), with the owner's rule of 18 November 2026:
this year's typed figures are imported and kept fixed. The workbooks are the
genuine `templates/mTool_*.xlsx`, filled by the step 8 fill from a run. No model.
"""
from __future__ import annotations

import io
import re
import zipfile
from types import SimpleNamespace

import pytest

from app import db
from app.checks.runner import read_checks
from app.extraction import agent, tools
from app.extraction.tools import FigureSave, PrintedLine
from app.figures import store
from app.filing.fill import fill_workbook
from app.starting import store as starting, workbook
from app.workbook.xlsx_cells import sheet_paths
from tests.conftest import field, make_run
from tests.mtool_fill_helpers import AGENT, GENUINE, TEMPLATES
from tests.test_extraction_job import SETUP, read_run, signed_in  # noqa: F401 - the fixture

SOFP = "mfrs-company-sofp-cunoncu-v1"
FACE, SUB = "SOFP-CuNonCu", "SOFP-Sub-CuNonCu"
COMPANY_RM = TEMPLATES / "mTool_MFRS_Company_SOFP-CuNonCu_SOPL-Function_SOCI-NetOfTax_SOCF-Indirect_SOCIE_RM.xlsx"
COMPANY_RM000 = TEMPLATES / "mTool_MFRS_Company_SOFP-CuNonCu_SOPL-Function_SOCI-NetOfTax_SOCF-Indirect_SOCIE_RM000.xlsx"
MPERS = TEMPLATES / "mTool_MPERS_Company_SOFP-CuNonCu_SOPL-Function_SOCI-NetOfTax_SOCF-Indirect_SOCIE_RM.xlsx"
GROUP = TEMPLATES / "mTool_MFRS_Group_SOFP-CuNonCu_SOPL-Function_SOCI-NetOfTax_SOCF-Indirect_SOCIE_RM000.xlsx"
ROU, OTHER_PPE, PPE_TOTAL = (FACE, 11), (SUB, 38), (SUB, 39)


def _f(where, level: str = "Company") -> str:
    return field(SOFP if level == "Company" else SOFP.replace("company", "group"), *where)


def _workbook(tmp_path, figures, *, template=COMPANY_RM, level="Company", name="last.xlsx"):
    """A genuine mTool workbook filled from a run holding `figures`: [(where, period, entity, value)]."""
    source = make_run([("SOFP", "CuNonCu")], level=level)
    with db.connect() as conn:
        results = store.save_figures(conn, source, [
            store.FigureWrite(_f(where, level), period, entity, value, [store.Line("A line", 3, value)])
            for where, period, entity, value in figures], AGENT)
    assert all(r["ok"] for r in results), results
    out = tmp_path / name
    fill_workbook(source, template, out)
    return out


def _type_over_formula(path, sheet: str, cell: str, value: float):
    """Type a number over a cell's formula, as a person does in Excel."""
    with zipfile.ZipFile(path) as zf:
        data = {n: zf.read(n) for n in zf.namelist()}
    member = sheet_paths(data)[sheet]
    xml = data[member].decode("utf-8")
    pattern = re.compile(rf'<c r="{cell}"([^>]*?)(?:/>|>.*?</c>)', re.S)
    assert pattern.search(xml), cell
    xml = pattern.sub(lambda m: f'<c r="{cell}"{re.sub(r" t=\"[^\"]*\"", "", m.group(1))}><v>{value}</v></c>',
                      xml, count=1)
    data[member] = xml.encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in data.items():
            zf.writestr(name, payload)
    path.write_bytes(buffer.getvalue())
    return path


def _import(run_id, path):
    starting.attach(run_id, path.read_bytes(), filename=path.name, uploaded_by="ana@firm.com")
    with db.connect(immediate=True) as conn:
        return starting.import_at_confirm(conn, run_id)


def _figure(run_id, where, period, entity="Company", level="Company"):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM figures WHERE run_id = ? AND concept_uuid = ? AND period = ? "
                           "AND entity_scope = ? AND dimension_key = ''",
                           (run_id, _f(where, level), period, entity)).fetchone()
        return dict(row) if row else None


# 10d: the import ---------------------------------------------------------------

def test_zero_is_kept_a_blank_is_not_imported_and_first_statements_are_refused(tmp_path):
    """v1 :236, with this year's typed figures kept fixed (owner, 18 November 2026)."""
    path = _workbook(tmp_path, [(ROU, "PY", "Company", 0), (OTHER_PPE, "PY", "Company", 900),
                                (OTHER_PPE, "CY", "Company", 1100)])
    run = make_run([("SOFP", "CuNonCu")])
    summary = _import(run, path)
    assert (summary["prior_year"], summary["typed_this_year"]) == (2, 1)
    zero = _figure(run, ROU, "PY")
    assert (zero["value"], zero["status"], zero["origin"], zero["locked"]) == (0, "explicit_zero",
                                                                               "prior_workbook", 1)
    assert _figure(run, ROU, "CY") is None                       # blank in the workbook: never zero
    typed = _figure(run, OTHER_PPE, "CY")
    assert (typed["value"], typed["origin"], typed["locked"]) == (1100, "typed_in_workbook", 0)
    with db.connect() as conn:
        cells = starting.imported_cells(conn, run)
        sha = starting.record(conn, run)["sha256"]
        history = conn.execute("SELECT action, actor_kind FROM figure_history WHERE figure_id = ?",
                               (zero["id"],)).fetchall()
        kinds = {r["kind"] for r in conn.execute("SELECT kind FROM events WHERE run_id = ?", (run,))}
    assert {c["cell"] for c in cells} >= {"SOFP-CuNonCu!F32"} and len(cells) == 3
    assert all(c["sha256"] == sha for c in cells)
    assert [tuple(h) for h in history] == [("import", "import")]
    assert {"starting_workbook", "workbook_imported"} <= kinds

    first = make_run([("SOFP", "CuNonCu")], first_statements=True)
    with pytest.raises(workbook.Refused, match="first financial statements, so there is no last year's workbook"):
        _import(first, path)


def test_imported_figures_cannot_be_changed_by_an_agent(tmp_path):
    path = _workbook(tmp_path, [(OTHER_PPE, "PY", "Company", 900), (OTHER_PPE, "CY", "Company", 1100)])
    run = make_run([("SOFP", "CuNonCu")])
    _import(run, path)
    with db.connect() as conn:
        out = store.save_figures(conn, run, [
            store.FigureWrite(_f(OTHER_PPE), period, "Company", 5, [store.Line("A line", 3, 5)])
            for period in ("PY", "CY")], AGENT)
    assert [r["refused"] for r in out] == [
        "This prior-year figure is kept as filed in last year's workbook, so leave a comment if the report "
        "shows a different amount.",
        "A person typed this figure into the workbook, so leave a comment for the reviewer rather than changing it."]


def test_group_and_company_columns_stay_apart(tmp_path):
    """v1 :521."""
    path = _workbook(tmp_path, [(OTHER_PPE, "PY", "Group", 123), (OTHER_PPE, "PY", "Company", 45)],
                     template=GROUP, level="Group")
    run = make_run([("SOFP", "CuNonCu")], level="Group")
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE run_setup SET unit = ? WHERE run_id = ?", ("RM'000", run))
    _import(run, path)
    assert _figure(run, OTHER_PPE, "PY", "Group", "Group")["value"] == 123
    assert _figure(run, OTHER_PPE, "PY", "Company", "Group")["value"] == 45


@pytest.mark.parametrize("line,warns", [(None, False), (500, False), (450, True)])
def test_a_typed_subtotal_keeps_its_amount_and_a_disagreement_shows(tmp_path, line, warns):
    """v1 :887 and :989: a total typed over its formula is imported with no breakdown."""
    figures = [(OTHER_PPE, "PY", "Company", line)] if line is not None else [(ROU, "PY", "Company", 7)]
    path = _type_over_formula(_workbook(tmp_path, figures), SUB, "F60", 500)
    run = make_run([("SOFP", "CuNonCu")])
    summary = _import(run, path)
    assert summary["typed_totals"] == 1
    total = _figure(run, PPE_TOTAL, "PY")
    assert (total["value"], total["children_status"], total["origin"], total["locked"]) == (
        500, "aggregate_only", "prior_workbook", 1)
    with db.connect() as conn:
        printed = next(c for c in read_checks(conn, run) if c["name"] == "printed_totals")
    assert (printed["status"] == "warning") is warns
    if warns:
        assert "saved as 500 with no breakdown, but the lines saved under it add up to 450" in printed["message"]


@pytest.mark.parametrize("template,setup,sentence", [
    (COMPANY_RM000, {}, "The workbook is in RM'000 (thousands) but the report is in RM, so attach a workbook "
                        "in the same unit."),
    (MPERS, {}, "The workbook is an MPERS filing but this run files MFRS"),
    (COMPANY_RM, {"year_end": "2022-12-31"}, "The workbook is set for the year ending 31 December 2021 but "
                                             "the report's year ends 31 December 2022, so roll the workbook "
                                             "forward to this year in mTool first."),
])
def test_a_workbook_that_does_not_fit_is_refused_in_one_sentence(tmp_path, template, setup, sentence):
    run = make_run([("SOFP", "CuNonCu")])
    if setup:
        with db.connect(immediate=True) as conn:
            conn.execute("UPDATE run_setup SET year_end = ? WHERE run_id = ?", (setup["year_end"], run))
    path = tmp_path / "wb.xlsx"
    path.write_bytes(template.read_bytes())
    with pytest.raises(workbook.Refused) as refused:
        _import(run, path)
    assert str(refused.value).startswith(sentence)
    with db.connect() as conn:
        assert not conn.execute("SELECT 1 FROM figures WHERE run_id = ?", (run,)).fetchone()


def test_a_layout_the_workbook_lacks_a_blank_workbook_and_a_non_mtool_file_are_refused(tmp_path):
    nature = make_run([("SOFP", "CuNonCu"), ("SOPL", "Nature")])
    blank = tmp_path / "blank.xlsx"
    blank.write_bytes(COMPANY_RM.read_bytes())
    with pytest.raises(workbook.Refused, match="no sheet for the statement of profit or loss in the Nature layout"):
        _import(nature, blank)
    with pytest.raises(workbook.Refused, match="holds no figures for this run's statements"):
        _import(make_run([("SOFP", "CuNonCu")]), blank)
    template = TEMPLATES / "XBRL-template-MFRS" / "Company" / "01-SOFP-CuNonCu.xlsx"
    with pytest.raises(workbook.Refused, match="This is not an mTool workbook"):
        starting.attach(make_run([("SOFP", "CuNonCu")]), template.read_bytes(), filename="t.xlsx", uploaded_by="x")


# 10d: the routes and the confirm ---------------------------------------------

def test_attach_at_setup_import_at_confirm_and_kept_after(signed_in, tmp_path):  # noqa: F811
    run_id = read_run(signed_in)
    first = _workbook(tmp_path, [(OTHER_PPE, "PY", "Company", 1)], name="first.xlsx")
    second = _workbook(tmp_path, [(OTHER_PPE, "PY", "Company", 900), (ROU, "CY", "Company", 30)], name="b.xlsx")
    url = f"/api/runs/{run_id}/starting-workbook"
    assert signed_in.get(url).json() == {"starting_workbook": None}
    attached = signed_in.post(url, files={"file": ("first.xlsx", first.read_bytes())})
    assert attached.status_code == 200, attached.text
    assert attached.json()["starting_workbook"]["workbook"] == {
        "standard": "MFRS", "level": "Company", "unit": "RM", "year_end": "2021-12-31"}
    replaced = signed_in.post(url, files={"file": ("b.xlsx", second.read_bytes())}).json()["starting_workbook"]
    assert replaced["filename"] == "b.xlsx" and replaced["imported"] is None
    assert len(list((tmp_path / "output" / "runs" / f"run-{run_id}").glob("starting-workbook-*"))) == 1
    assert signed_in.post(url, files={"file": ("a.pdf", b"x")}).json() == {
        "detail": "Choose an .xlsx or .xlsm workbook."}

    refused = signed_in.post(f"/api/runs/{run_id}/setup", json={**SETUP, "unit": "RM'000"})
    assert refused.status_code == 422
    assert refused.json()["detail"].startswith("The workbook is in RM but the report is in RM'000 (thousands)")
    with db.connect() as conn:   # nothing of the refused confirm is kept
        assert conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0] == "setup"
        assert not conn.execute("SELECT 1 FROM figures WHERE run_id = ?", (run_id,)).fetchone()

    assert signed_in.post(f"/api/runs/{run_id}/setup", json=SETUP).status_code == 200
    record = signed_in.get(url).json()["starting_workbook"]
    assert (record["imported"]["prior_year"], record["imported"]["typed_this_year"]) == (1, 1)
    assert _figure(run_id, OTHER_PPE, "PY")["value"] == 900
    late = signed_in.post(url, files={"file": ("b.xlsx", second.read_bytes())})
    assert late.status_code == 409
    assert signed_in.delete(url).json() == {
        "detail": "The starting workbook's figures are already in this run, so it stays attached."}


def test_remove_at_setup(signed_in, tmp_path):  # noqa: F811
    run_id = read_run(signed_in)
    url = f"/api/runs/{run_id}/starting-workbook"
    path = _workbook(tmp_path, [(OTHER_PPE, "PY", "Company", 1)])
    assert signed_in.delete(url).status_code == 404
    signed_in.post(url, files={"file": ("last.xlsx", path.read_bytes())})
    assert signed_in.delete(url).status_code == 204
    assert signed_in.get(url).json() == {"starting_workbook": None}
    assert not list((tmp_path / "output" / "runs" / f"run-{run_id}").glob("starting-workbook-*"))


# 10e: hints and the comparative check -----------------------------------------

@pytest.fixture
def imported(signed_in, tmp_path):  # noqa: F811
    run_id = read_run(signed_in)
    path = _workbook(tmp_path, [(OTHER_PPE, "PY", "Company", 900), (ROU, "PY", "Company", 70),
                                (ROU, "CY", "Company", 30)])
    assert signed_in.post(f"/api/runs/{run_id}/starting-workbook",
                          files={"file": ("last.xlsx", path.read_bytes())}).status_code == 200
    assert signed_in.post(f"/api/runs/{run_id}/setup", json=SETUP).status_code == 200
    deps, message = agent.build_deps(run_id, "SOFP")
    return SimpleNamespace(run_id=run_id, deps=deps, message=message, client=signed_in)


def _save_py(deps, fid_of, value, reason=""):
    fid = deps.outline.for_uuid(_f(fid_of)).id
    entry = FigureSave(field=fid, lines=[PrintedLine(label="A line", page=2, py=value)], reason=reason)
    return tools.save_figures(SimpleNamespace(deps=deps, run_step=1), [entry])


def _comparative(run_id):
    with db.connect() as conn:
        return next(c for c in read_checks(conn, run_id) if c["name"] == "prior_year_comparatives")


def test_the_opening_message_lists_last_years_fields_as_hints(imported):
    """v1 :62 (guidance): the imported fields reach the agent; they are not its own work."""
    rou = imported.deps.outline.for_uuid(_f(ROU))
    assert "save each line this year in the field that holds its comparative" in imported.message
    assert f"- {rou.id} {rou.name}: PY 70 (kept as filed)" in imported.message
    assert f"- {rou.id} {rou.name}: CY 30 (typed, kept fixed)" in imported.message
    assert "from an earlier attempt" not in imported.message
    assert imported.deps.writes == 3   # the imported figures count as work done (a fully typed statement)


def test_a_comparative_is_compared_and_never_changes_the_kept_figure(imported):
    """v1 :62 (comparative checks)."""
    run_id, deps = imported.run_id, imported.deps
    assert _comparative(run_id)["status"] == "not_assessed"
    out = _save_py(deps, OTHER_PPE, 900)
    assert "Last year's figure is kept as filed at 900, and the report agrees." in out
    check = _comparative(run_id)
    assert check["status"] == "warning" and "1 of 2 figures kept from last year's workbook were compared" in \
        check["message"]
    out = _save_py(deps, OTHER_PPE, 950)
    assert "Last year's workbook holds 900 but you read 950, a difference of 50." in out
    assert _figure(run_id, OTHER_PPE, "PY")["value"] == 900
    assert "Other property, plant and equipment is 900 in last year's workbook but the report shows 950" in \
        _comparative(run_id)["message"]
    # A person accepts the difference by confirming the figure.
    figure_id = _figure(run_id, OTHER_PPE, "PY")["id"]
    assert imported.client.post(f"/api/runs/{run_id}/figures/{figure_id}/confirm").status_code == 200
    _save_py(deps, ROU, 70)
    check = _comparative(run_id)
    assert check["status"] == "passed" and "1 difference(s) were accepted by a person." in check["message"]


def test_a_sign_only_difference_stays_open_for_a_person(imported):
    """v1 :1141 and :1211: the agent's later reading cannot close it; only a person can."""
    run_id, deps = imported.run_id, imported.deps
    out = _save_py(deps, ROU, -70)
    assert "the same amount with the opposite sign" in out
    assert "adds this field overall, so a positive figure here increases it." in out   # the row's overall sign
    figure = _figure(run_id, ROU, "PY")
    assert (figure["value"], figure["sign_question"], figure["certainty"]) == (70, 1, "unsure")
    again = _save_py(deps, ROU, 70, reason="Shown in brackets but the total adds it.")
    assert "the difference stays open until a person decides it" in again
    check = _comparative(run_id)
    assert check["status"] == "warning"
    assert "shows -70: the same amount with the opposite sign, which a person decides." in check["message"]
    assert "Shown in brackets but the total adds it." in check["message"]
    with db.connect() as conn:
        with pytest.raises(store.Refused, match="Only a person can settle a sign-only difference"):
            store.confirm_figure(conn, run_id, figure["id"], AGENT)
    assert imported.client.post(f"/api/runs/{run_id}/figures/{figure['id']}/confirm").status_code == 200
    assert _figure(run_id, ROU, "PY")["sign_question"] == 0
    assert "opposite sign" not in _comparative(run_id)["message"]
    assert "already decided this sign difference" in _save_py(deps, ROU, -70)
    assert _figure(run_id, ROU, "PY")["sign_question"] == 0


def test_the_review_grid_shows_a_kept_figure_with_its_comparative_and_sign_question(imported):
    """The review screen draws the report's comparative beside the kept figure, and the open sign question."""
    run_id, deps = imported.run_id, imported.deps
    _save_py(deps, ROU, -70)
    view = imported.client.get(f"/api/runs/{run_id}/statements/SOFP?order=template").json()
    cells = [c for row in view["rows"] for c in row["cells"].values() if c["concept_uuid"] == _f(ROU)]
    kept = next(c for c in cells if c["value"] == 70 and c["origin"] == "prior_workbook")
    assert kept["sign_question"] is True and kept["writable"] is False
    assert kept["comparison"] == {"report_value": -70, "page": 2, "open": True}
    typed = next(c for c in cells if c["origin"] == "typed_in_workbook")
    assert typed["comparison"] is None and typed["sign_question"] is False


def test_an_amount_difference_stays_open_on_screen_until_a_person_confirms_it(imported):
    run_id, deps, client = imported.run_id, imported.deps, imported.client

    def kept():
        view = client.get(f"/api/runs/{run_id}/statements/SOFP?order=template").json()
        return next(c for row in view["rows"] for c in row["cells"].values()
                    if c["concept_uuid"] == _f(OTHER_PPE) and c["origin"] == "prior_workbook")
    _save_py(deps, OTHER_PPE, 900)
    assert kept()["comparison"]["open"] is False
    _save_py(deps, OTHER_PPE, 950)
    cell = kept()
    assert cell["comparison"] == {"report_value": 950, "page": 2, "open": True} and cell["sign_question"] is False
    assert client.post(f"/api/runs/{run_id}/figures/{cell['figure_id']}/confirm").status_code == 200
    assert kept()["comparison"]["open"] is False


def test_the_same_workbook_sent_again_as_the_setup_is_confirmed_keeps_the_kept_file(signed_in, tmp_path,  # noqa: F811
                                                                                    monkeypatch):
    run_id = read_run(signed_in)
    path = _workbook(tmp_path, [(OTHER_PPE, "PY", "Company", 900)])
    url = f"/api/runs/{run_id}/starting-workbook"
    assert signed_in.post(url, files={"file": ("last.xlsx", path.read_bytes())}).status_code == 200
    read_facts = workbook.facts

    def confirmed_meanwhile(cells):   # another tab confirms the setup while this upload is read
        with db.connect() as conn:
            conn.execute("UPDATE runs SET status = 'ready' WHERE id = ?", (run_id,))
        return read_facts(cells)

    monkeypatch.setattr(workbook, "facts", confirmed_meanwhile)
    assert signed_in.post(url, files={"file": ("last.xlsx", path.read_bytes())}).status_code == 409
    with db.connect() as conn:
        assert starting.path_of(conn, run_id).is_file()
