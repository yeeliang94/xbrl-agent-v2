"""The template as the figures agent sees it: an outline of fields, each with
its own short id.

Why (owner, 18 November 2026): v1 showed the agent the raw SSM sheet and let
it write by label. The same label repeats under different headings (82
times on the MFRS Company balance sheet), and headings look like lines, so
it picked a heading or the wrong copy. Here every field has an id, its place
under its headings (its path), and its kind:

- heading: a section title; it never holds a value.
- line: a field to fill.
- total: worked out from named parts, each with its sign.

A face row that is a formula fed from the sub-sheet is the sub-sheet's total
shown on the face. The outline nests that total's sub-sheet lines under the
face row, so the agent fills the lines and the face follows.

Ids are `<statement code>-<row>` on the face sheet and `<code>-s<row>` on
the sub-sheet (for example `FP-8`, `FP-s141`); an equity-statement column
adds `-<column>`. They come from the template alone, so they are the same
in every run with that template.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from app.catalog import lookup
from app.catalog.statements import StatementType

if TYPE_CHECKING:
    from app.extraction.grid import Grid

CODES = {"SOFP": "FP", "SOPL": "PL", "SOCI": "CI", "SOCF": "CF", "SOCIE": "CE",
         "ISSUED_CAPITAL": "SC", "RELATED_PARTY": "RP"}   # the two numeric notes (the notes agent)
HEADING, LINE, TOTAL = "heading", "line", "total"
SEP = " › "


@dataclass
class Field:
    id: str
    concept_uuid: str
    statement: str
    label: str                      # as in the template, without the leading *
    mandatory: bool                 # the template marks it with a leading *
    kind: str                       # heading | line | total
    sheet: str
    row: int
    on_face: bool                   # its own face row, or a sub-sheet total shown on the face
    face_label: str = ""            # the face row's label, for a sub-sheet total shown on the face
    path: tuple[str, ...] = ()      # the headings above it, outermost first
    parts: list[tuple[str, float]] = field(default_factory=list)   # (field id, coefficient), for a total
    parent: Optional[str] = None    # the total it sits under in the outline
    children: list[str] = field(default_factory=list)
    used_by: list[str] = field(default_factory=list)                # every total that adds it up
    primary_concept: str = ""       # the SSM element, for its official definition
    column_label: str = ""          # an equity-statement column's label, such as "Retained earnings"

    @property
    def name(self) -> str:
        """The field as a person names it: the face label for a face-shown total."""
        return self.face_label or self.label

    @property
    def where(self) -> str:
        return SEP.join(self.path + (self.name,))

    @property
    def catch_all(self) -> bool:
        return self.kind == LINE and bool(re.match(r"(other|miscellaneous|sundry)\b", self.label, re.I))


# A word shaped like a field id: `<code>-<sheet letter?><row>`, then for an equity-statement column
# `-<column letters or digits>` ("FP-8", "FP-s141", "CE-6-B"). Only ids the outline knows are rewritten.
_ID_TOKEN = re.compile(r"\b[A-Za-z]{2,6}-[A-Za-z]?\d+(?:-[A-Za-z0-9]+)?\b")


def _segment(label: str) -> str:
    """A total's name as a heading: "*Total land and buildings" -> "Land and buildings"."""
    text = label.lstrip("*").strip()
    text = re.sub(r"^total\s+", "", text, flags=re.I)
    return text[:1].upper() + text[1:]


def _sheet_codes(sheets: list[str]) -> dict[str, str]:
    face = next((s for s in sheets if "-Sub-" not in s and "-Analysis-" not in s), sheets[0])
    rest = [s for s in sheets if s != face]
    return {face: "", **{s: "stuvwxyz"[i] for i, s in enumerate(rest)}}


@dataclass
class Outline:
    fields: dict[str, Field] = field(default_factory=dict)          # by id, in outline order
    by_uuid: dict[str, str] = field(default_factory=dict)           # concept_uuid -> id
    roots: dict[str, list[str]] = field(default_factory=dict)       # statement -> face order of ids
    loose: dict[str, list[str]] = field(default_factory=dict)       # statement -> sub-sheet roots no face row adds
    titles: dict[str, str] = field(default_factory=dict)            # statement -> template title
    folded: dict[str, str] = field(default_factory=dict)            # lower-case id -> id
    person_names: dict[str, str] = field(default_factory=dict)      # id -> the name a person finds it by
    grids: dict[str, "Grid"] = field(default_factory=dict)          # statement -> its equity grid
    aliases: dict[str, str] = field(default_factory=dict)           # a grid row id, upper case -> its label

    def get(self, field_id: str) -> Optional[Field]:
        """The field with this id, ignoring case and spaces."""
        key = "".join(str(field_id).split())
        return self.fields.get(key) or self.fields.get(self.folded.get(key.lower(), ""))

    def person_name(self, f: Field) -> str:
        """The field as a person finds it on the screen (`name_fields`)."""
        return self.person_names.get(f.id) or f.name

    def readable(self, text: str) -> str:
        """`text` with every field id the outline knows turned into the name a person finds the field by.

        The one rule for text a person reads that an agent wrote: comments, answers, guidance lines,
        summaries, figure reasons, questions and activity notes are stored through it. A word that only
        looks like an id ("MFRS-9") is left as it is."""
        def name(match: re.Match) -> str:
            token = match.group(0)
            f = self.get(token)
            if f is not None:
                return self.person_name(f)
            if token.upper() in self.aliases:   # a row of the equity grid, such as CE-11
                return self.aliases[token.upper()]
            head, dash, rest = token.rpartition("-")   # "FP-s28-and": the id, then an ordinary word
            f = self.get(head) if dash and head.count("-") == 1 else None
            return f"{self.person_name(f)}-{rest}" if f is not None else token
        return _ID_TOKEN.sub(name, text or "")

    def name_fields(self) -> None:
        """Work out, once, each field's name as a person finds it: its label (the face label for a total shown
        on the face), with an equity column's label; when that still repeats among the non-heading fields of
        its statement, headings go in front, nearest first, until it no longer repeats
        ("Current assets › Other receivables"). An asset and a liability must never read the same."""
        def base(f: Field) -> str:
            return f"{f.name} ({f.column_label})" if f.column_label else f.name

        def named(f: Field, depth: int) -> str:
            return SEP.join(f.path[len(f.path) - depth:] + (base(f),)) if depth else base(f)

        depth = {f.id: 0 for f in self.fields.values() if f.kind != HEADING}
        while True:   # each pass adds one heading to every name that still repeats and has one left to add
            groups: dict[tuple[str, str], list[Field]] = {}
            for fid in depth:
                f = self.fields[fid]
                groups.setdefault((f.statement, named(f, depth[fid]).lower()), []).append(f)
            grown = False
            for group in groups.values():
                if len(group) > 1:
                    for f in group:
                        if depth[f.id] < len(f.path):
                            depth[f.id] += 1
                            grown = True
            if not grown:
                break
        for f in self.fields.values():
            self.person_names[f.id] = named(f, depth[f.id]) if f.id in depth else base(f)

    def for_uuid(self, concept_uuid: str) -> Optional[Field]:
        fid = self.by_uuid.get(concept_uuid)
        return self.fields.get(fid) if fid else None

    def descendants(self, field_id: str) -> list[str]:
        out, stack = [], list(reversed(self.fields[field_id].children))
        while stack:
            fid = stack.pop()
            out.append(fid)
            stack.extend(reversed(self.fields[fid].children))
        return out

    def overall_sign(self, field_id: str) -> tuple[float, Optional[str]]:
        """The sign a field's value carries into the top total above it in the
        outline, and that total's id."""
        sign, current = 1.0, self.fields[field_id]
        top = None
        while current.parent:
            parent = self.fields[current.parent]
            sign *= next((c for p, c in parent.parts if p == current.id), 1.0)
            top, current = parent.id, parent
        # A face row adds into the face totals that use it; take the widest one.
        if current.used_by:
            widest = max(current.used_by, key=lambda t: len(self.fields[t].parts))
            sign *= next((c for p, c in self.fields[widest].parts if p == current.id), 1.0)
            top = widest
        return sign, top


def build(conn: sqlite3.Connection, family: lookup.RunFamily) -> Outline:
    """The outline of every statement template in the run."""
    outline = Outline()
    for statement, template_id in family.template_ids.items():
        _add_template(conn, outline, statement.value if isinstance(statement, StatementType) else statement,
                      template_id)
    outline.name_fields()
    _attach_grids(outline)
    return outline


def _attach_grids(outline: Outline) -> None:
    """The equity statement's grid of rows and columns (`grid.py`), for its view and its row names."""
    from app.extraction import grid   # grid.py builds on this module
    for statement in outline.roots:
        found = grid.build(outline, statement)
        if found is not None:
            outline.grids[statement] = found
            outline.aliases.update(grid.names(found))


def build_numeric_notes(conn: sqlite3.Connection, family: lookup.RunFamily) -> Outline:
    """The outline of the run's two numeric note templates, share capital and related parties, keyed by
    "ISSUED_CAPITAL" and "RELATED_PARTY" (ids SC-<row> and RP-<row>), for the notes agent."""
    outline = Outline()
    for note, template_id in family.note_template_ids.items():
        _add_template(conn, outline, note, template_id)
    outline.name_fields()
    return outline


def build_with_numeric_notes(conn: sqlite3.Connection, family: lookup.RunFamily) -> Outline:
    """The statements' outline with the two numeric note templates added (ids SC-<row> and RP-<row>), for the
    Reviewer when a round's comments are on share capital or related-party figures."""
    outline = Outline()
    for statement, template_id in family.template_ids.items():
        _add_template(conn, outline, statement.value if isinstance(statement, StatementType) else statement,
                      template_id)
    for note, template_id in family.note_template_ids.items():
        _add_template(conn, outline, note, template_id)
    outline.name_fields()
    _attach_grids(outline)
    return outline


def _add_template(conn: sqlite3.Connection, outline: Outline, statement: str, template_id: str) -> None:
    concepts = lookup.template_concepts(conn, template_id)
    if not concepts:
        return
    code = CODES.get(statement, statement[:2])
    sheets = list(dict.fromkeys(c.sheet for c in concepts))
    letters = _sheet_codes(sheets)
    face_sheet = next(s for s, letter in letters.items() if letter == "")
    primary = {r[0]: r[1] for r in conn.execute(
        "SELECT a.concept_uuid, a.primary_concept FROM concept_semantic_addresses a JOIN concept_nodes n "
        "ON n.concept_uuid = a.concept_uuid WHERE n.template_id = ?", (template_id,))}
    edges = lookup.edges_for(conn, {template_id})
    by_uuid: dict[str, Field] = {}
    for c in concepts:
        fid = f"{code}-{letters[c.sheet]}{c.row}" + (f"-{c.matrix_col}" if c.matrix_col else "")
        kind = HEADING if c.kind == "ABSTRACT" else TOTAL if c.is_total else LINE
        by_uuid[c.concept_uuid] = Field(fid, c.concept_uuid, statement, c.plain_label, c.label.startswith("*"),
                                        kind, c.sheet, c.row, c.sheet == face_sheet,
                                        primary_concept=primary.get(c.concept_uuid, ""),
                                        column_label=(c.matrix_col_label or "").strip() if c.matrix_col else "")
    for parent, children in edges.items():
        if parent in by_uuid:
            by_uuid[parent].parts = [(by_uuid[ch].id, coef) for ch, coef in children if ch in by_uuid]
            for ch, _ in children:
                if ch in by_uuid:
                    by_uuid[ch].used_by.append(by_uuid[parent].id)
    ids = {f.id: f for f in by_uuid.values()}
    for f in ids.values():
        f.parts.sort(key=lambda p: (ids[p[0]].sheet != f.sheet, ids[p[0]].row))

    # The face, in row order. A formula face row shows a sub-sheet total.
    alias_rows = {(sheet, row): uuid for uuid, sheet, row in lookup.aliases_for(conn, template_id)}
    face_rows = sorted({c.row for c in concepts if c.sheet == face_sheet}
                       | {r for s, r in alias_rows if s == face_sheet})
    own = {c.row: c.concept_uuid for c in concepts if c.sheet == face_sheet}
    labels = {r[0]: r[1] for r in conn.execute(
        "SELECT row, label FROM template_slots WHERE template_id = ? AND sheet = ?", (template_id, face_sheet))}
    order: list[str] = []
    heading: tuple[str, ...] = ()
    for row in face_rows:
        uuid = alias_rows.get((face_sheet, row)) or own.get(row)
        f = by_uuid[uuid]
        if f.kind == HEADING:
            if order and ids[order[-1]].kind == HEADING and ids[order[-1]].label == f.label:
                continue   # the title is printed on several rows
            heading = (f.label,) if f.label != outline.titles.get(statement) else ()
            outline.titles.setdefault(statement, f.label)
            f.path = ()
        else:
            f.path = heading
            if (face_sheet, row) in alias_rows:
                f.on_face = True
                f.face_label = (labels.get(row) or f.label).lstrip("*").strip()
                _nest(ids, f)
        order.append(f.id)
    outline.roots[statement] = order
    # An equity-statement row: every cell sits under the row's heading, not only the one the face lists.
    row_paths = {ids[fid].row: ids[fid].path for fid in order if ids[fid].kind != HEADING}
    for f in ids.values():
        if f.column_label and f.sheet == face_sheet and f.row in row_paths:
            f.path = row_paths[f.row]

    # Sub-sheet parts the face never adds up: shown as their own sections.
    heading_of = {r[0]: r[1] for r in conn.execute(
        "SELECT concept_uuid, parent_uuid FROM concept_nodes WHERE template_id = ? AND is_current = 1",
        (template_id,))}
    nested = Outline(fields=ids)
    placed = set(order) | {d for fid in order for d in nested.descendants(fid)}
    loose = []
    for f in sorted(ids.values(), key=lambda f: (f.sheet, f.row)):
        if f.id in placed or f.sheet == face_sheet or f.kind == HEADING or f.used_by:
            continue   # placed already, a heading, or nested under the total that uses it
        parent = by_uuid.get(heading_of.get(f.concept_uuid) or "")
        f.path = (parent.label,) if parent else ()
        if f.kind == TOTAL:
            _nest(ids, f)
        loose.append(f.id)
    outline.loose[statement] = loose
    # A sub-sheet heading takes its place from the first field filed under it.
    for f in ids.values():
        if f.kind == HEADING and f.sheet != face_sheet:
            first = next((by_uuid[u] for u, h in heading_of.items() if h == f.concept_uuid and u in by_uuid
                          and by_uuid[u].kind != HEADING), None)
            if first is not None:
                path = first.path
                f.path = path[:-1] if path and path[-1].lower() == f.label.lower() else path
    for f in sorted(ids.values(), key=lambda f: (f.sheet != face_sheet, f.sheet, f.row)):
        outline.fields[f.id] = f
        outline.by_uuid[f.concept_uuid] = f.id
        outline.folded[f.id.lower()] = f.id


def _nest(ids: dict[str, Field], total: Field) -> None:
    """Put a total's same-sheet parts under it, recursively, with their paths."""
    for part_id, _ in total.parts:
        part = ids[part_id]
        if part.sheet != total.sheet or part.parent is not None or part.on_face:
            continue
        part.parent = total.id
        part.path = total.path + (_segment(total.name),)
        total.children.append(part.id)
        if part.kind == TOTAL:
            _nest(ids, part)
