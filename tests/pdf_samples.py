"""Small PDFs built in the test, standing in for the real documents (which are
never committed). A4 pages; a "scan" is one full-page picture at 150 DPI."""
from __future__ import annotations

import pymupdf

A4 = (595, 842)
SCAN_PX = (1240, 1754)        # A4 at 150 DPI
STAMP = ("I wish to confirm that this copy was printed from the Company's records and is a true copy "
         "of the original audited financial statements. Signed: Company Secretary")
_PARAGRAPH = ("The directors are responsible for the preparation of financial statements that give a "
              "true and fair view of the financial position of the Company. ") * 3


def _scan_picture() -> pymupdf.Pixmap:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, *SCAN_PX))
    pix.clear_with(235)
    return pix


def add_text_page(doc: pymupdf.Document, *, rotation: int = 0) -> None:
    page = doc.new_page(width=A4[0], height=A4[1])
    for i in range(14):
        page.insert_textbox(pymupdf.Rect(60, 60 + i * 52, 535, 110 + i * 52), _PARAGRAPH, fontsize=8)
    if rotation:
        page.set_rotation(rotation)


def add_scan_page(doc: pymupdf.Document, *, stamp: bool = False, ocr: bool = False) -> None:
    page = doc.new_page(width=A4[0], height=A4[1])
    page.insert_image(page.rect, pixmap=_scan_picture())
    if stamp:   # real text laid over the scan, as a certification stamp is
        page.insert_textbox(pymupdf.Rect(60, 780, 535, 830), STAMP, fontsize=7)
    if ocr:     # a full searchable layer, drawn invisibly over the picture
        for i in range(14):
            page.insert_textbox(pymupdf.Rect(60, 60 + i * 52, 535, 110 + i * 52), _PARAGRAPH,
                                fontsize=8, render_mode=3)


def build(*pages: str, password: str | None = None) -> bytes:
    """A PDF with one page per word: "text", "scan", "stamped", "ocr", "rotated"."""
    doc = pymupdf.open()
    for kind in pages:
        if kind == "text":
            add_text_page(doc)
        elif kind == "rotated":
            add_text_page(doc, rotation=90)
        elif kind == "scan":
            add_scan_page(doc)
        elif kind == "stamped":
            add_scan_page(doc, stamp=True)
        elif kind == "ocr":
            add_scan_page(doc, ocr=True)
        else:
            raise ValueError(kind)
    options = {}
    if password:
        options = {"encryption": pymupdf.PDF_ENCRYPT_AES_256, "user_pw": password, "owner_pw": password}
    data = doc.tobytes(deflate=True, **options)
    doc.close()
    return data
