"""The file tools: read and search a Word or Excel file's own words and numbers.

A run that started from a Word or Excel file has pages only because the
server laid out a reading copy. The file itself holds the real text and
numbers, stored at upload (`app/documents/file_lines.py`). These two tools
give them to every agent that has the page tools, so a number is taken from
the file, not read off a picture of it (go-live plan C6). Nothing leaves the
server: the provider's code sandbox is not used.

`for_run` is the one place they are added (`loop.run_agent` calls it): a run
from a PDF gets neither the tools nor the paragraph about them, so nothing
changes for it. Like the page tools, a bad request is answered with a plain
sentence as the result.
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Optional

from pydantic_ai import RunContext

from app import db
from app.agents import budget
from app.agents.pages import PageSource, bad_pages
from app.documents import file_lines
from app.documents.reading_copy import HEADING, ROW, Line, parse_amount
from app.documents.source_file import EXCEL, WORD
from app.documents.workbook_copy import plain

MAX_READ = 6
MAX_HITS = 20

# One principle, the same for every agent (AGENTS.md: principles before rules). It says what the pages
# are, what the file is, and which of them to trust for what.
PRINCIPLE = """\
The source of this run. This run started from {a_file}, not from a PDF. The pages you read and view are a \
reading copy the server laid out from that file, so that every figure has a page a person can open: its page \
numbers are its own, and it prints no folios. The file's own words and numbers are kept exactly as the file \
holds them: read_file gives them for the pages you name, and search_file finds words or an amount anywhere in \
the file. So for this run the file is the authority for every word and number, and a transcription or a \
picture of the reading copy is a second-hand reading of it. Take words and amounts from the file, use the \
pictures for layout (what sits under which heading, which column is which year), and cite the reading-copy \
page as the source, as you would a PDF page."""
EXCEL_PRINCIPLE = """ Each sheet starts on a new page, and read_file names every value by its sheet, column \
letter and row number, as the sheet shows it. Take an amount as the sheet shows it, in the unit the statement \
declares; where a saved value is given beside it, the sheet rounds or scales that value, so use it only to \
settle rounding or a sign. A formula saved without a result reads as empty and is marked so: it is a value \
the file does not give, never a zero."""


def principle(kind: str) -> str:
    if kind == EXCEL:
        return PRINCIPLE.format(a_file="an Excel workbook") + EXCEL_PRINCIPLE
    return PRINCIPLE.format(a_file="a Word document")


def _excel_cell(row: int, cell: list) -> str:
    letter, text, value = cell
    # The sheet may show a rounded figure: then the value the file holds is given too.
    exact = "" if value is None or (parse_amount(text) is not None and abs(parse_amount(text) - value) < 1e-9) \
        else f" (saved value {plain(value)})"
    return f"{letter}{row} {text}{exact}"


def row_text(line: Line) -> str:
    if line.sheet is not None:
        return " | ".join(_excel_cell(line.row, cell) for cell in line.cells)
    return " | ".join(str(cell) for cell in line.cells)


def _where(line: Line) -> str:
    if line.sheet is not None:
        return f"sheet {line.sheet} row {line.row}"
    return f"table {line.block} row {line.row}" if line.kind == ROW else "text"


def _page_text(page: int, lines: list[Line]) -> str:
    if not lines:
        return f"=== Page {page}: the file holds nothing on this page."
    out, block, sheet = [], 0, None
    for line in lines:
        if line.sheet is not None:
            if line.sheet != sheet:
                sheet = line.sheet
                out.append(f"=== Page {page}, sheet {sheet}:")
            out.append(f"row {line.row}: {row_text(line)}")
            continue
        if not out:
            out.append(f"=== Page {page}, from the Word file:")
        if line.kind == ROW:
            if line.block != block:
                block = line.block
                out.append(f"Table {block}:")
            out.append(f"  row {line.row}: {row_text(line)}")
        else:
            block = 0
            out.append(("# " if line.kind == HEADING else "") + row_text(line))
    return "\n".join(out)


def read_file(ctx: RunContext[PageSource], pages: list[int], note: Optional[str] = None) -> str:
    """Read what the uploaded Word or Excel file itself holds on up to 6 reading-copy pages: its
    headings, paragraphs and table rows, word for word and number for number. For a workbook each
    value comes with its sheet and cell. The file is the authority for words and amounts.
    `note`: one plain sentence for the person following the run: what you are doing and why."""
    deps = ctx.deps
    problem = bad_pages(deps, pages, MAX_READ)
    if problem:
        return problem
    wanted = list(dict.fromkeys(pages))
    with db.connect() as conn:
        lines = file_lines.of_run(conn, deps.run_id, pages=wanted)
    return "\n\n".join(_page_text(page, [line for line in lines if line.page == page]) for page in wanted)


def _matches(line: Line, needle: str, amount: Optional[float]) -> bool:
    if amount is not None:
        for cell in line.cells:
            text, value = (cell[1], cell[2]) if line.sheet is not None else (str(cell), None)
            found = value if value is not None else parse_amount(text)
            # An amount is found whatever its sign is written as: brackets, a minus or none.
            if found is not None and abs(abs(found) - abs(amount)) < 1e-9:
                return True
    return needle in " ".join(row_text(line).split()).lower()


def search_file(ctx: RunContext[PageSource], text: str, note: Optional[str] = None) -> str:
    """Find words or an amount in the uploaded Word or Excel file itself, ignoring case, and for an
    amount ignoring its commas, brackets and sign. Each hit gives the reading-copy page and the
    whole line, and for a workbook the sheet and cell of every value.
    `note`: one plain sentence for the person following the run: what you are doing and why."""
    needle = " ".join(text.split()).lower()
    if len(needle) < 2:
        return "Search for at least two characters."
    amount = parse_amount(needle)
    with db.connect() as conn:
        lines = file_lines.of_run(conn, ctx.deps.run_id)
    hits = [f"- page {line.page}, {_where(line)}: {row_text(line)}" for line in lines
            if _matches(line, needle, amount)]
    if not hits:
        return f"The file does not hold {text!r}. Try another wording, or a shorter part of it."
    more = f"\n({len(hits) - MAX_HITS} more lines hold it.)" if len(hits) > MAX_HITS else ""
    return f"{len(hits)} line(s) of the file hold {text!r}:\n" + "\n".join(hits[:MAX_HITS]) + more


FILE_TOOLS = (read_file, search_file)
NAMES = frozenset(t.__name__ for t in FILE_TOOLS)


def for_run(spec: Any, run_id: Optional[int]) -> Any:
    """The agent's spec for this run: with the file tools and their principle when the run started
    from a Word or Excel file and the agent has the page tools; otherwise the spec as it is."""
    if run_id is None or not any(getattr(tool, "__name__", "") == "read_pages" for tool in spec.tools):
        return spec
    with db.connect() as conn:
        kind = file_lines.run_kind(conn, run_id)
    if kind not in (WORD, EXCEL):
        return spec
    return replace(spec, tools=[*spec.tools, *(budget.budgeted(t) for t in FILE_TOOLS)], instructions=f"{spec.instructions}\n{principle(kind)}\n")
