"""Page pictures: the drawing rule, the cache and the route (docs/api-contract.md, Step 3).

Copied in part from v1's test_render_policy.py, test_page_cache.py and
test_page_cache_single_flight.py, on PDFs built here instead of Doc 4.
"""
from __future__ import annotations

import io
import os
import threading
import time

import pymupdf
import pytest

from app.documents import pdf_viewer
from app.documents.page_cache import CACHE, PageCache
from tests import pdf_samples
from tests.conftest import OWNER, login, make_run, make_user


@pytest.fixture(autouse=True)
def _empty_cache():
    CACHE.reset()
    yield
    CACHE.reset()


def _save(tmp_path, data: bytes, name: str = "doc.pdf") -> str:
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def _size(png: bytes) -> tuple[int, int]:
    pix = pymupdf.Pixmap(png)
    return pix.width, pix.height


# The drawing rule -----------------------------------------------------------

def test_a_scan_is_drawn_at_its_own_resolution_not_200_dpi(tmp_path):
    path = _save(tmp_path, pdf_samples.build("scan"))
    width, _ = _size(pdf_viewer.render_page_png(path, 1))
    assert width == pytest.approx(pdf_samples.SCAN_PX[0], abs=4)   # 150 DPI, not 1653 px


def test_a_scan_is_never_drawn_above_the_cap(tmp_path):
    path = _save(tmp_path, pdf_samples.build("scan"))
    width, _ = _size(pdf_viewer.render_page_png(path, 1, cap=72))
    assert width == 595


def test_a_typed_page_with_a_small_logo_is_drawn_at_the_cap(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Notes to the financial statements", fontsize=12)
    logo = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20))
    logo.clear_with(128)
    page.insert_image(pymupdf.Rect(500, 40, 540, 80), pixmap=logo)
    path = _save(tmp_path, doc.tobytes())
    with pymupdf.open(path) as opened:
        assert pdf_viewer.dominant_raster_dpi(opened[0]) is None
    width, _ = _size(pdf_viewer.render_page_png(path, 1))
    assert width == round(595 * 200 / 72)


def test_a_region_keeps_the_pixel_density(tmp_path):
    path = _save(tmp_path, pdf_samples.build("text"))
    full_w, full_h = _size(pdf_viewer.render_page_png(path, 1))
    quarter_w, quarter_h = _size(pdf_viewer.render_page_png(path, 1, clip=(0.0, 0.0, 0.5, 0.5)))
    assert quarter_w == pytest.approx(full_w / 2, abs=2)
    assert quarter_h == pytest.approx(full_h / 2, abs=2)


@pytest.mark.parametrize("bad", [(-0.1, 0, 1, 1), (0, 0, 1.5, 1), (0.6, 0, 0.4, 1), (0, 0, 1, 0), ("a", 0, 1, 1)])
def test_a_region_out_of_range_or_order_is_refused(bad):
    with pytest.raises(pdf_viewer.BadClip):
        pdf_viewer.validate_clip(bad)


def test_a_huge_page_is_drawn_within_the_pixel_budget_without_drawing_it():
    doc = pymupdf.open()
    page = doc.new_page(width=2384, height=3370)            # A0: 62 million pixels at 200 DPI
    zoom = pdf_viewer.render_zoom(page, 200)
    assert (page.rect.width * zoom) * (page.rect.height * zoom) <= pdf_viewer.MAX_PIXELS * 1.001
    assert zoom < 200 / 72
    small = doc.new_page(width=595, height=842)              # A4 keeps its 200 DPI
    assert pdf_viewer.render_zoom(small, 200) == pytest.approx(200 / 72)
    doc.close()


# The cache --------------------------------------------------------------------

def _drawn(cache: PageCache, path: str, page: int, cap: int = 200, clip=None, picture: bytes = b"new") -> tuple:
    """(the picture served, whether it had to be drawn)."""
    drawn: list[int] = []

    def render() -> bytes:
        drawn.append(1)
        return picture

    return cache.get_or_render(path, page, cap, clip, render), bool(drawn)


def test_the_cache_keeps_recent_pictures_and_drops_the_least_recent():
    cache = PageCache(max_entries=3)
    for page in (1, 2, 3):
        _drawn(cache, "a.pdf", page, picture=f"P{page}".encode())
    assert _drawn(cache, "a.pdf", 1) == (b"P1", False)     # page 2 is now least recent
    _drawn(cache, "a.pdf", 4, picture=b"P4")
    assert _drawn(cache, "a.pdf", 2)[1] is True
    assert _drawn(cache, "a.pdf", 4) == (b"P4", False)


def test_the_cache_keeps_pages_regions_turns_and_files_apart():
    cache = PageCache()
    _drawn(cache, "a.pdf", 1, picture=b"whole")
    _drawn(cache, "a.pdf", 1, clip=(0, 0, 1, 0.5), picture=b"top")
    _drawn(cache, "b.pdf", 1, picture=b"other file")
    _drawn(cache, "a.pdf", 1, cap=100, picture=b"other cap")
    assert _drawn(cache, "a.pdf", 1) == (b"whole", False)
    assert _drawn(cache, "a.pdf", 1, clip=(0, 0, 1, 0.5)) == (b"top", False)
    assert _drawn(cache, "a.pdf", 1, clip=(0, 0.5, 1, 1))[1] is True
    assert _drawn(cache, "b.pdf", 1) == (b"other file", False)
    assert _drawn(cache, "a.pdf", 1, cap=100) == (b"other cap", False)
    turned = cache.get_or_render("a.pdf", 1, 200, None, lambda: b"turned", rotate=90)
    assert turned == b"turned"


def test_a_replaced_file_is_not_served_from_the_cache(tmp_path):
    cache = PageCache()
    path = _save(tmp_path, b"%PDF-1.4 first")
    _drawn(cache, path, 1, picture=b"first")
    stat = os.stat(path)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert _drawn(cache, path, 1) == (b"new", True)


def test_requests_for_the_same_cold_page_draw_it_once():
    cache, calls = PageCache(), []

    def render() -> bytes:
        calls.append(1)
        time.sleep(0.05)
        return b"picture"

    results: list[bytes] = []
    threads = [threading.Thread(target=lambda: results.append(cache.get_or_render("a.pdf", 1, 200, None, render)))
               for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(calls) == 1 and results == [b"picture"] * 5


def test_a_failed_drawing_is_not_cached():
    cache = PageCache()

    def broken() -> bytes:
        raise RuntimeError("drawing failed")

    with pytest.raises(RuntimeError):
        cache.get_or_render("a.pdf", 1, 200, None, broken)
    assert len(cache) == 0
    assert cache.get_or_render("a.pdf", 1, 200, None, lambda: b"ok") == b"ok"


# The route ----------------------------------------------------------------------

@pytest.fixture
def uploaded(client):
    make_user(OWNER)
    assert login(client, OWNER).status_code == 200
    data = pdf_samples.build("text", "scan")
    response = client.post("/api/runs", files={"file": ("Doc.pdf", io.BytesIO(data), "application/pdf")})
    return response.json()["run"]["id"]


def test_the_route_returns_each_page_as_a_png(client, uploaded):
    text = client.get(f"/api/runs/{uploaded}/pages/1/image")
    scan = client.get(f"/api/runs/{uploaded}/pages/2/image")
    assert text.status_code == 200 and text.headers["content-type"] == "image/png"
    assert _size(text.content)[0] == round(595 * 200 / 72)
    assert _size(scan.content)[0] == pytest.approx(pdf_samples.SCAN_PX[0], abs=4)


def test_the_route_returns_a_region(client, uploaded):
    full = _size(client.get(f"/api/runs/{uploaded}/pages/1/image").content)
    top = client.get(f"/api/runs/{uploaded}/pages/1/image", params={"clip": "0,0,1,0.5"})
    assert top.status_code == 200
    assert _size(top.content)[1] == pytest.approx(full[1] / 2, abs=2)


@pytest.mark.parametrize("clip", ["0,0,1", "0,0,2,1", "a,b,c,d", "0.5,0,0.2,1"])
def test_the_route_refuses_a_bad_region(client, uploaded, clip):
    response = client.get(f"/api/runs/{uploaded}/pages/1/image", params={"clip": clip})
    assert response.status_code == 422
    assert response.json() == {
        "detail": "Give the region as four page fractions from 0 to 1: left, top, right, bottom."}


def test_the_route_refuses_a_page_the_document_does_not_have(client, uploaded):
    for page in (0, 3):
        response = client.get(f"/api/runs/{uploaded}/pages/{page}/image")
        assert response.status_code == 404
        assert response.json() == {"detail": f"This document has no page {page}."}


def test_the_route_needs_a_run_with_a_document_and_a_session(client, uploaded):
    assert client.get("/api/runs/999/pages/1/image").json() == {"detail": "There is no such run."}
    assert client.get(f"/api/runs/{make_run()}/pages/1/image").json() == {"detail": "This run has no document."}
    client.post("/api/auth/logout")
    assert client.get(f"/api/runs/{uploaded}/pages/1/image").status_code == 401
