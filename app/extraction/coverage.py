"""Coverage: every printed line of the statement is written or skipped with
a reason (v1 lesson: silent omissions passed every arithmetic check).

The code reads the printed lines from the statement pages' transcribed
tables: each row with a label and at least one amount. The agent's report
is matched to them by page and wording, tolerant of small differences (v1's
receipt had to echo the exact label and warned on a filled statement, run of
5 August 2026). A repeated label needs one entry per time it is printed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, Field

from app.reading.content import table_rows

_AMOUNT = re.compile(r"^\(?\s*-?\s*(rm\s*)?[\d,]+(\.\d+)?\s*\)?$", re.I)
_DASH = {"-", "–", "—", "nil"}
_YEAR = re.compile(r"^(19\d\d|20\d\d|2100)$")   # a column heading such as 2021, not an amount


class CoverageLine(BaseModel):
    label: str = Field(description="The line as printed.")
    page: int = Field(description="The PDF page it is printed on.")
    action: Literal["written", "skipped"]
    fields: list[str] = Field(default_factory=list, description="For a written line: the field ids it went into.")
    reason: str = Field(default="", description="For a skipped line: why, for example the template works out "
                                                "this total, or it is a heading with no amount.")


@dataclass(frozen=True)
class Printed:
    label: str
    page: int
    order: int


def _is_amount(text: str) -> bool:
    t = text.strip()
    return bool(t) and not _YEAR.match(t) and (t.lower() in _DASH or bool(_AMOUNT.match(t)))


def printed_lines(contents: dict[int, dict], pages: list[int]) -> list[Printed]:
    """Each table row on the pages with a label and at least one amount."""
    out: list[Printed] = []
    for page in pages:
        content = contents.get(page) or {}
        for block in content.get("blocks", []):
            rows = table_rows(block)
            note_columns = {i for row in rows for i, cell in enumerate(row) if cell.strip().lower().startswith("note")}
            for row in rows:
                if not row or not row[0].strip():
                    continue
                amounts = [c for i, c in enumerate(row[1:], start=1) if i not in note_columns and _is_amount(c)]
                if amounts:
                    out.append(Printed(" ".join(row[0].split()), page, len(out)))
    return out


def normalise(label: str) -> str:
    text = re.sub(r"\(?\bnote\s*\d+[a-z]?\)?", " ", label.lower())
    text = re.sub(r"^[\s(]*([ivx]+|[a-z]|\d+)[).]\s+", "", text)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def same_line(a: str, b: str) -> bool:
    x, y = normalise(a), normalise(b)
    if not x or not y:
        return False
    if x == y or (min(len(x), len(y)) >= 6 and (x in y or y in x)):
        return True
    return SequenceMatcher(None, x, y).ratio() >= 0.8


def unaccounted(printed: list[Printed], report: list[CoverageLine]) -> list[Printed]:
    """The printed lines no entry of the report accounts for. Each entry
    covers one printed line, the first match on the same page if there is one."""
    unused = list(range(len(report)))
    missing = []
    for line in printed:
        match = next((i for i in unused if report[i].page == line.page and same_line(report[i].label, line.label)),
                     None)
        if match is None:
            match = next((i for i in unused if same_line(report[i].label, line.label)), None)
        if match is None:
            missing.append(line)
        else:
            unused.remove(match)
    return missing


def describe(line: Printed, printed: list[Printed]) -> str:
    repeats = [p for p in printed if normalise(p.label) == normalise(line.label) and p.page == line.page]
    nth = "" if len(repeats) < 2 else f", the {_ordinal(repeats.index(line) + 1)} time it is printed there"
    return f"{line.label!r} (page {line.page}{nth})"


def _ordinal(n: int) -> str:
    return {1: "first", 2: "second", 3: "third"}.get(n, f"{n}th")
