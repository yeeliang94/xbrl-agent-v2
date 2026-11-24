"""Draw a PDF page, or a region of one, as a PNG picture.

Copied from v1 `tools/pdf_viewer.py` (`dominant_raster_dpi`, the DPI choice,
the clip check and `render_page_png`). v1's opt-in "cap" policy is dropped:
v2 always draws a scan at the scan's own resolution.

Why, measured in v1: a Doc 4 page's scan is 1648 x 2336 px on an 11.0 x 15.58
inch page, a 150 DPI source. Drawing it at 200 DPI invents pixels: no extra
detail, a picture about 75% bigger, and every model provider scales a full
page down to a fixed budget anyway. So a scan is drawn at min(its DPI, cap),
and any other page at the cap.
"""
from __future__ import annotations

from typing import Optional, Tuple

import pymupdf

DEFAULT_DPI = 200
# No picture is drawn bigger than this many pixels (about 120 MB in memory);
# a larger page or region is drawn at a lower resolution instead.
MAX_PIXELS = 40_000_000

# A picture must cover at least this share of the page to be "the page's
# image". It guards a typed page carrying a small logo: keyed on any picture,
# the logo's DPI would set the whole page's. Several partial tiles also fail
# this test one by one, so a tiled page falls back to the cap.
MIN_DOMINANT_AREA_RATIO = 0.6

# A crop rectangle in page fractions: (x0, y0, x1, y1), each 0..1.
Clip = Tuple[float, float, float, float]


class BadClip(ValueError):
    """A region that is not four page fractions in order."""


class NoSuchPage(LookupError):
    """A page number outside the document."""


def dominant_raster_dpi(page: "pymupdf.Page", *, min_area_ratio: float = MIN_DOMINANT_AREA_RATIO) -> Optional[float]:
    """The resolution of a picture covering most of `page`, or None when no
    single picture does (no picture, small ones, or partial tiles)."""
    page_area = abs(page.rect.width * page.rect.height)
    if page_area <= 0:
        return None
    best: Optional[float] = None
    for info in page.get_image_info():
        try:
            bbox = pymupdf.Rect(info["bbox"])
            px_w, px_h = int(info["width"]), int(info["height"])
        except (KeyError, TypeError, ValueError):
            continue
        if bbox.width <= 0 or bbox.height <= 0 or px_w <= 0 or px_h <= 0:
            continue
        if abs(bbox.width * bbox.height) / page_area < min_area_ratio:
            continue
        # Points to inches is /72. The coarser axis limits the detail.
        dpi = min(px_w / (bbox.width / 72.0), px_h / (bbox.height / 72.0))
        if best is None or dpi > best:
            best = dpi
    return best


def render_dpi(page: "pymupdf.Page", cap: int = DEFAULT_DPI) -> int:
    """The scan's own DPI, never above `cap`; the cap for any other page."""
    native = dominant_raster_dpi(page)
    if native is None:
        return cap
    return max(1, min(int(round(native)), cap))


def render_zoom(page: "pymupdf.Page", cap: int = DEFAULT_DPI, clip_rect: "Optional[pymupdf.Rect]" = None) -> float:
    """The scale to draw at: the page's DPI over 72, lowered when the picture
    would pass MAX_PIXELS. Decided before anything is drawn."""
    zoom = render_dpi(page, cap) / 72
    area = clip_rect if clip_rect is not None else page.rect
    pixels = abs(area.width * zoom) * abs(area.height * zoom)
    if pixels > MAX_PIXELS:
        zoom *= (MAX_PIXELS / pixels) ** 0.5
    return zoom


def validate_clip(clip: Optional[Clip]) -> Optional[Clip]:
    """The region as four floats, or BadClip."""
    if clip is None:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in clip)
    except (TypeError, ValueError) as exc:
        raise BadClip(f"A region is four numbers (x0, y0, x1, y1), not {clip!r}.") from exc
    if not all(0.0 <= v <= 1.0 for v in (x0, y0, x1, y1)) or x0 >= x1 or y0 >= y1:
        raise BadClip(f"A region is four page fractions in order, not {(x0, y0, x1, y1)}.")
    return (x0, y0, x1, y1)


def upright_clip_to_page(clip: Clip, rotate: int) -> Clip:
    """A region given on the page turned `rotate` degrees clockwise, as
    fractions of the page as it is stored."""
    x0, y0, x1, y1 = clip
    if rotate == 90:     # upright (u, v) came from page (v, 1 - u)
        return (y0, 1 - x1, y1, 1 - x0)
    if rotate == 180:
        return (1 - x1, 1 - y1, 1 - x0, 1 - y0)
    if rotate == 270:    # upright (u, v) came from page (1 - v, u)
        return (1 - y1, x0, 1 - y0, x1)
    return clip


def render_page_png(path: str, page_num: int, *, cap: int = DEFAULT_DPI, clip: Optional[Clip] = None,
                    rotate: int = 0) -> bytes:
    """One 1-based page as PNG bytes, optionally cropped to `clip` (page
    fractions) and turned `rotate` degrees clockwise (0, 90, 180, 270; the
    clip is then given on the turned page). A crop keeps the page's pixel
    density; it covers less of it. The picture never passes MAX_PIXELS.
    Pure: caching is `page_cache`'s job."""
    rect = validate_clip(clip)
    if rotate not in (0, 90, 180, 270):
        raise ValueError("A page turns by 0, 90, 180 or 270 degrees.")
    if rect is not None and rotate:
        rect = upright_clip_to_page(rect, rotate)
    doc = pymupdf.open(path)
    try:
        if page_num < 1 or page_num > len(doc):
            raise NoSuchPage(f"This document has no page {page_num}.")
        page = doc[page_num - 1]
        clip_rect = None
        if rect is not None:
            r = page.rect
            clip_rect = pymupdf.Rect(r.x0 + rect[0] * r.width, r.y0 + rect[1] * r.height,
                                     r.x0 + rect[2] * r.width, r.y0 + rect[3] * r.height)
        zoom = render_zoom(page, cap, clip_rect)
        matrix = pymupdf.Matrix(zoom, zoom)
        if rotate:
            matrix = matrix.prerotate(rotate)
        return page.get_pixmap(matrix=matrix, clip=clip_rect).tobytes("png")
    finally:
        doc.close()
