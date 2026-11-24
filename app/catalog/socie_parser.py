"""Read the equity statement (SOCIE) template as a grid of cells.

Copied from v1 `concept_model/parser.py` (the matrix branch). A SOCIE block
runs from "Equity at beginning of period" to "Equity at end of period". Group
templates stack four blocks (Group CY, Group PY, Company CY, Company PY),
Company templates two. The concepts live in the first block; each cell
carries the target rows of every block, so the period and entity choose the
row, and the column is the equity component.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import column_index_from_string
from openpyxl.worksheet.worksheet import Worksheet

from app.catalog.parser import (
    ConceptNode, ConceptTree, UnknownFormulaShape, UnsupportedSchemaShape, collect_edges, mint_uuid,
)
from app.catalog.section_headers import discover_section_headers, keyword_fallback_for_sheet
from app.utils.paths import safe_path

_BLOCK_OPEN = {"equity at beginning of period", "balance at beginning of period"}
_BLOCK_CLOSE = {"equity at end of period", "balance at end of period"}


def _norm(value: Any) -> str:
    return str(value or "").strip().lstrip("*").strip().lower()


def _find_blocks(ws: Worksheet) -> list[tuple[int, int]]:
    begins = [r for r in range(1, ws.max_row + 1) if _norm(ws.cell(r, 1).value) in _BLOCK_OPEN]
    ends = [r for r in range(1, ws.max_row + 1) if _norm(ws.cell(r, 1).value) in _BLOCK_CLOSE]
    return list(zip(begins, ends))


def _component_cols(ws: Worksheet) -> list[str]:
    """Equity-component column letters from the row-2 header (B..X on MFRS)."""
    cols = [get_column_letter(c) for c in range(2, ws.max_column + 1)
            if ws.cell(2, c).value not in (None, "")]
    return cols or ["B"]


def _component_label(ws: Worksheet, col: str) -> str:
    return str(ws.cell(2, column_index_from_string(col)).value or "").strip() or "Value"


def _block_dims(n_blocks: int, idx: int) -> tuple[str, str] | None:
    if n_blocks == 4:
        return [("CY", "Group"), ("PY", "Group"), ("CY", "Company"), ("PY", "Company")][idx]
    if n_blocks == 2:
        return [("CY", "Company"), ("PY", "Company")][idx]
    return None


def _targets_for(sheet: str, base_row: int, col: str, blocks: list[tuple[int, int]],
                 base_begin: int) -> list[dict[str, Any]]:
    if len(blocks) == 1:
        # One block (older MPERS Company layout): the period is a column.
        return [
            {"period": "CY", "entity_scope": "Company", "sheet": sheet, "row": base_row, "col": "B"},
            {"period": "PY", "entity_scope": "Company", "sheet": sheet, "row": base_row, "col": "C"},
        ]
    targets = []
    for idx, (b_begin, _end) in enumerate(blocks):
        dims = _block_dims(len(blocks), idx)
        if dims is None:
            continue
        targets.append({"period": dims[0], "entity_scope": dims[1], "sheet": sheet,
                        "row": base_row + (b_begin - base_begin), "col": col})
    return targets


def parse_socie_matrix(path: Path, template_id: str) -> ConceptTree:
    wb = openpyxl.load_workbook(safe_path(path), data_only=False)
    sheet = "SOCIE" if "SOCIE" in wb.sheetnames else wb.sheetnames[0]
    ws = wb[sheet]
    blocks = _find_blocks(ws)
    if not blocks:
        raise UnsupportedSchemaShape(f"SOCIE template has no recognisable equity blocks ({path.name})")
    components = _component_cols(ws)
    base_begin, base_end = blocks[0]
    abstract_rows = {h.row for h in discover_section_headers(
        ws, extra_keywords=keyword_fallback_for_sheet(sheet))}
    native_mpers = template_id.startswith("mpers-") and ws.cell(2, 15).value == "Total"
    nodes: list[ConceptNode] = []
    pending: list[tuple[ConceptNode, str, str]] = []
    for row in range(base_begin, base_end + 1):
        raw = ws.cell(row, 1).value
        if raw is None or not str(raw).strip():
            continue
        label = str(raw).strip()
        if row in abstract_rows:
            nodes.append(ConceptNode(
                mint_uuid(template_id, sheet, row, label), None, "ABSTRACT", label,
                {"sheet": sheet, "row": row, "col": "A", "matrix_col": None, "targets": []}))
            continue
        for col in components:
            component_label = _component_label(ws, col)
            name = f"{col}::{component_label}::{label}" if native_mpers else f"{col}::{label}"
            node = ConceptNode(
                mint_uuid(template_id, sheet, row, name), None, "MATRIX_CELL", label,
                {"sheet": sheet, "row": row, "col": col, "matrix_col": col,
                 "matrix_col_label": component_label,
                 "targets": _targets_for(sheet, row, col, blocks, base_begin)})
            formula = ws.cell(row, column_index_from_string(col)).value
            if isinstance(formula, str) and formula.startswith("="):
                try:
                    collect_edges(node, sheet, formula, pending)
                except UnknownFormulaShape:
                    pass
            nodes.append(node)
    return ConceptTree(template_id=template_id, concepts=nodes, shape="matrix",
                       sheet_order=list(wb.sheetnames))
