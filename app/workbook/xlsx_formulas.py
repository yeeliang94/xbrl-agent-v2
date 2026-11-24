"""Work out a formula a person typed into a workbook, without Excel.

Copied from v1 `mtool/offline_fill.py` (`calculation_cells`,
`_translate_shared_formula`, `_calculated_value`). Standard library only.

Only arithmetic is worked out: numbers, cell references, + - * / and SUM
over a bounded range. Blank cells count as zero. A cached formula result is
never used, because a file the mTool fill patched carries stale ones.
Anything else raises `FormulaNotWorkedOut`, so the caller can list the cell
as not assessed rather than guess. One `WorkBudget` caps the cells visited
across every formula of one workbook read.
"""
from __future__ import annotations

import ast
import re
import xml.etree.ElementTree as ET
from decimal import Decimal

from app.workbook.xlsx_cells import Cells, col_to_idx, idx_to_col, read_sheet_cells, shared_strings, \
    sheet_paths, split_ref

_SHEET = r"(?:(?:'((?:[^']|'')+)'|([A-Za-z_][A-Za-z0-9_.]*))!)?"
_RANGE = re.compile(_SHEET + r"(\$?[A-Z]{1,3}\$?[1-9][0-9]*):(\$?[A-Z]{1,3}\$?[1-9][0-9]*)")
_REF = re.compile(_SHEET + r"(\$?[A-Z]{1,3}\$?[1-9][0-9]*)(?![A-Za-z0-9_(])")
_SHARED_TOKEN = re.compile(
    r"(?P<ref>(?P<sheet>(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)?"
    r"(?P<col_abs>\$?)(?P<col>[A-Z]{1,3})(?P<row_abs>\$?)(?P<row>[1-9][0-9]*))"
    r"|(?P<number>(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)"
    r"|(?P<operator>[+*/()=\s-])")


class FormulaNotWorkedOut(ValueError):
    """The formula uses something beyond plain arithmetic, or a cell it needs is not a number."""


class WorkBudgetSpent(FormulaNotWorkedOut):
    """Working out the workbook's formulas needed more cells than one read allows."""


class WorkBudget:
    """The cells one workbook read may visit while working out formulas, shared by all of them."""

    def __init__(self, cells: int = 1_000_000):
        self.left = cells

    def spend(self) -> None:
        if self.left <= 0:
            raise WorkBudgetSpent("The workbook's formulas need more work than one read allows.")
        self.left -= 1


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _translate_shared_formula(expression: str, origin: str, target: str) -> str:
    """A shared formula's text moved from its first cell to a follower. '' when unsupported."""
    origin_col, origin_row = split_ref(origin)
    target_col, target_row = split_ref(target)
    delta_col = col_to_idx(target_col) - col_to_idx(origin_col)
    delta_row = target_row - origin_row
    parts, position = [], 0
    while position < len(expression):
        match = _SHARED_TOKEN.match(expression, position)
        if match is None:
            return ""
        if match.group("ref"):
            col = col_to_idx(match.group("col")) + (0 if match.group("col_abs") else delta_col)
            row = int(match.group("row")) + (0 if match.group("row_abs") else delta_row)
            if not (1 <= col <= 16384 and 1 <= row <= 1048576):
                return ""
            parts.append((match.group("sheet") or "") + match.group("col_abs") + idx_to_col(col)
                         + match.group("row_abs") + str(row))
        else:
            parts.append(match.group())
        position = match.end()
    return "".join(parts)


def formula_cells(data: dict[str, bytes]) -> dict[str, Cells]:
    """Every sheet's cells with formula cells holding their expression, shared formulas expanded."""
    paths = sheet_paths(data)
    sst = shared_strings(data)
    out = {sheet: read_sheet_cells(data[path], sst) for sheet, path in paths.items() if path in data}
    for sheet, path in paths.items():
        if path not in data:
            continue
        formulas, masters = [], {}
        for cell in ET.fromstring(data[path]).iter():
            if _local(cell.tag) != "c" or not cell.get("r"):
                continue
            formula = next((child for child in cell if _local(child.tag) == "f"), None)
            if formula is not None:
                formulas.append((cell.get("r"), formula))
                if formula.get("t") == "shared" and formula.get("si") is not None and formula.text:
                    masters[formula.get("si")] = (cell.get("r"), formula.text)
        for addr, formula in formulas:
            expression = formula.text or ""
            if formula.get("t") == "shared" and not expression and formula.get("si") in masters:
                origin, text = masters[formula.get("si")]
                expression = _translate_shared_formula(text, origin, addr)
            col, row = split_ref(addr)
            out[sheet].setdefault(row, {})[col] = ("F", expression)
    return out


def _arithmetic(node: ast.AST, values: dict[str, Decimal]) -> Decimal:
    if isinstance(node, ast.Expression):
        return _arithmetic(node.body, values)
    if isinstance(node, ast.Name) and node.id in values:
        return values[node.id]
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return Decimal(str(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _arithmetic(node.operand, values)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp):
        a, b = _arithmetic(node.left, values), _arithmetic(node.right, values)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            return a / b
    raise FormulaNotWorkedOut("Only plain arithmetic can be worked out.")


def calculated_value(cells: dict[str, Cells], sheet: str, addr: str, visiting: set | None = None,
                     cache: dict | None = None, budget: WorkBudget | None = None) -> Decimal:
    """The value of one cell, working out formulas from their current inputs."""
    visiting = set() if visiting is None else visiting
    cache = {} if cache is None else cache
    budget = WorkBudget() if budget is None else budget
    key = (sheet, addr)
    if key in cache:
        return cache[key]
    budget.spend()
    if key in visiting or len(visiting) >= 100:
        raise FormulaNotWorkedOut("The formula refers back to itself or is too deep.")
    col, row = split_ref(addr)
    if sheet not in cells:
        raise FormulaNotWorkedOut(f"The formula refers to a missing sheet {sheet}.")
    kind, raw = cells[sheet].get(row, {}).get(col, (None, None))
    if kind is None or kind == "E":
        return Decimal(0)
    if kind == "N":
        try:
            value = Decimal(raw)
        except ArithmeticError as exc:
            raise FormulaNotWorkedOut("A cell the formula needs is not a number.") from exc
        if not value.is_finite():
            raise FormulaNotWorkedOut("A cell the formula needs is not a number.")
        return value
    if kind != "F" or not raw:
        raise FormulaNotWorkedOut(f"{sheet}!{addr} is not a number.")
    if len(raw) > 16000:
        raise FormulaNotWorkedOut("The formula is too long.")
    visiting.add(key)
    try:
        values: dict[str, Decimal] = {}

        def expand_sum(match: re.Match) -> str:
            terms = []
            for arg in match.group(1).split(","):
                area = _RANGE.fullmatch(arg.strip())
                if not area:
                    terms.append(arg)
                    continue
                ref_sheet = (area.group(1) or area.group(2) or sheet).replace("''", "'")
                c1, r1 = split_ref(area.group(3).replace("$", ""))
                c2, r2 = split_ref(area.group(4).replace("$", ""))
                left, right = sorted((col_to_idx(c1), col_to_idx(c2)))
                top, bottom = sorted((r1, r2))
                if (right - left + 1) * (bottom - top + 1) > 10000:
                    raise FormulaNotWorkedOut("The formula's range is too large.")
                name = f"range_value_{len(values)}"
                values[name] = sum((calculated_value(cells, ref_sheet, f"{idx_to_col(c)}{r}", visiting, cache,
                                                     budget)
                                    for c in range(left, right + 1) for r in range(top, bottom + 1)), Decimal(0))
                terms.append(name)
            return "(" + "+".join(terms) + ")"

        def reference(match: re.Match) -> str:
            ref_sheet = (match.group(1) or match.group(2) or sheet).replace("''", "'")
            name = f"v{len(values)}"
            values[name] = calculated_value(cells, ref_sheet, match.group(3).replace("$", ""), visiting, cache,
                                            budget)
            return name

        expression = re.sub(r"\bSUM\(([^()]*)\)", expand_sum, raw.lstrip("="), flags=re.IGNORECASE)
        expression = _REF.sub(reference, expression)
        if len(expression) > 16000:
            raise FormulaNotWorkedOut("The formula is too long.")
        try:
            value = _arithmetic(ast.parse(expression, mode="eval"), values)
        except (SyntaxError, ArithmeticError, RecursionError) as exc:
            raise FormulaNotWorkedOut("The formula could not be worked out.") from exc
        if not value.is_finite():
            raise FormulaNotWorkedOut("The formula does not give an ordinary number.")
        cache[key] = value
        return value
    finally:
        visiting.remove(key)
