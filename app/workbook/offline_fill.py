"""The one patcher: write figures and notes into a closed mTool workbook, without Excel.

Copied from v1 `mtool/offline_fill.py` (commit 4bb9c6bf), the smallest part
v2 uses: the number patch with read-back, the formula and locked-cell
refusals, the note-store fill with its read-back, and the command line.

Why this file is over the 400-line guide: it travels to the Windows machine
that runs mTool as one script and must run there on any Python 3.9 or later
with nothing installed (backend-plan section 4.4). So it imports only the
standard library and nothing from the app, and it repeats the few workbook
readers `app/workbook/xlsx_cells.py` also has. Splitting it would break that.

How it writes. Only the target sheet's XML inside the zip is edited, as
text; every other zip member is copied byte for byte. openpyxl load and save
corrupts an mTool package, and re-serialising the XML breaks its namespaces
(v1, phase 1). The output is written to a temporary file beside it and then
swapped in, and it is never the input file.

What it refuses, always, whatever the caller asks:

- a formula cell (`skipped_formula`),
- a locked cell on a protected sheet (`locked`),
- a value that is not a finite number. Values are written as given: no
  scaling, no sign change.

Every number written is read back from the output file (`mismatches`).

The one exception to the locked-cell refusal is a note's visible text-block
cell, which mTool locks on its protected note sheets. Only mTool's own
"[Text block added]" marker goes there, never a value, because that is how
mTool itself joins a text block to its cell: v1 proved this shape inside
mTool on Windows (5 July 2026), and a note cannot open without it.

Notes go into mTool's note store: the hidden `+FootnoteTexts` sheet holds
each text block's XHTML, joined to its visible cell by an `fn_N` defined
name. A genuine mTool template ships with no text blocks, so a note's slot is
created at the visible cell the caller names, in the shape v1 proved in mTool
on Windows (5 July 2026): a `+FootnoteTexts` row, an `fn_N` name and mTool's
own "[Text block added]" marker in the visible cell. Every note written is
read back whole.

Dropped from v1: finding a cell by its row label (fuzzy or exact) and the
strict mode around it, finding a note by its label, formula reconciliation,
the inspection of note targets and the Windows probes. The caller names
every cell; a cell is never found by label alone. Report fields came back in
step 10g and live beside this file in `report_cells.py`, which uses its
readers and travels with it.

Usage:
    python offline_fill.py inspect --workbook template.xlsx [--sheet NAME]
    python offline_fill.py fill --workbook template.xlsx --input fill.json \\
        --output filled.xlsx [--report report.json] [--force-recalc] [--dry-run]
    python offline_fill.py fill-notes --workbook template.xlsx \\
        --input notes.json --output filled.xlsx [--report report.json]

Input shapes:
    {"writes": [{"sheet": "SOFP-Sub-CuNonCu", "cell": "E25", "value": 2500}]}
    {"footnotes": [{"sheet": "Notes-Listofnotes", "cell": "E52",
                    "html": "<p>...</p>"}]}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from decimal import Decimal

_TEXT_CELL_TYPES = {"s", "str", "inlineStr", "b", "e"}


# ---------------------------------------------------------------- utilities

def col_to_idx(letters: str) -> int:
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


def idx_to_col(idx: int) -> str:
    if idx < 1:
        raise ValueError(f"column index must be >= 1, got {idx}")
    letters = ""
    while idx:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def split_ref(addr: str):
    m = re.fullmatch(r"([A-Z]{1,3})([1-9]\d*)", addr)
    if not m:
        raise ValueError(f"invalid cell reference: {addr!r}")
    return m.group(1), int(m.group(2))


def format_value(value) -> str:
    """The number as the cell's text, exactly as given: never scaled, never re-signed."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"value must be a number, got {value!r}")
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"value must be finite, got {value!r}")
        if value.is_integer():
            return str(int(value))
        # Plain fixed-point, never scientific notation: repr() is the shortest
        # round-trip text, and Decimal expands it to digits.
        return format(Decimal(repr(value)), "f")
    return str(value)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# ---------------------------------------------------------------- zip reading

def load_workbook_entries(path: str):
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        data = {i.filename: zf.read(i.filename) for i in infos}
        comment = zf.comment
    return infos, data, comment


def get_sheet_paths(data: dict) -> dict:
    """Sheet name -> zip member, via workbook.xml and its relationships."""
    wb = ET.fromstring(data["xl/workbook.xml"])
    rels = ET.fromstring(data["xl/_rels/workbook.xml.rels"])
    rid_to_target = {rel.get("Id"): rel.get("Target") for rel in rels if _local(rel.tag) == "Relationship"}
    out = {}
    for el in wb.iter():
        if _local(el.tag) != "sheet":
            continue
        rid = next((v for k, v in el.attrib.items() if _local(k) == "id"), None)
        target = rid_to_target.get(rid)
        if target:
            out[el.get("name")] = target.lstrip("/") if target.startswith("/") else "xl/" + target
    return out


def get_shared_strings(data: dict) -> list:
    raw = data.get("xl/sharedStrings.xml")
    if not raw:
        return []
    return ["".join(t.text or "" for t in si.iter() if _local(t.tag) == "t") for si in ET.fromstring(raw)]


def read_sheet_cells(sheet_xml: bytes, sst: list) -> dict:
    """{row: {column: (kind, text)}}; kinds F formula, S text, N number, E styled empty."""
    root = ET.fromstring(sheet_xml)
    rows = {}
    for row_el in root.iter():
        if _local(row_el.tag) != "row" or row_el.get("r") is None:
            continue
        cells = {}
        for c in row_el:
            if _local(c.tag) != "c" or not c.get("r"):
                continue
            col = split_ref(c.get("r"))[0]
            t = c.get("t")
            parts = {_local(child.tag): child for child in c}
            f_el, v_el, is_el = parts.get("f"), parts.get("v"), parts.get("is")
            if f_el is not None:
                cells[col] = ("F", v_el.text if v_el is not None else "")
            elif t == "s" and v_el is not None:
                try:
                    cells[col] = ("S", sst[int(v_el.text)])
                except (ValueError, TypeError, IndexError):
                    cells[col] = ("S", "")
            elif t == "inlineStr" and is_el is not None:
                cells[col] = ("S", "".join(e.text or "" for e in is_el.iter() if _local(e.tag) == "t"))
            elif t == "str" and v_el is not None:
                cells[col] = ("S", v_el.text or "")
            elif v_el is not None:
                cells[col] = ("N", v_el.text or "")
            else:
                cells[col] = ("E", "")
        rows[int(row_el.get("r"))] = cells
    return rows


# ------------------------------------------------------ note store, reading

_FOOTNOTE_SHEET_HINT = "FootnoteTexts"


def _parse_defined_ref(ref: str):
    """``'Notes-Listofnotes'!$E$132`` -> (sheet, cell); None unless one cell on one sheet."""
    ref = (ref or "").strip()
    if "!" not in ref:
        return None
    sheet_part, cell_part = ref.rsplit("!", 1)
    sheet_part = sheet_part.strip()
    if sheet_part.startswith("'") and sheet_part.endswith("'"):
        sheet_part = sheet_part[1:-1].replace("''", "'")
    cell = cell_part.replace("$", "").strip()
    try:
        split_ref(cell)
    except ValueError:
        return None
    return sheet_part, cell


def get_defined_names(data: dict, prefix: str = "fn_") -> dict:
    """{name: {sheet, cell, local_sheet_id}} for each single-cell defined name with the prefix."""
    wb = ET.fromstring(data["xl/workbook.xml"])
    out = {}
    for el in wb.iter():
        if _local(el.tag) != "definedName":
            continue
        name = el.get("name") or ""
        if prefix and not name.startswith(prefix):
            continue
        parsed = _parse_defined_ref(el.text or "")
        if parsed:
            out[name] = {"sheet": parsed[0], "cell": parsed[1], "local_sheet_id": el.get("localSheetId")}
    return out


def find_footnote_sheet(sheet_paths: dict) -> str | None:
    """The hidden note sheet: ``+FootnoteTexts``, else a sheet named like it."""
    if "+FootnoteTexts" in sheet_paths:
        return "+FootnoteTexts"
    return next((name for name in sheet_paths if _FOOTNOTE_SHEET_HINT in name), None)


def read_footnote_rows(data: dict, sheet_paths: dict, sst: list, footnote_sheet: str | None = None) -> dict:
    """``fn_N`` -> {row, payload_col, payload_text, payload_populated}. Column A
    holds the key; the payload is column C, else the first text cell right of B."""
    footnote_sheet = footnote_sheet or find_footnote_sheet(sheet_paths)
    entry = sheet_paths.get(footnote_sheet) if footnote_sheet else None
    if entry is None:
        return {}
    out = {}
    b_idx = col_to_idx("B")
    for row_num, cells in read_sheet_cells(data[entry], sst).items():
        a = cells.get("A")
        if not a or a[0] != "S" or not a[1].strip():
            continue
        payload_col = payload_text = None
        c_cell = cells.get("C")
        if c_cell and c_cell[0] == "S":
            payload_col, payload_text = "C", c_cell[1]
        else:
            for col in sorted((c for c in cells if col_to_idx(c) > b_idx), key=col_to_idx):
                kind, text = cells[col]
                if kind == "S" and text.strip():
                    payload_col, payload_text = col, text
                    break
        out[a[1].strip()] = {"row": row_num, "payload_col": payload_col, "payload_text": payload_text,
                             "payload_populated": bool(payload_text and payload_text.strip())}
    return out


# ---------------------------------------------------------------- patching

class PrefixedSheetError(Exception):
    """Sheet XML uses a namespace prefix; a text-level insert would corrupt it."""


def _cell_pattern(addr: str):
    # Self-closing and paired cells are two separate alternatives. A shared
    # `[^>]*` before `(?:/>|>.*?</c>)` lets the greedy part eat the `/` of a
    # self-closing cell and then swallow the following cells (v1 recon).
    a = re.escape(addr)
    return re.compile(r'<c\b(?=[^>]*\br="%s")[^>]*/>|<c\b(?=[^>]*\br="%s")[^>]*>.*?</c>' % (a, a), re.DOTALL)


def _find_cell(xml: str, addr: str):
    """The first match of `_cell_pattern(addr)`, found fast. A match needs the
    text r="ADDR" inside its opening tag, and an opening tag holds no "<", so
    the search can start at the last "<c" before that text's first
    appearance: the same match, without testing every cell before it."""
    at = xml.find(f'r="{addr}"')
    if at < 0:
        return None
    return _cell_pattern(addr).search(xml, max(0, xml.rfind("<c", 0, at)))


def _row_pattern(row_num: int):
    return re.compile(r'<row\b(?=[^>]*\br="%d")[^>]*/>|<row\b(?=[^>]*\br="%d")[^>]*>.*?</row>'
                      % (row_num, row_num), re.DOTALL)


def _attr(opening: str, name: str):
    m = re.search(r'\b%s="([^"]*)"' % name, opening)
    return m.group(1) if m else None


def _rebuild_cell(addr: str, style, value_str: str) -> str:
    s_part = f' s="{style}"' if style is not None else ""
    return f'<c r="{addr}"{s_part}><v>{value_str}</v></c>'


def _check_sheet_data(xml: str) -> None:
    if "<sheetData" not in xml:
        if re.search(r"<\w+:sheetData\b", xml):
            raise PrefixedSheetError("sheet XML uses a namespace prefix; refusing to patch")
        raise ValueError("no <sheetData> element found in sheet XML")


def _insert_in_row(row_xml: str, col: str, new_cell: str) -> str:
    if row_xml.endswith("/>"):
        return row_xml[:-2] + f">{new_cell}</row>"
    insert_at = len(row_xml) - len("</row>")
    for m in re.finditer(r'<c\b[^>]*\br="([A-Z]{1,3})\d+"', row_xml):
        if col_to_idx(m.group(1)) > col_to_idx(col):
            insert_at = m.start()
            break
    return row_xml[:insert_at] + new_cell + row_xml[insert_at:]


def patch_cell_in_sheet(xml: str, addr: str, value_str: str):
    """Apply one write. Returns (new_xml, action); action is one of replaced |
    expanded | rebuilt | type_changed | inserted_cell | inserted_row | formula_skipped."""
    _check_sheet_data(xml)
    col, row_num = split_ref(addr)
    cell_m = _find_cell(xml, addr)
    if cell_m:
        cell_xml = cell_m.group(0)
        if re.search(r"<f[ >/]", cell_xml):
            return xml, "formula_skipped"
        opening = re.match(r"<c\b[^>]*?/?>", cell_xml).group(0)
        t, style = _attr(opening, "t"), _attr(opening, "s")
        if t in _TEXT_CELL_TYPES:
            # <v> on a t="s" cell is a shared-string index: rebuild it typeless.
            new_cell, action = _rebuild_cell(addr, style, value_str), "type_changed"
        elif cell_xml.endswith("/>"):
            new_cell, action = cell_xml[:-2] + f"><v>{value_str}</v></c>", "expanded"
        elif re.search(r"<v\b[^>]*>.*?</v>", cell_xml, re.DOTALL):
            new_cell = re.sub(r"<v\b[^>]*>.*?</v>", f"<v>{value_str}</v>", cell_xml, count=1, flags=re.DOTALL)
            action = "replaced"
        else:
            new_cell, action = _rebuild_cell(addr, style, value_str), "rebuilt"
        return xml[:cell_m.start()] + new_cell + xml[cell_m.end():], action

    new_cell = _rebuild_cell(addr, None, value_str)
    row_m = _row_pattern(row_num).search(xml)
    if row_m:
        return xml[:row_m.start()] + _insert_in_row(row_m.group(0), col, new_cell) + xml[row_m.end():], \
            "inserted_cell"
    new_row = f'<row r="{row_num}">{new_cell}</row>'
    for m in re.finditer(r'<row\b[^>]*\br="(\d+)"', xml):
        if int(m.group(1)) > row_num:
            return xml[:m.start()] + new_row + xml[m.start():], "inserted_row"
    close_m = re.search(r"</sheetData>", xml)
    if close_m:
        return xml[:close_m.start()] + new_row + xml[close_m.start():], "inserted_row"
    empty_m = re.search(r"<sheetData\s*/>", xml)
    if not empty_m:
        raise ValueError(f"cannot locate insertion point for {addr}")
    return xml[:empty_m.start()] + f"<sheetData>{new_row}</sheetData>" + xml[empty_m.end():], "inserted_row"


def set_full_calc_on_load(workbook_xml: str):
    """Set fullCalcOnLoad="1" on an existing <calcPr>, so Excel works the totals
    out again on opening. Returns (xml, found). Never adds a <calcPr>."""
    m = re.search(r"<calcPr\b[^>]*/?>", workbook_xml)
    if not m:
        return workbook_xml, False
    tag = m.group(0)
    if 'fullCalcOnLoad="1"' in tag:
        return workbook_xml, True
    if "fullCalcOnLoad" in tag:
        new_tag = re.sub(r'fullCalcOnLoad="[^"]*"', 'fullCalcOnLoad="1"', tag)
    elif tag.endswith("/>"):
        new_tag = tag[:-2] + ' fullCalcOnLoad="1"/>'
    else:
        new_tag = tag[:-1] + ' fullCalcOnLoad="1">'
    return workbook_xml[:m.start()] + new_tag + workbook_xml[m.end():], True


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.exists(b) and os.path.samefile(a, b)
    except OSError:
        return os.path.abspath(a) == os.path.abspath(b)


def write_patched_zip(src_path: str, dst_path: str, replacements: dict):
    """Copy every member in its original order and metadata, with the patched
    bytes swapped in. Written to a temporary file beside `dst_path`, then
    swapped in. Refuses to write over `src_path`."""
    if _same_file(src_path, dst_path):
        raise ValueError("the output must be a new file; the input workbook is never patched in place")
    folder = os.path.dirname(os.path.abspath(dst_path))
    fd, temporary = tempfile.mkstemp(prefix=".fill-", suffix=".tmp", dir=folder)
    os.close(fd)
    try:
        with zipfile.ZipFile(src_path) as zin, zipfile.ZipFile(temporary, "w") as zout:
            zout.comment = zin.comment
            for info in zin.infolist():
                payload = replacements.get(info.filename, zin.read(info.filename))
                ni = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                ni.compress_type = info.compress_type
                ni.external_attr = info.external_attr
                ni.internal_attr = info.internal_attr
                ni.create_system = info.create_system
                # flag_bits is not copied: writestr sets it from the name (mTool names are ASCII).
                zout.writestr(ni, payload)
        with open(temporary, "rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, dst_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def verify_values(path: str, checks: list) -> list:
    """checks: [(sheet member, cell, expected text)] -> the ones the file does not hold."""
    _, data, _ = load_workbook_entries(path)
    mismatches = []
    decoded: dict = {}   # each sheet decoded once
    for entry_path, addr, expected in checks:
        if entry_path not in decoded:
            decoded[entry_path] = data.get(entry_path, b"").decode("utf-8", errors="replace")
        xml = decoded[entry_path]
        m = _find_cell(xml, addr)
        found = None
        if m and not re.search(r"<f[ >/]", m.group(0)):
            v = re.search(r"<v\b[^>]*>(.*?)</v>", m.group(0), re.DOTALL)
            found = v.group(1) if v else None
        try:
            ok = found is not None and Decimal(found) == Decimal(expected)
        except ArithmeticError:
            ok = False
        if not ok:
            mismatches.append({"entry": entry_path, "cell": addr, "expected": expected, "found": found})
    return mismatches


# ---------------------------------------------------------------- protection

def protected_input_cells(data: dict, sheet_paths: dict) -> dict:
    """Each protected sheet's cell, row and column styles, and which styles lock.

    Excel locks a cell by default; a cell, row or column style can unlock it.
    The lock holds only while the sheet is protected."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    styles = ET.fromstring(data.get("xl/styles.xml", b"<styleSheet/>"))
    bases = styles.find("m:cellStyleXfs", ns)
    xfs = styles.find("m:cellXfs", ns)
    locked = []
    for xf in ([] if xfs is None else xfs):
        protection = xf.find("m:protection", ns)
        if protection is None and bases is not None:
            base = int(xf.get("xfId", "0"))
            if base < len(bases):
                protection = bases[base].find("m:protection", ns)
        locked.append(protection is None or protection.get("locked", "1") not in {"0", "false"})
    result = {}
    for sheet, path in sheet_paths.items():
        root = ET.fromstring(data[path])
        protection = root.find("m:sheetProtection", ns)
        if protection is None or protection.get("sheet", "0") not in {"1", "true"}:
            continue
        cells = {c.get("r"): int(c.get("s")) for c in root.findall(".//m:sheetData/m:row/m:c", ns)
                 if c.get("s") is not None}
        rows = {int(r.get("r")): int(r.get("s")) for r in root.findall("m:sheetData/m:row", ns)
                if r.get("s") is not None and r.get("customFormat", "0") in {"1", "true"}}
        cols = [(int(c.get("min")), int(c.get("max")), int(c.get("style", "0")))
                for c in root.findall("m:cols/m:col", ns)]
        result[sheet] = (cells, rows, cols, locked)
    return result


def is_locked_input(protection: dict, sheet: str, addr: str) -> bool:
    if sheet not in protection:
        return False
    cells, rows, cols, locked = protection[sheet]
    match = re.fullmatch(r"([A-Z]+)([0-9]+)", addr)
    if match is None:
        return True
    col, row = col_to_idx(match.group(1)), int(match.group(2))
    style = cells.get(addr, rows.get(row))
    if style is None:
        style = next((s for lo, hi, s in cols if lo <= col <= hi), 0)
    return locked[style] if 0 <= style < len(locked) else True


# ---------------------------------------------------------------- numbers

def validate_input(doc: dict) -> list:
    if not isinstance(doc, dict) or not isinstance(doc.get("writes"), list) or not doc.get("writes"):
        return ["input must be an object with a non-empty 'writes' list"]
    errors = []
    seen = set()
    for i, w in enumerate(doc["writes"]):
        where = f"writes[{i}]"
        if not isinstance(w, dict):
            errors.append(f"{where}: must be an object")
            continue
        if not w.get("sheet"):
            errors.append(f"{where}: missing 'sheet'")
        if "cell" not in w:
            errors.append(f"{where}: missing 'cell'; every write names its cell")
        else:
            try:
                split_ref(str(w["cell"]).upper())
            except ValueError as exc:
                errors.append(f"{where}: {exc}")
            target = (w.get("sheet"), str(w["cell"]).upper())
            if target in seen:
                errors.append(f"{where}: duplicate write to {target}")
            seen.add(target)
        value = w.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{where}: 'value' must be a JSON number, got {value!r}")
    return errors


def fill_workbook(workbook_path: str, doc: dict, output_path: str | None = None, *,
                  force_recalc: bool = False, dry_run: bool = False) -> dict:
    """Write ``doc``'s numbers into a copy of the workbook and read each one back.

    ``doc`` has passed `validate_input`. Extra keys on a write are carried into
    the report untouched. When ``dry_run`` is False, ``output_path`` is needed."""
    _, data, _ = load_workbook_entries(workbook_path)
    sheet_paths = get_sheet_paths(data)
    protection = protected_input_cells(data, sheet_paths)
    report = {"workbook": workbook_path, "output": None if dry_run else output_path, "dry_run": bool(dry_run),
              "written": [], "skipped_formula": [], "locked": [], "type_changed": [], "mismatches": [],
              "errors": [], "force_recalc": None}
    patched_xml: dict = {}
    decoded: dict = {}
    verify_targets = []
    targets = set()
    for i, w in enumerate(doc["writes"]):
        sheet = w["sheet"]
        addr = str(w["cell"]).upper()
        base = {**w, "index": i, "cell": addr}
        entry_path = sheet_paths.get(sheet)
        if entry_path is None:
            report["errors"].append({**base, "error": f"sheet {sheet!r} not found"})
            continue
        if (sheet, addr) in targets:
            report["errors"].append({**base, "error": f"duplicate write to {sheet}!{addr}"})
            continue
        targets.add((sheet, addr))
        if entry_path not in patched_xml and entry_path not in decoded:   # each sheet decoded once
            decoded[entry_path] = data[entry_path].decode("utf-8")
        xml = patched_xml.get(entry_path) or decoded[entry_path]
        try:
            value_str = format_value(w["value"])
            if is_locked_input(protection, sheet, addr):
                # Not written either way: say whether it is a formula (as a patch would) without patching.
                _check_sheet_data(xml)
                split_ref(addr)
                cell_m = _find_cell(xml, addr)
                formula = bool(cell_m and re.search(r"<f[ >/]", cell_m.group(0)))
                base["action"] = "formula_skipped" if formula else "locked"
                report["skipped_formula" if formula else "locked"].append(base)
                continue
            candidate_xml, action = patch_cell_in_sheet(xml, addr, value_str)
        except (PrefixedSheetError, ValueError) as exc:
            report["errors"].append({**base, "error": str(exc)})
            continue
        base["action"] = action
        if action == "formula_skipped":
            report["skipped_formula"].append(base)
            continue
        patched_xml[entry_path] = candidate_xml
        if action == "type_changed":
            report["type_changed"].append(base)
        report["written"].append(base)
        verify_targets.append((entry_path, addr, value_str))

    if force_recalc:
        wb_xml, found = set_full_calc_on_load(data["xl/workbook.xml"].decode("utf-8"))
        report["force_recalc"] = {"requested": True, "calcPr_found": found}
        if found:
            patched_xml["xl/workbook.xml"] = wb_xml
    if not dry_run:
        write_patched_zip(workbook_path, output_path, {p: x.encode("utf-8") for p, x in patched_xml.items()})
        found = {(m["entry"], m["cell"]): m for m in verify_values(output_path, verify_targets)}
        for w in report["written"]:
            miss = found.get((sheet_paths[w["sheet"]], w["cell"]))
            if miss:
                report["mismatches"].append({**w, "found": miss["found"]})
    degraded = any(report[k] for k in ("skipped_formula", "locked", "type_changed", "mismatches", "errors"))
    report["status"] = "degraded" if degraded else "ok"
    return report


# ---------------------------------------------------------------- notes
#
# The note text goes into the hidden +FootnoteTexts sheet as mTool's XHTML
# text-block shell (v1's Windows recon, 5 July 2026). A line break is Excel's
# "_x000D_" token and a newline, as mTool's own files have it.

_FN_BODY_STYLE = "font-family:'Arial';font-size:12pt;background-color:#FFFFFF;text-align:left;"
_FN_CR = "_x000D_\n"

# Excel's cell limit, on the unescaped length of the wrapped text. Longer
# text makes Excel "repair" the file and cut the note. Never cut here
# (cutting XHTML breaks the popup): an over-limit note is skipped and listed.
EXCEL_CELL_CHAR_LIMIT = 32_767

# Characters XML 1.0 cannot hold even escaped. Left in a shared string they
# make Excel repair the file on opening, so they are dropped. Tab, LF, CR stay.
_XML_ILLEGAL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_TEXT_BLOCK_MARKER = "[Text block added]"


def _xml_escape(text: str) -> str:
    # One level of escaping: an HTML entity (&amp;) is stored as &amp;amp; and reads back as &amp;.
    text = _XML_ILLEGAL_RE.sub("", text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wrap_footnote_html(fragment: str) -> str:
    """Wrap an HTML fragment in mTool's TX27 XHTML text-block shell."""
    return ('<?xml version="1.0" ?>' + _FN_CR + '<html xmlns="http://www.w3.org/1999/xhtml">' + _FN_CR
            + "<head>" + _FN_CR + '<meta content="TX27_HTM 27.0.700.500" name="GENERATOR" />' + _FN_CR
            + "<title></title>" + _FN_CR + "</head>" + _FN_CR + '<body style="' + _FN_BODY_STYLE + '">' + _FN_CR
            + fragment + _FN_CR + "</body>" + _FN_CR + "</html>")


_SI_PATTERN = re.compile(r"<si\b[^>]*>.*?</si>|<si\b[^>]*/>", re.DOTALL)
_TS_REF_PATTERN = re.compile(r'<c\b[^>]*?\bt="s"')


def replace_shared_string(sst_xml: str, index: int, raw_text: str) -> str:
    """Replace the index-th <si> in place (a note payload is referenced by one cell)."""
    matches = list(_SI_PATTERN.finditer(sst_xml))
    if not 0 <= index < len(matches):
        raise ValueError(f"shared-string index {index} out of range ({len(matches)} entries)")
    m = matches[index]
    return sst_xml[:m.start()] + '<si><t xml:space="preserve">' + _xml_escape(raw_text) + "</t></si>" \
        + sst_xml[m.end():]


def _set_sst_count_attrs(sst_xml: str, count: int, unique: int) -> str:
    m = re.search(r"<sst\b[^>]*?>", sst_xml)
    if not m:
        return sst_xml
    tag = m.group(0)
    for name, val in (("count", count), ("uniqueCount", unique)):
        if re.search(rf'\b{name}="\d+"', tag):
            tag = re.sub(rf'\b{name}="\d+"', f'{name}="{val}"', tag)
        else:
            tag = tag[:-1].rstrip() + f' {name}="{val}">'
    return sst_xml[:m.start()] + tag + sst_xml[m.end():]


def _finalize_sst_counts(sst_xml: str, sheet_xmls) -> str:
    """`uniqueCount` is the number of <si>; `count` is every t="s" cell across
    the final sheets. Mixing the two makes Excel repair the file (v1, Windows,
    6 July 2026), so both are counted once, from the final XML."""
    unique = sum(1 for _ in _SI_PATTERN.finditer(sst_xml))
    refs = sum(len(_TS_REF_PATTERN.findall(xml)) for xml in sheet_xmls)
    return _set_sst_count_attrs(sst_xml, refs, unique)


def append_shared_string(sst_xml: str, raw_text: str):
    """Append an <si> before </sst>. Returns (new_xml, index). Counts are set by `_finalize_sst_counts`."""
    new_index = sum(1 for _ in _SI_PATTERN.finditer(sst_xml))
    close = re.search(r"</sst>", sst_xml)
    if not close:
        raise ValueError("no </sst> in sharedStrings.xml")
    new_si = '<si><t xml:space="preserve">' + _xml_escape(raw_text) + "</t></si>"
    return sst_xml[:close.start()] + new_si + sst_xml[close.start():], new_index


def _cell_shared_index(sheet_xml: str, addr: str):
    m = _find_cell(sheet_xml, addr)
    if not m:
        return None
    opening = re.match(r"<c\b[^>]*?/?>", m.group(0)).group(0)
    v = re.search(r"<v\b[^>]*>(.*?)</v>", m.group(0), re.DOTALL)
    if _attr(opening, "t") != "s" or not v:
        return None
    try:
        return int(v.group(1))
    except ValueError:
        return None


def patch_shared_cell(sheet_xml: str, addr: str, index: int):
    """Point cell `addr` at shared string `index`, keeping its style. Refuses a formula cell."""
    _check_sheet_data(sheet_xml)
    col, row_num = split_ref(addr)
    cell_m = _find_cell(sheet_xml, addr)
    if cell_m:
        if re.search(r"<f[ >/]", cell_m.group(0)):
            raise ValueError(f"refusing to overwrite formula cell {addr}")
        style = _attr(re.match(r"<c\b[^>]*?/?>", cell_m.group(0)).group(0), "s")
        s_part = f' s="{style}"' if style is not None else ""
        return sheet_xml[:cell_m.start()] + f'<c r="{addr}"{s_part} t="s"><v>{index}</v></c>' \
            + sheet_xml[cell_m.end():]
    row_m = _row_pattern(row_num).search(sheet_xml)
    if not row_m:
        raise ValueError(f"no row {row_num} for cell {addr}")
    new_row = _insert_in_row(row_m.group(0), col, f'<c r="{addr}" t="s"><v>{index}</v></c>')
    return sheet_xml[:row_m.start()] + new_row + sheet_xml[row_m.end():]


def validate_notes_input(doc: dict) -> list:
    items = doc.get("footnotes") if isinstance(doc, dict) else None
    if not isinstance(items, list) or not items:
        return ["input must be an object with a non-empty 'footnotes' list"]
    errors = []
    for i, it in enumerate(items):
        where = f"footnotes[{i}]"
        if not isinstance(it, dict):
            errors.append(f"{where}: must be an object")
            continue
        if not (it.get("key") or (it.get("sheet") and it.get("cell"))):
            errors.append(f"{where}: need 'key', or both 'sheet' and 'cell'")
        if not isinstance(it.get("html"), str) or not it["html"].strip():
            errors.append(f"{where}: 'html' must be a non-empty string")
    return errors


def _sheet_local_index(data: dict, sheet_name: str):
    """The sheet's position in workbook order: a sheet-scoped name's localSheetId."""
    sheets = [el.get("name") for el in ET.fromstring(data["xl/workbook.xml"]).iter() if _local(el.tag) == "sheet"]
    return sheets.index(sheet_name) if sheet_name in sheets else None


def _find_donor_shape(fn_rows: dict, fn_sheet_xml: str) -> dict:
    """The row shape of an existing note row, so a new one looks native; mTool's defaults otherwise."""
    for key in sorted(fn_rows, key=lambda k: fn_rows[k]["row"]):
        row = fn_rows[key]["row"]
        rm = _row_pattern(row).search(fn_sheet_xml)
        if not rm:
            continue
        opentag = re.match(r"<row\b[^>]*?>", rm.group(0)).group(0)
        cm = _find_cell(fn_sheet_xml, f"C{row}")
        pstyle = _attr(re.match(r"<c\b[^>]*?/?>", cm.group(0)).group(0), "s") if cm else None
        return {"spans": _attr(opentag, "spans"), "ht": _attr(opentag, "ht"),
                "custom_height": 'customHeight="1"' in opentag, "payload_style": pstyle}
    return {"spans": "1:7", "ht": "409.5", "custom_height": True, "payload_style": None}


def _ensure_shared_string(sst_xml: str, index_map: dict, text: str):
    if text in index_map:
        return sst_xml, index_map[text]
    sst_xml, idx = append_shared_string(sst_xml, text)
    index_map[text] = idx
    return sst_xml, idx


def _footnote_row_xml(row_num: int, a_idx: int, b_idx: int, p_idx: int, donor: dict) -> str:
    spans = f' spans="{donor["spans"]}"' if donor.get("spans") else ""
    ht = (f' ht="{donor["ht"]}"' + (' customHeight="1"' if donor.get("custom_height") else "")) \
        if donor.get("ht") else ""
    ps = f' s="{donor["payload_style"]}"' if donor.get("payload_style") else ""
    return (f'<row r="{row_num}"{spans}{ht}><c r="A{row_num}" t="s"><v>{a_idx}</v></c>'
            f'<c r="B{row_num}" t="s"><v>{b_idx}</v></c><c r="C{row_num}"{ps} t="s"><v>{p_idx}</v></c></row>')


def _insert_row_ordered(sheet_xml: str, row_num: int, row_xml: str) -> str:
    for m in re.finditer(r'<row\b[^>]*\br="(\d+)"', sheet_xml):
        if int(m.group(1)) > row_num:
            return sheet_xml[:m.start()] + row_xml + sheet_xml[m.start():]
    close = re.search(r"</sheetData>", sheet_xml)
    if close:
        return sheet_xml[:close.start()] + row_xml + sheet_xml[close.start():]
    empty = re.search(r"<sheetData\s*/>", sheet_xml)
    if empty:
        return sheet_xml[:empty.start()] + f"<sheetData>{row_xml}</sheetData>" + sheet_xml[empty.end():]
    raise ValueError("no <sheetData> to insert a note row into")


def _bump_footnote_dimension(sheet_xml: str, row_num: int) -> str:
    m = re.search(r'<dimension ref="([A-Z]+)(\d+):([A-Z]+)(\d+)"', sheet_xml)
    if m:
        if row_num <= int(m.group(4)):
            return sheet_xml
        new = f'<dimension ref="{m.group(1)}{m.group(2)}:{m.group(3)}{row_num}"'
        return sheet_xml[:m.start()] + new + sheet_xml[m.end():]
    single = re.search(r'<dimension ref="A1"\s*/>', sheet_xml)   # an empty sheet
    if single:
        return sheet_xml[:single.start()] + f'<dimension ref="A1:C{row_num}"/>' + sheet_xml[single.end():]
    return sheet_xml


def _add_defined_name(workbook_xml: str, name: str, sheet: str, cell: str, local_index) -> str:
    col, row_num = split_ref(cell)
    ref = _xml_escape(f"'{sheet.replace(chr(39), chr(39) * 2)}'!${col}${row_num}")
    lsid = f' localSheetId="{local_index}"' if local_index is not None else ""
    dn = f'<definedName name="{name}"{lsid}>{ref}</definedName>'
    close = re.search(r"</definedNames>", workbook_xml)
    if close:
        return workbook_xml[:close.start()] + dn + workbook_xml[close.start():]
    sheets = re.search(r"</sheets>", workbook_xml)
    if not sheets:
        raise ValueError("no </sheets> to anchor a <definedNames> block")
    return workbook_xml[:sheets.end()] + f"<definedNames>{dn}</definedNames>" + workbook_xml[sheets.end():]


def _alloc_fn_key(fn_used: set) -> str:
    n = max((int(re.sub(r"\D", "", k) or 0) for k in fn_used), default=0) + 1
    fn_used.add(f"fn_{n}")
    return f"fn_{n}"


def _build_orphan_pool(fn_sheet_cells: dict, defined: dict, fn_rows: dict) -> list:
    """Pre-provisioned free note rows: an fn_N in column A with no defined name
    and no payload. Reusing one is how mTool assigns a text block; minting a key
    that duplicates one leaves the popup empty (v1, 5 July 2026)."""
    pool = []
    b_idx = col_to_idx("B")
    for key in sorted(fn_rows, key=lambda k: int(re.sub(r"\D", "", k) or 0)):
        if key in defined or fn_rows[key]["payload_populated"]:
            continue
        row = fn_rows[key]["row"]
        cells = fn_sheet_cells.get(row, {})
        cand = sorted((c for c in cells if col_to_idx(c) > b_idx), key=col_to_idx)
        b_cell = cells.get("B")
        pool.append({"key": key, "row": row, "payload_col": cand[0] if cand else "C",
                     "sheet": b_cell[1] if b_cell and b_cell[0] == "S" else None})
    return pool


def _take_orphan(pool: list, sheet: str):
    for i, orphan in enumerate(pool):
        if orphan["sheet"] == sheet:
            return pool.pop(i)
    return pool.pop(0) if pool else None


def _create_footnote_slot(st: dict, sheet: str, cell: str, wrapped: str):
    """A new note slot at visible `sheet`!`cell`, holding `wrapped`. Mutates `st`,
    the one allocator, so a batch never reuses a key. Returns (key, payload cell, source)."""
    vis_entry = st["sheet_paths"].get(sheet)
    if vis_entry is None:
        raise ValueError(f"visible sheet {sheet!r} not found")
    orphan = _take_orphan(st["orphan_pool"], sheet)
    if orphan is not None:
        key, row_num, source = orphan["key"], orphan["row"], "orphan_reused"
        payload_addr = f"{orphan['payload_col']}{row_num}"
        # Never replace the empty <si> an orphan points at: other cells may share it.
        st["sst_xml"], p_idx = append_shared_string(st["sst_xml"], wrapped)
        st["fn_sheet_xml"] = patch_shared_cell(st["fn_sheet_xml"], payload_addr, p_idx)
        if orphan["sheet"] != sheet:
            st["sst_xml"], b_idx = _ensure_shared_string(st["sst_xml"], st["sindex"], sheet)
            st["fn_sheet_xml"] = patch_shared_cell(st["fn_sheet_xml"], f"B{row_num}", b_idx)
    else:
        key, row_num, source = _alloc_fn_key(st["fn_used"]), st["next_row"], "row_appended"
        st["next_row"] += 1
        payload_addr = f"C{row_num}"
        st["sst_xml"], a_idx = _ensure_shared_string(st["sst_xml"], st["sindex"], key)
        st["sst_xml"], b_idx = _ensure_shared_string(st["sst_xml"], st["sindex"], sheet)
        st["sst_xml"], p_idx = append_shared_string(st["sst_xml"], wrapped)
        row_xml = _footnote_row_xml(row_num, a_idx, b_idx, p_idx, st["donor"])
        st["fn_sheet_xml"] = _bump_footnote_dimension(_insert_row_ordered(st["fn_sheet_xml"], row_num, row_xml),
                                                      row_num)
    st["sst_xml"], trig_idx = _ensure_shared_string(st["sst_xml"], st["sindex"], _TEXT_BLOCK_MARKER)
    vis_xml = st["visible"].get(vis_entry) or st["data"][vis_entry].decode("utf-8")
    st["visible"][vis_entry] = patch_shared_cell(vis_xml, cell, trig_idx)
    st["workbook_xml"] = _add_defined_name(st["workbook_xml"], key, sheet, cell,
                                           _sheet_local_index(st["data"], sheet))
    return key, payload_addr, source


def _max_row(sheet_xml: str) -> int:
    return max((int(m.group(1)) for m in re.finditer(r'<row\b[^>]*\br="(\d+)"', sheet_xml)), default=0)


def fill_footnotes(workbook_path: str, doc: dict, output_path: str | None = None, *,
                   dry_run: bool = False, create_missing: bool = True) -> dict:
    """Write each note's HTML into the note store and read every one back.

    An item names its slot by `key` (an existing fn_N) or by the visible
    `sheet` and `cell`. A visible cell with no slot gets one when
    `create_missing` is on. Extra keys on an item are carried into the report."""
    _, data, _ = load_workbook_entries(workbook_path)
    sheet_paths = get_sheet_paths(data)
    sst = get_shared_strings(data)
    defined = get_defined_names(data, "fn_")
    footnote_sheet = find_footnote_sheet(sheet_paths)
    report = {"workbook": workbook_path, "output": None if dry_run else output_path, "dry_run": bool(dry_run),
              "footnotes_written": [], "footnotes_created": [], "unresolved": [], "errors": [],
              "footnote_mismatches": []}
    fn_entry = sheet_paths.get(footnote_sheet) if footnote_sheet else None
    if fn_entry is None or "xl/sharedStrings.xml" not in data:
        report["errors"].append({"error": "workbook has no +FootnoteTexts sheet or shared strings"})
        report["status"] = "degraded"
        if not dry_run and output_path:
            write_patched_zip(workbook_path, output_path, {})
        return report

    cell_to_fn = {f"{d['sheet']}!{d['cell']}": k for k, d in defined.items()}
    fn_rows = read_footnote_rows(data, sheet_paths, sst, footnote_sheet)
    fn_sheet_xml = data[fn_entry].decode("utf-8")
    st = {"data": data, "sheet_paths": sheet_paths, "workbook_xml": data["xl/workbook.xml"].decode("utf-8"),
          "fn_sheet_xml": fn_sheet_xml, "sst_xml": data["xl/sharedStrings.xml"].decode("utf-8"),
          "visible": {}, "sindex": {v: i for i, v in reversed(list(enumerate(sst)))},
          "fn_used": set(defined) | set(fn_rows), "next_row": _max_row(fn_sheet_xml) + 1,
          "donor": _find_donor_shape(fn_rows, fn_sheet_xml),
          "orphan_pool": _build_orphan_pool(read_sheet_cells(data[fn_entry], sst), defined, fn_rows)}
    resolved_html = {}
    seen_keys = set()
    for i, it in enumerate(doc["footnotes"]):
        base = {**{k: v for k, v in it.items() if k != "html"}, "index": i}
        wrapped = wrap_footnote_html(it["html"])
        if len(wrapped) > EXCEL_CELL_CHAR_LIMIT:
            report["unresolved"].append({**base, "reason": "oversize", "payload_chars": len(wrapped),
                                         "detail": f"payload is {len(wrapped)} characters, over Excel's "
                                                   f"{EXCEL_CELL_CHAR_LIMIT}-character cell limit"})
            continue
        key = it.get("key")
        if not key:
            cell = str(it["cell"]).upper()
            vis = f"{it['sheet']}!{cell}"
            base["cell"] = cell
            key = cell_to_fn.get(vis)
            if not key and create_missing:
                try:
                    key, payload_addr, source = _create_footnote_slot(st, it["sheet"], cell, wrapped)
                except (ValueError, PrefixedSheetError) as exc:
                    report["errors"].append({**base, "error": str(exc)})
                    continue
                base.update(key=key, hidden_sheet=footnote_sheet, hidden_cell=payload_addr,
                            action="slot_created", slot_source=source)
                cell_to_fn[vis] = key
                seen_keys.add(key)
                resolved_html[key] = it["html"]
                report["footnotes_created"].append(base)
                report["footnotes_written"].append(base)
                continue
            if not key:
                report["unresolved"].append({**base, "reason": "no_slot", "detail": f"no fn_* backs {vis}"})
                continue
        base["key"] = key
        if key in seen_keys:
            report["errors"].append({**base, "error": f"duplicate note write to {key}"})
            continue
        fn = fn_rows.get(key)
        if fn is None:
            report["unresolved"].append({**base, "reason": "no_payload_row",
                                         "detail": f"no {footnote_sheet} row for {key}"})
            continue
        seen_keys.add(key)
        payload_addr = f"{fn['payload_col'] or 'C'}{fn['row']}"
        try:
            existing = _cell_shared_index(st["fn_sheet_xml"], payload_addr)
            # Replace in place only a non-empty payload: an empty one may be shared with other cells.
            if existing is not None and (existing >= len(sst) or sst[existing].strip()):
                st["sst_xml"] = replace_shared_string(st["sst_xml"], existing, wrapped)
                action = "shared_string_replaced"
            else:
                st["sst_xml"], new_index = append_shared_string(st["sst_xml"], wrapped)
                st["fn_sheet_xml"] = patch_shared_cell(st["fn_sheet_xml"], payload_addr, new_index)
                action = "shared_string_appended"
        except (ValueError, PrefixedSheetError) as exc:
            report["errors"].append({**base, "error": str(exc)})
            continue
        base.update(hidden_sheet=footnote_sheet, hidden_cell=payload_addr, action=action)
        resolved_html[key] = it["html"]
        report["footnotes_written"].append(base)

    if not dry_run:
        final_sheets = [st["visible"].get(e) or (st["fn_sheet_xml"] if e == fn_entry else data[e].decode("utf-8"))
                        for e in set(sheet_paths.values())]
        st["sst_xml"] = _finalize_sst_counts(st["sst_xml"], final_sheets)
        replacements = {"xl/sharedStrings.xml": st["sst_xml"].encode("utf-8"),
                        fn_entry: st["fn_sheet_xml"].encode("utf-8")}
        if report["footnotes_created"]:
            replacements["xl/workbook.xml"] = st["workbook_xml"].encode("utf-8")
            replacements.update({e: x.encode("utf-8") for e, x in st["visible"].items()})
        write_patched_zip(workbook_path, output_path, replacements)
        report["footnote_mismatches"] = _verify_footnotes(output_path, footnote_sheet,
                                                          report["footnotes_written"], resolved_html)
        for dup in _detect_duplicate_fn_keys(output_path, footnote_sheet):
            report["errors"].append({"key": dup["key"], "rows": dup["rows"],
                                     "error": f"duplicate note key {dup['key']} on rows {dup['rows']}; mTool "
                                              "reads the first, so its popup would open empty"})
    report["status"] = "degraded" if any(report[k] for k in ("unresolved", "errors", "footnote_mismatches")) \
        else "ok"
    return report


def _detect_duplicate_fn_keys(path: str, footnote_sheet: str) -> list:
    """fn_N keys on more than one note row (a raw scan: `read_footnote_rows` keeps the last)."""
    _, data, _ = load_workbook_entries(path)
    entry = get_sheet_paths(data).get(footnote_sheet) if footnote_sheet else None
    if entry is None:
        return []
    rows_by_key: dict = {}
    for row_num, cells in sorted(read_sheet_cells(data[entry], get_shared_strings(data)).items()):
        a = cells.get("A")
        if a and a[0] == "S" and a[1].strip().startswith("fn_"):
            rows_by_key.setdefault(a[1].strip(), []).append(row_num)
    return [{"key": k, "rows": rows} for k, rows in sorted(rows_by_key.items()) if len(rows) > 1]


def read_note_payloads(path: str) -> dict:
    """{(visible sheet, cell): stored payload} for every note slot of a workbook."""
    _, data, _ = load_workbook_entries(path)
    sheet_paths = get_sheet_paths(data)
    fn_rows = read_footnote_rows(data, sheet_paths, get_shared_strings(data))
    return {(d["sheet"], d["cell"]): fn_rows[k]["payload_text"]
            for k, d in get_defined_names(data, "fn_").items() if k in fn_rows}


def _verify_footnotes(path: str, footnote_sheet: str, written: list, html_by_key: dict) -> list:
    """Each written payload read back whole and compared with what was sent."""
    _, data, _ = load_workbook_entries(path)
    fn_rows = read_footnote_rows(data, get_sheet_paths(data), get_shared_strings(data), footnote_sheet)

    def normalize(value):   # XML normalises literal line endings
        return value.replace("\r\n", "\n").replace("\r", "\n")

    mismatches = []
    for w in written:
        fn = fn_rows.get(w["key"])
        payload = fn["payload_text"] if fn else None
        fragment = html_by_key.get(w["key"])
        if not payload or fragment is None or normalize(payload) != normalize(wrap_footnote_html(fragment)):
            mismatches.append({**w, "found": bool(payload)})
    return mismatches


# ---------------------------------------------------------------- commands

def _load_json(path: str) -> dict:
    # utf-8-sig: PowerShell, the shell on the mTool machine, writes a byte-order mark.
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def _write_report(path: str | None, report: dict) -> None:
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)


def run_fill(args) -> int:
    doc = _load_json(args.input)
    errors = validate_input(doc)
    if errors:
        for e in errors:
            print(f"INPUT ERROR: {e}", file=sys.stderr)
        return 2
    report = fill_workbook(args.workbook, doc, output_path=None if args.dry_run else args.output,
                           force_recalc=bool(args.force_recalc), dry_run=bool(args.dry_run))
    _write_report(args.report, report)
    print(f"status: {report['status']}" + (" (dry run)" if report["dry_run"] else ""))
    for key in ("written", "skipped_formula", "locked", "type_changed", "mismatches", "errors"):
        print(f"  {key + ':':<16} {len(report[key])}")
        if key != "written":
            for e in report[key]:
                print(f"    - {e.get('sheet', '')}!{e.get('cell', '')} {e.get('error') or e.get('found') or ''}")
    return 1 if report["status"] == "degraded" else 0


def run_fill_notes(args) -> int:
    doc = _load_json(args.input)
    errors = validate_notes_input(doc)
    if errors:
        for e in errors:
            print(f"INPUT ERROR: {e}", file=sys.stderr)
        return 2
    report = fill_footnotes(args.workbook, doc, output_path=None if args.dry_run else args.output,
                            dry_run=bool(args.dry_run))
    _write_report(args.report, report)
    print(f"status: {report['status']}" + (" (dry run)" if report["dry_run"] else ""))
    print(f"  footnotes_written: {len(report['footnotes_written'])}")
    for key in ("unresolved", "footnote_mismatches", "errors"):
        print(f"  {key + ':':<19} {len(report[key])}")
        for e in report[key]:
            print(f"    - {e.get('key') or e.get('cell') or ''} {e.get('detail') or e.get('error') or ''}")
    return 1 if report["status"] == "degraded" else 0


def run_inspect(args) -> int:
    _, data, _ = load_workbook_entries(args.workbook)
    sheet_paths = get_sheet_paths(data)
    if not args.sheet:
        print("sheets:")
        for name, path in sheet_paths.items():
            print(f"  {name}  ({path})")
        return 0
    if args.sheet not in sheet_paths:
        print(f"sheet {args.sheet!r} not found; workbook has {sorted(sheet_paths)}", file=sys.stderr)
        return 2
    rows = read_sheet_cells(data[sheet_paths[args.sheet]], get_shared_strings(data))
    print(f"{args.sheet}: kinds F formula, S text, N number, E styled empty")
    for row_num in sorted(rows):
        cells = rows[row_num]
        print(f"  {row_num:>4} | " + " ".join(f"{col}:{kind}" for col, (kind, _) in
                                              sorted(cells.items(), key=lambda kv: col_to_idx(kv[0]))))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="offline_fill",
                                     description="Fill a closed mTool workbook without Excel.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_inspect = sub.add_parser("inspect", help="list sheets, or one sheet's cells")
    p_inspect.add_argument("--workbook", required=True)
    p_inspect.add_argument("--sheet")
    for name, helptext in (("fill", "write numbers from an input file"),
                           ("fill-notes", "write notes into the note store from an input file")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--workbook", required=True)
        p.add_argument("--input", required=True)
        p.add_argument("--output")
        p.add_argument("--report")
        p.add_argument("--dry-run", action="store_true", dest="dry_run")
        if name == "fill":
            p.add_argument("--force-recalc", action="store_true", dest="force_recalc")
    args = parser.parse_args(argv)
    if args.command == "inspect":
        return run_inspect(args)
    if not args.dry_run and not args.output:
        parser.error(f"{args.command} requires --output (or --dry-run)")
    if args.output and os.path.abspath(args.output) == os.path.abspath(args.workbook):
        parser.error("--output must differ from --workbook (never patch the original in place)")
    return run_fill_notes(args) if args.command == "fill-notes" else run_fill(args)


if __name__ == "__main__":
    sys.exit(main())
