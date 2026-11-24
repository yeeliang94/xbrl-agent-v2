"""A report's short fields into a closed mTool workbook, without Excel (step 10g).

Copied from v1 `offline_fill.fill_report_fields`. A report's short fields are
text, a date or a choice. The caller names every cell and the encoding:
`text` goes in as an inline string, `date_serial` as the Excel day number,
`blank` empties the cell (a field a person cleared). The same refusals as
numbers: never a formula cell, never a locked cell. Every write is read back.

Like `offline_fill.py`, whose readers and patch helpers it uses, it imports
only the standard library, so the two files travel to the mTool machine
together and run there on any Python 3.9 or later with nothing installed.
"""
from __future__ import annotations

import re
from decimal import Decimal

try:   # inside the app
    from app.workbook.offline_fill import (
        _XML_ILLEGAL_RE, EXCEL_CELL_CHAR_LIMIT, PrefixedSheetError, _attr, _check_sheet_data, _find_cell,
        _xml_escape, format_value, get_shared_strings, get_sheet_paths, is_locked_input, load_workbook_entries,
        patch_cell_in_sheet, protected_input_cells, read_sheet_cells, split_ref, write_patched_zip)
except ImportError:   # beside offline_fill.py on the mTool machine
    from offline_fill import (  # type: ignore[no-redef]
        _XML_ILLEGAL_RE, EXCEL_CELL_CHAR_LIMIT, PrefixedSheetError, _attr, _check_sheet_data, _find_cell,
        _xml_escape, format_value, get_shared_strings, get_sheet_paths, is_locked_input, load_workbook_entries,
        patch_cell_in_sheet, protected_input_cells, read_sheet_cells, split_ref, write_patched_zip)


def _report_cell(addr: str, style, kind: str, value) -> str:
    s_part = f' s="{style}"' if style is not None else ""
    if kind == "blank":
        return f'<c r="{addr}"{s_part}/>'
    if kind == "date_serial":
        return f'<c r="{addr}"{s_part}><v>{format_value(value)}</v></c>'
    return (f'<c r="{addr}"{s_part} t="inlineStr"><is><t xml:space="preserve">{_xml_escape(value)}</t></is>'
            "</c>")


def fill_report_fields(workbook_path: str, doc: dict, output_path: str) -> dict:
    """Write `doc["writes"]` ({"sheet", "cell", "kind", "value"}) into a copy and read each back.
    Extra keys on a write are carried into the report."""
    _, data, _ = load_workbook_entries(workbook_path)
    sheet_paths = get_sheet_paths(data)
    protection = protected_input_cells(data, sheet_paths)
    report = {"written": [], "skipped_formula": [], "locked": [], "mismatches": [], "errors": []}
    patched: dict = {}
    targets = set()
    for w in doc.get("writes", []):
        sheet, addr, kind, value = w["sheet"], str(w["cell"]).upper(), w["kind"], w.get("value")
        entry = sheet_paths.get(sheet)
        if entry is None or (sheet, addr) in targets:
            report["errors"].append({**w, "error": f"sheet {sheet!r} not found" if entry is None
                                     else f"duplicate write to {sheet}!{addr}"})
            continue
        targets.add((sheet, addr))
        if is_locked_input(protection, sheet, addr):
            report["locked"].append(w)
            continue
        try:
            if kind not in ("text", "date_serial", "blank") or (
                    kind == "text" and (not isinstance(value, str) or len(value) > EXCEL_CELL_CHAR_LIMIT)):
                raise ValueError("a report field is bounded text, a date serial or a blank")
            xml = patched.get(entry) or data[entry].decode("utf-8")
            _check_sheet_data(xml)
            cell_m = _find_cell(xml, addr)
            if cell_m and re.search(r"<f[ >/]", cell_m.group(0)):
                report["skipped_formula"].append(w)
                continue
            if cell_m:
                style = _attr(re.match(r"<c\b[^>]*?/?>", cell_m.group(0)).group(0), "s")
                xml = xml[:cell_m.start()] + _report_cell(addr, style, kind, value) + xml[cell_m.end():]
            elif kind != "blank":
                xml, _ = patch_cell_in_sheet(xml, addr, "0")
                cell_m = _find_cell(xml, addr)
                xml = xml[:cell_m.start()] + _report_cell(addr, None, kind, value) + xml[cell_m.end():]
        except (PrefixedSheetError, ValueError) as exc:
            report["errors"].append({**w, "error": str(exc)})
            continue
        patched[entry] = xml
        report["written"].append(w)
    write_patched_zip(workbook_path, output_path, {p: x.encode("utf-8") for p, x in patched.items()})
    _, after, _ = load_workbook_entries(output_path)
    sst, after_paths = get_shared_strings(after), get_sheet_paths(after)
    cells = {}
    for w in report["written"]:
        sheet = w["sheet"]
        if sheet not in cells:
            cells[sheet] = read_sheet_cells(after[after_paths[sheet]], sst)
        col, row = split_ref(str(w["cell"]).upper())
        kind, found = cells[sheet].get(row, {}).get(col, ("E", ""))
        if w["kind"] == "blank":
            ok = kind == "E"
        elif w["kind"] == "date_serial":
            ok = kind == "N" and Decimal(found or "NaN") == Decimal(format_value(w["value"]))
        else:
            ok = kind == "S" and found == _XML_ILLEGAL_RE.sub("", w["value"])
        if not ok:
            report["mismatches"].append({**w, "found": found})
    report["status"] = "degraded" if any(report[k] for k in ("skipped_formula", "locked", "mismatches",
                                                             "errors")) else "ok"
    return report
