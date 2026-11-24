"""Notes into mTool's note store (app/filing/notes.py through the patcher):
the same prepared text the review screen shows and Copy gives, read back."""
from __future__ import annotations

import dataclasses

from app import db
from app.catalog.note_fields import run_note_fields
from app.filing.fill import fill_workbook
from app.filing.identify import identify
from app.filing.notes import plan_notes
from app.notes import field_text, store
from app.workbook.mtool_layout import index_taxonomy
from app.workbook.offline_fill import read_note_payloads, wrap_footnote_html
from app.workbook.xlsx_cells import read_workbook
from tests.mtool_fill_helpers import GENUINE
from tests.notes_helpers import notes_run

AGENT = store.Actor("agent", "notes")
COMPANY = GENUINE[0]
PPE = ("4", "Property, plant and equipment", [(23, 0), (23, 1), (23, 2)])
RECEIVABLES = ("5", "Trade and other receivables", [(23, 3), (23, 4), (24, 0)])


def _field(run_id: int, words: str):
    with db.connect() as conn:
        return next(f for f in run_note_fields(conn, run_id)
                    if f.template == "LIST_OF_NOTES" and not f.heading and words in f.label.lower())


def _place(run_id: int, note: tuple, node_uuid: str) -> dict:
    number, title, sources = note
    with db.connect(immediate=True) as conn:
        return store.place_note(conn, run_id, store.NotePlacement(number, title, sources, node_uuid), AGENT)


def test_two_prose_notes_land_in_the_note_store_as_their_prepared_text(tmp_path):
    run_id = notes_run()
    ppe, receivables = _field(run_id, "property, plant and equipment"), _field(run_id, "trade and other receivables")
    first, second = _place(run_id, PPE, ppe.field_id), _place(run_id, RECEIVABLES, receivables.field_id)
    out = tmp_path / "filled.xlsx"

    report = fill_workbook(run_id, COMPANY, out)

    notes = report["notes"]
    assert [n["field_id"] for n in notes["written"]] == [ppe.field_id, receivables.field_id]
    assert notes["unresolved"] == notes["mismatched"] == notes["skipped"] == []
    payloads = read_note_payloads(str(out))
    with db.connect() as conn:
        for note, written in zip((first, second), notes["written"]):
            copied = store.prepared_text(conn, run_id, note["id"])["html"]   # what Copy and review give
            assert copied == field_text.prepared(conn, run_id, written["field_id"]).html
            sheet, cell = written["cell"].split("!")
            assert payloads[(sheet, cell)] == wrap_footnote_html(copied)
            assert written["revision"] == store.prepared_text(conn, run_id, note["id"])["revision"]
    assert all(n["cell"].startswith("Notes-Listofnotes!E") for n in notes["written"])
    assert identify(read_workbook(str(out))[1]).compatibility == "known"
    assert report["counts"]["notes_written"] == 2


def test_a_note_too_long_for_mtool_or_with_no_cell_is_listed_not_written():
    run_id = notes_run()
    ppe = _field(run_id, "property, plant and equipment")
    _place(run_id, PPE, ppe.field_id)
    with db.connect() as conn:
        text = field_text.prepared(conn, run_id, ppe.field_id)
    cells = read_workbook(str(COMPANY))[1]
    occurrences = index_taxonomy(cells)

    plan = plan_notes([ppe], {ppe.field_id: dataclasses.replace(text, too_long=True)}, cells, occurrences)
    assert plan.items == [] and plan.skipped[0]["code"] == "too_long" and plan.skipped[0]["reason"]

    renamed = dataclasses.replace(ppe, taxonomy_element_id="ifrs-full_NotAnElementAnywhere")
    plan = plan_notes([renamed], {ppe.field_id: text}, cells, occurrences)
    assert plan.items == [] and plan.unresolved[0]["code"] == "no_note_cell"

    plan = plan_notes([ppe], {ppe.field_id: text}, cells, occurrences)
    assert [(i["sheet"], i["html"]) for i in plan.items] == [("Notes-Listofnotes", text.html)]


def test_patcher_errors_are_kept_as_detail_and_a_note_key_held_twice_is_not_written(tmp_path, monkeypatch, caplog):
    """The patcher's own errors stay in the report (never on the receipt) and in the log. A note-store
    error with no line of its own, a key held twice, marks the note it touches not written."""
    import logging

    from app.filing import receipts
    from app.workbook import offline_fill
    from tests.mtool_fill_helpers import seed_input_figures

    run_id = notes_run()
    seed_input_figures(run_id, every=40)
    ppe, receivables = _field(run_id, "property, plant and equipment"), _field(run_id, "trade and other receivables")
    _place(run_id, PPE, ppe.field_id)
    _place(run_id, RECEIVABLES, receivables.field_id)
    numbers, notes = offline_fill.fill_workbook, offline_fill.fill_footnotes

    def numbers_with_an_error(path, doc, out, **kw):
        first, rest = doc["writes"][0], doc["writes"][1:]
        report = numbers(path, {"writes": rest}, out, **kw)
        report["errors"].append({**first, "error": "cannot locate insertion point for E999"})
        return report

    def notes_with_a_key_held_twice(path, doc, out, **kw):
        report = notes(path, doc, out, **kw)
        key = report["footnotes_written"][0]["key"]
        report["errors"].append({"key": key, "rows": [4, 9], "error": f"duplicate note key {key} on rows [4, 9]"})
        return report

    monkeypatch.setattr(offline_fill, "fill_workbook", numbers_with_an_error)
    monkeypatch.setattr(offline_fill, "fill_footnotes", notes_with_a_key_held_twice)
    with caplog.at_level(logging.WARNING):
        report = fill_workbook(run_id, COMPANY, tmp_path / "filled.xlsx")

    figure = next(x for x in report["unresolved"] if x["code"] == "not_written")
    assert figure["detail"] == "cannot locate insertion point for E999" and figure["reason"]
    twice = [n for n in report["notes"]["unresolved"] if n["code"] == "duplicate_key"]
    assert [n["field_id"] for n in twice] == [ppe.field_id] and "duplicate note key" in twice[0]["detail"]
    assert twice[0]["reason"].startswith("mTool's note store holds this note's key twice")
    assert [n["field_id"] for n in report["notes"]["written"]] == [receivables.field_id]
    assert report["status"] == "needs review"
    shown = receipts.receipt(report)
    assert "detail" not in str(shown["lines"]) and "E999" not in str(shown)
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "cannot locate insertion point for E999" in logged and "duplicate note key" in logged


def test_a_note_too_long_for_mtool_leaves_the_file_needing_a_check(tmp_path, monkeypatch):
    run_id = notes_run()
    ppe = _field(run_id, "property, plant and equipment")
    _place(run_id, PPE, ppe.field_id)
    prepared = field_text.prepared

    def over_the_limit(*args, **kwargs):
        text = prepared(*args, **kwargs)
        return text and dataclasses.replace(text, too_long=True)

    monkeypatch.setattr(field_text, "prepared", over_the_limit)

    report = fill_workbook(run_id, COMPANY, tmp_path / "filled.xlsx")

    assert [n["code"] for n in report["notes"]["skipped"]] == ["too_long"]
    assert report["status"] == "needs review"
