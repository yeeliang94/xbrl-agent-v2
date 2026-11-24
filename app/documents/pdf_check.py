"""Check that an uploaded file is a readable PDF, and look at each page once.

Uploads are PDF only on every machine (`backend-plan.md` section 9). Each
refusal is one plain sentence the person can act on.
"""
from __future__ import annotations

from dataclasses import dataclass

import pymupdf

from app.documents.pdf_viewer import dominant_raster_dpi

WORD_SUFFIXES = (".doc", ".docx", ".docm", ".dot", ".dotx", ".dotm")
WORD_REFUSAL = "Save the Word file as a PDF in Word, then upload the PDF."

# Financial statements run to tens of pages; a long group report to a few
# hundred. More than this is not one set of statements, and reading it would
# cost a model call per page.
MAX_PAGES = 500
# A0 paper in points (841 x 1189 mm). A bigger page is no printed statement
# and could not be drawn at a sane size.
A0_POINTS = (2384.0, 3370.0)
# A page whose words cover less than this share of it, under a picture that
# covers most of it, is a scan (see `_has_text_layer`).
SCAN_TEXT_COVER = 0.10

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"            # old .doc (and .xls)
_OLE_WORD_STREAM = "WordDocument".encode("utf-16-le")


class NotAPdf(ValueError):
    """An upload that is not a PDF the app can read. `str()` is one plain sentence."""


@dataclass(frozen=True)
class PageFacts:
    page: int              # PDF page number, from 1
    width: float           # points, after the page's rotation
    height: float
    rotation: int          # as stored in the PDF
    has_text_layer: bool


def is_word(filename: str, data: bytes = b"") -> bool:
    """A Word file, by its name or by its content (a .docx is a zip holding a
    `word/` folder; an old .doc is an OLE file with a WordDocument stream)."""
    if filename.lower().endswith(WORD_SUFFIXES):
        return True
    if data.startswith(b"PK\x03\x04"):
        return b"word/" in data[:65536]
    return data.startswith(_OLE_MAGIC) and _OLE_WORD_STREAM in data[:65536]


def inspect_pdf(data: bytes) -> list[PageFacts]:
    """One PageFacts per page, or NotAPdf saying why the file was refused."""
    if b"%PDF-" not in data[:1024]:
        raise NotAPdf("This file is not a PDF, so choose the PDF of the financial statements.")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several types for a broken file
        raise NotAPdf("This file could not be read as a PDF.") from exc
    try:
        if doc.needs_pass:
            raise NotAPdf("This PDF is protected by a password, so upload a copy saved without one.")
        if len(doc) == 0:
            raise NotAPdf("This file could not be read as a PDF.")
        if len(doc) > MAX_PAGES:
            raise NotAPdf(f"This PDF has more than {MAX_PAGES} pages, so upload the financial statements on "
                          "their own.")
        try:
            sizes = [sorted((abs(page.rect.width), abs(page.rect.height))) for page in doc]
        except Exception as exc:
            raise NotAPdf("This file could not be read as a PDF.") from exc
        for number, (short, long) in enumerate(sizes, start=1):
            if short > A0_POINTS[0] * 1.01 or long > A0_POINTS[1] * 1.01:
                raise NotAPdf(f"Page {number} is larger than A0 paper, so upload a PDF with ordinary page sizes.")
        try:
            return [PageFacts(page=i + 1, width=round(page.rect.width, 2), height=round(page.rect.height, 2),
                              rotation=int(page.rotation), has_text_layer=_has_text_layer(page))
                    for i, page in enumerate(doc)]
        except Exception as exc:
            raise NotAPdf("This file could not be read as a PDF.") from exc
    finally:
        doc.close()


def _has_text_layer(page: "pymupdf.Page") -> bool:
    # Decided per page, never per document: one report mixes typed and
    # scanned pages. A page has a real text layer when it holds words, unless
    # one picture covers most of the page and the words cover under 10% of
    # it. That second case is a scan with a stamp or certification line laid
    # over it (one test document has 159 characters of stamp text, 2.5% of
    # the page, on every scanned page). A typed page's words cover far more,
    # and so does a scan with a full searchable (OCR) layer, which counts as
    # text.
    blocks = [b for b in page.get_text("blocks") if b[6] == 0 and str(b[4]).strip()]
    if not blocks:
        return False
    if dominant_raster_dpi(page) is None:
        return True
    page_area = abs(page.rect.width * page.rect.height) or 1.0
    covered = sum(abs((b[2] - b[0]) * (b[3] - b[1])) for b in blocks)
    return covered / page_area >= SCAN_TEXT_COVER
