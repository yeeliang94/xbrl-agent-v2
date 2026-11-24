"""The size tiers: styling steps down to fit mTool's 32,767 characters, and
words are never cut. The tier cases are v1's (tests/test_mtool_notes_exporter.py),
run on the tier function directly instead of through v1's database."""
import pytest
from bs4 import BeautifulSoup

from app.notes.render import fit as fit_module
from app.notes.render.decorate import NotesTableStyle, decorate_notes_html
from app.notes.render.fit import (
    EXCEL_CELL_CHAR_LIMIT, ContentChanged, content_structure, fit, mtool_length, wrap_footnote_html,
)

GRID = NotesTableStyle()                       # v1's bordered baseline
NO_GRID = NotesTableStyle(border_style="none")  # v2's house: blank edges painted white


def _wide_table(n_rows: int, n_cols: int = 10, user_style: bool = False) -> str:
    """An all-amount table; ``user_style`` gives the first cell its own border,
    which keeps the compact tier from applying."""
    cells = "".join("<td>1,234</td>" for _ in range(n_cols))
    first = ('<td style="border: 2px solid #000">1,234</td>'
             + "".join("<td>1,234</td>" for _ in range(n_cols - 1)))
    rows = [f"<tr>{first if (user_style and i == 0) else cells}</tr>" for i in range(n_rows)]
    return "<table><tbody>" + "".join(rows) + "</tbody></table>"


def _words(html: str) -> list[str]:
    return BeautifulSoup(html, "html.parser").get_text(" ").split()


def test_the_count_is_on_the_wrapped_text_as_the_patcher_writes_it():
    assert mtool_length("<p>x</p>") == len(wrap_footnote_html("<p>x</p>")) > len("<p>x</p>")
    assert wrap_footnote_html("<p>x</p>").startswith('<?xml version="1.0" ?>_x000D_\n')


def test_a_normal_note_stays_full():
    out = fit("<table><tbody><tr><td>x</td></tr></tbody></table>", GRID)
    assert out.tier == "full" and 'border="1"' in out.html


def test_a_big_note_steps_down_to_compact_and_keeps_its_visible_look():
    out = fit(_wide_table(40, 9), GRID)
    assert out.tier == "compact"
    assert 'border="1"' in out.html and "text-align: right" in out.html
    assert "border: 0.75px solid" in out.html and "padding:" not in out.html
    assert out.chars <= EXCEL_CELL_CHAR_LIMIT


def test_a_note_that_cannot_compact_steps_down_to_lite():
    out = fit(_wide_table(40, 9, user_style=True), GRID)
    assert out.tier == "lite"
    assert "border: 0.75px solid" in out.html and "vertical-align: top" not in out.html
    assert out.chars <= EXCEL_CELL_CHAR_LIMIT


def test_a_note_over_every_styled_tier_goes_flat_with_every_word():
    raw = _wide_table(30, 40)
    out = fit(raw, GRID)
    assert out.tier == "flat" and out.html == raw
    assert out.chars <= EXCEL_CELL_CHAR_LIMIT


def test_a_note_too_long_even_flat_is_kept_whole_and_reported():
    raw = _wide_table(240)
    out = fit(raw, GRID)
    assert out.tier == "too_long"
    assert out.html == raw and _words(out.html) == _words(raw)
    assert out.chars > EXCEL_CELL_CHAR_LIMIT


def _borderless(rows: int) -> str:
    """Cells that state no edge: under the house look every edge is painted
    white, the most costly case for the white grid."""
    return "<table>" + ("<tr>" + '<td style="padding: 1px 0px">39,827</td>' * 6 + "</tr>") * rows + "</table>"


def test_the_white_grid_goes_before_any_styling_is_lost():
    out = fit(_borderless(65), NO_GRID)
    assert out.tier in ("full", "compact", "lite") and out.white_grid_dropped
    assert "#ffffff" not in out.html and "padding: 1px 0px" in out.html
    small = fit(_borderless(10), NO_GRID)
    assert small.tier == "full" and not small.white_grid_dropped and "#ffffff" in small.html


def test_no_tier_is_worse_than_the_ladder_without_the_white_grid():
    rank = {"full": 0, "compact": 1, "lite": 2, "flat": 3, "too_long": 4}
    for rows in (45, 65, 80, 100):
        raw = _borderless(rows)
        fits = lambda h: mtool_length(h) <= EXCEL_CELL_CHAR_LIMIT  # noqa: E731
        if fits(decorate_notes_html(raw, NO_GRID, fill_white_grid=False)):
            old = "full"
        elif fits(decorate_notes_html(raw, NO_GRID, lite=True, fill_white_grid=False)):
            old = "lite"
        elif fits(raw):
            old = "flat"
        else:
            old = "too_long"
        assert rank[fit(raw, NO_GRID).tier] <= rank[old], rows


def test_a_cleared_large_table_keeps_one_white_border_per_cell():
    cleared = ("border-top: 1px hidden #000000; border-right: 1px hidden #000000; "
               "border-bottom: 1px hidden #000000; border-left: 1px hidden #000000; text-align: right")
    rows = "".join("<tr>" + "".join(f'<td style="{cleared}">{r * 5 + c:,}</td>' for c in range(5)) + "</tr>"
                   for r in range(21))
    out = fit(f"<table>{rows}</table>", GRID)
    assert out.tier == "full" and "hidden" not in out.html
    assert out.html.count("border: 0.75px solid #ffffff") == 105


def test_styling_that_would_lose_words_is_refused(monkeypatch):
    monkeypatch.setattr(fit_module, "_walk", lambda raw, style: ("<h3>Heading</h3>", "full", False))
    with pytest.raises(ContentChanged, match="words or structure"):
        fit("<h3>Heading</h3><p>Full text.</p>", GRID)


def test_the_blank_lines_for_mtool_are_not_counted_as_content():
    raw = "<p>One.</p><p>Two.</p>"
    out = fit(raw, GRID)
    assert out.html.count('data-mtool-spacer="1"') == 1
    assert content_structure(raw) == content_structure(fit_module.without_transport_breaks(out.html))
