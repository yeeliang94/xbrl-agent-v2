"""The patcher's note store: notes into mTool's hidden +FootnoteTexts sheet.

Copied from v1 `tests/test_mtool_offline_fill.py` (the footnote writing
tests) for what v2 kept. A slot is named by its fn_ key or its visible cell;
v1's label matching is gone. The workbooks are hand-built so they carry a real
shared-strings table, as mTool's do.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
import zipfile

import pytest

from app.workbook.offline_fill import (EXCEL_CELL_CHAR_LIMIT, _detect_duplicate_fn_keys, _verify_footnotes,
                                       _xml_escape, append_shared_string, fill_footnotes, get_defined_names,
                                       get_shared_strings, get_sheet_paths, load_workbook_entries, main,
                                       read_footnote_rows, read_note_payloads, read_sheet_cells,
                                       replace_shared_string, validate_notes_input, wrap_footnote_html)

_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PPE_HTML = ("<h3>Property, plant and equipment</h3><p>Depreciated on a straight-line basis.</p>"
            "<table><tr><td>Total &amp; net</td><td>9,340</td></tr></table>")


def _esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ws(rows, dimension=None):
    """A worksheet from {row: [(column, shared-string index or None)]}."""
    body = "".join(f'<row r="{r}">' + "".join(f'<c r="{c}{r}"/>' if i is None else f'<c r="{c}{r}" t="s"><v>{i}</v></c>'
                                              for c, i in rows[r]) + "</row>" for r in sorted(rows))
    dim = f'<dimension ref="{dimension}"/>' if dimension else ""
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{_NS_MAIN}">{dim}<sheetData>{body}</sheetData></worksheet>'


def _write_fn_workbook(tmp_path, name, strings, sheets, defined_names):
    sst = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><sst xmlns="{_NS_MAIN}" count="{len(strings)}" '
           f'uniqueCount="{len(strings)}">' + "".join(f'<si><t xml:space="preserve">{_esc(s)}</t></si>' for s in strings)
           + "</sst>")
    workbook = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{_NS_MAIN}" xmlns:r="{_NS_R}">'
                "<sheets>" + "".join(f'<sheet name="{n}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, (n, _) in enumerate(sheets))
                + "</sheets><definedNames>" + "".join(defined_names) + "</definedNames></workbook>")
    pkg, doc = "http://schemas.openxmlformats.org/package/2006", "http://schemas.openxmlformats.org/officeDocument/2006"
    rels = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{pkg}/relationships">'
            + "".join(f'<Relationship Id="rId{i + 1}" Type="{doc}/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
                      for i in range(len(sheets)))
            + f'<Relationship Id="rId{len(sheets) + 1}" Type="{doc}/relationships/sharedStrings" Target="sharedStrings.xml"/>'
            "</Relationships>")
    types = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="{pkg}/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/></Types>')
    root = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{pkg}/relationships">'
            f'<Relationship Id="rId1" Type="{doc}/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", root)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/sharedStrings.xml", sst)
        for i, (_, xml) in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", xml)
    return str(path)


_FN_STRINGS = ["Property, plant and equipment", "[Text block added]", "Inventories", "Corporate information",
               "fn_14", "Notes-Listofnotes", "<html><body><p>Existing PPE note</p></body></html>", "fn_20", "fn_99",
               "<html><body><p>orphan</p></body></html>", "Deferred taxation"]


@pytest.fixture
def footnote_template(tmp_path):
    """mTool's text-block storage: visible cells backed by fn_ names pointing at +FootnoteTexts rows."""
    return _write_fn_workbook(tmp_path, "mtool_notes.xlsx", _FN_STRINGS, [
        ("Notes-Listofnotes", _ws({132: [("D", 0), ("E", 1)], 140: [("D", 2), ("E", 1)]})),
        ("Notes-CI", _ws({14: [("D", 3)], 20: [("D", 10)]})),
        ("+FootnoteTexts", _ws({14: [("A", 4), ("B", 5), ("C", 6)], 15: [("A", 7), ("B", 5), ("C", None)],
                                16: [("A", 8), ("B", 5), ("C", 9)]}, dimension="A1:G16"))],
        ["<definedName name=\"fn_14\">'Notes-Listofnotes'!$E$132</definedName>",
         "<definedName name=\"fn_20\">'Notes-Listofnotes'!$E$140</definedName>"])


@pytest.fixture
def orphan_pool_template(tmp_path):
    """Free pre-provisioned rows (fn_5, fn_6) with no defined name. fn_5's payload shares the "" string with F10."""
    strings = ["Corporate information", "[Text block added]", "Accrued expenses", "Capital management", "fn_1",
               "Notes-Listofnotes", "<html><body><p>existing CI note</p></body></html>", "fn_5", "fn_6", "",
               "Deferred taxation"]
    return _write_fn_workbook(tmp_path, "orphan_pool.xlsx", strings, [
        ("Notes-Listofnotes", _ws({9: [("D", 0), ("E", 1)], 10: [("D", 2), ("F", 9)], 11: [("D", 3)],
                                   12: [("D", 10)]})),
        ("+FootnoteTexts", _ws({1: [("A", 4), ("B", 5), ("C", 6)], 5: [("A", 7), ("B", 5), ("C", 9)],
                                6: [("A", 8), ("B", 5), ("C", None)]}, dimension="A1:G6"))],
        ["<definedName name=\"fn_1\">'Notes-Listofnotes'!$E$9</definedName>"])


def _payload_of(path, key):
    _, data, _ = load_workbook_entries(path)
    return read_footnote_rows(data, get_sheet_paths(data), get_shared_strings(data))[key]["payload_text"]


def _visible_cell(path, sheet, addr):
    _, data, _ = load_workbook_entries(path)
    rows = read_sheet_cells(data[get_sheet_paths(data)[sheet]], get_shared_strings(data))
    return rows.get(int(addr[1:]), {}).get(addr[0])


def _assert_sst_consistent(path):
    with zipfile.ZipFile(path) as z:
        sst = z.read("xl/sharedStrings.xml").decode()
        refs = sum(len(re.findall(r'<c\b[^>]*?\bt="s"', z.read(n).decode())) for n in z.namelist()
                   if n.startswith("xl/worksheets/"))
    header = re.search(r"<sst\b[^>]*>", sst).group(0)
    assert int(re.search(r'\buniqueCount="(\d+)"', header).group(1)) == len(re.findall(r"<si\b", sst))
    assert int(re.search(r'\bcount="(\d+)"', header).group(1)) == refs


def test_illegal_xml_characters_are_dropped_and_markup_escaped():
    escaped = _xml_escape("Lease\x00 note\x0b<b>&</b>\x0c end\x1f\tOK\nline")
    assert not any(bad in escaped for bad in ("\x00", "\x0b", "\x0c", "\x1f"))
    assert "\t" in escaped and "\n" in escaped and "&amp;" in escaped and "&lt;b&gt;" in escaped
    ET.fromstring(f'<t xml:space="preserve">{escaped}</t>')


def test_the_note_is_wrapped_in_mtools_text_block_shell():
    out = wrap_footnote_html("<p>x</p>")
    assert "TX27_HTM 27.0.700.500" in out and 'xmlns="http://www.w3.org/1999/xhtml"' in out
    assert "<p>x</p>" in out and "_x000D_" in out


def test_a_filled_payload_is_replaced_in_place_and_nothing_else_changes(tmp_path, footnote_template):
    out = tmp_path / "filled.xlsx"
    report = fill_footnotes(footnote_template, {"footnotes": [{"key": "fn_14", "html": PPE_HTML}]}, str(out))
    assert report["status"] == "ok", report
    assert report["footnotes_written"][0]["action"] == "shared_string_replaced"
    payload = _payload_of(str(out), "fn_14")
    assert "TX27_HTM" in payload and "Total &amp; net" in payload and "Existing PPE note" not in payload
    with zipfile.ZipFile(footnote_template) as zin, zipfile.ZipFile(out) as zout:
        assert {n for n in zin.namelist() if zin.read(n) != zout.read(n)} == {"xl/sharedStrings.xml"}


def test_an_empty_payload_gets_a_new_string_and_the_counts_stay_right(tmp_path, footnote_template):
    out = tmp_path / "filled.xlsx"
    report = fill_footnotes(footnote_template, {"footnotes": [{"key": "fn_20", "html": "<p>Inventories</p>"}]},
                            str(out))
    assert report["status"] == "ok", report
    assert report["footnotes_written"][0]["action"] == "shared_string_appended"
    assert "Inventories" in _payload_of(str(out), "fn_20")
    _assert_sst_consistent(str(out))


def test_a_note_over_excels_limit_is_skipped_never_cut(tmp_path, footnote_template):
    out = tmp_path / "filled.xlsx"
    huge = "<p>" + "x" * (EXCEL_CELL_CHAR_LIMIT + 5000) + "</p>"
    report = fill_footnotes(footnote_template, {"footnotes": [{"key": "fn_14", "html": huge}]}, str(out))
    assert report["status"] == "degraded" and report["footnotes_written"] == []
    assert report["unresolved"][0]["reason"] == "oversize"
    assert "x" * 100 not in _payload_of(str(out), "fn_14")
    exact = "y" * (EXCEL_CELL_CHAR_LIMIT - len(wrap_footnote_html("")))
    report = fill_footnotes(footnote_template, {"footnotes": [{"key": "fn_14", "html": exact}]},
                            str(tmp_path / "exact.xlsx"))
    assert report["status"] == "ok"


def test_a_visible_cell_finds_its_slot_and_without_one_needs_creating(tmp_path, footnote_template):
    report = fill_footnotes(footnote_template, {"footnotes": [{"sheet": "Notes-Listofnotes", "cell": "E132",
                                                               "html": PPE_HTML}]}, str(tmp_path / "a.xlsx"))
    assert report["footnotes_written"][0]["key"] == "fn_14"
    report = fill_footnotes(footnote_template, {"footnotes": [{"sheet": "Notes-CI", "cell": "E14", "html": "<p>x</p>"}]},
                            str(tmp_path / "b.xlsx"), create_missing=False)
    assert report["status"] == "degraded" and report["unresolved"][0]["reason"] == "no_slot"


def test_a_new_slot_is_created_in_mtools_shape(tmp_path, footnote_template):
    out = tmp_path / "filled.xlsx"
    report = fill_footnotes(footnote_template, {"footnotes": [
        {"sheet": "Notes-CI", "cell": "E14", "html": "<p>AAA</p>"},
        {"sheet": "Notes-CI", "cell": "E20", "html": "<p>BBB</p>"}]}, str(out))
    assert report["status"] == "ok", report
    created = report["footnotes_created"]
    assert [c["key"] for c in created] == ["fn_100", "fn_101"]   # past every key in use, fn_99 included
    assert len({c["hidden_cell"] for c in created}) == 2
    _, data, _ = load_workbook_entries(str(out))
    assert get_defined_names(data)["fn_100"] == {"sheet": "Notes-CI", "cell": "E14", "local_sheet_id": "1"}
    assert _visible_cell(str(out), "Notes-CI", "E14") == ("S", "[Text block added]")
    assert "AAA" in _payload_of(str(out), "fn_100") and "BBB" in _payload_of(str(out), "fn_101")
    assert 'ref="A1:G18"' in data[get_sheet_paths(data)["+FootnoteTexts"]].decode()
    assert read_note_payloads(str(out))[("Notes-CI", "E20")] == wrap_footnote_html("<p>BBB</p>")
    assert _detect_duplicate_fn_keys(str(out), "+FootnoteTexts") == []
    _assert_sst_consistent(str(out))


def test_free_pre_provisioned_rows_are_reused_before_new_rows(tmp_path, orphan_pool_template):
    out = tmp_path / "filled.xlsx"
    report = fill_footnotes(orphan_pool_template, {"footnotes": [
        {"sheet": "Notes-Listofnotes", "cell": f"E{r}", "html": f"<p>body {r}</p>"} for r in (10, 11, 12)]}, str(out))
    assert report["status"] == "ok", report
    created = report["footnotes_created"]
    assert [c["key"] for c in created] == ["fn_5", "fn_6", "fn_7"]
    assert [c["slot_source"] for c in created] == ["orphan_reused", "orphan_reused", "row_appended"]
    assert _visible_cell(str(out), "Notes-Listofnotes", "F10") == ("S", "")   # the shared "" was not rewritten
    assert _detect_duplicate_fn_keys(str(out), "+FootnoteTexts") == []
    _assert_sst_consistent(str(out))
    again = fill_footnotes(str(out), {"footnotes": [{"sheet": "Notes-Listofnotes", "cell": "E10",
                                                     "html": "<p>v2</p>"}]}, str(tmp_path / "again.xlsx"))
    assert again["footnotes_created"] == [] and again["footnotes_written"][0]["action"] == "shared_string_replaced"


def test_duplicate_note_keys_already_in_a_workbook_are_reported(tmp_path):
    strings = ["Corporate information", "[Text block added]", "fn_1", "Notes-Listofnotes", "<p>old</p>"]
    path = _write_fn_workbook(tmp_path, "dup.xlsx", strings, [
        ("Notes-Listofnotes", _ws({9: [("D", 0), ("E", 1)]})),
        ("+FootnoteTexts", _ws({1: [("A", 2), ("B", 3), ("C", None)], 7: [("A", 2), ("B", 3), ("C", 4)]}))],
        ["<definedName name=\"fn_1\">'Notes-Listofnotes'!$E$9</definedName>"])
    report = fill_footnotes(path, {"footnotes": [{"sheet": "Notes-Listofnotes", "cell": "E9", "html": "<p>n</p>"}]},
                            str(tmp_path / "filled.xlsx"))
    assert report["status"] == "degraded"
    assert any("duplicate note key fn_1" in e["error"] for e in report["errors"])


def test_read_back_compares_the_whole_note(tmp_path, footnote_template):
    output = str(tmp_path / "doubled.xlsx")
    fragment = "<p>Original complete note.</p>"
    report = fill_footnotes(footnote_template, {"footnotes": [{"key": "fn_14", "html": fragment + fragment}]}, output)
    assert _verify_footnotes(output, "+FootnoteTexts", report["footnotes_written"], {"fn_14": fragment})
    assert _verify_footnotes(output, "+FootnoteTexts", report["footnotes_written"], {"fn_14": fragment + fragment}) == []


def test_note_input_and_the_command_line(tmp_path, footnote_template):
    assert validate_notes_input({"footnotes": []})
    assert validate_notes_input({"footnotes": [{"key": "fn_1"}]})
    assert validate_notes_input({"footnotes": [{"label": "Inventories", "html": "x"}]})
    assert not validate_notes_input({"footnotes": [{"key": "fn_1", "html": "<p>x</p>"}]})
    source, out, report = tmp_path / "notes.json", tmp_path / "filled.xlsx", tmp_path / "report.json"
    source.write_text(json.dumps({"footnotes": [{"key": "fn_14", "html": PPE_HTML}]}), encoding="utf-8")
    assert main(["fill-notes", "--workbook", footnote_template, "--input", str(source), "--output", str(out),
                 "--report", str(report)]) == 0
    assert json.loads(report.read_text())["status"] == "ok"
    with pytest.raises(SystemExit):
        main(["fill-notes", "--workbook", footnote_template, "--input", str(source), "--output", footnote_template])


def test_shared_string_edits():
    sst = '<sst count="2" uniqueCount="2"><si><t>a</t></si><si><t>b</t></si></sst>'
    assert "&lt;p&gt;x &amp; y&lt;/p&gt;" in replace_shared_string(sst, 0, "<p>x & y</p>")
    out, index = append_shared_string(sst, "z")
    assert index == 2 and out.count("<si>") == 3
