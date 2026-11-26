"""The units a report's amounts may be printed in: one list for setup, the
Reader, the agents' opening messages, the starting workbook and the fill.

A figure is always stored and filed exactly as printed, never rescaled
(requirements 3.1.4). The unit says what those printed amounts mean, and it
must agree with the mTool workbook's own "level of rounding", because mTool
reads the same digits in the workbook's unit.
"""
from __future__ import annotations

import re
from typing import Optional

RM, THOUSANDS, MILLIONS = "RM", "RM'000", "RM'000,000"
UNITS = (RM, THOUSANDS, MILLIONS)
# In a sentence: "Amounts are in RM thousands".
WORDS = {RM: "RM", THOUSANDS: "RM thousands", MILLIONS: "RM millions"}
CHOOSE = "Choose whether amounts are in RM, RM thousands or RM millions."

# Ways a report's column heading prints the unit, squeezed and upper-cased.
_PRINTED = {
    "RM": RM,
    "RM'000": THOUSANDS, "RM000": THOUSANDS, "RM'000S": THOUSANDS,
    "RM'000,000": MILLIONS, "RM'000000": MILLIONS, "RM000,000": MILLIONS, "RM000000": MILLIONS,
    "RMMILLION": MILLIONS, "RMMILLIONS": MILLIONS, "RM'MILLION": MILLIONS, "RM'MILLIONS": MILLIONS,
    "RMMIL": MILLIONS, "RM'MIL": MILLIONS, "RM'M": MILLIONS, "RMM": MILLIONS,
}


def unit_words(unit: Optional[str]) -> str:
    """The unit as a person reads it. A unit not on the list is shown as it is."""
    return WORDS.get(unit or RM, unit or RM)


def from_printed(text: Optional[str]) -> Optional[str]:
    """The unit a column heading prints ("RM '000", "RM million", "RM'm"), or None when it is none of them."""
    return _PRINTED.get(re.sub(r"[\s’‘`]", "", text or "").upper())   # spaces and curly quotes are dropped


def from_rounding(text: Optional[str]) -> Optional[str]:
    """The unit of an mTool workbook from its "level of rounding used in financial statements" (SSM's
    list: Actuals, In thousands ('000'), In millions ('000,000')), or None when it says none of them."""
    words = (text or "").lower()
    if "million" in words:
        return MILLIONS
    if "thousand" in words:
        return THOUSANDS
    if "actual" in words:
        return RM
    return None
