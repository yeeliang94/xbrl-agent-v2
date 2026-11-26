"""A run that starts from a Word file: the reading copy, the file's own lines,
the refusals, and the run going through reading (go-live plan C6, part a)."""
from __future__ import annotations

import io
import zipfile

import pymupdf
import pytest

from app import db
from app.documents import file_lines, routes as document_routes
from app.documents.word_copy import word_copy
from app.jobs import worker
from app.models import factory
from app.utils.paths import output_dir
from tests import office_samples as samples, reading_fakes as fakes
from tests.conftest import OWNER, login, make_user


@pytest.fixture
def signed_in(client):
    make_user(OWNER)
    assert login(client, OWNER).status_code == 200
    return client


def upload(client, data: bytes, name: str):
    return client.post("/api/runs", files={"file": (name, io.BytesIO(data), "application/octet-stream")})


def test_a_word_file_starts_a_run_with_a_reading_copy_and_keeps_the_file(signed_in):
    data = samples.word()

    response = upload(signed_in, data, "Statements 2025.docx")

    assert response.status_code == 200, response.text
    run, document = response.json()["run"], response.json()["document"]
    assert run["status"] == "reading" and run["filename"] == "Statements 2025.docx"
    assert document["kind"] == "word" and document["page_count"] == 1 and document["scanned_pages"] == 0
    assert document["size_bytes"] == len(data)          # the uploaded file's size, not the reading copy's
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE run_id = ?", (run["id"],)).fetchone()
    assert (output_dir() / row["source_path"]).read_bytes() == data
    copy = (output_dir() / row["stored_path"]).read_bytes()
    assert copy.startswith(b"%PDF-")
    text = pymupdf.open(stream=copy, filetype="pdf")[0].get_text()
    assert samples.COMPANY in text and "1,284,300" in text
    events = signed_in.get(f"/api/runs/{run['id']}/events").json()["events"]
    assert [e["message"] for e in events] == ["The Word file is stored and its reading copy is made: 1 page."]
    picture = signed_in.get(f"/api/runs/{run['id']}/pages/1/image")
    assert picture.status_code == 200 and picture.headers["content-type"] == "image/png"


def test_the_files_own_lines_are_stored_with_their_pages(signed_in):
    run_id = upload(signed_in, samples.word(), "s.docx").json()["run"]["id"]

    with db.connect() as conn:
        lines = file_lines.of_run(conn, run_id)
    assert (lines[0].kind, lines[0].cells) == ("heading", [samples.COMPANY])
    rows = [line for line in lines if line.kind == "row"]
    assert [(r.block, r.row) for r in rows[:2]] == [(1, 1), (1, 2)]
    assert rows[1].cells == ["Property, plant and equipment", "1,284,300", "1,196,450"]
    assert {line.page for line in lines} == {1}


def test_every_line_of_a_long_word_file_names_the_page_it_is_on():
    copy = word_copy("long.docx", samples.word(note_paragraphs=60))

    assert copy.page_count > 2
    pages = pymupdf.open(stream=copy.pdf, filetype="pdf")
    # The PDF's text layer joins "fi" into one letter shape; the picture reads the same.
    texts = [" ".join(page.get_text().replace("ﬁ", "fi").replace("ﬂ", "fl").split()) for page in pages]
    for line in copy.lines:
        assert " ".join(str(line.cells[0]).split()[:4]) in texts[line.page - 1], line
    assert [line.page for line in copy.lines] == sorted(line.page for line in copy.lines)
    assert max(line.page for line in copy.lines) == copy.page_count


def test_a_tracked_change_reads_as_accepted():
    copy = word_copy("t.docx", samples.word(tracked=True))

    words = " ".join(str(cell) for line in copy.lines for cell in line.cells)
    assert "approved the new wording" in words and "rejected the old wording" not in words


def test_a_picture_in_a_word_file_is_drawn_in_the_reading_copy():
    copy = word_copy("p.docx", samples.word(picture=True))

    assert pymupdf.open(stream=copy.pdf, filetype="pdf")[0].get_images()


def test_a_picture_in_a_word_table_cell_is_drawn_in_the_reading_copy():
    document = samples.docx.Document()
    document.add_paragraph("Statement of financial position")
    table = document.add_table(rows=2, cols=1)
    table.rows[0].cells[0].text = "Pasted as a picture:"
    table.rows[1].cells[0].paragraphs[0].add_run().add_picture(io.BytesIO(samples._picture()))
    out = io.BytesIO()
    document.save(out)

    copy = word_copy("cell.docx", out.getvalue())

    assert pymupdf.open(stream=copy.pdf, filetype="pdf")[0].get_images()


def test_a_picture_in_a_word_list_item_is_drawn_in_the_reading_copy():
    document = samples.docx.Document()
    document.add_paragraph("Notes to the financial statements")
    document.add_paragraph("", style="List Bullet").add_run().add_picture(io.BytesIO(samples._picture()))
    out = io.BytesIO()
    document.save(out)

    copy = word_copy("list.docx", out.getvalue())

    assert pymupdf.open(stream=copy.pdf, filetype="pdf")[0].get_images()


def test_a_word_file_of_pictures_alone_is_read_from_its_pages():
    document = samples.docx.Document()
    document.add_paragraph().add_run().add_picture(io.BytesIO(samples._picture()))
    out = io.BytesIO()
    document.save(out)

    copy = word_copy("scanned.docx", out.getvalue())

    assert copy.page_count == 1 and copy.lines == []
    assert pymupdf.open(stream=copy.pdf, filetype="pdf")[0].get_images()


def test_a_word_picture_the_reading_copy_cannot_draw_is_said_on_its_page_and_on_upload():
    from app.documents.intake import prepare
    from app.documents.store import _word_notice

    upload = prepare("emf.docx", samples.pictures_as_emf(samples.word(picture=True)))

    page = pymupdf.open(stream=upload.pdf, filetype="pdf")[0]
    assert "A picture is not shown: it is saved as EMF" in " ".join(page.get_text().split())
    assert not page.get_images()
    assert not any("is not shown" in str(cell) for line in upload.lines for cell in line.cells)
    assert _word_notice(upload.pictures_not_drawn) == (
        "The Word file has 1 picture saved in a format the reading copy cannot draw, so it is not shown. Paste the "
        "pictures in again as PNG or JPEG and upload it again.")


def test_a_word_file_of_pictures_the_reading_copy_cannot_draw_is_refused():
    from app.documents.source_file import Refused

    document = samples.docx.Document()
    document.add_paragraph().add_run().add_picture(io.BytesIO(samples._picture()))
    out = io.BytesIO()
    document.save(out)

    with pytest.raises(Refused, match="emf.docx holds only pictures saved in a format the reading copy cannot draw"):
        word_copy("emf.docx", samples.pictures_as_emf(out.getvalue()))


def test_a_table_row_taller_than_a_page_is_drawn_in_full():
    document = samples.docx.Document()
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Basis of preparation"
    table.rows[0].cells[1].text = " ".join(f"word{i}" for i in range(5000)) + " closing-word"
    document.add_paragraph("The paragraph after the table.")
    out = io.BytesIO()
    document.save(out)
    copy = word_copy("tall.docx", out.getvalue())
    drawn = "".join(page.get_text() for page in pymupdf.open(stream=copy.pdf, filetype="pdf"))
    assert "closing-word" in drawn and "The paragraph after the table." in drawn
    row = next(line for line in copy.lines if line.kind == "row")
    assert row.cells[0] == "Basis of preparation" and row.page == 1


def test_a_row_of_several_long_cells_is_drawn_in_full():
    document = samples.docx.Document()
    table = document.add_table(rows=1, cols=6)
    for number, cell in enumerate(table.rows[0].cells):
        cell.text = " ".join(f"w{number}x{i}" for i in range(170)) + f" end-of-cell-{number}"
    out = io.BytesIO()
    document.save(out)

    copy = word_copy("six.docx", out.getvalue())

    drawn = "".join(page.get_text() for page in pymupdf.open(stream=copy.pdf, filetype="pdf"))
    assert all(f"end-of-cell-{number}" in drawn for number in range(6))


def test_a_long_cell_squeezed_by_the_other_rows_of_its_table_is_drawn_in_full():
    document = samples.docx.Document()
    table = document.add_table(rows=2, cols=6)
    table.rows[0].cells[0].text = " ".join(f"token{i}" for i in range(200)) + " ENDOFTARGET"
    for number, cell in enumerate(table.rows[1].cells):
        cell.text = f"Heading {number:02}"
    out = io.BytesIO()
    document.save(out)

    copy = word_copy("squeezed.docx", out.getvalue())

    drawn = " ".join("".join(page.get_text() for page in pymupdf.open(stream=copy.pdf, filetype="pdf")).split())
    assert "ENDOFTARGET" in drawn and "Heading 05" in drawn


def test_a_wide_table_is_laid_out_on_a_wide_page():
    copy = word_copy("w.docx", samples.word(columns=10))

    page = pymupdf.open(stream=copy.pdf, filetype="pdf")[0]
    assert page.rect.width > page.rect.height


@pytest.mark.parametrize("name, data, detail", [
    ("Old.doc", b"anything", "Old.doc is in the old Word format. Save it as .docx and upload that."),
    ("Old.xls", b"anything", "Old.xls is in the old Excel format. Save it as .xlsx and upload that."),
    ("Report.pdf", samples.OLD_WORD, "Report.pdf is in the old Word format. Save it as .docx and upload that."),
    ("Report.xlsx", samples.OLD_EXCEL, "Report.xlsx is in the old Excel format. Save it as .xlsx and upload that."),
    ("Locked.docx", samples.ENCRYPTED, "Locked.docx is protected by a password. Remove the password and upload it again."),
    ("Locked.xlsx", samples.ENCRYPTED, "Locked.xlsx is protected by a password. Remove the password and upload it again."),
    ("Macro.docm", samples.word(), "Macro.docm is not a .docx file. Save it as .docx and upload that."),
    ("Macro.xlsm", samples.excel(), "Macro.xlsm is not an .xlsx file. Save it as .xlsx and upload that."),
    ("Figures.csv", b"Revenue,100\n", "Figures.csv is not a PDF, a Word document (.docx) or an Excel workbook (.xlsx)."),
    ("Broken.docx", b"PK\x03\x04 not a real file", "Broken.docx is not a PDF, a Word document (.docx) or an Excel workbook (.xlsx)."),
])
def test_a_file_a_run_cannot_start_from_is_refused_in_one_sentence(signed_in, name, data, detail):
    response = upload(signed_in, data, name)

    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert signed_in.get("/api/runs").json()["runs"] == []


def test_a_word_file_that_will_not_open_is_refused(signed_in):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")

    response = upload(signed_in, out.getvalue(), "Empty shell.docx")

    assert response.status_code == 422
    assert response.json() == {"detail": "Empty shell.docx could not be read as a Word file."}


def test_a_file_over_the_limit_is_refused_by_name_and_size(signed_in, monkeypatch):
    monkeypatch.setattr(document_routes, "MAX_UPLOAD_BYTES", 2 * 1024 * 1024)
    response = upload(signed_in, b"%PDF-1.7" + b"0" * (3 * 1024 * 1024), "Big.pdf")

    assert response.status_code == 413
    assert response.json() == {"detail": "Big.pdf is 3 MB. The largest file a run can take is 2 MB."}


async def test_a_word_run_is_read_and_waits_at_setup(signed_in, monkeypatch):
    monkeypatch.setattr(factory, "build_model", lambda model_id: fakes.world(
        [("save_map", {"document_map": fakes.good_map(
            statements=fakes.statements(**{s: {"pages": [1]} for s in ("SOFP", "SOPL", "SOCF", "SOCIE")}),
            notes=[], other_sections=[], standard=fakes.finding("MFRS", (1,)), unit=fakes.finding("RM", (1,)),
            company=fakes.finding("Test Sdn. Bhd.", (1,)), year_end=fakes.finding("2021-12-31", (1,)),
            level=fakes.finding("Company", (1,)))}), "Done."]))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    run_id = upload(signed_in, samples.word(), "s.docx").json()["run"]["id"]

    assert await worker.run_once()

    assert signed_in.get(f"/api/runs/{run_id}").json()["run"]["status"] == "setup"
    assert signed_in.get(f"/api/runs/{run_id}/setup").json()["setup"]["statements"][0]["pages"] == [1]


def test_the_export_holds_the_files_lines_and_both_files_when_asked(signed_in):
    data = samples.word()
    run_id = upload(signed_in, data, "s.docx").json()["run"]["id"]

    plain = zipfile.ZipFile(io.BytesIO(signed_in.get(f"/api/runs/{run_id}/traces").content))
    assert "file_lines.json" in plain.namelist()
    assert not [n for n in plain.namelist() if n.endswith((".docx", ".pdf"))]
    full = zipfile.ZipFile(io.BytesIO(signed_in.get(f"/api/runs/{run_id}/traces?include_pdf=1").content))
    assert full.read("uploaded/s.docx") == data
    assert full.read("uploaded/reading copy of s.docx.pdf").startswith(b"%PDF-")


def test_a_workbook_whose_merged_cells_cover_too_much_is_refused_before_it_is_loaded():
    from app.documents.source_file import Refused
    from app.documents.workbook_copy import workbook_copy

    book = samples.openpyxl.Workbook()
    book.active["A1"] = "Statement"
    book.active.merge_cells("A1:Z40000")
    out = io.BytesIO()
    book.save(out)
    with pytest.raises(Refused, match="merged cells covering more than 200,000 cells"):
        workbook_copy("merged.xlsx", out.getvalue())
    # However the sheet's XML spells the range, it is read as Excel reads it.
    with zipfile.ZipFile(io.BytesIO(out.getvalue())) as source, io.BytesIO() as respelled:
        with zipfile.ZipFile(respelled, "w") as target:
            for info in source.infolist():
                data = source.read(info)
                if info.filename.startswith("xl/worksheets/"):
                    data = data.replace(b'ref="A1:Z40000"', b"ref = 'A1:Z40000'")
                target.writestr(info, data)
        with pytest.raises(Refused, match="merged cells"):
            workbook_copy("merged.xlsx", respelled.getvalue())


def _rezipped(data: bytes, change) -> bytes:
    """The zip with each part passed through `change(name, data)`, which returns the new (name, data) pairs."""
    source, out = zipfile.ZipFile(io.BytesIO(data)), io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            for name, part in change(info.filename, source.read(info)):
                target.writestr(name, part)
    return out.getvalue()


def _spare_sheet_workbook() -> bytes:
    """A workbook whose hidden second sheet keeps eleven empty cells Excel saved for their style."""
    book = samples.openpyxl.Workbook()
    book.active["A1"] = "Statement"
    hidden = book.create_sheet("Spare")
    hidden.sheet_state = "hidden"
    for row in range(1, 12):
        hidden.cell(row=row, column=1).number_format = "0.00"
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _moved(name: str, data: bytes):
    """The hidden sheet's part moved out of xl/worksheets/, and the workbook's link and content types with it."""
    if name == "xl/worksheets/sheet2.xml":
        return [("xl/elsewhere/sheet2.xml", data)]
    if name in ("xl/_rels/workbook.xml.rels", "[Content_Types].xml"):
        return [(name, data.replace(b"worksheets/sheet2.xml", b"elsewhere/sheet2.xml"))]
    return [(name, data)]


def _junk_first(name: str, data: bytes):
    """An unlinked part that is not XML, placed before the sheets."""
    return [("xl/worksheets/aaa.xml", b"<not xml"), (name, data)] if name == "[Content_Types].xml" else [(name, data)]


@pytest.mark.parametrize("change", [lambda name, data: [(name, data)], _moved, _junk_first],
                         ids=["as saved", "sheet stored elsewhere", "junk part first"])
def test_a_workbook_storing_too_many_cells_is_refused_before_it_is_loaded(monkeypatch, change):
    import openpyxl
    from app.documents import workbook_copy as wc
    from app.documents.source_file import Refused

    data = _rezipped(_spare_sheet_workbook(), change)
    monkeypatch.setattr(wc, "MAX_STORED", 10)
    loaded = []
    monkeypatch.setattr(openpyxl, "load_workbook", lambda *a, **k: loaded.append(1))

    with pytest.raises(Refused, match="keeps more than 10 rows and cells, counting the empty ones Excel saved"):
        wc.workbook_copy("stored.xlsx", data)
    assert loaded == []


def test_a_workbook_of_many_empty_rows_is_refused_before_it_is_loaded(monkeypatch):
    import openpyxl
    from app.documents import workbook_copy as wc
    from app.documents.source_file import Refused

    book = samples.openpyxl.Workbook()
    book.active["A1"] = "Statement"
    out = io.BytesIO()
    book.save(out)
    rows = b"".join(b'<row r="%d" ht="20" customHeight="1"/>' % n for n in range(2, 13))   # rows with no cells
    data = _rezipped(out.getvalue(), lambda name, part: [(name, part.replace(b"</sheetData>", rows + b"</sheetData>")
                                                          if name == "xl/worksheets/sheet1.xml" else part)])
    monkeypatch.setattr(wc, "MAX_STORED", 12)
    monkeypatch.setattr(openpyxl, "load_workbook", lambda *a, **k: None)

    with pytest.raises(Refused, match="keeps more than 12 rows and cells"):
        wc.workbook_copy("rows.xlsx", data)
