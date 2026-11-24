"""The mTool decorator: v1's tests (tests/test_mtool_notes_decorate.py), less
the Word-table, editor-resize, merged-cell and legacy-theme cases whose code
v2 does not carry."""
import re
import pytest

from bs4 import BeautifulSoup

from app.notes.render.decorate import NotesTableStyle, decorate_notes_html
from app.notes.render.tables import is_numeric_cell_text, should_right_align_cell

# v1's shipped house look: no grid, 11 pt, tight padding and spacing.
V1_HOUSE = NotesTableStyle(border_style="none", font_size_pt=11, cell_padding_px=(3, 3),
                           paragraph_spacing_px=3, header_fill="transparent")


# --- numeric detection (parity with tableAlign.ts) --------------------------
def test_numeric_cell_detection():
    for yes in ("1,595", "(95)", "-", "—", "1.5", "-42", "16,330"):
        assert is_numeric_cell_text(yes), yes
    for no in ("Freehold land", "2024 note", "Total assets", "N/A"):
        assert not is_numeric_cell_text(no), no


def test_row_label_column_stays_left_even_if_numeric():
    # First cell of a multi-column row is the label column — left even when it
    # reads like a number (a "2024" period label).
    assert should_right_align_cell("2024", 0, 3) is False
    assert should_right_align_cell("1,500", 1, 3) is True
    # A bare single-cell numeric row still right-aligns.
    assert should_right_align_cell("1,500", 0, 1) is True
    # A full-width merged "2024" section row is a label (runs 347-349).
    assert should_right_align_cell("2024", 0, 1, colspan=5) is False


# --- prose decoration -------------------------------------------------------
def test_prose_gets_arial_and_paragraph_spacing():
    out = decorate_notes_html("<p>First paragraph.</p>")
    assert re.search(r'<p[^>]*style="[^"]*font-family: Arial[^"]*"[^>]*>First', out)
    assert re.search(r'<p[^>]*style="[^"]*font-size: 10pt', out)
    assert re.search(r'<p[^>]*style="[^"]*margin: 0 0 8px 0', out)
    # Wrapping container carries the face so bare <strong>/loose text inherits.
    assert re.match(r'<div[^>]*style="[^"]*font-family: Arial', out)
    assert "text-align: justify" in BeautifulSoup(out, "html.parser").div["style"]


@pytest.mark.parametrize("mode", [{}, {"compact": True}, {"lite": True}])
def test_justified_prose_preserves_explicit_alignment_and_table_alignment(mode):
    html = ('<h3>Accounting policies</h3><p>Policy prose.</p>'
            '<ul><li>Policy item.</li></ul>'
            '<p style="text-align: left">Manual left.</p>'
            '<h3 style="text-align: center">Manual heading</h3>'
            '<div style="text-align: right"><p>Manual section.</p></div>'
            '<table><tr><td><p>Description</p></td><td><p>1,000</p></td></tr>'
            '<tr><td>Heading amount</td><td><h3>2,000</h3></td></tr></table>')
    soup = BeautifulSoup(decorate_notes_html(html, **mode), "html.parser")
    assert "text-align: justify" in soup.div["style"]
    assert "text-align: left" in soup.h3["style"]
    assert soup.find("p", string="Manual left.")["style"].count("text-align") == 1
    assert "text-align: left" in soup.find("p", string="Manual left.")["style"]
    assert "text-align: center" in soup.find("h3", string="Manual heading")["style"]
    assert "text-align: right" in soup.find("p", string="Manual section.").parent["style"]
    assert "text-align: left" in soup.table["style"]
    assert "text-align: right" in soup.find_all("td")[1]["style"]
    assert all("text-align" not in p["style"] for p in soup.table.find_all("p"))
    assert "text-align" not in soup.table.h3["style"]
    assert "text-align: right" in soup.table.h3.parent["style"]
    assert list(soup.stripped_strings) == list(BeautifulSoup(html, "html.parser").stripped_strings)


def test_house_spacing_separates_paragraphs_and_adjacent_tables():

    html = ("<p>First paragraph.</p><p>Second paragraph.</p>"
            "<table><tr><th>Category</th><th>Group</th></tr>"
            "<tr><th>Item</th><th>2024 RM'000</th></tr>"
            "<tr><td>Fees</td><td>1,595</td></tr></table>"
            "<table><tr><td>Other</td><td>265</td></tr></table>")
    out = BeautifulSoup(decorate_notes_html(
        html, V1_HOUSE), "html.parser")
    prose = [p for p in out.find_all("p") if p.get("data-mtool-spacer") != "1"]
    assert len(prose) == 2
    assert all("margin: 0 0 3px 0" in p["style"] for p in prose)
    assert len(out.select('p[data-mtool-spacer="1"]')) == 3
    assert all("margin: 3px 0" in t["style"] for t in out.find_all("table"))
    assert all("padding: 3px 3px" in cell["style"] for cell in out.find_all(["td", "th"]))
    header = out.find("th", string="2024 RM'000")
    assert header is not None and "text-align: right" in header["style"]
    group = out.find("th", string="Group")
    assert group is not None and "text-align: right" in group["style"]


def test_descriptive_body_text_stays_left_in_partly_numeric_column():
    html = ("<table><tr><th>Relationship</th><th>2024</th></tr>"
            "<tr><td>Director</td><td>12</td></tr>"
            "<tr><td>Other</td><td>Spouse of director</td></tr></table>")
    out = BeautifulSoup(decorate_notes_html(html), "html.parser")
    assert "text-align: right" in out.find("th", string="2024")["style"]
    assert "text-align: right" in out.find("td", string="12")["style"]
    assert "text-align: left" in out.find("td", string="Spouse of director")["style"]


def test_bold_and_inline_marks_are_preserved():
    html = ('<h3>13. Deferred tax</h3><p>a <strong>bold</strong> <em>it</em></p>'
            '<table><tr><th><strong>2025</strong></th></tr>'
            '<tr><td><b>Deferred tax assets</b></td></tr></table>')
    out = decorate_notes_html(html)
    soup = BeautifulSoup(out, "html.parser")
    assert soup.h3.get_text() == "13. Deferred tax"
    assert "font-weight: 600" in soup.h3["style"]
    assert "font-weight: 600" in soup.p.strong["style"]
    assert "font-weight: 600" in soup.th.strong["style"]
    assert "font-weight: 600" in soup.td.b["style"]
    assert "<em>it</em>" in out
    assert len(soup.table.find_all("tr")) == 2
    assert " ".join(BeautifulSoup(html, "html.parser").stripped_strings) == " ".join(soup.stripped_strings)


def test_semibold_preserves_explicit_weights_and_does_not_compound_nested_emphasis():
    html = ('<h3><strong>Heading</strong></h3><p><strong>Outer <b>nested</b></strong></p>'
            '<p><strong style="font-weight: 800">Explicit</strong></p>'
            '<table><tr><td style="font-weight:700"><strong>Source label</strong></td></tr></table>')
    soup = BeautifulSoup(decorate_notes_html(html), "html.parser")
    assert "font-weight: 600" in soup.h3["style"]
    assert "font-weight: 600" in soup.h3.strong["style"]
    assert "font-weight: 600" in soup.p.strong["style"]
    assert "font-weight: 600" in soup.p.b["style"]
    assert soup.find("strong", string="Explicit")["style"] == "font-weight: 800"
    assert "font-weight:700" in soup.td["style"]
    assert "font-weight: 700" in soup.td.strong["style"]


def test_emphasis_inherits_bold_ancestor_written_in_any_case_or_important():
    html = ('<p><span style="font-weight: BOLD"><strong>upper</strong></span></p>'
            '<p><span style="font-weight:800 !important"><b>important</b></span></p>')
    soup = BeautifulSoup(decorate_notes_html(html), "html.parser")
    assert "font-weight: 700" in soup.find("strong", string="upper")["style"]
    assert "font-weight: 800" in soup.find("b", string="important")["style"]


def test_emphasis_inherits_a_bold_weight_between_round_values():
    soup = BeautifulSoup(decorate_notes_html(
        '<p style="font-weight: 650"><strong>Title</strong></p>'), "html.parser")
    assert "font-weight: 650" in soup.p.strong["style"]


def test_prose_and_table_boundaries_have_native_blank_paragraphs():
    html = ("<h3>Note</h3><p>First.</p><p>Second.</p>"
            "<table><tr><td><p>Cell.</p></td></tr></table><p>After.</p>")
    soup = BeautifulSoup(decorate_notes_html(html), "html.parser")
    blocks = [child for child in soup.div.children if getattr(child, "name", None)]
    assert [block.name for block in blocks] == [
        "h3", "p", "p", "p", "p", "table", "p", "p",
    ]
    spacers = soup.select('p[data-mtool-spacer="1"]')
    assert len(spacers) == 3
    assert all(spacer.get_text() == "\xa0" for spacer in spacers)
    assert not soup.table.select('p[data-mtool-spacer="1"]')


def test_nested_source_headings_indent_their_body_for_mtool():
    html = ("<h3>3. Estimates</h3><p>Introduction.</p>"
            "<h4>(a) Judgements</h4><p>First section.</p>"
            "<h4>(b) Uncertainty</h4><p>Second section.</p>")
    soup = BeautifulSoup(decorate_notes_html(html), "html.parser")
    headings = soup.find_all(["h3", "h4"])
    assert "margin-left" not in headings[0].get("style", "")
    assert "margin-left" not in soup.find("p", string="Introduction.").get("style", "")
    assert all("margin-left: 2em" in h.get("style", "") for h in headings[1:])
    for text in ("First section.", "Second section."):
        assert "margin-left: 2em" in soup.find("p", string=text).get("style", "")


def test_adjacent_same_level_subnote_heading_and_body_indent_for_mtool():
    html = ("<h3>2 Accounting policies</h3><h3>2.10 Employee benefits</h3>"
            "<p>Short term benefits.</p><h3>3 Estimates</h3><p>Judgements.</p>")
    soup = BeautifulSoup(decorate_notes_html(html), "html.parser")
    assert "margin-left: 2em" in soup.find("h3", string="2.10 Employee benefits")["style"]
    assert "margin-left: 2em" in soup.find("p", string="Short term benefits.")["style"]
    assert "margin-left" not in soup.find("h3", string="3 Estimates")["style"]
    assert "margin-left" not in soup.find("p", string="Judgements.")["style"]


def test_adjacent_top_level_notes_remain_aligned_for_mtool():
    html = ("<h3>2 Accounting policies</h3><h3>3 Estimates</h3>"
            "<p>Judgements.</p>")
    soup = BeautifulSoup(decorate_notes_html(html), "html.parser")
    assert "margin-left" not in soup.find("h3", string="3 Estimates")["style"]
    assert "margin-left" not in soup.find("p", string="Judgements.")["style"]


# --- table decoration -------------------------------------------------------
def test_table_gets_borders_font_and_legacy_attrs():
    out = decorate_notes_html(
        "<table><tbody><tr><td>Land</td><td>1,595</td></tr></tbody></table>")
    assert re.search(r'<table[^>]*style="[^"]*border-collapse: collapse', out)
    assert re.search(r'<table[^>]*border="1"', out)
    assert re.search(r'<table[^>]*cellpadding="4"', out)
    assert re.search(r'<td[^>]*style="[^"]*border: 0.75px solid', out)
    assert re.search(r'<td[^>]*style="[^"]*padding: 4px 8px', out)
    # Font is HOISTED to the table (inheritable) rather than repeated on every
    # cell — the Step-3 size hoist. Cells no longer carry font-family.
    assert re.search(r'<table[^>]*style="[^"]*font-family: Arial[^"]*font-size: 10pt', out)
    assert not re.search(r'<td[^>]*style="[^"]*font-family', out)


def test_header_cells_get_fill_and_bold():
    out = decorate_notes_html(
        "<table><thead><tr><th>Item</th><th>2024</th></tr></thead></table>")
    assert re.search(r'<th[^>]*style="[^"]*background: #f3f4f6', out)
    assert re.search(r'<th[^>]*style="[^"]*font-weight: 600', out)


def test_numeric_columns_right_align_label_column_left():
    out = decorate_notes_html(
        "<table><tbody>"
        "<tr><td>Total</td><td>(95)</td><td>-</td><td>1,125</td></tr>"
        "</tbody></table>")
    assert re.search(r'<td[^>]*style="[^"]*text-align: left[^"]*"[^>]*>Total<', out)
    assert re.search(r'<td[^>]*style="[^"]*text-align: right[^"]*"[^>]*>\(95\)<', out)
    assert re.search(r'<td[^>]*style="[^"]*text-align: right[^"]*"[^>]*>-<', out)
    assert re.search(r'<td[^>]*style="[^"]*text-align: right[^"]*"[^>]*>1,125<', out)


# --- persisted (WYSIWYG) styles win -----------------------------------------
def test_persisted_cell_style_wins_over_decorator_defaults():
    # A user-applied cell colour + border must survive; the decorator only adds
    # what the cell does not already control (family-aware for border).
    out = decorate_notes_html(
        '<table><tbody><tr>'
        '<td style="color: red; border: 2px solid #000">x</td>'
        '</tr></tbody></table>')
    assert "color: red" in out
    assert "2px solid #000" in out
    # decorator's own 0.75px border must NOT be appended (cell owns the family)
    assert "0.75px solid #999" not in out


# --- hidden-border → white translation (mTool TX accommodation) -------------
def test_formatter_cleared_border_becomes_white_not_hidden():
    # The AI formatter clears a border with per-side `1px hidden #000000`
    # (format_patch clear_border). mTool's TX renderer draws hidden as a grey
    # line, so the decorator substitutes an invisible white border.
    cleared = ("border-top: 1px hidden #000000; "
               "border-right: 1px hidden #000000; "
               "border-bottom: 1px hidden #000000; "
               "border-left: 1px hidden #000000")
    out = decorate_notes_html(
        f'<table><tbody><tr><td style="{cleared}">x</td></tr></tbody></table>')
    assert "hidden" not in out
    assert out.lower().count("0.75px solid #ffffff") == 1
    assert "border: 0.75px solid #ffffff" in out.lower()


def test_border_none_becomes_white():
    out = decorate_notes_html(
        '<table><tbody><tr>'
        '<td style="border: none">x</td>'
        '</tr></tbody></table>')
    assert "border: none" not in out
    assert "0.75px solid #ffffff" in out.lower()


def test_default_grey_grid_is_not_whited_out():
    # An unformatted table keeps the decorator's default grey grid — the
    # white-out only touches borders explicitly set to hidden/none.
    out = decorate_notes_html(
        "<table><tbody><tr><td>x</td></tr></tbody></table>")
    assert "0.75px solid #999" in out
    assert "0.75px solid #ffffff" not in out.lower()


def test_real_border_is_preserved_not_whited_out():
    out = decorate_notes_html(
        '<table><tbody><tr>'
        '<td style="border-bottom: 2.5px solid #000000">x</td>'
        '</tr></tbody></table>')
    assert "2.5px solid #000000" in out
    assert "0.75px solid #ffffff" not in out.lower()


def test_grouped_border_style_hidden_becomes_white():
    # Chrome collapses uniform per-side hidden borders into the grouped
    # `border-style: hidden` longhand (gotcha #16). It must still white out —
    # the shorthand-only version missed this and left a grey TX line.
    out = decorate_notes_html(
        '<table><tbody><tr>'
        '<td style="border-width: 1px; border-style: hidden; border-color: #000000">x</td>'
        '</tr></tbody></table>')
    assert "hidden" not in out
    assert out.lower().count("0.75px solid #ffffff") == 1
    assert "border: 0.75px solid #ffffff" in out.lower()


def test_mixed_grouped_border_style_whites_only_hidden_sides():
    # A partly-erased grid: top/bottom solid, right/left hidden. Only the
    # hidden sides go white; the visible rules are preserved.
    out = decorate_notes_html(
        '<table><tbody><tr>'
        '<td style="border-width: 1px; border-style: solid hidden solid hidden; '
        'border-color: #000000">x</td>'
        '</tr></tbody></table>')
    assert "hidden" not in out
    assert "border-top: 1px solid #000000" in out
    assert "border-bottom: 1px solid #000000" in out
    assert out.lower().count("0.75px solid #ffffff") == 2


def test_border_collapse_survives_whiteout():
    # border-collapse / border-radius are NOT border-LINE props — they must
    # never be dropped by the white-out even when a cell has a hidden border.
    out = decorate_notes_html(
        '<table style="border-collapse: collapse"><tbody><tr>'
        '<td style="border: none; border-radius: 4px">x</td>'
        '</tr></tbody></table>')
    assert "border-collapse: collapse" in out
    assert "border-radius: 4px" in out
    assert "0.75px solid #ffffff" in out.lower()


# --- options ----------------------------------------------------------------
def test_no_border_option_paints_white_grid_and_keeps_padding():
    """Run-76: mTool's TX renderer draws its default grey grid on UNDECLARED
    cell boundaries — in that renderer there is no "no line", only visible or
    white. So "none" must be spelled out as explicit white per cell, the same
    accommodation _whiteout_hidden_borders makes for erased borders."""
    out = decorate_notes_html(
        "<table><tbody><tr><td>x</td></tr></tbody></table>",
        NotesTableStyle(border_style="none"))
    assert not re.search(r'<table[^>]*border="1"', out)
    assert "border: 0.75px solid #ffffff" in out       # explicit white, not silence
    assert "border: 0.75px solid #999" not in out      # and no visible grid
    assert re.search(r'<td[^>]*style="[^"]*padding: 4px 8px', out)


def test_lite_tier_keeps_formatting_drops_cosmetics():
    html = "<table><tbody><tr><td>x</td><td>1,234</td></tr></tbody></table>"
    full = decorate_notes_html(html)
    lite = decorate_notes_html(html, lite=True)
    # lite keeps the formatting a reader notices...
    assert "border: 0.75px solid" in lite
    assert "text-align: right" in lite
    assert "font-family: Arial" in lite
    # ...but drops the cosmetic-only props, so it is strictly smaller.
    assert "vertical-align: top" not in lite
    assert "overflow-wrap" not in lite
    assert "word-break" not in lite
    assert len(lite) < len(full)


def test_inheritable_props_hoisted_to_table_not_repeated_per_cell():
    """Step-3 size hoist (docs/PLAN-word-formatting-fidelity.md): font +
    text-wrapping are declared ONCE on the table (they inherit) rather than on
    every cell, so a big table's per-cell styling stays under Excel's cell
    limit. Cells keep only the non-inheritable props (border/padding/align/
    vertical-align)."""
    html = ("<table><tbody>"
            + "".join("<tr><td>Item</td><td>1,234</td></tr>" for _ in range(3))
            + "</tbody></table>")
    out = decorate_notes_html(html)
    # font + wrap live on the table, once
    assert re.search(r'<table[^>]*style="[^"]*font-family: Arial', out)
    assert re.search(r'<table[^>]*style="[^"]*overflow-wrap: break-word', out)
    # ...and NOT on any cell
    assert not re.search(r'<td[^>]*style="[^"]*font-family', out)
    assert not re.search(r'<td[^>]*style="[^"]*overflow-wrap', out)
    # cells keep the non-inheritable props
    assert re.search(r'<td[^>]*style="[^"]*vertical-align: top', out)
    assert re.search(r'<td[^>]*style="[^"]*border: 0.75px solid', out)


def test_size_hoist_lets_a_previously_flat_table_fit_full():
    """Concrete run-66 win: a realistic 40-row, 6-col disclosure table that
    landed FLAT under the old per-cell styling now fits FULL under Excel's
    32,767-char cell limit."""
    from app.notes.render.fit import wrap_footnote_html, EXCEL_CELL_CHAR_LIMIT
    header = "<tr>" + "".join(f"<th>Col{c}</th>" for c in range(6)) + "</tr>"
    body = "".join(
        "<tr><td>Property, plant and equipment item</td>"
        + "".join("<td>1,234,567</td>" for _ in range(5)) + "</tr>"
        for _ in range(40))
    html = f"<p><strong>4. PPE</strong></p><table>{header}{body}</table>"
    full = wrap_footnote_html(decorate_notes_html(html))
    assert len(full) <= EXCEL_CELL_CHAR_LIMIT


def test_decorator_does_not_double_pad_a_source_padded_cell():
    """Phase 4: a cell carrying agent-mirrored padding keeps ITS padding — the
    decorator must not append its own on top (which would both look wrong and
    re-inflate the mTool payload the Step-3 hoist slimmed)."""
    out = decorate_notes_html(
        '<table><tr><td style="padding: 2px 3px">x</td></tr></table>')
    assert "padding: 2px 3px" in out
    assert "padding: 4px 8px" not in out   # decorator default suppressed
    # exactly one CSS padding declaration (the cell's own); the table's
    # `cellpadding=` attribute is not a CSS declaration.
    assert out.count("padding:") == 1


def test_empty_html_passthrough():
    assert decorate_notes_html("") == ""


