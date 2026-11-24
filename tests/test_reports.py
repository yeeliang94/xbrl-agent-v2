"""The report catalogue, the report store and the report routes (step 10a, 10c).

Ported in spirit from v1 `tests/test_reports.py`: every field of the three
reports in all four standard and level pairs (`:141`), identity numbers,
choices and dates kept as given (`:362`, `:497`), nothing guessed (`:455`),
a stale edit refused (`:160`).
"""
from __future__ import annotations

import openpyxl
import pytest

from app import db
from app.catalog import reports as catalogue
from app.catalog.parser import derive_template_id
from app.reports import store
from tests.conftest import OWNER, login, make_user
from tests.report_helpers import reports_run

AGENT = store.Actor("agent", "reports")
PERSON = store.Actor("person", OWNER)
COUNTS = {"DIRECTORS_REPORT": 22, "STATEMENT_BY_DIRECTORS": 27, "AUDITORS_REPORT": 13}


# The catalogue ----------------------------------------------------------------

@pytest.mark.parametrize("standard", ["mfrs", "mpers"])
@pytest.mark.parametrize("level", ["company", "group"])
def test_every_report_field_loads_in_each_standard_and_level_with_its_kind(standard, level):
    for report, count in COUNTS.items():
        fields = catalogue.report_fields(report, standard)
        assert len(fields) == count
        assert sum(f.kind == "html" for f in fields) == 1
        path = catalogue.report_template_path(report, level, standard)
        wb = openpyxl.load_workbook(path, read_only=True)
        try:
            ws = wb.worksheets[0]
            assert ws.title == catalogue.REPORTS[report][2]
            labels = {r: str(v).strip() for r, (v,) in enumerate(
                ws.iter_rows(min_col=1, max_col=1, values_only=True), start=1) if v}
        finally:
            wb.close()
        assert all(labels[f.row] == f.label for f in fields)   # the same rows on Group as on Company
        with db.connect() as conn:
            node = conn.execute("SELECT * FROM notes_nodes WHERE template_id = ?",
                                (derive_template_id(path),)).fetchall()
        narrative = catalogue.narrative_field(report, standard)
        assert [(n["row"], n["kind"], n["taxonomy_element_id"]) for n in node] == [
            (narrative.row, "LEAF", narrative.element_id)]


def test_kinds_and_choice_lists_come_from_the_taxonomy():
    by_id = {f.element_id: f for r in catalogue.REPORTS for f in catalogue.report_fields(r, "mfrs")}
    assert by_id["ssmt_TypeOfAuditorsOpinion"].choices == (
        "Unmodified opinion", "Unmodified but emphasis of matter", "Modified opinion - Except for",
        "Modified opinion - Disclaimer", "Modified opinion - Adverse")
    assert by_id["ssmt_DateOfSigningDirectorsReport"].kind == "date"
    assert by_id["ssmt_NumberOfDirectorsSigningDirectorsReport"].choices == ("1", "2", "3", "4", "5")
    assert by_id["ssmt_DisclosureOfStatusOfDividend"].kind == "choice"
    # Identity, licence and registration numbers are text, copied as printed.
    for element in ("ssmt_IdentificationNumberOfFirstDirectorWhoSignedDirectorsReport", "ssmt_LicenseNumberOfAuditor",
                    "ssmt_RegistrationNumberOfAuditFirm"):
        assert by_id[element].kind == "text"
    with db.connect() as conn:
        fields = catalogue.report_note_fields(conn, "group", "mpers")
    assert [f.template for f in fields] == list(catalogue.REPORTS)
    assert {f.taxonomy_element_id for f in fields} == {
        "ssmt_DisclosureOfDirectorsReportExplanatory", "ssmt_DisclosureOfStatementByDirectorsExplanatory",
        "ssmt_DisclosureOfAuditorsReportToMembersExplanatory"}


# The store ----------------------------------------------------------------------

def _save(run_id, report, field, write, actor=AGENT, **kw):
    with db.connect(immediate=True) as conn:
        return store.save_field(conn, run_id, report, field, write, actor, **kw)


def _refused(run_id, report, field, write, actor=AGENT, **kw) -> str:
    with pytest.raises(store.Refused) as caught:
        _save(run_id, report, field, write, actor, **kw)
    return str(caught.value)


@pytest.mark.parametrize("element, value", [
    ("ssmt_LicenseNumberOfAuditor", "03339/12/2025 J"),
    ("ssmt_RegistrationNumberOfAuditFirm", "AF0001 & AF0002"),
    ("ssmt_RegistrationNumberOfAuditFirm", "LLP0010081-LCA"),
    ("ssmt_NameOfAuditFirm", "Example & Co."),
])
def test_identifiers_and_names_are_kept_exactly_as_given(element, value):
    run_id = reports_run()
    saved = _save(run_id, "AUDITORS_REPORT", element, store.FieldWrite("filled", value, pages=[5]))
    assert (saved["value"], saved["status"], saved["pages"], saved["revision"]) == (value, "filled", [5], 1)


def test_choices_dates_and_lengths_are_checked_and_a_choice_takes_its_listed_spelling():
    run_id = reports_run()
    opinion = "ssmt_TypeOfAuditorsOpinion"
    assert _save(run_id, "AUDITORS_REPORT", opinion, store.FieldWrite("filled", "unmodified OPINION", pages=[5])
                 )["value"] == "Unmodified opinion"
    assert "takes one of: Unmodified opinion;" in _refused(
        run_id, "AUDITORS_REPORT", opinion, store.FieldWrite("filled", "Clean", pages=[5]))
    for bad in ("30 April 2026", "2026-02-30", "2026-4-30"):
        assert "YYYY-MM-DD" in _refused(run_id, "AUDITORS_REPORT", "AUD-7", store.FieldWrite("filled", bad, pages=[5]))
    assert _save(run_id, "AUDITORS_REPORT", "AUD-7", store.FieldWrite("filled", "2026-04-30", pages=[5]))["value"] \
        == "2026-04-30"
    assert "longer than 4,096" in _refused(run_id, "AUDITORS_REPORT", "ssmt_NameOfAuditFirm",
                                           store.FieldWrite("filled", "x" * 4097, pages=[5]))


def test_nothing_is_guessed_a_value_needs_its_page_and_an_empty_field_its_reason():
    run_id = reports_run()
    name = "ssmt_NameOfFirstDirectorWhoSignedDirectorsReport"
    assert "give the PDF page" in _refused(run_id, "DIRECTORS_REPORT", name, store.FieldWrite("filled", "Tan Ah Kow"))
    assert "not a page of this document" in _refused(run_id, "DIRECTORS_REPORT", name,
                                                     store.FieldWrite("filled", "Tan Ah Kow", pages=[99]))
    assert "instead of writing 'None'" in _refused(run_id, "DIRECTORS_REPORT", name,
                                                   store.FieldWrite("filled", "None", pages=[3]))
    assert "say in the reason why" in _refused(run_id, "DIRECTORS_REPORT", "DIR-13", store.FieldWrite("not_shown"))
    left = _save(run_id, "DIRECTORS_REPORT", "DIR-13",
                 store.FieldWrite("not_shown", "ignored", pages=[3], reason="Only two directors signed."))
    assert (left["status"], left["value"], left["reason"]) == ("not_shown", None, "Only two directors signed.")
    assert "no field DIR-99" in _refused(run_id, "DIRECTORS_REPORT", "DIR-99", store.FieldWrite("filled", "x"))
    assert "Only a person clears" in _refused(run_id, "DIRECTORS_REPORT", name, store.FieldWrite("cleared"))
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM report_fields WHERE run_id = ?", (run_id,)).fetchone()[0] == 1


def test_the_narrative_is_copied_from_the_pages_and_drawn_by_the_note_renderer():
    run_id = reports_run()
    saved = _save(run_id, "DIRECTORS_REPORT", "DIR-5",
                  store.FieldWrite("filled", sources=[(2, 0), (2, 1), (2, 2), (2, 3), (3, 0), (3, 1)]))
    assert saved["pages"] == [2, 3] and saved["value"] is None
    assert "The directors present their report" in saved["html"] and saved["fit"]["tier"] == "full"
    assert "has no block 9" in _refused(run_id, "DIRECTORS_REPORT", "DIR-5",
                                        store.FieldWrite("filled", sources=[(2, 9)]))
    with db.connect() as conn:
        text = store.narrative_text(conn, run_id, "DIRECTORS_REPORT")
        assert text is not None and "Signed in accordance" in text.html
        assert store.narrative_text(conn, run_id, "AUDITORS_REPORT") is None
        # The narrative is the report's own: it never becomes one of the run's notes.
        assert conn.execute("SELECT COUNT(*) FROM notes WHERE run_id = ?", (run_id,)).fetchone()[0] == 0


def test_a_person_edit_adds_history_a_stale_edit_is_refused_and_the_agent_leaves_it():
    run_id = reports_run()
    field = "ssmt_NameOfAuditFirm"
    _save(run_id, "AUDITORS_REPORT", field, store.FieldWrite("filled", "Example and Co", pages=[5]))
    edited = _save(run_id, "AUDITORS_REPORT", field, store.FieldWrite("filled", "Example & Co."), PERSON,
                   expected_revision=1)
    assert (edited["value"], edited["revision"], edited["actor_kind"], edited["updated_by"]) == (
        "Example & Co.", 2, "person", OWNER)
    with pytest.raises(store.StaleEdit, match="reload it"):
        _save(run_id, "AUDITORS_REPORT", field, store.FieldWrite("filled", "Other"), PERSON, expected_revision=1)
    assert "A person set Name of audit firm" in _refused(
        run_id, "AUDITORS_REPORT", field, store.FieldWrite("filled", "Example and Co", pages=[5]))
    with db.connect(immediate=True) as conn:
        cleared = store.clear_field(conn, run_id, "AUDITORS_REPORT", field, PERSON, expected_revision=2)
        history = store.field_history(conn, run_id, "AUDITORS_REPORT", field)
        events = [r["kind"] for r in conn.execute("SELECT kind FROM events WHERE run_id = ? AND source = 'reports' "
                                                  "ORDER BY id", (run_id,))]
        fill = {v["element_id"]: v for v in store.fill_values(conn, run_id)}
    assert (cleared["status"], cleared["value"], cleared["revision"]) == ("cleared", None, 3)
    assert [(h["action"], h["actor_kind"]) for h in history] == [("save", "agent"), ("edit", "person"),
                                                                 ("clear", "person")]
    assert history[0]["before"] is None and history[1]["before"]["value"] == "Example and Co"
    assert events == ["save", "edit", "clear"]
    assert fill[field]["status"] == "cleared" and fill["ssmt_StateWhereAuditFirmIsLocated"]["status"] == "not_assessed"


# The routes ---------------------------------------------------------------------

@pytest.fixture
def signed_in(client):
    make_user(OWNER)
    assert login(client, OWNER).status_code == 200
    return client


def test_the_routes_list_edit_and_clear_with_revisions(signed_in):
    run_id = reports_run()
    listed = signed_in.get(f"/api/runs/{run_id}/reports")
    assert listed.status_code == 200, listed.text
    reports = listed.json()["reports"]
    assert [(r["report"], r["total"], r["assessed"]) for r in reports] == [
        ("DIRECTORS_REPORT", 22, 0), ("STATEMENT_BY_DIRECTORS", 27, 0), ("AUDITORS_REPORT", 13, 0)]
    assert reports[2]["fields"][1]["status"] == "not_assessed" and reports[2]["fields"][1]["revision"] == 0

    url = f"/api/runs/{run_id}/reports/AUDITORS_REPORT/ssmt_LicenseNumberOfAuditor"
    first = signed_in.patch(url, json={"value": "03339/12/2025 J", "revision": 0})
    assert first.status_code == 200, first.text
    assert first.json()["field"]["value"] == "03339/12/2025 J" and first.json()["field"]["revision"] == 1
    stale = signed_in.patch(url, json={"value": "0001", "revision": 0})
    assert stale.status_code == 409 and "reload it" in stale.json()["detail"]
    bad = signed_in.patch(f"/api/runs/{run_id}/reports/AUDITORS_REPORT/AUD-7", json={"value": "soon", "revision": 0})
    assert bad.status_code == 422 and "YYYY-MM-DD" in bad.json()["detail"]
    narrative = signed_in.patch(f"/api/runs/{run_id}/reports/AUDITORS_REPORT/AUD-5",
                                json={"blocks": ["p5b0-p5b2"], "revision": 0})
    assert narrative.status_code == 200 and "We have audited" in narrative.json()["field"]["html"]
    cleared = signed_in.post(f"{url}/clear", json={"revision": 1})
    assert cleared.status_code == 200 and cleared.json()["field"]["status"] == "cleared"
    history = signed_in.get(f"{url}/history").json()["history"]
    assert [h["action"] for h in history] == ["edit", "clear"]
    assert signed_in.get(f"/api/runs/{run_id}/reports/OTHER/x/history").status_code == 404
    assert signed_in.get("/api/runs/99999/reports").status_code == 404


def test_the_routes_need_a_session(client):
    run_id = reports_run()
    assert client.get(f"/api/runs/{run_id}/reports").status_code == 401
