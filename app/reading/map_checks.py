"""What the save tool checks in a document map before and after saving it.

Two kinds of answer:

- Problems: the map would mislead every later step (a page outside the
  document, a statement without its page or reason, a layout the statement
  does not have). Nothing is saved; every problem is listed at once, one
  plain sentence each, so the Reader can fix them all in one go.
- Points to check: gaps the code can see in the notes list and the unit's
  evidence. The map is saved; the points go back to the Reader, which may
  correct the list or give a reason (`note_gaps`). v1 missed gaps at both
  ends of the numbering, so the first and last notes are checked too.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Iterable, Optional

from app.reading.content import table_rows
from app.catalog.statements import printed_layouts
from app.reading.map_schema import STATEMENT_NAMES, STATEMENTS, DocumentMap
from app.runs import units

_NOTE_HEADING = re.compile(r"^\s*(?:note\s+)?(\d{1,3})(?:\s*[.)])?\s+(?=[A-Za-z(])", re.I)
_NOTE_COLUMN = re.compile(r"^\s*notes?\s*$", re.I)
_CITED = re.compile(r"\b(\d{1,3})(?![\d,])")
_AMOUNT = re.compile(r"\d,\d{3}|\d{4,}")


def note_number(text: str) -> Optional[int]:
    """The whole-note number of a printed number: "4", "4.", "Note 4", "4(a)" -> 4. "4.1" -> 4."""
    found = re.match(r"^\s*(?:note\s+)?(\d{1,3})", text or "", re.I)
    return int(found.group(1)) if found else None


def normalise(doc_map: DocumentMap) -> None:
    """Spellings the map may arrive in, made canonical in place."""
    if doc_map.unit.value:
        doc_map.unit.value = units.from_printed(doc_map.unit.value) or doc_map.unit.value
    first = doc_map.first_statements
    if first is not None and first.value:
        first.value = first.value.strip().lower()
    for field in (doc_map.standard, doc_map.level):
        if field.value:
            field.value = field.value.strip()
    if doc_map.standard.value:
        doc_map.standard.value = {"mfrs": "MFRS", "mpers": "MPERS", "unknown": "unknown"}.get(
            doc_map.standard.value.lower(), doc_map.standard.value)
    if doc_map.level.value:
        doc_map.level.value = doc_map.level.value.capitalize()
    for st in doc_map.statements:
        if not st.found:
            st.layout = None


def _pages_cited(doc_map: DocumentMap) -> Iterable[tuple[str, int]]:
    for name in ("company", "year_end", "standard", "level", "unit"):
        for page in getattr(doc_map, name).pages:
            yield f"the {name.replace('_', ' ')}", page
    for st in doc_map.statements:
        for page in st.pages:
            yield st.statement, page
    for note in doc_map.notes:
        yield f"note {note.number or note.title}", note.first_page
        yield f"note {note.number or note.title}", note.last_page
        for sub in note.sub_notes:
            yield f"sub-note {sub.number or sub.title}", sub.page
    for section in doc_map.other_sections:
        yield section.kind.replace("_", " "), section.first_page
        yield section.kind.replace("_", " "), section.last_page


def problems(doc_map: DocumentMap, page_count: int) -> list[str]:
    """Every reason the map cannot be saved, one plain sentence each; empty when it can."""
    normalise(doc_map)
    out: list[str] = []
    names = [st.statement for st in doc_map.statements]
    missing = [s for s in STATEMENTS if s not in names]
    if missing or len(names) != len(STATEMENTS):
        out.append(f"Give all five statements once each (SOFP, SOPL, SOCI, SOCF, SOCIE); "
                   f"{', '.join(missing) or 'one is given twice'}{' is missing' if missing else ''}, so add it, "
                   "marked not printed if the document does not print it.")
    for what, page in _pages_cited(doc_map):
        if not 1 <= page <= page_count:
            out.append(f"Page {page} for {what} is outside the document, which has {page_count} pages, so cite "
                       "the PDF page number, not the printed folio.")
    for name in ("company", "year_end", "standard", "level", "unit"):
        if not getattr(doc_map, name).reason:
            out.append(f"Give a one-sentence reason for the {name.replace('_', ' ')}.")
    if doc_map.standard.value not in ("MFRS", "MPERS", "unknown"):
        out.append("The standard must be MFRS, MPERS or unknown.")
    if doc_map.level.value not in ("Company", "Group"):
        out.append("The level must be Company, or Group when Group and Company columns are printed.")
    if doc_map.unit.value not in units.UNITS:
        out.append("The unit must be RM, RM'000 or RM'000,000 (millions), as the statements' headings print it; "
                   "figures are never rescaled.")
    first = doc_map.first_statements
    if first is not None:
        if first.value not in ("yes", "no"):
            out.append("Say yes or no for first statements: yes when no statement prints figures for a prior year.")
        if not first.reason:
            out.append("Give a one-sentence reason for first statements.")
        for page in first.pages:
            if not 1 <= page <= page_count:
                out.append(f"Page {page} for first statements is outside the document, which has {page_count} "
                           "pages, so cite the PDF page number, not the printed folio.")
    if doc_map.year_end.value is not None:
        try:
            date.fromisoformat(doc_map.year_end.value)
        except ValueError:
            out.append("Give the year end as YYYY-MM-DD, or null when it cannot be read.")
    standard = doc_map.standard.value if doc_map.standard.value in ("MFRS", "MPERS") else None
    for st in doc_map.statements:
        label = STATEMENT_NAMES[st.statement].lower()
        if not st.reason:
            out.append(f"Give a one-sentence reason for {st.statement} ({label}).")
        if st.found and not st.pages:
            out.append(f"{st.statement} is marked found but has no page, so give its PDF page.")
        if not st.found and st.pages:
            out.append(f"{st.statement} is marked not printed but cites pages, so mark it found or remove the pages.")
        if not st.found:
            continue
        if st.layout not in printed_layouts(st.statement):
            out.append(f"The layout of {st.statement} must be {' or '.join(printed_layouts(st.statement))}.")
        elif st.layout not in printed_layouts(st.statement, standard or "MFRS"):
            # Only the statement of retained earnings is limited to one standard (MPERS).
            out.append("A statement of retained earnings exists only under MPERS, so choose Default for SOCIE or "
                       "set the standard to MPERS if the basis of preparation names it.")
    for note in doc_map.notes:
        if note.first_page > note.last_page:
            out.append(f"Note {note.number or note.title} ends on page {note.last_page}, before it starts on page "
                       f"{note.first_page}.")
    for section in doc_map.other_sections:
        if section.first_page > section.last_page:
            out.append(f"The {section.kind.replace('_', ' ')} ends before it starts; check its pages.")
    return out


# Points to check -----------------------------------------------------------

def _cited_on_faces(doc_map: DocumentMap, contents: dict[int, dict]) -> dict[int, int]:
    """{note number: first face page} from each statement table's Note column."""
    cited: dict[int, int] = {}
    for st in doc_map.statements:
        for page in st.pages if st.found else []:
            for block in (contents.get(page) or {}).get("blocks", []):
                column: Optional[int] = None
                for row in table_rows(block):
                    if column is None:
                        column = next((i for i, cell in enumerate(row) if _NOTE_COLUMN.match(cell)), None)
                        continue
                    cell = row[column] if column < len(row) else ""
                    # A row that is short a cell shifts an amount into the Note column; an
                    # amount is never a note reference.
                    if cell and len(cell) <= 15 and not _AMOUNT.search(cell):
                        for number in _CITED.findall(cell):
                            cited.setdefault(int(number), page)
    return cited


def _headings_seen(doc_map: DocumentMap, contents: dict[int, dict]) -> dict[int, int]:
    """{note number: first page} from note-like headings on the notes pages."""
    starts = [n.first_page for n in doc_map.notes]
    if not starts:
        return {}
    seen: dict[int, int] = {}
    for page in sorted(p for p in contents if p >= min(starts)):
        for block in (contents.get(page) or {}).get("blocks", []):
            if block.get("type") == "heading" and (block.get("level") or 2) <= 2:
                found = _NOTE_HEADING.match(block.get("text", ""))
                if found:
                    seen.setdefault(int(found.group(1)), page)
    return seen


def points_to_check(doc_map: DocumentMap, contents: dict[int, dict]) -> list[str]:
    """Plain sentences about gaps the code can see. `contents` is
    {PDF page: stored page content}. Numbers the Reader explained in
    `note_gaps` are left out."""
    explained = {note_number(g.note) for g in doc_map.note_gaps if g.reason}
    listed: dict[int, int] = {}
    points: list[tuple[Optional[int], str]] = []
    for note in doc_map.notes:
        number = note_number(note.number)
        if number is None:
            continue
        if number in listed:
            points.append((number, f"Note {number} is listed twice; a heading marked continued belongs to the "
                                   "same note, so merge them into one entry."))
        listed[number] = listed.get(number, 0) + 1
    if listed:
        first, last = min(listed), max(listed)
        if first > 1:
            points.append((None, f"The list starts at note {first}; check whether notes 1 to {first - 1} exist "
                                 "before it, and add them or say why they are absent."))
        for number in range(max(first, 1), last + 1):
            if number not in listed:
                points.append((number, f"Note {number} is not in the list; find it or say why it is absent."))
    elif doc_map.notes:
        points.append((None, "No note in the list has a readable number, so the list cannot be checked for gaps."))
    for number, page in sorted(_cited_on_faces(doc_map, contents).items()):
        if number not in listed:
            points.append((number, f"Note {number} is cited on page {page} but is not in the notes list; find it "
                                   "or say why it is absent."))
    seen = _headings_seen(doc_map, contents)
    top = None
    if seen and listed and max(seen) > max(listed):
        top = max(seen)
        points.append((top, f"The last note heading seen is note {top} on page {seen[top]}, but the list ends "
                            f"at note {max(listed)}; check the pages after it."))
    for number, page in sorted(seen.items()):
        if number not in listed and number != top:
            points.append((number, f"A heading on page {page} reads as note {number}, which is not in the list; "
                                   "check it."))
    found = [st for st in doc_map.statements if st.found]
    if len(found) >= 2 and len(set(doc_map.unit.pages)) < 2:
        points.append((None, "The unit rests on fewer than two pages; check the column headings of a second "
                             "statement and give both pages."))
    out: list[str] = []
    for number, text in points:
        if (number is None or number not in explained) and text not in out:
            out.append(text)
    return out
