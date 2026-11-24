"""The mTool decorator's compact tier, table widths and white edges: v1's
tests (tests/test_mtool_notes_decorate.py), continued from test_notes_decorate.py."""
import re

import pytest

from bs4 import BeautifulSoup

from app.notes.render.decorate import NotesTableStyle, decorate_notes_html

# v1's shipped house look: no grid, 11 pt, tight padding and spacing.
V1_HOUSE = NotesTableStyle(border_style="none", font_size_pt=11, cell_padding_px=(3, 3),
                           paragraph_spacing_px=3, header_fill="transparent")


# --- compact tier (mTool-only; docs/PLAN-mtool-compact-decoration.md) --------
def test_compact_body_cells_keep_default_border_without_padding():
    """The whole point of the tier: a plain left-aligned body cell rides on
    the table's legacy attrs + renderer defaults and gets ZERO per-cell style."""
    out = decorate_notes_html(
        "<table><tbody><tr><td>Land</td><td>1,595</td></tr></tbody></table>",
        compact=True)
    # The label cell carries only the explicit default border.
    assert re.search(r'<td[^>]*style="border: 0.75px solid #999; "[^>]*>Land</td>', out)
    # The numeric cell also carries right-alignment.
    assert re.search(r'<td[^>]*style="border: 0.75px solid #999; text-align: right;"[^>]*>1,595<', out)
    # No per-cell boilerplate anywhere.
    assert "border: 0.75px solid" in out
    assert not re.search(r'<td[^>]*style="[^"]*padding', out)
    assert "vertical-align: top" not in out


def test_compact_table_keeps_legacy_attrs_and_hoisted_font():
    """The grid + padding move to the table-level legacy attributes and the
    hoisted (inheritable) font stays on the table element."""
    out = decorate_notes_html(
        "<table><tbody><tr><td>Land</td><td>1,595</td></tr></tbody></table>",
        compact=True)
    assert re.search(r'<table[^>]*border="1"', out)
    assert re.search(r'<table[^>]*cellpadding="4"', out)
    assert re.search(r'<table[^>]*cellspacing="0"', out)
    assert re.search(r'<table[^>]*style="[^"]*font-family: Arial', out)


def test_compact_th_keeps_fill_weight_and_explicit_align():
    """<th> defaults to CENTER in most renderers, so compact must still write
    an explicit alignment — plus the header fill + weight."""
    out = decorate_notes_html(
        "<table><thead><tr><th>Item</th><th>2024</th></tr></thead></table>",
        compact=True)
    assert re.search(r'<th[^>]*style="[^"]*background: #f3f4f6', out)
    assert re.search(r'<th[^>]*style="[^"]*font-weight: 600', out)
    assert re.search(r'<th[^>]*style="[^"]*text-align: left[^"]*"[^>]*>Item<', out)
    assert re.search(r'<th[^>]*style="[^"]*text-align: right[^"]*"[^>]*>2024<', out)


def test_compact_skips_table_with_user_owned_cell_border():
    """A table where any cell carries a user (WYSIWYG/sidecar) border keeps
    the FULL per-cell treatment — a table-level grid would fight the user's
    deliberate styling. The user's style itself always survives."""
    out = decorate_notes_html(
        '<table><tbody><tr>'
        '<td style="border: 2px solid #000">A</td><td>1,000</td>'
        '</tr></tbody></table>', compact=True)
    assert "2px solid #000" in out                      # user style survives
    # Sibling cell got the full per-cell treatment, not the compact one.
    assert re.search(r'<td[^>]*style="[^"]*border: 0.75px solid #999', out)
    assert re.search(r'<td[^>]*style="[^"]*padding: 4px 8px', out)


def test_compact_skips_table_with_user_owned_cell_fill():
    out = decorate_notes_html(
        '<table><tbody><tr>'
        '<td style="background-color: #ffff00">A</td><td>1,000</td>'
        '</tr></tbody></table>', compact=True)
    assert "background-color: #ffff00" in out           # user fill survives
    assert re.search(r'<td[^>]*style="[^"]*border: 0.75px solid #999', out)


def test_compact_only_compacts_the_eligible_sibling_table():
    """Per-TABLE decision: a user-styled table keeps the full form while a
    plain sibling table in the same note compacts."""
    out = decorate_notes_html(
        '<table><tbody><tr><td style="border: 2px solid #000">A</td>'
        '</tr></tbody></table>'
        '<table><tbody><tr><td>Plain</td><td>1,000</td></tr></tbody></table>',
        compact=True)
    # The plain table keeps its thin grid without padding boilerplate.
    assert re.search(r'<td[^>]*style="border: 0.75px solid #999; "[^>]*>Plain</td>', out)
    # …while the user-styled table's sibling decoration is the full form.
    assert "2px solid #000" in out


def test_compact_border_none_theme_keeps_full_cell_treatment():
    """borderStyle 'none' suppresses the table attrs, so there is nothing for
    compact cells to inherit — those tables keep the full per-cell form
    (which for border-none means padding, no grid)."""
    out = decorate_notes_html(
        "<table><tbody><tr><td>x</td></tr></tbody></table>",
        NotesTableStyle(border_style="none"), compact=True)
    assert not re.search(r'<table[^>]*border="1"', out)
    assert re.search(r'<td[^>]*style="[^"]*padding: 4px 8px', out)


def test_compact_whiteout_still_runs_on_cleared_borders():
    """A formatter-cleared (hidden) border still translates to white in
    compact mode — the cell owns a border, so its table isn't compacted, and
    the TX grey-line accommodation must keep working."""
    out = decorate_notes_html(
        '<table><tbody><tr><td style="border: none">x</td></tr></tbody></table>',
        compact=True)
    assert "border: none" not in out
    assert "0.75px solid #ffffff" in out.lower()


def test_compact_fits_when_full_exceeds_cell_limit_and_preserves_text():
    from bs4 import BeautifulSoup
    from app.notes.render.fit import EXCEL_CELL_CHAR_LIMIT, wrap_footnote_html
    html = ("<table><tbody>"
            + "".join("<tr><td>Item</td>"
                      + "".join("<td>1,234</td>" for _ in range(5)) + "</tr>"
                      for _ in range(50))
            + "</tbody></table>")
    full = decorate_notes_html(html)
    compact = decorate_notes_html(html, compact=True)
    assert len(wrap_footnote_html(full)) > EXCEL_CELL_CHAR_LIMIT
    assert len(wrap_footnote_html(compact)) <= EXCEL_CELL_CHAR_LIMIT
    # Content is untouched — identical rendered text.
    assert (BeautifulSoup(compact, "html.parser").get_text()
            == BeautifulSoup(full, "html.parser").get_text())


def test_unstyled_cell_still_receives_theme_defaults():
    """Verbatim precedence must not disable decoration for PDF-sourced notes
    that legitimately arrive plain."""
    out = decorate_notes_html(
        "<table><tr><td>1,595</td></tr></table>", NotesTableStyle()
    )
    assert "style=" in out  # the decorator did its normal job


# --- Page-width fit for TX (run 76) -----------------------------------------
# TX ignores CSS widths and sizes columns to content, so a long label column
# jams the amounts against itself and the operator hand-resizes every table.
# Legacy width ATTRIBUTES are the dialect TX honours.

def test_unsized_table_gets_page_width_and_column_split():
    html = ("<table><tbody><tr><td>United Arab Emirates</td><td>60,882</td>"
            "<td>66,336</td></tr></tbody></table>")
    out = decorate_notes_html(html, NotesTableStyle())
    assert re.search(r'<table[^>]*width="100%"', out)
    widths = re.findall(r'<td[^>]*width="(\d+%)"', out)
    assert widths == ["64%", "18%", "18%"]  # label keeps the rest


def test_formatter_column_widths_reach_tx_as_width_attributes():
    """Formatter sizing is CSS-only (TX ignores CSS widths), so the decorator
    restates it as legacy attributes in the same proportion instead of
    dropping the table to content-sized columns."""
    out = decorate_notes_html(
        '<table><colgroup data-formatter-widths="true"><col style="width: 300px"><col style="width: 100px">'
        '</colgroup><tbody><tr><th>Capital</th><th></th></tr>'
        "<tr><td>Ordinary shares</td><td>1,000</td></tr></tbody></table>", NotesTableStyle())
    assert re.findall(r'<th[^>]*width="(\d+%)"', out) == ["75%", "25%"]
    assert re.search(r'<table[^>]*width="100%"', out)


def test_formatter_column_widths_without_table_width_fill_the_page():
    out = decorate_notes_html(
        '<table><colgroup data-formatter-widths="true"><col style="width: 100px"><col style="width: 100px">'
        '<col style="width: 100px">'
        "</colgroup><tbody><tr><td>Label</td><td>1</td><td>2</td></tr></tbody></table>",
        NotesTableStyle())
    assert re.search(r'<table[^>]*width="100%"', out)
    assert re.findall(r'<td[^>]*width="(\d+%)"', out) == ["34%", "33%", "33%"]


def test_formatter_column_shares_never_round_to_zero():
    out = decorate_notes_html(
        '<table><colgroup data-formatter-widths="true"><col style="width: 2000px">'
        '<col style="width: 2000px"><col style="width: 16px"></colgroup>'
        "<tbody><tr><td>a</td><td>1</td><td>2</td></tr></tbody></table>", NotesTableStyle())
    shares = [int(w) for w in re.findall(r'<td[^>]*width="(\d+)%"', out)]
    assert shares == [49, 50, 1] and sum(shares) == 100


def test_formatter_markers_never_reach_tx():
    from app.notes.render.decorate import add_transport_breaks
    html = ('<table data-formatter-font-size="9" data-frame="grid">'
            '<colgroup data-formatter-widths="true"><col style="width: 300px">'
            '<col style="width: 100px"></colgroup><tr><td>'
            '<strong>Total</strong></td><td>1</td></tr></table>')
    for out in (decorate_notes_html(html, NotesTableStyle()), add_transport_breaks(html)):
        assert "data-formatter" not in out and "data-frame" not in out
        assert ">Total</strong>" in out


def test_text_table_gets_page_fit_but_no_accountant_split():
    """The split assumes columns 2..n hold AMOUNTS. A two-column TEXT table
    (director / designation, address lines) must not have its second column
    crushed to 18% — page fit only, TX sizes by content."""
    out = decorate_notes_html(
        "<table><tbody>"
        "<tr><td>Dato' Ahmad bin Ismail</td><td>Managing Director</td></tr>"
        "<tr><td>Lim Wei Ling</td><td>Independent Director</td></tr>"
        "</tbody></table>", NotesTableStyle())
    assert re.search(r'<table[^>]*width="100%"', out)
    assert not re.findall(r'<td[^>]*width="\d+%"', out)


def test_mostly_numeric_trailing_columns_still_split():
    """Header rows (year labels, dashes, a stray unit cell) must not defeat
    the gate — a strict majority of numeric trailing cells keeps the split."""
    out = decorate_notes_html(
        "<table><tbody>"
        "<tr><td>Country</td><td>2024</td><td>2023</td></tr>"
        "<tr><td>Qatar</td><td>60,882</td><td>-</td></tr>"
        "</tbody></table>", NotesTableStyle())
    assert re.findall(r'<td[^>]*width="(\d+%)"', out) == ["64%", "18%", "18%"]


def test_nine_plus_columns_bail_to_page_fit_only():
    """At 9+ columns the label floor (30%) and amount floor (10%) can't both
    hold — the split would sum past 100%, which TX can't honour. Page fit
    only; TX shares the width by content."""
    html = ("<table><tbody><tr><td>Label</td>"
            + "".join(f"<td>1,00{i}</td>" for i in range(9))
            + "</tr></tbody></table>")
    out = decorate_notes_html(html, NotesTableStyle())
    assert re.search(r'<table[^>]*width="100%"', out)
    assert not re.findall(r'<td[^>]*width="\d+%"', out)


def test_nested_table_widths_stay_per_table():
    """A nested table's rows are its own: the inner table gets its own
    independent fit from its own 4 columns, and the outer table — whose
    "second column" holds a table, not an amount — gets the page fit only."""
    html = ("<table><tbody><tr><td>Outer label</td>"
            "<td><table><tbody><tr><td>Item</td><td>1,500</td><td>2,300</td>"
            "<td>3,100</td></tr></tbody></table></td></tr></tbody></table>")
    out = decorate_notes_html(html, NotesTableStyle())
    widths = re.findall(r'<td[^>]*width="(\d+%)"', out)
    assert sorted(widths) == sorted(["46%", "18%", "18%", "18%"])
    assert out.count('width="100%"') == 2   # both tables page-fitted


# --- neighbour suppression: white must not contest a declared shared edge ---

def test_white_fill_skips_edge_declared_by_neighbour():
    """A cell declaring only a bottom line shares that edge with the
    cell below. Painting the below-cell's TOP white would contest the underline
    (a same-width CSS border-collapse tie is won by the TOPMOST cell — the
    white one). The shared edge stays silent instead; all other edges of both
    cells are painted white as usual."""
    html = ('<table><tbody>'
            '<tr><td style="border-bottom: 1px solid #000000">Total</td></tr>'
            "<tr><td>after</td></tr></tbody></table>")
    out = decorate_notes_html(html, NotesTableStyle(border_style="none"))
    cells = re.findall(r"<td[^>]*>", out)
    assert len(cells) == 2
    top_cell, bottom_cell = cells
    assert "border-bottom: 1px solid #000000" in top_cell   # source rule kept
    assert "border-top" not in bottom_cell                  # shared edge silent
    # The rest of both cells' edges are still painted white.
    assert "border-left: 0.75px solid #ffffff" in bottom_cell
    assert "border-bottom: 0.75px solid #ffffff" in bottom_cell



@pytest.mark.parametrize("level", range(1, 7))
def test_all_source_heading_levels_retain_semantics_and_receive_mbrs_style(level):
    out = decorate_notes_html(
        f"<h{level}>Policy <em>detail</em></h{level}>",
        NotesTableStyle(font_size_pt=14),
    )
    soup = BeautifulSoup(out, "html.parser")
    heading = soup.find(f"h{level}")
    assert heading is not None
    assert heading.em.get_text() == "detail"
    assert "font-size: 14pt" in heading["style"]
    assert "font-weight: 600" in heading["style"]


def test_heading_cells_below_the_heading_rows_render_as_data_cells():
    """Doc 1 notes 19 and 71: a row label or a total captured as <th> below the
    data must not inherit heading bold or fill; the top heading row keeps it."""
    from app.notes.render.decorate import NotesTableStyle, decorate_notes_html
    html = ("<table><tr><th></th><th>2025</th></tr>"
            "<tr><th>Total cash outflows for leases</th><td>1,127</td></tr>"
            "<tr><th></th><th>12,856</th></tr></table>")
    for style in (NotesTableStyle(), V1_HOUSE):
        for compact in (False, True):
            out = decorate_notes_html(html, style, compact=compact)
            cells = re.findall(r"<th([^>]*)>([^<]*)</th>", out)
            styles = {text: attrs for attrs, text in cells}
            assert "font-weight: 600" in styles["2025"]
            for body in ("Total cash outflows for leases", "12,856"):
                assert "font-weight: 400" in styles[body] and "background" not in styles[body]
            assert "text-align: left" in styles["Total cash outflows for leases"]
            assert "text-align: right" in styles["12,856"]
