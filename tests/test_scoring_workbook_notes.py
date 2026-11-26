"""Notes in a workbook a person filled, compared with the run's notes (app/scoring/workbook_notes.py).

"Same field" only: the words are not compared. Every workbook is built by
the test: the app's own template layout from a copy of the statement
template plus a small notes sheet, and the smallest mTool-shaped notes sheet
with mTool's hidden note store.
"""
from __future__ import annotations

from openpyxl import Workbook, load_workbook
from openpyxl.workbook.defined_name import DefinedName

from app import db
from app.catalog.note_fields import run_note_fields
from app.catalog.statements import StatementType, template_path
from app.filing.fill import fill_workbook
from app.notes import field_text, store
from app.scoring import attached
from app.scoring.workbook_notes import RunNote, WorkbookNote, compare_notes, read_filled_notes, text_lines
from app.workbook.offline_fill import wrap_footnote_html
from tests.conftest import OWNER, login
from tests.mtool_fill_helpers import GENUINE
from tests.notes_helpers import notes_run

AGENT = store.Actor("agent", "notes")
PPE = ("4", "Property, plant and equipment", [(23, 0), (23, 1), (23, 2)])
RECEIVABLES = ("5", "Trade and other receivables", [(23, 3), (23, 4), (24, 0)])
SHEET = "Notes-Listofnotes"


def _field(run_id: int, words: str):
    with db.connect() as conn:
        return next(f for f in run_note_fields(conn, run_id)
                    if f.template == "LIST_OF_NOTES" and not f.heading and words in f.label.lower())


def _fields(run_id: int) -> dict:
    return {name: _field(run_id, words) for name, words in {
        "ppe": "property, plant and equipment", "receivables": "trade and other receivables",
        "borrowings": "disclosure of borrowings", "commitments": "capital and other commitments"}.items()}


def _place(run_id: int, note: tuple, node_uuid: str) -> dict:
    number, title, sources = note
    with db.connect(immediate=True) as conn:
        return store.place_note(conn, run_id, store.NotePlacement(number, title, sources, node_uuid), AGENT)


def _template_workbook(tmp_path, texts: dict):
    """The statement template with a notes sheet in the app's own layout: label in A, text in B."""
    wb = load_workbook(template_path(StatementType("SOFP"), "CuNonCu", "company", "mfrs"))
    ws = wb.create_sheet(SHEET)
    for note_field, text in texts.items():
        ws.cell(note_field.row, 1).value = note_field.label
        ws.cell(note_field.row, 2).value = text
    path = tmp_path / "filled.xlsx"
    wb.save(path)
    return path


def _attach(run_id: int, path) -> dict:
    attached.attach(run_id, path.read_bytes(), filename="filled.xlsx", uploaded_by=OWNER)
    return attached.comparison(run_id)["notes"]


def test_an_attached_workbook_with_notes_gives_a_score_and_lists_notes_elsewhere_or_missing(tmp_path):
    run_id = notes_run()
    f = _fields(run_id)
    placed = _place(run_id, PPE, f["ppe"].field_id)
    moved = _place(run_id, RECEIVABLES, f["borrowings"].field_id)   # the run chose another field
    with db.connect() as conn:   # confirmed at setup, never stored by the run
        conn.execute("INSERT INTO run_notes(run_id, position, number, title, first_page, last_page) "
                     "VALUES (?, 0, '6', 'Borrowings', 24, 24)", (run_id,))
    path = _template_workbook(tmp_path, {
        f["ppe"]: "<p>Plant and machinery, in the accountant's own words.</p>",
        f["receivables"]: "<p><b>5. TRADE AND OTHER RECEIVABLES</b></p><p>Credit terms are 30 days.</p>",
        f["borrowings"]: "<p>Note 6 Borrowings</p><p>The term loan is secured.</p>",
        f["commitments"]: "<p>Capital expenditure approved but not contracted for.</p>"})

    notes = _attach(run_id, path)

    assert (notes["in_workbook"], notes["same_field"], notes["different_field"], notes["missing"]) == (4, 1, 1, 2)
    assert notes["score"] == 0.25
    rows = {d["title"]: d for d in notes["differences"]}
    assert placed["title"] not in rows   # same field, though the words differ
    elsewhere = rows["Trade and other receivables"]
    assert elsewhere["kind"] == "different_field" and elsewhere["number"] == "5"
    assert [x["label"] for x in elsewhere["run_fields"]] == [f["borrowings"].label]
    assert f["receivables"].label in [x["label"] for x in elsewhere["workbook_fields"]]
    assert elsewhere["note_id"] == moved["id"] and elsewhere["pages"] == [23, 24]
    missing = rows["Borrowings"]
    assert missing["kind"] == "missing" and missing["run_fields"] == [] and missing["note_id"] is None
    assert [x["label"] for x in missing["workbook_fields"]] == [f["borrowings"].label]
    unnamed = rows[f["commitments"].label]   # no note of the run sits there or is named there
    assert unnamed["kind"] == "missing" and unnamed["number"] == ""


def test_the_score_follows_the_runs_notes_as_they_change(tmp_path):
    run_id = notes_run()
    f = _fields(run_id)
    path = _template_workbook(tmp_path, {f["ppe"]: "4. Property, plant and equipment\nStated at cost."})
    assert _attach(run_id, path)["missing"] == 1

    _place(run_id, PPE, f["ppe"].field_id)

    notes = attached.comparison(run_id)["notes"]
    assert notes["score"] == 1.0 and notes["differences"] == []


def test_a_workbook_with_no_notes_has_no_notes_score_and_removing_it_forgets_its_notes(tmp_path):
    run_id = notes_run()
    f = _fields(run_id)
    _place(run_id, PPE, f["ppe"].field_id)
    assert _attach(run_id, _template_workbook(tmp_path, {})) is None

    assert _attach(run_id, _template_workbook(tmp_path, {f["ppe"]: "Stated at cost."}))["in_workbook"] == 1
    attached.remove(run_id)
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM filled_workbook_notes").fetchone()[0] == 0


def test_a_row_whose_label_is_not_the_fields_label_is_not_read_as_that_field(tmp_path):
    run_id = notes_run()
    f = _fields(run_id)
    path = _template_workbook(tmp_path, {f["ppe"]: "Stated at cost."})
    wb = load_workbook(path)
    wb[SHEET].cell(f["ppe"].row, 1).value = "Disclosure of something else"
    wb.save(path)

    with db.connect() as conn:
        assert read_filled_notes(conn, run_id, str(path)) == []


def test_a_workbook_attached_before_notes_were_read_is_read_again(tmp_path):
    run_id = notes_run()
    f = _fields(run_id)
    _attach(run_id, _template_workbook(tmp_path, {f["ppe"]: "Stated at cost."}))
    with db.connect() as conn:   # as an earlier version stored it
        conn.execute("DELETE FROM filled_workbook_notes")
        conn.execute("UPDATE filled_workbooks SET read_for = ?",
                     (attached._read_for(attached.run_family(conn, run_id)).replace(', "notes"', ""),))

    assert attached.comparison(run_id)["notes"]["in_workbook"] == 1


def test_the_comparison_route_carries_the_notes(client, tmp_path):
    run_id = notes_run()
    f = _fields(run_id)
    _place(run_id, PPE, f["ppe"].field_id)
    path = _template_workbook(tmp_path, {f["ppe"]: "Stated at cost.", f["commitments"]: "None at year end."})
    assert login(client, OWNER).status_code == 200
    with path.open("rb") as handle:
        assert client.post(f"/api/runs/{run_id}/filled-workbook", files={"file": ("f.xlsx", handle)}).status_code == 200

    notes = client.get(f"/api/runs/{run_id}/comparison").json()["comparison"]["notes"]

    assert notes["score"] == 0.5 and [d["kind"] for d in notes["differences"]] == ["missing"]


# mTool's layout ---------------------------------------------------------------

def _mtool_workbook(tmp_path, rows: list[tuple], stored: dict[str, str]):
    """The smallest mTool-shaped notes sheet: each field's SSM name on its row, a `#PRIM#` label column,
    and the hidden note store a text-block cell points at through an `fn_` name."""
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws["C3"], ws["D3"] = "#LAYOUTSCSR#", "#PRIM#"
    for row, (note_field, typed, name) in enumerate(rows, start=5):
        ws.cell(row, 1).value = f"ssmt-mfrs-cor_2022-12-31.xsd#{note_field.taxonomy_element_id}"
        ws.cell(row, 4).value = note_field.label
        ws.cell(row, 5).value = typed
        if name:
            wb.defined_names[name] = DefinedName(name, attr_text=f"'{SHEET}'!$E${row}")
    hidden = wb.create_sheet("+FootnoteTexts")
    for row, (name, text) in enumerate(stored.items(), start=1):
        hidden.cell(row, 1).value, hidden.cell(row, 3).value = name, wrap_footnote_html(text)
    path = tmp_path / "mtool.xlsx"
    wb.save(path)
    return path


def test_mtool_notes_are_read_from_the_note_store_by_the_fields_ssm_name(tmp_path):
    run_id = notes_run()
    f = _fields(run_id)
    path = _mtool_workbook(tmp_path, [
        (f["ppe"], "[Text block added]", "fn_1"),
        (f["receivables"], "[Text block added]", None),      # mTool's marker with nothing stored: empty
        (f["borrowings"], "6. Borrowings, typed in the cell", None),
        (f["commitments"], "[Text block added]", "fn_2")],
        {"fn_1": "<p>4. Property, plant &amp; equipment</p><p>Stated at cost.</p>", "fn_2": "<p> </p>"})

    with db.connect() as conn:
        found = read_filled_notes(conn, run_id, str(path))

    assert {n.field_id: n.workbook_cell for n in found} == {
        f["ppe"].field_id: f"{SHEET}!E5", f["borrowings"].field_id: f"{SHEET}!E7"}
    lines = {n.field_id: n.lines for n in found}
    assert lines[f["ppe"].field_id] == ("4. Property, plant & equipment", "Stated at cost.")


def test_a_genuine_mtool_file_the_app_filled_reads_back_as_the_same_fields(tmp_path):
    run_id = notes_run()
    f = _fields(run_id)
    _place(run_id, PPE, f["ppe"].field_id)
    _place(run_id, RECEIVABLES, f["receivables"].field_id)
    out = tmp_path / "filled.xlsx"
    field_text._KEPT.clear()   # prepared texts are kept across tests; one test keeps them with a small limit
    fill_workbook(run_id, GENUINE[0], out)

    notes = _attach(run_id, out)

    assert (notes["in_workbook"], notes["same_field"], notes["score"]) == (2, 2, 1.0)


# The comparison itself (pure) ---------------------------------------------------

LABELS = {"f-a": "Disclosure of A", "f-b": "Disclosure of B", "f-c": "Disclosure of C"}


def _compare(workbook: list[WorkbookNote], run: list[RunNote], listed=()) -> dict:
    return compare_notes(workbook, run, listed, LABELS)


def test_a_note_split_over_fields_the_workbook_also_filled_is_in_the_same_field():
    run = [RunNote(1, "2", "Accounting policies", "f-a", (10,)), RunNote(2, "2", "Accounting policies", "f-b", (11,))]
    both = [WorkbookNote("f-a", "S!B1", ("2. Accounting policies",)), WorkbookNote("f-b", "S!B2", ("Inventories",))]
    assert _compare(both, run)["same_field"] == 1 and _compare(both, run)["in_workbook"] == 1

    one = _compare(both[:1], run)   # a part sits in a field the workbook left empty
    assert one["different_field"] == 1 and [f["field_id"] for f in one["differences"][0]["run_fields"]] == ["f-a", "f-b"]


def test_a_title_alone_or_inside_a_sentence_does_not_name_a_note():
    run = [RunNote(1, "9", "Inventories", "f-a", (12,))]
    workbook = [WorkbookNote("f-b", "S!B2", ("Inventories", "See note 9 Inventories for details."))]
    result = _compare(workbook, run)
    assert result["missing"] == 1 and result["differences"][0]["title"] == "Disclosure of B"
    assert result["only_in_run"] == [{"number": "9", "title": "Inventories",
                                      "run_fields": [{"field_id": "f-a", "label": "Disclosure of A"}]}]


def test_text_lines_drop_the_tags_and_mtools_shell():
    wrapped = wrap_footnote_html("<p>7. Share&nbsp;capital</p><table><tr><td>Issued</td></tr></table>")
    assert text_lines(wrapped) == ["7. Share capital", "Issued"]
    assert text_lines("<p> </p>") == [] and text_lines("") == []


def test_a_run_note_in_a_field_the_workbook_gives_to_another_note_is_not_counted_right():
    run = [RunNote(1, "1", "Revenue", "f-b", (10,)), RunNote(2, "2", "Inventories", "f-a", (11,))]
    workbook = [WorkbookNote("f-a", "S!B1", ("Note 1 Revenue",))]
    result = _compare(workbook, run)
    assert result["same_field"] == 0 and result["different_field"] == 1
