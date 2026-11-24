"""Inline-style helpers for the mTool decorator.

Copied from v1's `mtool/notes_decorate.py` (style merge, lines 330-397; the
white-border accommodation, lines 400-560 and 731-800). mTool's note editor
(TX27) draws a hidden, absent or "none" cell edge as a grey line, so an edge
meant to be blank is written as a white one (v1 recon, 6 July 2026).
"""
from __future__ import annotations

from bs4 import Tag

WHITE_BORDER = "0.75px solid #ffffff"
SIDES = ("top", "right", "bottom", "left")
_BORDER_LINE_PROPS = frozenset((
    "border", "border-width", "border-style", "border-color",
    "border-top", "border-right", "border-bottom", "border-left"))
_INVISIBLE = frozenset(("hidden", "none"))


def decls(style: str) -> list[str]:
    return [d.strip() for d in style.split(";") if d.strip()]


def prop_of(decl: str) -> str:
    return decl.split(":", 1)[0].strip().lower()


def parse_decls(style: str) -> dict[str, str]:
    """A style attribute as {property: value}; the last declaration wins."""
    parsed: dict[str, str] = {}
    for d in decls(style):
        if ":" in d:
            p, v = d.split(":", 1)
            parsed[p.strip().lower()] = v.strip()
    return parsed


def _family(prop: str) -> str:
    if prop == "border" or prop.startswith("border-"):
        return "border"
    if prop == "background" or prop.startswith("background-"):
        return "background"
    return prop


def merge_style(el: Tag, addition: str) -> None:
    """Append ``addition`` to ``el``'s style; existing declarations are kept."""
    existing = el.get("style")
    if not existing:
        el["style"] = addition
        return
    sep = " " if existing.rstrip().endswith(";") else "; "
    el["style"] = existing.rstrip() + sep + addition.lstrip()


def merge_cell_style(cell: Tag, addition: str) -> None:
    """Add house defaults only for properties (or the border and background
    families) the element does not already set: a set look always wins."""
    existing = cell.get("style")
    if not existing:
        cell["style"] = addition
        return
    parts = decls(existing)
    owned = {_family(prop_of(d)) for d in parts}
    owned_props = {prop_of(d) for d in parts}
    for decl in decls(addition):
        prop = prop_of(decl)
        fam = _family(prop)
        if fam in ("border", "background"):
            if fam in owned:
                continue
        elif prop in owned_props:
            continue
        parts.append(decl)
    cell["style"] = "; ".join(parts)


def _tokens(value: str) -> list[str]:
    """Split a CSS value on spaces, keeping ``rgb(...)`` as one token."""
    tokens: list[str] = []
    cur: list[str] = []
    depth = 0
    for ch in value.strip():
        if ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            depth -= 1
            cur.append(ch)
        elif ch.isspace() and depth == 0:
            if cur:
                tokens.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        tokens.append("".join(cur))
    return tokens


def _positional(tokens: list[str]) -> list[str | None]:
    """One to four tokens as [top, right, bottom, left]."""
    n = len(tokens)
    if n == 1:
        return [tokens[0]] * 4
    if n == 2:
        return [tokens[0], tokens[1], tokens[0], tokens[1]]
    if n == 3:
        return [tokens[0], tokens[1], tokens[2], tokens[1]]
    if n >= 4:
        return list(tokens[:4])
    return [None, None, None, None]


def resolve_borders(parsed: dict[str, str]) -> dict[str, str | None]:
    """Each side's border value, from the shorthand, the grouped longhands or
    the per-side longhands."""
    widths = _positional(_tokens(parsed["border-width"])) if parsed.get("border-width") else None
    styles = _positional(_tokens(parsed["border-style"])) if parsed.get("border-style") else None
    colors = _positional(_tokens(parsed["border-color"])) if parsed.get("border-color") else None
    shorthand = parsed.get("border")
    grouped = widths or styles or colors
    out: dict[str, str | None] = {}
    for i, side in enumerate(SIDES):
        per = parsed.get(f"border-{side}")
        if per:
            out[side] = per
        elif grouped:
            parts = [t for t in (widths[i] if widths else None,
                                 styles[i] if styles else None,
                                 colors[i] if colors else None) if t]
            out[side] = " ".join(parts) if parts else shorthand
        else:
            out[side] = shorthand
    return out


def _invisible(value: str) -> bool:
    return any(t.lower() in _INVISIBLE for t in _tokens(value))


def whiteout_hidden_borders(el: Tag) -> None:
    """Rewrite any edge set to hidden or none as a white edge. Untouched
    unless such an edge is present."""
    existing = el.get("style")
    if not existing:
        return
    parsed = parse_decls(existing)
    if not any(p in _BORDER_LINE_PROPS and _invisible(v) for p, v in parsed.items()):
        return
    sides = resolve_borders(parsed)
    out = [d for d in decls(existing) if prop_of(d) not in _BORDER_LINE_PROPS]
    resolved: dict[str, str] = {}
    for side in SIDES:
        value = sides.get(side)
        if value:
            resolved[side] = WHITE_BORDER if _invisible(value) else value
    # Four equal edges stay one shorthand: it counts against mTool's limit.
    if len(resolved) == 4 and len(set(resolved.values())) == 1:
        out.append(f"border: {next(iter(resolved.values()))}")
    else:
        out.extend(f"border-{s}: {resolved[s]}" for s in SIDES if s in resolved)
    el["style"] = "; ".join(out)


def fill_undeclared_borders_white(el: Tag, skip: frozenset[str] = frozenset()) -> None:
    """Paint every edge the cell does not declare white, except the ``skip``
    sides whose shared edge a neighbour declares (that line must win)."""
    parts = decls(el.get("style") or "")
    sides = resolve_borders(parse_decls(el.get("style") or ""))
    missing = [s for s in SIDES if not sides.get(s) and s not in skip]
    if not missing:
        return
    if len(missing) == 4:
        parts.append(f"border: {WHITE_BORDER}")
    else:
        parts.extend(f"border-{s}: {WHITE_BORDER}" for s in missing)
    el["style"] = "; ".join(parts)


def neighbour_declared_sides(grid: list[list[Tag]]) -> dict[int, frozenset[str]]:
    """Per cell (by ``id``), the sides whose shared edge the adjacent cell
    declares. ``grid`` is the table's own rows of cells."""
    declared = [[resolve_borders(parse_decls(c.get("style") or "")) for c in cells]
                for cells in grid]
    skip: dict[int, frozenset[str]] = {}
    for r, cells in enumerate(grid):
        for c, cell in enumerate(cells):
            s = set()
            if c > 0 and declared[r][c - 1].get("right"):
                s.add("left")
            if c + 1 < len(cells) and declared[r][c + 1].get("left"):
                s.add("right")
            if r > 0 and c < len(grid[r - 1]) and declared[r - 1][c].get("bottom"):
                s.add("top")
            if r + 1 < len(grid) and c < len(grid[r + 1]) and declared[r + 1][c].get("top"):
                s.add("bottom")
            if s:
                skip[id(cell)] = frozenset(s)
    return skip
