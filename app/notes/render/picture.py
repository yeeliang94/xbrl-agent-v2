"""Draw a field's text as mTool gets it, so an agent can see its formatting.

Copied from v1's `notes/render.py` (191 lines). PyMuPDF's HTML engine lays
the text out on mTool's note page: A4 portrait, 20 mm margins on every side,
so text is 170 mm wide and a page holds 257 mm. Text is set in Liberation
Sans, whose letter widths equal Arial's, so lines wrap where Arial would.
The picture approximates a browser: it shows alignment, lines, bold,
indents, column widths and wrapping, not mTool's exact pixels.
"""
from __future__ import annotations

import io
import re
import threading
from pathlib import Path

import fitz
from bs4 import BeautifulSoup, Tag

from app.notes.render.decorate import FONT_SIZE_ATTR, NotesTableStyle, decorate_notes_html

# The fonts ship with the app (read-only package files, not run files).
_FONTS = Path(__file__).resolve().parent.parent / "fonts"
# Unstyled text (a flat-tier field) also draws in the Arial-width font.
_FONT_CSS = "body { font-family: Arial; font-size: 10pt; } " + "".join(
    f"@font-face {{ font-family: Arial; {face} src: url(LiberationSans-{name}.ttf); }}"
    for face, name in (
        ("", "Regular"),
        ("font-weight: bold;", "Bold"),
        ("font-style: italic;", "Italic"),
        ("font-weight: bold; font-style: italic;", "BoldItalic"),
    )
)

PAGE_WIDTH_PT = 595.3     # 210 mm
PAGE_HEIGHT_PT = 841.9    # 297 mm
MARGIN_PT = 56.7          # 20 mm
RENDER_DPI = 110
MAX_PAGES = 40

# PyMuPDF layout is not thread-safe: one drawing at a time.
_DRAW_LOCK = threading.Lock()

_PERCENT = re.compile(r"^\s*(\d+(?:\.\d+)?)%\s*$")
_PIXELS = re.compile(r"width:\s*(\d+(?:\.\d+)?)px")


def _column_shares(table: Tag) -> list[float] | None:
    """Each column's share: the percent widths mTool gets, else the
    proportions of pixel column widths."""
    for row in (r for r in table.find_all("tr") if r.find_parent("table") is table):
        cells = row.find_all(["th", "td"], recursive=False)
        widths = [_PERCENT.match(str(cell.get("width", ""))) for cell in cells]
        if cells and all(widths) and not any(cell.get("colspan") for cell in cells):
            return [float(width.group(1)) for width in widths]
        break
    group = table.find("colgroup")
    if group is None or group.find_parent("table") is not table:
        return None
    widths = [_PIXELS.search(str(col.get("style", ""))) for col in group.find_all("col")]
    return [float(width.group(1)) for width in widths] if widths and all(widths) else None


def _fit_columns(html: str, scale: float = 1.0) -> str:
    """State column widths as the drawing engine reads them: it ignores
    percentages and takes pixels as absolute. ``scale`` leaves room for the
    padding and borders it adds on top."""
    soup = BeautifulSoup(html, "html.parser")
    body = PAGE_WIDTH_PT - 2 * MARGIN_PT
    for table in soup.find_all("table"):
        shares = _column_shares(table)
        group = table.find("colgroup")
        if group is not None and group.find_parent("table") is table:
            group.decompose()
        if not shares or not sum(shares):
            continue
        stated = _PERCENT.match(str(table.get("width", "")))
        width = scale * (body * min(float(stated.group(1)), 100) / 100 if stated else body)
        group = soup.new_tag("colgroup")
        for share in shares:
            group.append(soup.new_tag("col", style=f"width: {width * share / sum(shares):.1f}pt"))
        table.insert(0, group)
    return str(soup)


def _note_pdf(html: str, extra_width: float = 0) -> tuple[bytes, list[fitz.Rect]]:
    """Lay ``html`` out as a PDF; return it with the area drawn on each page.
    ``extra_width`` widens the text area, only for a table that cannot fit."""
    story = fitz.Story(html=html, user_css=_FONT_CSS, archive=fitz.Archive(str(_FONTS)))
    page = fitz.Rect(0, 0, PAGE_WIDTH_PT + extra_width, PAGE_HEIGHT_PT)
    body = page + (MARGIN_PT, MARGIN_PT, -MARGIN_PT, -MARGIN_PT)
    buffer = io.BytesIO()
    writer = fitz.DocumentWriter(buffer)
    drawn: list[fitz.Rect] = []
    more = True
    while more:
        if len(drawn) == MAX_PAGES:
            writer.close()
            # A row taller than one page is never placed, so it ends here too.
            raise ValueError(f"The note cannot be drawn: it is over {MAX_PAGES} pages, "
                             "or holds a table row taller than one page.")
        device = writer.begin_page(page)
        more, filled = story.place(body)
        story.draw(device)
        writer.end_page()
        drawn.append(fitz.Rect(filled))
    writer.close()
    return buffer.getvalue(), drawn


def draw(html: str) -> tuple[list[bytes], float]:
    """PNG pages of ``html``, top to bottom, and how far in points its widest
    table runs past mTool's text area (0 when everything fits)."""
    if not (html or "").strip():
        return [], 0.0
    images: list[bytes] = []
    with _DRAW_LOCK:
        body = PAGE_WIDTH_PT - 2 * MARGIN_PT
        scale = 1.0
        for _ in range(4):
            pdf, drawn = _note_pdf(_fit_columns(html, scale))
            overflow = max(filled.x1 for filled in drawn) - (PAGE_WIDTH_PT - MARGIN_PT)
            if overflow <= 1:
                break
            # Padding and borders pushed the widest table past the page.
            scale *= body / (body + overflow)
        overflow = max(overflow, 0.0) if overflow > 1 else 0.0
        if overflow:
            # It cannot be narrower: show it whole on a widened page.
            pdf, drawn = _note_pdf(_fit_columns(html, scale), extra_width=overflow)
        with fitz.open(stream=pdf, filetype="pdf") as doc:
            for page, filled in zip(doc, drawn):
                if filled.is_empty:
                    continue
                clip = fitz.Rect(0, 0, PAGE_WIDTH_PT + overflow,
                                 min(PAGE_HEIGHT_PT, filled.y1 + MARGIN_PT))
                images.append(page.get_pixmap(dpi=RENDER_DPI, clip=clip).tobytes("png"))
    return images, overflow


def to_mm(points: float) -> float:
    return round(points * 25.4 / 72, 1)


def fitting_font_size(raw: str, style: NotesTableStyle) -> int | None:
    """The largest table font below the house size, and not under the
    Settings minimum, at which every table fits mTool's width; None if none."""
    for size in range(min(style.font_size_pt - 1, 14), style.min_font_pt - 1, -1):
        soup = BeautifulSoup(raw, "html.parser")
        for table in soup.find_all("table"):
            if not table.find_parent("table"):
                table[FONT_SIZE_ATTR] = str(size)
        if not draw(decorate_notes_html(str(soup), style))[1]:
            return size
    return None
