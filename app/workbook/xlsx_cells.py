"""Read the cells of an .xlsx workbook with the standard library only.

Copied from v1 `mtool/offline_fill.py` (`load_workbook_entries`,
`get_sheet_paths`, `get_shared_strings`, `read_sheet_cells`, `split_ref`,
`col_to_idx`, `idx_to_col`, `resolve_sheet_name`) and the upload limits of
v1 `api/mtool.py` (`_assert_zip_within_budget`). Nothing here writes.

A sheet's cells are `{row: {column: (kind, text)}}` with kinds `F` formula
(text is the cached result, never trusted), `S` text, `N` number and `E` a
styled empty cell. Absent cells do not appear.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile

MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024   # an honest workbook is a few MB unpacked
MAX_ZIP_MEMBERS = 5000

Cells = dict[int, dict[str, tuple[str, str]]]

# A taxonomy reference as mTool stores it: `<file>.xsd#<element id>`.
TAXONOMY_HREF = re.compile(r"[A-Za-z0-9_.-]+\.xsd#([A-Za-z_][A-Za-z0-9_.-]*)")

# Native MPERS sheet names differ from the template's. Accepted only when the
# sheet carries its MPERS role marker (v1 `_MPERS_SHEET_NAMES`).
_MPERS_SHEET_NAMES = {
    "sore": ("StatementofRetainedEarnings", "ssmt-mpers_DisclosureOfRetainedEarningsAbstract"),
    "notes-issuedcapital": ("Notes-IssuedCap", "ifrs-smes_ClassesOfShareCapitalAxis"),
    "notes-relatedpartytran": ("Notes-RelatedParty", "ifrs-smes_CategoriesOfRelatedPartiesAxis"),
    "notes-summaryofaccpol": ("Notes-SummaryOfAcc",
                              "ssmt-mpers_DisclosureOnSummaryOfSignificantAccountingPoliciesAbstract"),
}


class WorkbookUnreadable(ValueError):
    """The file is not a workbook this reader can open. `str()` is one plain sentence."""


def taxonomy_ids(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(TAXONOMY_HREF.findall(text or "")))


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


def split_ref(addr: str) -> tuple[str, int]:
    m = re.fullmatch(r"([A-Z]{1,3})([1-9]\d*)", addr)
    if not m:
        raise ValueError(f"invalid cell reference: {addr!r}")
    return m.group(1), int(m.group(2))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def load_entries(path: str) -> dict[str, bytes]:
    """Every zip member of the workbook, after checking its size limits."""
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_MEMBERS or sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES:
                raise WorkbookUnreadable("This workbook is too large to read once unpacked.")
            data = {i.filename: zf.read(i.filename) for i in infos}
    except (zipfile.BadZipFile, OSError, EOFError) as exc:
        raise WorkbookUnreadable("This file could not be read as an Excel workbook.") from exc
    if "xl/workbook.xml" not in data or "xl/_rels/workbook.xml.rels" not in data:
        raise WorkbookUnreadable("This file could not be read as an Excel workbook.")
    return data


def sheet_paths(data: dict[str, bytes]) -> dict[str, str]:
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


def shared_strings(data: dict[str, bytes]) -> list[str]:
    raw = data.get("xl/sharedStrings.xml")
    if not raw:
        return []
    return ["".join(t.text or "" for t in si.iter() if _local(t.tag) == "t") for si in ET.fromstring(raw)]


def read_sheet_cells(sheet_xml: bytes, sst: list[str]) -> Cells:
    root = ET.fromstring(sheet_xml)
    rows: Cells = {}
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
            elif t in ("str", "b", "e") and v_el is not None:
                cells[col] = ("S", v_el.text or "")
            elif v_el is not None:
                cells[col] = ("N", v_el.text or "")
            else:
                cells[col] = ("E", "")
        rows[int(row_el.get("r"))] = cells
    return rows


def read_workbook(path: str) -> tuple[dict[str, bytes], dict[str, Cells]]:
    """The zip members and every sheet's cells. Raises WorkbookUnreadable."""
    data = load_entries(path)
    try:
        sst = shared_strings(data)
        return data, {name: read_sheet_cells(data[member], sst)
                      for name, member in sheet_paths(data).items() if member in data}
    except (ET.ParseError, KeyError, ValueError) as exc:
        raise WorkbookUnreadable("This file could not be read as an Excel workbook.") from exc


def resolve_sheet_name(source_sheet: str, cells_by_sheet: dict[str, Cells]) -> str | None:
    """The workbook's sheet for a template sheet: same name (any case), or a
    native MPERS name verified by its role marker. None when not exactly one."""
    candidates = [s for s in cells_by_sheet if s.casefold() == source_sheet.casefold()]
    spec = _MPERS_SHEET_NAMES.get(source_sheet.casefold())
    if spec:
        name, marker = spec
        for sheet, cells in cells_by_sheet.items():
            if sheet.casefold() == name.casefold() and sheet not in candidates and any(
                    marker in taxonomy_ids(raw) for row in cells.values() for _, raw in row.values()):
                candidates.append(sheet)
    return candidates[0] if len(candidates) == 1 else None
