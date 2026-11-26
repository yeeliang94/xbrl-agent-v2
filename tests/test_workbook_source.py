"""A run that starts from an Excel workbook, and the file tools every agent gets
for a Word or Excel run (go-live plan C6, part b)."""
from __future__ import annotations

import io
from types import SimpleNamespace

import pymupdf
import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from app import db
from app.agents import file_tools, loop, pages as page_tools
from app.documents import file_lines, sheets
from app.documents.workbook_copy import shown, workbook_copy
from app.runs.events import list_events
from app.utils.paths import output_dir
from tests import office_samples as samples, pdf_samples
from tests.conftest import OWNER, login, make_user


@pytest.fixture
def signed_in(client):
    make_user(OWNER)
    assert login(client, OWNER).status_code == 200
    return client


def upload(client, data: bytes, name: str) -> dict:
    response = client.post("/api/runs", files={"file": (name, io.BytesIO(data), "application/octet-stream")})
    assert response.status_code == 200, response.text
    return response.json()


def ctx(run_id: int, page_count: int = 3):
    return SimpleNamespace(deps=SimpleNamespace(run_id=run_id, page_count=page_count))


# The workbook -----------------------------------------------------------------

def test_a_workbook_starts_a_run_with_a_page_per_sheet_and_hidden_sheets_left_out(signed_in):
    data = samples.excel()

    body = upload(signed_in, data, "Accounts 2025.xlsx")

    document = body["document"]
    assert document["kind"] == "excel" and document["page_count"] == 3
    assert [(s["name"], s["hidden"], s["used"], s["first_page"]) for s in document["sheets"]] == [
        ("Cover", False, True, 1), ("SOFP", False, True, 2), ("Notes", False, True, 3), ("Old SOFP", True, False, None)]
    run_id = body["run"]["id"]
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE run_id = ?", (run_id,)).fetchone()
        lines = file_lines.of_run(conn, run_id)
    assert (output_dir() / row["source_path"]).read_bytes() == data
    text = pymupdf.open(output_dir() / row["stored_path"])[1].get_text()
    assert "SOFP" in text and "1,284,300" in text and "(5,000)" in text
    assert not any(line.sheet == "Old SOFP" for line in lines)
    ppe = next(line for line in lines if line.sheet == "SOFP" and line.row == 5)
    assert ppe.cells == [["A", "Property, plant and equipment", None], ["B", "1,284,300", 1284300],
                         ["C", "1,196,450", 1196450]]
    assert ppe.page == 2
    events = [e["message"] for e in signed_in.get(f"/api/runs/{run_id}/events").json()["events"]]
    assert events == ["The Excel workbook is stored and its reading copy is made: 3 pages from 3 sheets; "
                      "1 hidden sheet left out."]


def test_a_formula_saved_without_a_result_reads_as_empty_and_the_person_is_told(signed_in):
    body = upload(signed_in, samples.excel(formula=True), "f.xlsx")

    sofp = next(s for s in body["document"]["sheets"] if s["name"] == "SOFP")
    sentence = ("The sheet SOFP has 1 formula saved without a result, so it reads as empty. Open the workbook "
                "in Excel, save it and upload it again.")
    assert sofp["empty_formulas"] == 1 and sofp["notice"] == sentence
    events = [e["message"] for e in signed_in.get(f"/api/runs/{body['run']['id']}/events").json()["events"]]
    assert sentence in events
    read = file_tools.read_file(ctx(body["run"]["id"]), [2])
    assert "row 11: A11 Total | B11 [no saved result]" in read


def test_a_cell_is_shown_as_its_number_format_shows_it():
    assert shown(1284300, "#,##0_);(#,##0)") == "1,284,300"
    assert shown(-5000.4, "#,##0_);(#,##0)") == "(5,000)"
    assert shown(-12.5, "0.00") == "-12.50"
    assert shown(0.125, "0.0%") == "12.5%"
    assert shown(2025, "General") == "2025" and shown(1234567890123.0) == "1234567890123"
    assert shown(None) == "" and shown("  Trade   payables ") == "Trade payables"
    # A comma after the last digit divides by a thousand, as a sheet kept in RM'000 shows it.
    assert shown(1234567, "#,##0,") == "1,235" and shown(1234567, "0.0,,") == "1.2"
    # A half rounds away from zero, as Excel shows it, not to even.
    assert shown(1284500, "#,##0,") == "1,285" and shown(-1284500, "#,##0,_);(#,##0,)") == "(1,285)"
    assert shown(2.675, "0.00") == "2.68" and shown(0.5, "0") == "1"
    # A negative takes the format's second section, with that section's decimals and brackets.
    assert shown(-1.25, "#,##0;(#,##0.00)") == "(1.25)" and shown(-3, "0;-0") == "-3"
    # Brackets or a minus the section writes escaped or quoted still mark it negative; padding does not.
    assert shown(-1234, "#,##0;\\(#,##0\\)") == "(1,234)" and shown(-1234, '#,##0;"("#,##0")"') == "(1,234)"
    assert shown(-1234, "#,##0;\\-#,##0") == "-1,234" and shown(-1234, "#,##0_);#,##0_)") == "1,234"
    # A section with a condition is used only when it holds; colours and currency codes hold no digits.
    assert shown(500, "[>=1000]#,##0,;0") == "500" and shown(1500, "[>=1000]#,##0,;0") == "2"
    assert shown(-1234, "[<0](#,##0);#,##0") == "(1,234)" and shown(-1234, "[Red]#,##0;[Red](#,##0)") == "(1,234)"
    assert shown(1234, "[$RM-409]#,##0") == "1,234"
    # A fraction or scientific format is not drawn: the number is given in full, not rounded.
    assert shown(1.25, "# ?/?") == "1.25" and shown(1234567, "0.00E+00") == "1234567"
    # An amount too long for ordinary decimal arithmetic is still shown in full.
    assert shown(1e30, "#,##0") == "1,000,000,000,000,000,000,000,000,000,000"
    assert shown(1234, '"RM"#,##0') == "1,234"


def test_a_scaled_cell_gives_the_value_the_file_holds_too(signed_in):
    import openpyxl

    book = openpyxl.Workbook()
    book.active.title = "SOFP"
    book.active["A1"], book.active["B1"] = "Inventories", 342150
    book.active["B1"].number_format = "#,##0,"
    book.active["A2"], book.active["B2"] = "Payables", 1234567
    book.active["B2"].number_format = "#,##0,"
    out = io.BytesIO()
    book.save(out)
    run_id = upload(signed_in, out.getvalue(), "k.xlsx")["run"]["id"]

    assert "row 1: A1 Inventories | B1 342 (saved value 342150)" in file_tools.read_file(ctx(run_id, 1), [1])
    # The amount is found by what the sheet shows and by what the file saves.
    assert "B2 1,235" in file_tools.search_file(ctx(run_id, 1), "1235")
    assert "B2 1,235" in file_tools.search_file(ctx(run_id, 1), "1,234,567")


def test_two_cells_far_apart_read_quickly_as_two_cells():
    import time

    import openpyxl

    book = openpyxl.Workbook()
    book.active["A1"], book.active["XFD1048576"] = "Start", 1
    out = io.BytesIO()
    book.save(out)

    started = time.monotonic()
    copy, sheets_found = workbook_copy("far.xlsx", out.getvalue())
    assert time.monotonic() - started < 10
    assert [line.cells for line in copy.lines] == [[["A", "Start", None]], [["XFD", "1", 1]]]


def test_a_file_that_unpacks_too_large_is_refused_before_it_is_read(signed_in, monkeypatch):
    from app.documents import workbook_copy as wc

    monkeypatch.setattr(wc, "MAX_UNZIPPED", 1000)
    for name, data in (("big.xlsx", samples.excel()), ("big.docx", samples.word())):
        response = signed_in.post("/api/runs", files={"file": (name, io.BytesIO(data), "application/octet-stream")})
        assert response.status_code == 422
        assert response.json() == {"detail": f"{name} unpacks to more than 0 MB, so upload the financial statements on their own."}


def test_a_workbook_with_nothing_to_read_is_refused(signed_in):
    import openpyxl

    out = io.BytesIO()
    openpyxl.Workbook().save(out)
    response = signed_in.post("/api/runs", files={"file": ("Empty.xlsx", out, "application/octet-stream")})

    assert response.status_code == 422
    assert response.json() == {"detail": "Empty.xlsx has no sheet with anything on it to read."}


def test_a_wide_sheet_is_laid_out_on_a_wide_page():
    copy, _ = workbook_copy("w.xlsx", samples.excel(wide=12))

    sofp = pymupdf.open(stream=copy.pdf, filetype="pdf")[1]
    assert sofp.rect.width > sofp.rect.height


def test_a_sheet_reads_back_as_its_cells(signed_in):
    run_id = upload(signed_in, samples.excel(), "a.xlsx")["run"]["id"]

    sheet = signed_in.get(f"/api/runs/{run_id}/sheets/SOFP").json()["sheet"]

    assert (sheet["name"], sheet["position"], sheet["count"], sheet["columns"]) == ("SOFP", 2, 3, ["A", "B", "C"])
    assert {"row": 5, "cells": {"A": "Property, plant and equipment", "B": "1,284,300", "C": "1,196,450"}} in sheet["rows"]
    assert signed_in.get(f"/api/runs/{run_id}/sheets/Old SOFP").status_code == 404
    assert signed_in.get(f"/api/runs/{run_id}/sheets/SOFP").status_code == 200


def test_a_hidden_sheet_is_brought_in_after_the_pages_already_read(signed_in):
    run_id = upload(signed_in, samples.excel(), "a.xlsx")["run"]["id"]
    refused = signed_in.post(f"/api/runs/{run_id}/sheets/bring-in", json={"sheet": "Old SOFP"})
    assert refused.status_code == 409
    assert refused.json() == {"detail": "A sheet can be brought in only while the run waits at setup."}
    with db.connect(immediate=True) as conn:      # reading finished: every page read, the run at setup
        conn.execute("UPDATE pages SET content_json = '{\"blank\": true}'")
        conn.execute("UPDATE runs SET status = 'setup' WHERE id = ?", (run_id,))
        conn.execute("UPDATE stages SET status = 'done' WHERE run_id = ? AND name = 'read'", (run_id,))

    response = signed_in.post(f"/api/runs/{run_id}/sheets/bring-in", json={"sheet": "Old SOFP"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run"]["status"] == "reading" and body["document"]["page_count"] == 4
    old = next(s for s in body["document"]["sheets"] if s["name"] == "Old SOFP")
    assert (old["used"], old["first_page"], old["last_page"]) == (True, 4, 4)
    assert [s["first_page"] for s in body["document"]["sheets"][:3]] == [1, 2, 3]
    with db.connect() as conn:
        waiting = [r["page"] for r in conn.execute("SELECT page FROM pages WHERE content_json IS NULL")]
        lines = file_lines.of_run(conn, run_id, pages=[4])
        jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE run_id = ? AND kind = 'read' AND status = 'queued'",
                            (run_id,)).fetchone()[0]
    assert waiting == [4] and jobs >= 1
    assert [line.cells for line in lines] == [[["A", "Superseded total", None], ["B", "999", 999]]]
    again = signed_in.post(f"/api/runs/{run_id}/sheets/bring-in", json={"sheet": "Old SOFP"})
    assert again.status_code == 409


def test_a_figures_sheet_and_cell_are_found_from_its_page_label_and_amount(signed_in):
    run_id = upload(signed_in, samples.excel(), "a.xlsx")["run"]["id"]
    cell = lambda amount: {"figure_id": 1, "printed": amount, "value": amount}
    view = {"rows": [
        {"page": 2, "printed_label": "Trade and other receivables", "label": "x",
         "cells": {"Company:CY": cell(687420), "Company:PY": cell(602310)}},
        {"page": 2, "printed_label": "Accumulated losses", "label": "x", "cells": {"Company:CY": cell(5000.4)}},
        {"page": 2, "printed_label": "A line the sheet does not have", "label": "x", "cells": {"Company:CY": cell(1)}},
        {"page": None, "printed_label": None, "label": "Heading", "cells": {}},
        # As the sheet shows it: the cell saves -5000.4 and shows (5,000).
        {"page": 2, "printed_label": "Accumulated losses", "label": "x", "cells": {"Company:CY": cell(-5000)}},
    ]}

    with db.connect() as conn:
        rows = sheets.annotate(conn, run_id, view)["rows"]

    assert rows[0]["source"] == {"sheet": "SOFP", "row": 7}
    assert [c["source_cell"] for c in rows[0]["cells"].values()] == ["B7", "C7"]
    assert rows[1]["source"] == {"sheet": "SOFP", "row": 10} and rows[1]["cells"]["Company:CY"]["source_cell"] == "B10"
    assert rows[2]["source"] == {"sheet": "SOFP", "row": None} and "source_cell" not in rows[2]["cells"]["Company:CY"]
    assert "source" not in rows[3]
    assert rows[4]["cells"]["Company:CY"]["source_cell"] == "B10"
    assert view["source_kind"] == "excel"


def test_a_cell_is_not_named_when_both_years_show_the_amount_and_one_is_saved(signed_in):
    import openpyxl

    book = openpyxl.Workbook()
    book.active.title = "SOFP"
    book.active.append(["Share capital", 100000, 100000])
    out = io.BytesIO()
    book.save(out)
    run_id = upload(signed_in, out.getvalue(), "same.xlsx")["run"]["id"]
    cell = {"figure_id": 1, "printed": 100000, "value": 100000}
    view = {"rows": [{"page": 1, "printed_label": "Share capital", "label": "x", "cells": {"Company:PY": dict(cell)}},
                     {"page": 1, "printed_label": "Share capital", "label": "x",
                      "cells": {"Company:CY": dict(cell), "Company:PY": dict(cell)}}]}

    with db.connect() as conn:
        rows = sheets.annotate(conn, run_id, view)["rows"]

    assert rows[0]["source"] == {"sheet": "SOFP", "row": 1} and "source_cell" not in rows[0]["cells"]["Company:PY"]
    assert [c["source_cell"] for c in rows[1]["cells"].values()] == ["B1", "C1"]


def test_a_cell_taller_than_a_page_is_drawn_in_full():
    import openpyxl
    import pymupdf
    from app.documents.workbook_copy import workbook_copy

    book = openpyxl.Workbook()
    book.active.title = "Notes"
    book.active["A1"] = "Basis of preparation"
    book.active["B1"] = " ".join(f"word{i}" for i in range(3000)) + " closing-word"   # under Excel's 32,767
    book.active["A2"], book.active["B2"] = "Revenue", 1200
    out = io.BytesIO()
    book.save(out)

    copy, _ = workbook_copy("long.xlsx", out.getvalue())

    drawn = "".join(page.get_text() for page in pymupdf.open(stream=copy.pdf, filetype="pdf"))
    assert "closing-word" in drawn and "Revenue" in drawn
    assert [line.row for line in copy.lines] == [1, 2]


def test_pictures_on_a_sheet_are_drawn_and_a_sheet_of_only_a_picture_is_kept():
    import openpyxl
    import pymupdf
    from app.documents.workbook_copy import workbook_copy

    book = openpyxl.Workbook()
    book.active.title = "SOFP"
    book.active["A1"] = "Statement of financial position"
    book.create_sheet("Scanned note")
    out = io.BytesIO()
    book.save(out)
    data = samples.with_pictures(out.getvalue(), {"sheet1.xml": "1,11", "sheet2.xml": "0,0"})

    copy, sheet_list = workbook_copy("pictures.xlsx", data)

    assert [(s["name"], s["used"]) for s in sheet_list] == [("SOFP", True), ("Scanned note", True)]
    pages = pymupdf.open(stream=copy.pdf, filetype="pdf")
    assert pages[0].get_images() and "Picture at B12" in pages[0].get_text()
    assert pages[1].get_images() and "Picture at A1" in pages[1].get_text()


def test_a_sparse_workbook_that_would_draw_too_large_a_grid_is_refused(monkeypatch):
    import openpyxl
    from app.documents import workbook_copy as wc
    from app.documents.source_file import Refused

    book = openpyxl.Workbook()
    for i in range(1, 101):              # 100 cells on a diagonal draw a 100 by 100 grid
        book.active.cell(row=i, column=i, value=i)
    out = io.BytesIO()
    book.save(out)
    monkeypatch.setattr(wc, "MAX_GRID", 5_000)
    with pytest.raises(Refused, match="spreads its cells over more than 5,000 places"):
        wc.workbook_copy("sparse.xlsx", out.getvalue())


def test_every_statement_view_says_what_the_run_started_from(signed_in):
    word_run = upload(signed_in, samples.word(), "s.docx")["run"]["id"]
    row = {"page": 1, "printed_label": "Inventories", "label": "x", "cells": {}}

    with db.connect() as conn:
        view = sheets.annotate(conn, word_run, {"rows": [dict(row)]})
        no_document = sheets.annotate(conn, 999, {"rows": []})
    assert view["source_kind"] == "word" and "source" not in view["rows"][0]
    assert no_document["source_kind"] == "pdf"


# The file tools ------------------------------------------------------------------

def test_read_file_gives_a_word_files_own_lines_by_page(signed_in):
    run_id = upload(signed_in, samples.word(), "s.docx")["run"]["id"]

    text = file_tools.read_file(ctx(run_id, 1), [1])

    assert text.startswith("=== Page 1, from the Word file:\n# " + samples.COMPANY)
    assert "Table 1:\n  row 1:  | 2025 RM | 2024 RM\n  row 2: Property, plant and equipment | 1,284,300 | 1,196,450" in text
    assert file_tools.read_file(ctx(run_id, 1), [2]) == "Page 2 is outside the document, which has 1 pages."


def test_read_file_names_every_workbook_value_by_sheet_and_cell(signed_in):
    run_id = upload(signed_in, samples.excel(), "a.xlsx")["run"]["id"]

    text = file_tools.read_file(ctx(run_id), [2])

    assert text.startswith("=== Page 2, sheet SOFP:\nrow 1: A1 Statement of financial position")
    assert "row 5: A5 Property, plant and equipment | B5 1,284,300 | C5 1,196,450" in text
    # The sheet shows a rounded figure: the value the file holds is given too.
    assert "row 10: A10 Accumulated losses | B10 (5,000) (saved value -5000.4)" in text


def test_search_file_finds_words_and_amounts_however_they_are_written(signed_in):
    word_run = upload(signed_in, samples.word(), "s.docx")["run"]["id"]
    excel_run = upload(signed_in, samples.excel(), "a.xlsx")["run"]["id"]

    assert file_tools.search_file(ctx(word_run), "INVENTORIES") == (
        "1 line(s) of the file hold 'INVENTORIES':\n- page 1, table 1 row 3: Inventories | 342,150 | 318,900")
    by_amount = file_tools.search_file(ctx(excel_run), "(687420)")
    assert "- page 2, sheet SOFP row 7: A7 Trade and other receivables | B7 687,420 | C7 602,310" in by_amount
    assert file_tools.search_file(ctx(excel_run), "goodwill") == (
        "The file does not hold 'goodwill'. Try another wording, or a shorter part of it.")
    assert "Superseded" not in file_tools.search_file(ctx(excel_run), "total")     # the hidden sheet is left out
    assert file_tools.search_file(ctx(excel_run), "x") == "Search for at least two characters."


def _spec() -> loop.AgentSpec:
    return loop.AgentSpec(name="reader", model_id="gpt-test", instructions="Map the document.",
                          tools=list(page_tools.PAGE_TOOLS))


def test_only_a_word_or_excel_run_gets_the_file_tools_and_their_principle(signed_in):
    pdf_run = signed_in.post("/api/runs", files={"file": ("d.pdf", io.BytesIO(pdf_samples.build("text")),
                                                          "application/pdf")}).json()["run"]["id"]
    word_run = upload(signed_in, samples.word(), "s.docx")["run"]["id"]
    excel_run = upload(signed_in, samples.excel(), "a.xlsx")["run"]["id"]

    assert file_tools.for_run(_spec(), pdf_run) == _spec() and file_tools.for_run(_spec(), None) == _spec()
    for_word, for_excel = file_tools.for_run(_spec(), word_run), file_tools.for_run(_spec(), excel_run)
    assert [t.__name__ for t in for_word.tools][-2:] == ["read_file", "search_file"]
    # They carry the note on the steps and time left, as the page tools do.
    assert [t.__wrapped__ for t in for_word.tools[-2:]] == [file_tools.read_file, file_tools.search_file]
    assert "started from a Word document" in for_word.instructions and "sheet" not in for_word.instructions
    assert "started from an Excel workbook" in for_excel.instructions and "never a zero" in for_excel.instructions
    no_pages = loop.AgentSpec(name="other", model_id="gpt-test", instructions="x", tools=[])
    assert file_tools.for_run(no_pages, word_run) == no_pages      # an agent with no page tools is left alone


async def test_an_agent_reads_the_file_and_the_step_shows_in_the_activity(signed_in):
    run_id = upload(signed_in, samples.word(), "s.docx")["run"]["id"]
    seen: list[str] = []

    def answer(messages, info):
        seen.append(info.instructions or "")
        if sum(isinstance(m, ModelResponse) for m in messages) == 0:
            return ModelResponse(parts=[ToolCallPart("read_file", {"pages": [1], "note": "Reading the balance sheet from the file."})])
        return ModelResponse(parts=[TextPart("Done.")])

    deps = page_tools.PageSource(run_id=run_id, pdf_path="", page_count=1, contents={})
    outcome = await loop.run_agent(_spec(), "Go.", deps=deps, run_id=run_id, model=FunctionModel(answer))

    assert outcome.status == loop.COMPLETED and outcome.tool_calls == ["read_file"]
    assert "started from a Word document" in seen[0]
    looked = [e for e in list_events(run_id=run_id) if e["kind"] == "looked"]
    assert [(e["message"], e["pages"]) for e in looked] == [("Reading the balance sheet from the file.", [1])]
