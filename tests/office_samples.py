"""Small Word and Excel files built in the test, with invented content, standing
in for real statements (which are never committed)."""
from __future__ import annotations

import io

import docx
import openpyxl
import pymupdf
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

COMPANY = "Contoh Maju Sdn. Bhd."
SOFP = [("Property, plant and equipment", 1284300, 1196450), ("Inventories", 342150, 318900),
        ("Trade and other receivables", 687420, 602310), ("Total assets", 2313870, 2117660)]
ENCRYPTED = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64 + "EncryptedPackage".encode("utf-16-le") + b"\0" * 64
OLD_WORD = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + "WordDocument".encode("utf-16-le") + b"\0" * 64
OLD_EXCEL = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + "Workbook".encode("utf-16-le") + b"\0" * 64


def _saved(document) -> bytes:
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def _picture() -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 30))
    pix.clear_with(120)
    return pix.tobytes("png")


def _tracked(paragraph, tag: str, text: str) -> None:
    """A run inside a tracked insertion (`ins`) or deletion (`del`)."""
    change = OxmlElement(f"w:{tag}")
    change.set(qn("w:id"), "1")
    change.set(qn("w:author"), "Reviewer")
    run = OxmlElement("w:r")
    words = OxmlElement("w:delText" if tag == "del" else "w:t")
    words.text = text
    run.append(words)
    change.append(run)
    paragraph._p.append(change)


def word(*, note_paragraphs: int = 3, picture: bool = False, tracked: bool = False, columns: int = 3) -> bytes:
    """A .docx with a title, a statement of financial position as a table, and a notes section."""
    document = docx.Document()
    document.add_heading(COMPANY, level=1)
    document.add_paragraph("Statement of financial position as at 31 December 2025")
    if picture:
        document.add_picture(io.BytesIO(_picture()))
    table = document.add_table(rows=1, cols=columns)
    for cell, text in zip(table.rows[0].cells, ["", "2025 RM", "2024 RM"] + [f"Extra {i}" for i in range(columns - 3)]):
        cell.text = text
    for label, this_year, last_year in SOFP:
        cells = table.add_row().cells
        cells[0].text, cells[1].text, cells[2].text = label, f"{this_year:,}", f"{last_year:,}"
    document.add_heading("Notes to the financial statements", level=2)
    for number in range(1, note_paragraphs + 1):
        document.add_paragraph(f"Note paragraph {number}. The Company is a private limited liability company "
                               "incorporated and domiciled in Malaysia. " * 3)
    if tracked:
        paragraph = document.add_paragraph("The directors ")
        _tracked(paragraph, "del", "rejected the old wording")
        _tracked(paragraph, "ins", "approved the new wording")
    return _saved(document)


def excel(*, hidden: bool = True, formula: bool = False, wide: int = 0) -> bytes:
    """An .xlsx with a cover, a statement of financial position, notes and, by default, a hidden sheet.
    `formula` adds a total as a formula, which openpyxl saves without a result."""
    book = openpyxl.Workbook()
    cover = book.active
    cover.title = "Cover"
    cover["A1"], cover["A2"] = COMPANY, "Financial statements for the year ended 31 December 2025"
    sheet = book.create_sheet("SOFP")
    sheet["A1"] = "Statement of financial position as at 31 December 2025"
    sheet["B3"], sheet["C3"] = 2025, 2024
    for offset, (label, this_year, last_year) in enumerate(SOFP):
        row = 5 + offset
        sheet.cell(row, 1, label)
        for column, value in ((2, this_year), (3, last_year)):
            sheet.cell(row, column, value).number_format = "#,##0_);(#,##0)"
    sheet["A10"], sheet["B10"] = "Accumulated losses", -5000.4
    sheet["B10"].number_format = "#,##0_);(#,##0)"
    if formula:
        sheet["A11"], sheet["B11"] = "Total", "=SUM(B5:B7)"
    for column in range(wide):
        sheet.cell(3, 4 + column, f"Extra {column}")
    notes = book.create_sheet("Notes")
    notes["A1"], notes["A2"] = "1. Corporate information", "The Company is incorporated in Malaysia."
    if hidden:
        old = book.create_sheet("Old SOFP")
        old["A1"], old["B1"] = "Superseded total", 999
        old.sheet_state = "hidden"
    return _saved(book)
