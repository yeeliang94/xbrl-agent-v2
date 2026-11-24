"""The one renderer: a field's notes as blocks become one text that review,
Copy and mTool all use, sized to mTool's limit, and a picture of that text."""
import fitz
import pytest
from bs4 import BeautifulSoup

from app.notes import render
from app.notes.blocks import NoteBody, words
from app.notes.render import picture
from app.notes.render.fit import EXCEL_CELL_CHAR_LIMIT, mtool_length, wrap_footnote_html

HOUSE = {"body_text": "justified", "table_font_pt": 10, "smallest_table_font_pt": 8,
         "double_underline": "thick_bottom_border", "bold_totals": False}
_SRC = {"page": 4, "block": 0}


def _note(*blocks) -> NoteBody:
    return NoteBody.model_validate({"blocks": [{"source": _SRC, "id": f"b{i}", **b}
                                               for i, b in enumerate(blocks)]})


def _table(rows, columns=None, **extra):
    width = len(rows[0]["cells"])
    columns = columns or [{"role": "label"}] + [{"role": "amount"}] * (width - 1)
    return {"kind": "table", "columns": columns, "rows": rows, **extra}


def _row(*texts, **look):
    return {"cells": [{"text": t} for t in texts], **look}


REVENUE = _note(
    {"kind": "heading", "level": 1, "text": "5. Revenue"},
    {"kind": "paragraph", "text": "Revenue is recognised when control of the goods passes."},
    _table([_row("", "2025 RM", "2024 RM", role="heading"),
            _row("Sales of goods", "1,200,000", "900,000"),
            _row("Services", "65,564", "99,111"),
            _row("Total", "1,265,564", "999,111", role="total", bold=True,
                 line_below={"style": "double", "columns": [1, 2]})]),
)


def _text(html: str) -> list[str]:
    return BeautifulSoup(html, "html.parser").get_text(" ").split()


def _cell(html: str, text: str):
    soup = BeautifulSoup(html, "html.parser")
    return next(c for c in soup.find_all(["td", "th"]) if c.get_text() == text)


# --- one text -----------------------------------------------------------------

def test_review_copy_and_mtool_get_one_identical_text():
    first = render.prepare([REVENUE], HOUSE)
    again = render.prepare([REVENUE], HOUSE)
    assert first.html == again.html and first.revision == again.revision
    assert first.tier == "full" and not first.too_long
    # mTool's cell is that same text in the patcher's shell, counted whole.
    assert wrap_footnote_html(first.html).count(first.html) == 1
    assert first.chars == mtool_length(first.html)
    # The preview draws that same text, not a second rendering of the note.
    assert render.preview(first).pages == picture.draw(first.html)[0]


def test_every_word_of_the_note_reaches_the_text():
    out = render.prepare([REVENUE], HOUSE)
    assert _text(out.html) == " ".join(words(REVENUE)).split()


def test_a_field_with_several_notes_is_counted_as_one_text():
    second = _note({"kind": "heading", "level": 1, "text": "6. Cost of sales"},
                   {"kind": "paragraph", "text": "Cost of sales comprises materials."})
    one, two = render.prepare([REVENUE], HOUSE), render.prepare([second], HOUSE)
    both = render.prepare([REVENUE, second], HOUSE)
    assert both.chars == mtool_length(both.html) > max(one.chars, two.chars)
    assert _text(both.html) == _text(one.html) + _text(two.html)
    # Two notes that each fit can be too long together.
    para = {"kind": "paragraph", "text": "word " * 3000}
    half = _note(*[dict(para) for _ in range(2)])
    assert not render.prepare([half], HOUSE).too_long
    assert render.prepare([half, half, half], HOUSE).too_long


# --- size ---------------------------------------------------------------------

def _big_table(rows: int) -> NoteBody:
    body = [_row(f"Item {i}", f"{i * 1000:,}", f"{i * 900:,}", f"{i * 800:,}", f"{i * 700:,}")
            for i in range(1, rows + 1)]
    return _note(_table([_row("", "2025", "2024", "2023", "2022", role="heading"), *body]))


def test_an_over_limit_field_steps_down_the_tiers_and_keeps_every_word():
    tiers = []
    for rows in (20, 120, 200, 400, 900):
        note = _big_table(rows)
        out = render.prepare([note], HOUSE)
        tiers.append(out.tier)
        assert _text(out.html) == _text(out.source_html)
        assert (out.chars <= EXCEL_CELL_CHAR_LIMIT) != out.too_long
    order = ["full", "compact", "lite", "flat", "too_long"]
    assert tiers == sorted(tiers, key=order.index)  # never richer as it grows
    assert tiers[0] == "full" and tiers[-1] == "too_long"
    assert len(set(tiers)) >= 3


def test_the_tiers_hold_on_a_200_row_table():
    note = _big_table(200)
    out = render.prepare([note], HOUSE)
    assert out.tier in ("full", "compact", "lite", "flat")
    assert out.chars <= EXCEL_CELL_CHAR_LIMIT and not out.too_long
    cells = [c.get_text() for c in BeautifulSoup(out.html, "html.parser").find_all(["td", "th"])]
    assert cells == words(note)


# --- the house style fills only what is not set ---------------------------------

def test_a_set_look_is_never_overridden_by_the_house_style():
    note = _note(
        {"kind": "paragraph", "text": "Left by the source.", "look": {"align": "left"}},
        {"kind": "paragraph", "text": "No alignment of its own."},
        _table([_row("Label", "Centred", "1,000"),
                _row("Total", "2,000", "3,000", role="total",
                     line_below={"style": "single", "columns": [1, 2]})],
               columns=[{"role": "label"}, {"role": "amount", "align": "center"}, {"role": "amount"}],
               font_pt=9),
    )
    for house in (HOUSE, {**HOUSE, "body_text": "left", "bold_totals": True, "table_font_pt": 11}):
        html = render.prepare([note], house).html
        soup = BeautifulSoup(html, "html.parser")
        set_para, plain_para = soup.find_all("p", string=True)[:2]
        assert "text-align: left" in set_para["style"]
        wrapper_align = "left" if house["body_text"] == "left" else "justify"
        assert soup.div["style"].endswith(f"text-align: {wrapper_align};")
        assert "text-align" not in plain_para["style"]
        assert "text-align: center" in _cell(html, "Centred")["style"]
        assert "text-align: right" in _cell(html, "1,000")["style"]
        assert "font-size: 9pt" in soup.table["style"]
        assert "border-bottom: 0.75px solid #000000" in _cell(html, "2,000")["style"]
    # Bold totals fills a total row with no bold of its own.
    bolded = render.prepare([note], {**HOUSE, "bold_totals": True}).html
    assert _cell(bolded, "2,000").strong is not None
    assert _cell(render.prepare([note], HOUSE).html, "2,000").strong is None


def test_a_look_the_agent_was_not_sure_of_is_drawn_in_the_house_style():
    note = _note(
        {"kind": "paragraph", "text": "Unsure.", "look": {"align": "center", "unsure": ["align"]}},
        _table([_row("Total", "1,000", role="total", bold=True, unsure=["bold"])]),
    )
    html = render.prepare([note], HOUSE).html
    assert "text-align" not in BeautifulSoup(html, "html.parser").p["style"]
    assert _cell(html, "1,000").strong is None
    assert _cell(render.prepare([note], {**HOUSE, "bold_totals": True}).html, "1,000").strong is not None


def test_a_double_line_draws_as_the_house_style_says():
    thick = _cell(render.prepare([REVENUE], HOUSE).html, "999,111")["style"]
    single = _cell(render.prepare([REVENUE], {**HOUSE, "double_underline": "single_bottom_border"}).html,
                   "999,111")["style"]
    assert "border-bottom: 2.5px solid #000000" in thick
    assert "border-bottom: 0.75px solid #000000" in single
    assert "double" not in thick + single


def test_no_line_is_drawn_white_because_mtool_draws_blank_edges_grey():
    html = render.prepare([REVENUE], HOUSE).html
    label = _cell(html, "Sales of goods")["style"]
    assert "border: 0.75px solid #ffffff" in label
    for text in ("2025 RM", "Sales of goods", "Total"):
        assert "hidden" not in _cell(html, text)["style"]
    gridded = _note(_table([_row("A", "1")], frame="grid"))
    assert "border: 0.75px solid #000000" in _cell(render.prepare([gridded], HOUSE).html, "1")["style"]


def test_a_font_size_is_never_below_the_settings_minimum():
    note = _note(_table([_row("A", "1")], font_pt=8))
    html = render.prepare([note], {**HOUSE, "smallest_table_font_pt": 9}).html
    assert "font-size: 9pt" in BeautifulSoup(html, "html.parser").table["style"]


# --- the picture -----------------------------------------------------------------

def _ink_rows(png: bytes) -> list[int]:
    """Rows of the picture that hold dark ink, top to bottom."""
    pix = fitz.Pixmap(png)
    return [y for y in range(pix.height)
            if min(pix.pixel(x, y)[0] for x in range(0, pix.width, 2)) < 80]


def test_a_bold_total_and_its_rule_show_in_the_picture():
    plain = _note(_table([_row("Sales", "1,265,564"), _row("Total", "1,265,564", role="total")]))
    styled = _note(_table([_row("Sales", "1,265,564"),
                           _row("Total", "1,265,564", role="total", bold=True,
                                line_below={"style": "double", "columns": [1]})]))
    before, = render.preview(render.prepare([plain], HOUSE)).pages
    after, = render.preview(render.prepare([styled], HOUSE)).pages
    assert fitz.Pixmap(before).samples != fitz.Pixmap(after).samples
    # The thick rule: a run of solid dark rows below the last line of text.
    extra = sorted(set(_ink_rows(after)) - set(_ink_rows(before)))
    assert len(extra) >= 3


def test_a_wide_table_reports_its_overflow_and_the_font_that_fits():
    heads = [f"Heading {i}" for i in range(10)]
    wide = _note(_table([_row(*heads, role="heading"), _row("Item", *["1,265,564"] * 9)]))
    shown = render.preview(render.prepare([wide], {**HOUSE, "table_font_pt": 11}))
    assert shown.overflow_mm > 0
    assert shown.fits_at_pt is not None and 8 <= shown.fits_at_pt < 11
    assert fitz.Pixmap(shown.pages[0]).width > picture.PAGE_WIDTH_PT * picture.RENDER_DPI / 72 + 1
    fits = render.preview(render.prepare([REVENUE], HOUSE))
    assert fits.overflow_mm == 0 and fits.fits_at_pt is None


@pytest.mark.parametrize("minimum", [8, 9])
def test_the_font_that_fits_is_never_below_the_settings_minimum(minimum):
    house = {**HOUSE, "table_font_pt": 11, "smallest_table_font_pt": minimum}
    for columns in (10, 12, 30):
        note = _note(_table([_row(*[f"Heading {i}" for i in range(columns)], role="heading"),
                             _row("Item", *["1,265,564"] * (columns - 1))]))
        shown = render.preview(render.prepare([note], house))
        assert shown.min_font_pt == minimum
        assert shown.fits_at_pt is None or shown.fits_at_pt >= minimum
    assert shown.overflow_mm > 0 and shown.fits_at_pt is None  # 30 columns never fit
