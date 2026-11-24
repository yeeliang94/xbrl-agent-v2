"""Which template a workbook is: one of the known genuine mTool templates,
probably compatible, or unknown.

New in v2. v1's list (`mtool/known_templates.json`) held v1's own generated
templates, never a genuine mTool workbook (v1-reuse-map section 2.4). Here
the list holds the ten genuine templates under `templates/`, fingerprinted
from the files themselves (`known_templates.json`, checked against the files
by a test).

The fingerprint is the workbook's structure, never its content: each sheet's
mTool markers and the SSM names in it, each with its column. Typed figures,
notes and mTool's fresh GUID in row 1 leave it unchanged; removing a sheet's
SSM names or its column markers changes it.

"Probably compatible" is a workbook not on the list in which every sheet with
SSM names is laid out the mTool way: it marks its label column and its value
columns, and every sheet that marks a label column carries SSM names. Its
cells are still found by meaning, but nobody has checked the template.
Anything else is unknown. A confirmed saved mapping (step 8f) makes a
template known: `identify` takes it from the caller.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.utils.paths import safe_path
from app.workbook.mtool_layout import MARKER_DIMENSION, MARKER_END_DATE, MARKER_LABEL
from app.workbook.xlsx_cells import TAXONOMY_HREF, Cells

KNOWN_TEMPLATES = Path(__file__).with_name("known_templates.json")
KNOWN, PROBABLY, UNKNOWN = "known", "probably_compatible", "unknown"
_MARKER = re.compile(r"^#[A-Z]+#$")
MARKER_UNIT, MARKER_TABLE = "#UNITSCALE#", "#TABLE#"   # a sheet of amounts; a table of fields


@dataclass
class Identity:
    compatibility: str                      # known | probably_compatible | unknown
    fingerprint: str
    name: Optional[str] = None              # the known template's file name
    template: dict = field(default_factory=dict)   # the known template's standard, level and layouts
    reasons: list[str] = field(default_factory=list)   # why it is not known, in plain sentences


def _sheet_structure(cells: Cells) -> dict:
    markers, names = set(), set()
    for row_cells in cells.values():
        for col, (_kind, text) in row_cells.items():
            value = (text or "").strip()
            if _MARKER.match(value):
                markers.add(f"{value}@{col}")
            for element in TAXONOMY_HREF.findall(text or ""):
                names.add(f"{element}@{col}")
    return {"markers": sorted(markers), "names": sorted(names)}


def fingerprint(cells_by_sheet: dict[str, Cells]) -> str:
    payload = {name: _sheet_structure(cells) for name, cells in sorted(cells_by_sheet.items())}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:32]


@lru_cache(maxsize=1)
def known_templates() -> dict[str, dict]:
    return json.loads(safe_path(KNOWN_TEMPLATES).read_text(encoding="utf-8"))


def layout_problems(cells_by_sheet: dict[str, Cells]) -> list[str]:
    """Sentences naming each sheet that is not laid out the mTool way."""
    problems = []
    laid_out = 0
    for sheet, cells in cells_by_sheet.items():
        structure = _sheet_structure(cells)
        markers = {m.split("@")[0] for m in structure["markers"]}
        has_names = bool(structure["names"])
        if MARKER_LABEL in markers and not has_names:
            problems.append(f"{sheet} marks a label column but carries no SSM names.")
        elif MARKER_UNIT in markers and not markers & {MARKER_END_DATE, MARKER_DIMENSION}:
            problems.append(f"{sheet} holds amounts but does not mark its value columns.")
        elif has_names and not markers:
            problems.append(f"{sheet} carries SSM names but no mTool markers.")
        elif has_names and markers & {MARKER_TABLE, MARKER_UNIT} and MARKER_LABEL not in markers:
            problems.append(f"{sheet} carries SSM names but does not mark its label column.")
        laid_out += MARKER_LABEL in markers and has_names
    if not laid_out:
        problems.append("No sheet carries SSM names in mTool's layout.")
    return problems


def identify(cells_by_sheet: dict[str, Cells], *, confirmed_mapping: Optional[dict] = None) -> Identity:
    """The workbook's identity. `confirmed_mapping` is a mapping a person
    confirmed for this fingerprint (step 8f); it makes the template known."""
    print_ = fingerprint(cells_by_sheet)
    entry = known_templates().get(print_)
    if entry:
        return Identity(KNOWN, print_, entry["name"], entry)
    if confirmed_mapping is not None:
        return Identity(KNOWN, print_, confirmed_mapping.get("name"), confirmed_mapping)
    problems = layout_problems(cells_by_sheet)
    if problems:
        return Identity(UNKNOWN, print_, reasons=problems)
    return Identity(PROBABLY, print_, reasons=["This workbook is laid out the mTool way but is not one of the "
                                              "known mTool templates, so nobody has checked it."])
