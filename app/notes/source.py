"""A note's source blocks on the run's pages, for the notes agent.

A block is named by its id, `p<page>b<index>` (the note store's own ids,
`app/notes/copy.block_id`). A note's source runs from its printed heading,
across its pages, on to the next note heading of the confirmed notes list,
reading past the page range set at setup (v1 lesson: notes ran on past the
expected pages). The agent sees every block and judges the end itself; this
is where to start reading, never a limit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.notes.copy import block_id, table_grid

_NUMBER = re.compile(r"^\s*(?:note\s+)?(\d+(?:\.\d+)?[a-z]?)(?:[.):\s]|$)", re.I)
_REF = re.compile(r"^p(\d+)b(\d+)$")
MAX_BLOCKS = 80
MAX_TEXT = 400


@dataclass(frozen=True)
class Block:
    page: int
    index: int
    data: dict

    @property
    def id(self) -> str:
        return block_id(self.page, self.index)


def _words(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def number_of(text: str) -> Optional[str]:
    m = _NUMBER.match(text or "")
    return m.group(1).lower().rstrip(".") if m else None


def plain_number(number: str) -> str:
    return (number or "").strip().lower().rstrip(".")


def starts_note(block: dict, note: dict) -> bool:
    """A heading (or a short first line) printed as this note's heading: its number, or its title."""
    if block.get("type") not in ("heading", "paragraph"):
        return False
    text = block.get("text") or ""
    if block.get("type") == "paragraph" and len(text) > 120:
        return False
    number = plain_number(note.get("number", ""))
    if number and number_of(text) == number:
        return True
    title = _words(note.get("title", ""))
    return bool(title) and block.get("type") == "heading" and _words(text).endswith(title)


def reading_order(contents: dict[int, dict], first: int, last: int) -> list[Block]:
    out = []
    for page in range(first, last + 1):
        for i, b in enumerate((contents.get(page) or {}).get("blocks", [])):
            out.append(Block(page, i, b))
    return out


def note_span(contents: dict[int, dict], notes: list[dict], position: int, page_count: int) -> list[Block]:
    """The blocks from note `position`'s heading to the next listed note's heading."""
    note = notes[position]
    later = notes[position + 1:]
    stop_page = max([note["last_page"] + 1] + [n["first_page"] for n in later[:1]])
    blocks = reading_order(contents, note["first_page"], min(page_count, stop_page))
    start = next((i for i, b in enumerate(blocks) if b.page == note["first_page"] and starts_note(b.data, note)), 0)
    own = plain_number(note["number"])
    others = [n for n in notes if n is not note and (not own or plain_number(n["number"]) != own)]
    out = []
    for b in blocks[start:]:
        if out and any(starts_note(b.data, other) for other in others):
            break
        out.append(b)
        if len(out) >= MAX_BLOCKS:
            break
    return out


def _short(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 1] + "…"


def describe(block: Block) -> list[str]:
    """One block as the agent sees it: its id, kind and words; a table row by row, numbered from 1."""
    data = block.data
    kind = data.get("type")
    if kind in ("heading", "paragraph"):
        return [f"{block.id} {kind}: {_short(data.get('text', ''))}"]
    if kind == "list":
        items = data.get("items", [])
        return [f"{block.id} list of {len(items)} item(s):"] + [f"    - {_short(i)}" for i in items]
    if kind == "table":
        grid = table_grid(data.get("html", ""))
        width = len(grid.rows[0]) if grid.rows else 0
        lines = [f"{block.id} table, {len(grid.rows)} rows x {width} columns:"]
        for n, row in enumerate(grid.rows, 1):
            lines.append(f"    row {n}: " + " | ".join(_short(c) or "·" for c in row))
        return lines
    return [f"{block.id} {kind}"]


def parse_refs(refs: list[str], contents: dict[int, dict]) -> tuple[list[tuple[int, int]], Optional[str]]:
    """Block ids, or ranges "p23b2-p24b1" in reading order, as (page, index) pairs; or a refusal."""
    out: list[tuple[int, int]] = []
    for ref in refs:
        parts = [p.strip().lower() for p in str(ref).split("-")]
        if len(parts) > 2 or not all(_REF.match(p) for p in parts):
            return [], f"{ref!r} is not a block id; use ids such as p23b4, or a range such as p23b4-p24b2."
        ends = [tuple(int(x) for x in _REF.match(p).groups()) for p in parts]
        if len(ends) == 1:
            out.append(ends[0])
            continue
        (p1, b1), (p2, b2) = ends
        if (p2, b2) < (p1, b1):
            return [], f"The range {ref} runs backwards; give its first block first."
        for block in reading_order(contents, p1, p2):
            if (p1, b1) <= (block.page, block.index) <= (p2, b2):
                out.append((block.page, block.index))
    return list(dict.fromkeys(out)), None


def unplaced(span: list[Block], own: set[str], held: set[str], note: dict) -> tuple[list[Block], list[Block]]:
    """A placed note's coverage by blocks: (the blocks it is judged on, those in no field). It is judged up to
    its last placed block, since the span may read on past the note's end; the note's own heading printed again
    on a later page ("continued") is not part of its words."""
    last = max((i for i, b in enumerate(span) if b.id in own), default=-1)
    judged = [b for i, b in enumerate(span[:last + 1]) if i == 0 or not starts_note(b.data, note)]
    return judged, [b for b in judged if b.id not in held]


def ranges(blocks: list[Block], among: list[Block]) -> str:
    """Block ids as ranges in reading order, such as p16b0-p18b0, p19b2: a range runs while the blocks
    follow one another in `among`."""
    position = {b.id: i for i, b in enumerate(among)}
    runs: list[list[str]] = []
    last = None
    for b in blocks:
        at = position.get(b.id)
        if runs and at is not None and last is not None and at == last + 1:
            runs[-1].append(b.id)
        else:
            runs.append([b.id])
        last = at
    return ", ".join(r[0] if len(r) == 1 else f"{r[0]}-{r[-1]}" for r in runs)
