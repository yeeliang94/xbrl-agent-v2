"""Read one template workbook into a tree of concepts and the sums between them.

Copied from v1 `concept_model/parser.py`. A concept is one template line:
ABSTRACT (a heading, never holds a value), LEAF (typed in), COMPUTED (a total
with a formula) or MATRIX_CELL (one equity-statement cell, `socie_parser`).
Its ID is a UUID5 of template, sheet, row and label, so v2's IDs equal v1's.

Formula grammar: signed sums (`=1*B10+1*B11-1*B12`, `=B10+B11`), cross-sheet
references (`='SOFP-Sub-CuNonCu'!B39`) and single-column `SUM` ranges.
Anything else raises `UnknownFormulaShape`.

One change from v1: `derive_template_id` reads only the template's own two
folders, so a checkout path containing "mpers" or "group" cannot change it.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import column_index_from_string
from openpyxl.worksheet.worksheet import Worksheet

from app.catalog.section_headers import discover_section_headers, keyword_fallback_for_sheet
from app.utils.paths import safe_path

# Fixed namespace: the same template always gives the same concept IDs (v1's).
CONCEPT_NS = uuid.UUID("8c2dc94e-1d2a-4d3f-9c1e-b6f0e8a3a8e0")


class UnknownFormulaShape(Exception):
    def __init__(self, sheet: str, coordinate: str, formula: str) -> None:
        super().__init__(f"{sheet}!{coordinate}: {formula!r}")
        self.sheet, self.coordinate, self.formula = sheet, coordinate, formula


class UnsupportedSchemaShape(Exception):
    """A whole template the parser cannot represent."""


@dataclass
class ConceptNode:
    concept_uuid: str
    parent_uuid: str | None
    kind: str              # ABSTRACT | LEAF | COMPUTED | MATRIX_CELL
    canonical_label: str   # column-A text, trimmed; a leading '*' is kept
    render_key: dict[str, Any]
    edges: list[dict[str, Any]] = field(default_factory=list)
    _indent: int = 0


@dataclass
class ConceptTree:
    template_id: str
    concepts: list[ConceptNode]
    shape: str = "linear"   # "matrix" for SOCIE
    sheet_order: list[str] = field(default_factory=list)


def parse_template(xlsx_path: str | Path) -> ConceptTree:
    path = Path(xlsx_path)
    template_id = derive_template_id(path)
    if "socie" in path.stem.lower():
        from app.catalog.socie_parser import parse_socie_matrix

        tree = parse_socie_matrix(path, template_id)
    else:
        wb = openpyxl.load_workbook(safe_path(path), data_only=False)
        nodes: list[ConceptNode] = []
        coord_to_uuid: dict[tuple[str, int, str], str] = {}
        pending: list[tuple[ConceptNode, str, str]] = []
        for sheet_name in wb.sheetnames:
            _classify_sheet(wb[sheet_name], sheet_name, template_id, nodes, coord_to_uuid, pending)
        _resolve_cross_refs(nodes, coord_to_uuid, pending)
        tree = ConceptTree(template_id=template_id, concepts=nodes, sheet_order=list(wb.sheetnames))
    _attach_semantic_addresses(tree, path)
    return tree


def _attach_semantic_addresses(tree: ConceptTree, path: Path) -> None:
    """Add each concept's taxonomy element and its slot role.

    The taxonomy is authoritative: a row whose element is not reportable
    becomes a heading. It never turns a styled heading into a field.
    """
    from app.catalog.taxonomy import semantic_addresses_for

    addresses = semantic_addresses_for(str(path.resolve()))
    for node in tree.concepts:
        rk = node.render_key
        key = (rk.get("sheet", ""), int(rk.get("row", 0) or 0), rk.get("matrix_col"))
        address = addresses.get(key)
        if address is None and rk.get("matrix_col") is None:
            address = addresses.get((key[0], key[1], None))
        if address is not None:
            rk["semantic_address"] = address
        owns_formula = node.kind == "COMPUTED" or bool(node.edges)
        if address is not None and not address.get("reportable", False):
            node.kind = "ABSTRACT"
        if node.kind == "ABSTRACT":
            rk["slot_role"] = "PRESENTATION_ONLY"
        elif owns_formula:
            rk["slot_role"] = "MATRIX_FORMULA" if rk.get("matrix_col") else "FORMULA"
        elif address is None:
            rk["slot_role"] = "UNMAPPED"
        else:
            rk["slot_role"] = "MATRIX_INPUT" if rk.get("matrix_col") else "INPUT"


def derive_template_id(path: Path) -> str:
    """`{standard}-{level}-{slug}-v1`, for example `mfrs-company-sofp-cunoncu-v1`."""
    parent = path.parent.name.lower()
    family = path.parent.parent.name.lower()
    standard = "mpers" if "mpers" in family else "mfrs"
    level = "group" if parent == "group" else "company"
    slug = re.sub(r"^\d+-", "", path.stem).lower()
    return f"{standard}-{level}-{slug}-v1"


def mint_uuid(template_id: str, sheet: str, row: int, label: str) -> str:
    return str(uuid.uuid5(CONCEPT_NS, f"{template_id}::{sheet}::{row}::{label}"))


def _classify_sheet(ws: Worksheet, sheet_name: str, template_id: str, out_nodes: list[ConceptNode],
                    coord_to_uuid: dict[tuple[str, int, str], str],
                    pending: list[tuple[ConceptNode, str, str]]) -> None:
    """Headings become ABSTRACT, rows with a formula COMPUTED, the rest LEAF."""
    abstract_rows = {h.row for h in discover_section_headers(
        ws, extra_keywords=keyword_fallback_for_sheet(sheet_name))}
    parent_by_indent: dict[int, str] = {}
    last_col = max(3, ws.max_column + 1)
    for row_num in range(1, ws.max_row + 1):
        label_cell = ws.cell(row=row_num, column=1)
        if label_cell.value is None:
            continue
        label = str(label_cell.value).strip()
        if not label:
            continue
        kind = _classify_row(ws, row_num, abstract_rows, last_col)
        indent = int(getattr(label_cell.alignment, "indent", 0) or 0)
        parent_uuid: str | None = None
        for lvl in sorted(parent_by_indent.keys(), reverse=True):
            if lvl < indent or kind != "ABSTRACT":
                if lvl <= indent and not (kind == "ABSTRACT" and lvl == indent):
                    parent_uuid = parent_by_indent[lvl]
                    break
        node_uuid = mint_uuid(template_id, sheet_name, row_num, label)
        node = ConceptNode(node_uuid, parent_uuid, kind, label,
                           {"sheet": sheet_name, "row": row_num, "col": "B"}, _indent=indent)
        out_nodes.append(node)
        coord_to_uuid[(sheet_name, row_num, "B")] = node_uuid
        if kind == "ABSTRACT":
            for lvl in list(parent_by_indent.keys()):
                if lvl >= indent:
                    del parent_by_indent[lvl]
            parent_by_indent[indent] = node_uuid
        if kind == "COMPUTED":
            formula = _first_formula_in_row(ws, row_num, last_col)
            if formula:
                collect_edges(node, sheet_name, formula, pending)


def _classify_row(ws: Worksheet, row: int, abstract_rows: set[int], last_col: int) -> str:
    if row in abstract_rows:
        return "ABSTRACT"
    return "COMPUTED" if _first_formula_in_row(ws, row, last_col) else "LEAF"


def _first_formula_in_row(ws: Worksheet, row: int, last_col: int) -> str | None:
    for col in range(2, last_col):
        val = ws.cell(row=row, column=col).value
        if isinstance(val, str) and val.startswith("="):
            return val
    return None


_SIGNED_SUM_TERM_RE = re.compile(
    r"(?P<sign>[+-])?\s*(?:(?P<coef>\d+(?:\.\d+)?)\s*\*\s*)?(?P<col>[A-Z]+)(?P<row>\d+)")
_CROSS_SHEET_RE = re.compile(r"^=\s*'(?P<sheet>[^']+)'\s*!\s*(?P<col>[A-Z]+)(?P<row>\d+)\s*$")
_SUM_RANGE_RE = re.compile(
    r"^=\s*SUM\s*\(\s*(?P<col1>[A-Z]+)(?P<row1>\d+)\s*:\s*(?P<col2>[A-Z]+)(?P<row2>\d+)\s*\)\s*$",
    re.IGNORECASE)


def collect_edges(node: ConceptNode, sheet_name: str, formula: str,
                  pending: list[tuple[ConceptNode, str, str]]) -> None:
    """Parse one formula into the node's sum edges (cross-sheet ones deferred)."""
    body = formula.strip()
    m = _CROSS_SHEET_RE.match(body)
    if m:
        pending.append((node, m.group("sheet"), f"{m.group('col')}{m.group('row')}"))
        return
    m = _SUM_RANGE_RE.match(body)
    if m:
        c1, r1, c2, r2 = m.group("col1"), int(m.group("row1")), m.group("col2"), int(m.group("row2"))
        if c1 != c2 and r1 != r2:
            raise UnknownFormulaShape(sheet_name, node.render_key.get("coord", "?"), formula)
        if c1 == c2:
            for r in range(r1, r2 + 1):
                node.edges.append({"ref": {"sheet": sheet_name, "col": c1, "row": r}, "coefficient": 1})
        else:
            for ci in range(column_index_from_string(c1), column_index_from_string(c2) + 1):
                node.edges.append({"ref": {"sheet": sheet_name, "col": get_column_letter(ci), "row": r1},
                                   "coefficient": 1})
        return
    if body.startswith("="):
        for sign, coef, col, row in _parse_signed_sum(body, sheet_name, formula):
            node.edges.append({"ref": {"sheet": sheet_name, "col": col, "row": int(row)},
                               "coefficient": sign * coef})
        return
    raise UnknownFormulaShape(sheet_name, "?", formula)


def _parse_signed_sum(body: str, sheet_name: str, formula_raw: str) -> list[tuple[int, float, str, str]]:
    expr = body.lstrip("=").replace(" ", "")
    while True:
        new = expr.replace("+-", "-").replace("-+", "-").replace("--", "+").replace("++", "+")
        if new == expr:
            break
        expr = new
    if expr and expr[0] not in "+-":
        expr = "+" + expr
    pos = 0
    out: list[tuple[int, float, str, str]] = []
    while pos < len(expr):
        m = _SIGNED_SUM_TERM_RE.match(expr, pos)
        if not m or m.end() == pos:
            raise UnknownFormulaShape(sheet_name, "?", formula_raw)
        sign = -1 if m.group("sign") == "-" else 1
        coef = float(m.group("coef")) if m.group("coef") else 1.0
        out.append((sign, coef, m.group("col"), m.group("row")))
        pos = m.end()
    if not out:
        raise UnknownFormulaShape(sheet_name, "?", formula_raw)
    return out


def _resolve_cross_refs(nodes: list[ConceptNode], coord_to_uuid: dict[tuple[str, int, str], str],
                        pending: list[tuple[ConceptNode, str, str]]) -> None:
    """A face row that points at a sub-sheet total shares that total's identity.

    It keeps its own render key, so the face cell can still be shown.
    """
    for face_node, target_sheet, target_coord in pending:
        m = re.match(r"^([A-Z]+)(\d+)$", target_coord)
        if not m:
            continue
        col, row = m.group(1), int(m.group(2))
        target_uuid = coord_to_uuid.get((target_sheet, row, col))
        if target_uuid is None:
            for (s, r, _c), uid in coord_to_uuid.items():
                if s == target_sheet and r == row:
                    target_uuid = uid
                    break
        if target_uuid is None:
            continue
        face_node.concept_uuid = target_uuid
        face_node.edges = [{"ref": {"sheet": target_sheet, "col": col, "row": row},
                            "coefficient": 1, "kind": "cross_sheet"}]
