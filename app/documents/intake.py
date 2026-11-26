"""Turn an uploaded file into what a run starts from.

A PDF is checked and kept as it is. A Word or Excel file is opened by the
server, which lays out a reading copy (`reading_copy.py`) and keeps the
file's own words and numbers beside it. Either way the result has PDF pages,
so everything after the upload works the same.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from app.documents import pdf_check
from app.documents.reading_copy import Line
from app.documents.source_file import EXCEL, PDF, WORD, Refused, kind_of, locked


@dataclass
class Prepared:
    kind: str                                  # pdf, word or excel
    filename: str
    data: bytes                                # the file as uploaded
    pdf: bytes                                 # the PDF the run reads: the upload itself, or its reading copy
    pages: list[pdf_check.PageFacts]
    lines: list[Line] = field(default_factory=list)
    sheets: Optional[list[dict]] = None        # Excel only


def prepare(filename: str, data: bytes, brought_in: Sequence[str] = ()) -> Prepared:
    """The upload ready to become a run, or `Refused` with one plain sentence."""
    kind = kind_of(filename, data)
    if kind == PDF:
        try:
            return Prepared(PDF, filename, data, data, pdf_check.inspect_pdf(data))
        except pdf_check.PdfLocked as exc:
            raise locked(filename) from exc
        except pdf_check.NotAPdf as exc:
            raise Refused(str(exc)) from exc
    sheets = None
    if kind == WORD:
        from app.documents.word_copy import word_copy

        copy = word_copy(filename, data)
    else:
        from app.documents.workbook_copy import workbook_copy

        copy, sheets = workbook_copy(filename, data, brought_in)
    if copy.page_count > pdf_check.MAX_PAGES:
        raise Refused(f"{filename} makes more than {pdf_check.MAX_PAGES} pages, so upload the financial "
                      "statements on their own.")
    return Prepared(kind, filename, data, copy.pdf, pdf_check.inspect_pdf(copy.pdf), copy.lines, sheets)
