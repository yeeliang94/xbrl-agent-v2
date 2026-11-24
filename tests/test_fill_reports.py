"""The mTool fill writes the three reports (step 10g).

Ported from v1 `tests/test_reports.py` `:25` (narratives and the auditor's
details in a native workbook) and `:405` (the auditor table's one typing
row), against every genuine `templates/mTool_*.xlsx`. No model is called.
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import date

import pytest

from app import db
from app.filing import receipts
from app.filing.fill import fill_workbook
from app.reports import store
from app.workbook.offline_fill import read_note_payloads
from app.workbook.xlsx_cells import read_workbook, sheet_paths
from tests.mtool_fill_helpers import GENUINE, setup_of
from tests.report_helpers import reports_run

AGENT = store.Actor("agent", "reports")
PERSON = store.Actor("person", "ana@firm.com")
MFRS_COMPANY = next(t for t in GENUINE if setup_of(t)["standard"] == "MFRS" and setup_of(t)["level"] == "Company")
NARRATIVES = {"DIRECTORS_REPORT": [(2, 0), (2, 1)], "STATEMENT_BY_DIRECTORS": [(4, 0), (4, 1)],
              "AUDITORS_REPORT": [(5, 0), (5, 1)]}
VALUES = [
    ("DIRECTORS_REPORT", "ssmt_NameOfFirstDirectorWhoSignedDirectorsReport", "Tan Ah Kow", 3),
    ("DIRECTORS_REPORT", "ssmt_IdentificationNumberOfFirstDirectorWhoSignedDirectorsReport", "900101-14-5678", 3),
    ("DIRECTORS_REPORT", "ssmt_DateOfSigningDirectorsReport", "2026-04-30", 3),
    ("DIRECTORS_REPORT", "ssmt_DisclosureOfStatusOfDividend", "Not mentioned", 2),
    ("STATEMENT_BY_DIRECTORS", "ssmt_NameOfFirstDirectorWhoSignedStatementByDirectors", "Tan Ah Kow", 4),
    ("AUDITORS_REPORT", "ssmt_TypeOfAuditorsOpinion", "Unmodified opinion", 5),
    ("AUDITORS_REPORT", "ssmt_DateOfSigningAuditorsReport", "2026-04-30", 5),
    ("AUDITORS_REPORT", "ssmt_LicenseNumberOfAuditor", "0012", 5),
    ("AUDITORS_REPORT", "ssmt_NameOfAuditorSigningReport", "Wong Kar Wai", 5),
    ("AUDITORS_REPORT", "ssmt_RegistrationNumberOfAuditFirm", "LLP0010081-LCA & AF 0758", 5),
    ("AUDITORS_REPORT", "ssmt_NameOfAuditFirm", "Example & Co.", 5),
    ("AUDITORS_REPORT", "ssmt_AddressOne", "1 Example Street", 5),
    ("AUDITORS_REPORT", "ssmt_PostcodeOfAuditFirm", "00100", 5),
    ("AUDITORS_REPORT", "ssmt_TownWhereAuditFirmIsLocated", "Kuala Lumpur", 5),
    ("AUDITORS_REPORT", "ssmt_StateWhereAuditFirmIsLocated", "Selangor", 5),
]


def _save(run_id, report, element, write, actor=AGENT):
    with db.connect(immediate=True) as conn:
        return store.save_field(conn, run_id, report, element, write, actor)


def _reports(run_id: int) -> None:
    for report, sources in NARRATIVES.items():
        _save(run_id, report, report[:3] + "-5" if report != "STATEMENT_BY_DIRECTORS" else "SBD-5",
              store.FieldWrite("filled", sources=sources))
    for report, element, value, page in VALUES:
        _save(run_id, report, element, store.FieldWrite("filled", value, pages=[page]))
    _save(run_id, "DIRECTORS_REPORT", "ssmt_NameOfSecondDirectorWhoSignedDirectorsReport",
          store.FieldWrite("not_shown", reason="Only one director signed."))
    _save(run_id, "AUDITORS_REPORT", "ssmt_AddressTwo", store.FieldWrite("filled", "Suite 2", pages=[5]))
    with db.connect(immediate=True) as conn:
        store.clear_field(conn, run_id, "AUDITORS_REPORT", "ssmt_AddressTwo", PERSON)


def _by_element(report: dict) -> dict:
    return {(line["report"], line["element_id"]): line for kind in ("written", "skipped", "unresolved", "mismatched")
            for line in report["reports"][kind]}


@pytest.mark.parametrize("template", GENUINE, ids=lambda p: p.stem)
def test_each_genuine_template_takes_the_reports_and_reads_them_back(tmp_path, template):
    setup = setup_of(template)
    run_id = reports_run(standard=setup["standard"], level=setup["level"])
    _reports(run_id)
    before, before_cells = read_workbook(str(template))
    out = tmp_path / "filled.xlsx"

    report = fill_workbook(run_id, template, out)

    after, cells = read_workbook(str(out))
    lines = _by_element(report)
    code = {key: line["code"] for key, line in lines.items()}
    audit = "Auditorsreport" if setup["standard"] == "MPERS" else "AuditReport"
    # Names and numbers on their rows; the auditor's details in the table's one typing row.
    assert cells["DirectorsRep"][17]["E"] == ("S", "Tan Ah Kow")
    assert cells["DirectorsRep"][19]["E"] == ("S", "900101-14-5678")   # as printed
    assert cells["StatOfDirectors"][18]["E"] == ("S", "Tan Ah Kow")
    typing = {col: cells[audit][32][col] for col in "EFGHIKLM"}
    assert typing == {"E": ("S", "0012"), "F": ("S", "Wong Kar Wai"), "G": ("S", "AF0758"),
                      "H": ("S", "Example & Co."), "I": ("S", "1 Example Street"), "K": before_cells[audit][32]["K"],
                      "L": ("S", "00100"), "M": ("S", "Kuala Lumpur")}
    firm = lines[("AUDITORS_REPORT", "ssmt_RegistrationNumberOfAuditFirm")]
    assert (firm["code"], firm["written"], firm["value"]) == ("written", "AF0758", "LLP0010081-LCA & AF 0758")
    assert code[("AUDITORS_REPORT", "ssmt_AddressTwo")] == "cleared" and cells[audit][32]["J"] == ("E", "")
    # mTool's own pickers stay mTool's: the choices, the dates and the state are listed, never typed in.
    for key in (("AUDITORS_REPORT", "ssmt_TypeOfAuditorsOpinion"), ("AUDITORS_REPORT", "ssmt_DateOfSigningAuditorsReport"),
                ("DIRECTORS_REPORT", "ssmt_DateOfSigningDirectorsReport"),
                ("DIRECTORS_REPORT", "ssmt_DisclosureOfStatusOfDividend"),
                ("AUDITORS_REPORT", "ssmt_StateWhereAuditFirmIsLocated")):
        assert code[key] == "in_mtool", key
    assert cells[audit][16]["E"] == before_cells[audit][16]["E"] and cells[audit][32]["N"] == before_cells[audit][32]["N"]
    # A field the document does not show is left and listed.
    second = lines[("DIRECTORS_REPORT", "ssmt_NameOfSecondDirectorWhoSignedDirectorsReport")]
    assert second["code"] == "not_shown" and cells["DirectorsRep"][20]["E"] == before_cells["DirectorsRep"][20]["E"]
    # The three narratives go into mTool's note store at their text-block cell, labels untouched.
    payloads = read_note_payloads(str(out))
    for sheet in ("DirectorsRep", "StatOfDirectors", audit):
        assert cells[sheet][15]["E"] == ("S", "[Text block added]")
        assert cells[sheet][15]["D"] == before_cells[sheet][15]["D"]
        assert payloads[(sheet, "E15")]
    assert len(report["notes"]["written"]) == 3 and not report["reports"]["mismatched"]
    # Every sheet but the report sheets and the note store keeps its XML.
    paths = sheet_paths(before)
    touched = {paths[s] for s in ("DirectorsRep", "StatOfDirectors", audit, "+FootnoteTexts")}
    assert all(after[p] == before[p] for p in paths.values() if p not in touched)
    # The receipt names each report line in words, once.
    shown = receipts.receipt(report)
    report_lines = [x for x in shown["lines"] if x["kind"].startswith("report_")]
    assert len({x["id"] for x in shown["lines"]}) == len(shown["lines"])
    assert report_lines and all(x["name"] and x["reason"] and "!" not in x["name"] for x in report_lines)
    assert shown["counts"]["reports"] == len(report["reports"]["written"]) == 11


def _expose(template, out, sheet: str, rules: list[tuple[str, str]]):
    """The template with these cells unlocked and given their own check (a list or a date), as an mTool
    workbook that lets the cell be typed would have."""
    with zipfile.ZipFile(template) as zf:
        data = {n: zf.read(n) for n in zf.namelist()}
    member = sheet_paths(data)[sheet]
    xml = data[member].decode("utf-8")
    open_style = re.search(r'<c r="E32" s="(\d+)"', xml).group(1)   # the auditor table's unlocked style
    checks = []
    for cell, rule in rules:
        xml = re.sub(rf'<c r="{cell}" s="\d+"', f'<c r="{cell}" s="{open_style}"', xml, count=1)
        formula = (f'<formula1>"{rule}"</formula1>' if rule != "date" else "<formula1>1</formula1>")
        checks.append(f'<dataValidation type="{"date" if rule == "date" else "list"}" allowBlank="1" '
                      f'sqref="{cell}">{formula}</dataValidation>')
    block = f'<dataValidations count="{len(checks)}">{"".join(checks)}</dataValidations>'
    xml = xml.replace("<pageMargins", block + "<pageMargins", 1)
    data[member] = xml.encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in data.items():
            zf.writestr(name, payload)
    out.write_bytes(buffer.getvalue())
    return out


def test_a_date_and_a_choice_go_in_when_the_cell_takes_them(tmp_path):
    choices = "Unmodified opinion,Unmodified but emphasis of matter"
    template = _expose(MFRS_COMPANY, tmp_path / "open.xlsx", "AuditReport", [("E16", choices), ("E17", "date")])
    run_id = reports_run()
    _reports(run_id)
    out = tmp_path / "filled.xlsx"

    report = fill_workbook(run_id, template, out)

    cells = read_workbook(str(out))[1]["AuditReport"]
    assert cells[16]["E"] == ("S", "Unmodified opinion")
    assert cells[17]["E"] == ("N", str((date(2026, 4, 30) - date(1899, 12, 30)).days))   # Excel's day number
    code = {key: line["code"] for key, line in _by_element(report).items()}
    assert code[("AUDITORS_REPORT", "ssmt_TypeOfAuditorsOpinion")] == "written"
    assert code[("AUDITORS_REPORT", "ssmt_DateOfSigningAuditorsReport")] == "written"

    # A choice the cell's own list does not offer, and a date cell with no date check, are left for a person.
    narrow = _expose(MFRS_COMPANY, tmp_path / "narrow.xlsx", "AuditReport",
                     [("E16", "Modified opinion - Except for"), ("E17", "Not a date")])
    report = fill_workbook(run_id, narrow, tmp_path / "narrow-filled.xlsx")
    code = {key: line["code"] for key, line in _by_element(report).items()}
    assert code[("AUDITORS_REPORT", "ssmt_TypeOfAuditorsOpinion")] == "choice_not_listed"
    assert code[("AUDITORS_REPORT", "ssmt_DateOfSigningAuditorsReport")] == "not_a_date_cell"
    assert report["status"] == "needs review"


@pytest.mark.parametrize("element, value, reason", [
    ("ssmt_LicenseNumberOfAuditor", "03339/12/2025 J", "licence_format"),
    ("ssmt_RegistrationNumberOfAuditFirm", "AF0001 & AF0002", "firm_format"),
    ("ssmt_RegistrationNumberOfAuditFirm", "LLP0010081-LCA", "firm_format"),
])
def test_an_identifier_mtool_cannot_take_as_printed_is_listed_never_shortened(tmp_path, element, value, reason):
    run_id = reports_run()
    _save(run_id, "AUDITORS_REPORT", element, store.FieldWrite("filled", value, pages=[5]))
    report = fill_workbook(run_id, MFRS_COMPANY, tmp_path / "filled.xlsx")
    line = _by_element(report)[("AUDITORS_REPORT", element)]
    assert line["code"] == reason and line in report["reports"]["unresolved"]
    cells = read_workbook(str(tmp_path / "filled.xlsx"))[1]["AuditReport"]
    assert cells[32]["E"] == ("E", "") and cells[32]["G"] == ("E", "")


def test_reports_nobody_read_are_one_line_each_and_leave_the_sheets_as_they_are(tmp_path):
    run_id = reports_run()
    before = read_workbook(str(MFRS_COMPANY))[0]
    report = fill_workbook(run_id, MFRS_COMPANY, tmp_path / "filled.xlsx")
    after = read_workbook(str(tmp_path / "filled.xlsx"))[0]
    assert [x["code"] for x in report["reports"]["skipped"]] == ["no_reports"] * 3
    assert not report["reports"]["written"] and not report["reports"]["unresolved"]
    paths = sheet_paths(before)
    assert all(after[paths[s]] == before[paths[s]] for s in ("DirectorsRep", "StatOfDirectors", "AuditReport"))


# A starting workbook (step 10g): what this fill leaves in last year's cells is listed --------------------------

def _starting_run(tmp_path, last_year_reports=None) -> tuple[int, object]:
    """Last year's genuine workbook (a figure, and the reports of `last_year_reports` when given) attached to a
    new reports run. Returns the run and last year's file."""
    from tests.test_fill_starting import OTHER_PPE, _last_year
    from tests.test_starting_workbook import _import

    path, _cell = _last_year(tmp_path, [(OTHER_PPE, "PY", 900)])
    if last_year_reports is not None:
        with_reports = tmp_path / "last-reports.xlsx"
        fill_workbook(last_year_reports, path, with_reports)
        path = with_reports
    run_id = reports_run()
    with db.connect() as conn:
        conn.execute("UPDATE runs SET status = 'setup' WHERE id = ?", (run_id,))
        conn.execute("UPDATE run_setup SET year_end = NULL WHERE run_id = ?", (run_id,))
    _import(run_id, path)
    return run_id, path


def test_a_starting_workbook_value_the_fill_leaves_is_listed_in_every_report_and_picker_cell(tmp_path):
    from tests.test_fill_starting import OTHER_PPE, _last_year, _set_cell
    from tests.test_starting_workbook import _import

    path, _cell = _last_year(tmp_path, [(OTHER_PPE, "PY", 900)])
    _set_cell(path, "AuditReport!E16", "<is><t>Unmodified opinion</t></is>")        # mTool's locked picker
    _set_cell(path, "StatOfDirectors!E18", "<is><t>Last Year Director</t></is>")    # a report nobody read
    run_id = reports_run()
    with db.connect() as conn:
        conn.execute("UPDATE runs SET status = 'setup' WHERE id = ?", (run_id,))
        conn.execute("UPDATE run_setup SET year_end = NULL WHERE run_id = ?", (run_id,))
    _import(run_id, path)
    _save(run_id, "AUDITORS_REPORT", "ssmt_TypeOfAuditorsOpinion",
          store.FieldWrite("filled", "Unmodified opinion", pages=[5]))
    out = tmp_path / "filled.xlsx"

    report = fill_workbook(run_id, None, out)

    lines = _by_element(report)
    picker = lines[("AUDITORS_REPORT", "ssmt_TypeOfAuditorsOpinion")]
    assert (picker["code"], picker["cell"]) == ("in_mtool_kept", "AuditReport!E16")
    unread = lines[("STATEMENT_BY_DIRECTORS", "ssmt_NameOfFirstDirectorWhoSignedStatementByDirectors")]
    assert (unread["code"], unread["cell"]) == ("kept_workbook_value", "StatOfDirectors!E18")
    assert picker in report["reports"]["unresolved"] and unread in report["reports"]["unresolved"]
    kept = {x["element_id"] for x in report["reports"]["unresolved"]}
    assert kept == {"ssmt_TypeOfAuditorsOpinion", "ssmt_NameOfFirstDirectorWhoSignedStatementByDirectors"}
    assert "STATEMENT_BY_DIRECTORS" in {x["report"] for x in report["reports"]["skipped"] if x["code"] == "no_reports"}
    cells = read_workbook(str(out))[1]
    assert cells["StatOfDirectors"][18]["E"] == ("S", "Last Year Director")       # kept as in the workbook
    assert report["status"] == "needs review"


def test_a_starting_workbook_text_block_the_fill_does_not_replace_is_listed(tmp_path):
    last_year = reports_run()
    _reports(last_year)
    run_id, path = _starting_run(tmp_path, last_year)
    _save(run_id, "DIRECTORS_REPORT", "DIR-5", store.FieldWrite("not_shown", reason="No directors' report printed."))
    with db.connect(immediate=True) as conn:
        store.clear_field(conn, run_id, "STATEMENT_BY_DIRECTORS", "SBD-5", PERSON)
    _save(run_id, "AUDITORS_REPORT", "AUD-5", store.FieldWrite("filled", sources=NARRATIVES["AUDITORS_REPORT"]))
    out = tmp_path / "filled.xlsx"

    report = fill_workbook(run_id, None, out)

    unresolved = {x["report"]: x for x in report["reports"]["unresolved"] if x.get("field_id", "").endswith("-5")}
    assert (unresolved["DIRECTORS_REPORT"]["code"], unresolved["DIRECTORS_REPORT"]["cell"]) == \
        ("narrative_kept", "DirectorsRep!E15")
    assert unresolved["STATEMENT_BY_DIRECTORS"]["code"] == "narrative_clear_in_mtool"
    assert "AUDITORS_REPORT" not in unresolved                                     # this year's text replaces it
    before, after = read_note_payloads(str(path)), read_note_payloads(str(out))
    assert after[("DirectorsRep", "E15")] == before[("DirectorsRep", "E15")]
    assert after[("AuditReport", "E15")] and report["status"] == "needs review"
    shown = receipts.receipt(report)
    assert any(x["kind"] == "report_unresolved" and "remove it in mTool" in x["reason"] for x in shown["lines"])
