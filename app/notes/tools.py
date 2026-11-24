"""The notes agent's tools for the notes list, the source and the fields, and
placing a note.

Fields are named by id (`state.NotesOutline`), notes by their number as
printed and, once placed, by their note id. Every tool takes a list, so one
call does a batch. A bad request is answered with plain sentences as the
result, so it costs none of the tool's retries. Every write goes through
the note store (`app/notes/store.py`); its refusals (the hard stops) come
back to the agent word for word. Code copies the words: the agent names
blocks, never text.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from app import db
from app.catalog import definitions
from app.catalog.note_fields import NoteField
from app.catalog.statements import NOTE_TEMPLATES
from app.extraction.tools import _match as match_score
from app.notes import coverage, source, store
from app.notes.state import NotesDeps
from app.runs.events import clean_note

MAX_QUERIES = 12
MAX_MATCHES = 6
MAX_NOTES = 4
MAX_MEANING = 240


def actor(deps: NotesDeps) -> store.Actor:
    return store.Actor("agent", deps.actor_name)


def unknown_field(fid: str) -> str:
    return f"{fid} is not a note field id; find the field with find_note_fields."


def field_line(deps: NotesDeps, f: NoteField) -> str:
    marks = [m for m, on in (("required", f.mandatory), ("catch-all", f.catch_all)) if on]
    where = " › ".join((*f.path, f.label))
    return (f"{deps.outline.note_ids[f.field_id]} ({NOTE_TEMPLATES[f.template]}) {where}"
            + (f" [{', '.join(marks)}]" if marks else ""))


@lru_cache(maxsize=4)
def _by_local(standard: str) -> dict[str, str]:
    return {e["concept_id"].split("_", 1)[-1]: " ".join(e.get("definition", "").split())
            for e in definitions.load(standard)}


def definition(standard: str, element: Optional[str]) -> str:
    if not element:
        return ""
    return definitions.definition_of(standard, element) or _by_local(standard).get(element.split("_", 1)[-1], "")


# The notes list and the source ------------------------------------------------

def list_notes(ctx: RunContext[NotesDeps]) -> str:
    """The notes list a person confirmed at setup, with where each note is placed or reported so far,
    and any placed note that is not in the list."""
    deps = ctx.deps
    with db.connect() as conn:
        status = coverage.status(conn, deps)
    out = ["The confirmed notes list (number, title, PDF pages) and where each note stands:"]
    for line in status.lines:
        out.append(f"- {line}")
    if status.extra:
        out += ["Placed notes that are not in the list:", *[f"- {x}" for x in status.extra]]
    if status.reports:
        out += ["Reports so far:", *[f"- {x}" for x in status.reports]]
    return "\n".join(out)


def holders(conn, deps: NotesDeps) -> dict[str, str]:
    """Block id -> where it is placed, for the "[placed: ...]" marks."""
    out: dict[str, str] = {}
    for n in store.run_notes(conn, deps.run_id, blocks=True):
        if n["field"]:
            for b in n["blocks"]:
                out[b["id"]] = f"note id {n['id']} in {deps.outline.note_ids.get(n['field']['node_uuid'], '')}"
    return out


def note_text(deps: NotesDeps, position: int, holder: dict[str, str]) -> str:
    """One listed note's source blocks with their ids, as show_note_source gives them."""
    note = deps.notes_list[position]
    span = source.note_span(deps.contents, deps.notes_list, position, deps.page_count)
    head = f"=== Note {note['number'] or '(no number)'} {note['title']}, listed on p{note['first_page']}"
    head += (f"-{note['last_page']}" if note["last_page"] != note["first_page"] else "") + ":"
    if not span:
        return head + "\nNo transcribed blocks on these pages; view the pages and report a gap if the text is missing."
    lines = [head]
    for block in span:
        described = source.describe(block)
        if block.id in holder:
            described[0] += f" [placed: {holder[block.id]}]"
        lines += described
    last = span[-1]
    if len(span) >= source.MAX_BLOCKS:
        lines.append(f"(Shown up to {last.id}; the note may go on. Read the next page.)")
    else:
        lines.append(f"(Ends before the next note heading after {last.id}. Check the page to confirm.)")
    return "\n".join(lines)


def show_note_source(ctx: RunContext[NotesDeps], notes: list[str]) -> str:
    """A note's source blocks with their ids, across its pages, from its heading on to the next note
    heading, up to 4 notes at a time. Name each note by its number as printed in the notes list (or its
    title when it has no number). Tables are shown row by row, rows numbered from 1. A block already placed
    says where. Your first message already holds this for every listed note, as it was then."""
    deps = ctx.deps
    if not notes:
        return "Name at least one note."
    if len(notes) > MAX_NOTES:
        return f"Ask for at most {MAX_NOTES} notes at a time."
    with db.connect() as conn:
        holder = holders(conn, deps)
    out = []
    for wanted in notes:
        position = coverage.find_listed(deps.notes_list, wanted)
        if position is None:
            out.append(f"{wanted!r} is not in the notes list; give its number as listed, or read the pages.")
            continue
        out.append(note_text(deps, position, holder))
    return "\n\n".join(out)


# Fields --------------------------------------------------------------------------

def find_note_fields(ctx: RunContext[NotesDeps], queries: list[str]) -> str:
    """Find note fields by label or meaning (their official definitions count too), up to 12 queries at
    a time. Each match gives the field id, its template and its place under its headings, and whether it is
    required or the template's catch-all."""
    deps = ctx.deps
    if not queries:
        return "Give at least one query."
    if len(queries) > MAX_QUERIES:
        return f"Ask at most {MAX_QUERIES} queries at a time."
    standard = deps.family.standard
    candidates = [(f, definition(standard, f.taxonomy_element_id)) for f in deps.outline.notes.values()
                  if not f.heading]
    parts = []
    for query in queries:
        scored = sorted(((s, f) for f, meaning in candidates
                         if (s := match_score(query, f.label, " ".join(f.path), meaning)) > 0.6),
                        key=lambda pair: -pair[0])[:MAX_MATCHES]
        if not scored:
            parts.append(f"{query!r}: no field matches; try other words, or use the template's catch-all.")
            continue
        parts.append(f"{query!r}:\n" + "\n".join(f"- {field_line(deps, f)}" for _, f in scored))
    return "\n".join(parts)


def show_note_fields(ctx: RunContext[NotesDeps], fields: list[str]) -> str:
    """Show note fields in detail, up to 6 at a time: the place under its headings, required and
    catch-all marks, the official definition, and the notes placed there now in order."""
    deps = ctx.deps
    if not fields:
        return "Name at least one field id."
    if len(fields) > 6:
        return "Ask for at most 6 fields at a time."
    with db.connect() as conn:
        placed = store.run_notes(conn, deps.run_id)
    out = []
    for fid in fields:
        f = deps.outline.note_field(fid)
        if f is None:
            out.append(unknown_field(fid))
            continue
        lines = [field_line(deps, f)]
        if f.heading:
            lines.append("A heading: it holds no note; place notes in a field under it.")
        meaning = definition(deps.family.standard, f.taxonomy_element_id)
        lines.append(f"Definition: {meaning or 'none is recorded.'}")
        here = [n for n in placed if n["field"] and n["field"]["node_uuid"] == f.field_id]
        lines.append("Placed here: " + ("; ".join(f"note id {n['id']} (note {n['number'] or '-'} {n['title']}"
                                                  + (f", part {n['part']} of {n['parts']}" if n["parts"] > 1 else "")
                                                  + ")" for n in here) if here else "nothing yet."))
        out.append("\n".join(lines))
    return "\n\n".join(out)


def lookup_definitions(ctx: RunContext[NotesDeps], queries: list[str]) -> str:
    """The official SSM definitions, up to 12 at a time. A query is a note field id (that field's
    definition) or words (the best-matching definitions, with the note fields that carry each)."""
    deps = ctx.deps
    if not queries:
        return "Give at least one field id or term."
    if len(queries) > MAX_QUERIES:
        return f"Ask at most {MAX_QUERIES} at a time."
    standard = deps.family.standard
    carriers: dict[str, list[str]] = {}
    for fid, f in deps.outline.notes.items():
        if f.taxonomy_element_id and not f.heading:
            carriers.setdefault(f.taxonomy_element_id.split("_", 1)[-1], []).append(fid)
    out = []
    for query in queries:
        f = deps.outline.note_field(query)
        if f is not None:
            out.append(f"{query} {f.label}: {definition(standard, f.taxonomy_element_id) or 'no official definition is recorded for this field.'}")
            continue
        found = definitions.search(standard, query)
        if not found:
            out.append(f"{query!r}: no official definition matches.")
            continue
        lines = []
        for e in found:
            ids = carriers.get(e["concept_id"].split("_", 1)[-1])
            lines.append(f"- {e['label']}: {' '.join(e['definition'].split())}"
                         + (f" Fields: {', '.join(ids)}." if ids else " Not a note field."))
        out.append(f"{query!r}:\n" + "\n".join(lines))
    return "\n".join(out)


# Placing -------------------------------------------------------------------------

class Placement(BaseModel):
    note: str = Field(description="The note's number as printed in the notes list, such as 4 or 12(b); "
                                  "empty for a note with no number.")
    title: str = Field(default="", description="The note's title as printed; leave it empty to use the list's.")
    field: str = Field(description="The note field id, such as LIST-40.")
    blocks: list[str] = Field(description="The source blocks in reading order: ids such as p23b4, or ranges "
                                          "such as p23b4-p24b2. Code copies their words.")
    part: int = Field(default=1, description="For a note split at a first-level sub-section: this part's number.")
    parts: int = Field(default=1, description="For a split note: how many parts it has in all.")
    double: bool = Field(default=False, description="True only for share capital, the one note placed whole twice: "
                                                     "once in the list of notes' share capital field and once in "
                                                     "the issued capital text field. Code refuses it elsewhere. A "
                                                     "split note's opening paragraph at the start of each part needs "
                                                     "no double.")
    certainty: Literal["sure", "unsure"] = "sure"
    reason: str = Field(default="", description="One line: why this field.")


def _is_note(n: dict, number: str, title: str) -> bool:
    if number:
        return source.plain_number(n["number"]) == source.plain_number(number)
    return not n["number"] and n["title"].lower() == title.lower()


def _same_note(n: dict, number: str, title: str, part: int) -> bool:
    return n["part"] == part and _is_note(n, number, title)


def _foreign_heading(deps: NotesDeps, pairs: list[tuple[int, int]], number: str) -> Optional[str]:
    """The first block after the first that is printed as another listed note's heading, if any."""
    others = [n for n in deps.notes_list if source.plain_number(n["number"]) != source.plain_number(number)]
    for page, index in pairs[1:]:
        blocks = (deps.contents.get(page) or {}).get("blocks", [])
        if index < len(blocks) and any(source.starts_note(blocks[index], n) for n in others):
            return f"p{page}b{index}"
    return None


def _chosen(deps: NotesDeps, fid: str, f: NoteField) -> str:
    """The chosen field as the agent should check it: id, template, label and its official meaning."""
    meaning = definition(deps.family.standard, f.taxonomy_element_id)
    if len(meaning) > MAX_MEANING:
        meaning = meaning[:MAX_MEANING - 1] + "…"
    return f"{fid} ({NOTE_TEMPLATES[f.template]}) {f.label}" + (f", meaning: {meaning}" if meaning else "")


def share_capital(f: NoteField) -> bool:
    """The two fields that may hold the same share capital note: the issued capital text field and the list of
    notes' share capital field (owner's product decision, `docs/agent-lessons.md`; not "issued capital")."""
    return f.template == "ISSUED_CAPITAL" or (f.template == "LIST_OF_NOTES" and "share capital" in f.label.lower())


def _field_of(deps: NotesDeps, note: dict) -> Optional[NoteField]:
    fid = deps.outline.note_ids.get(note["field"]["node_uuid"])
    return deps.outline.note_field(fid) if fid else None


def _double_refusal(deps: NotesDeps, f: NoteField, held: list[dict]) -> Optional[str]:
    """Why this double is refused, or None. It pairs the issued capital text field with the list's share capital
    field, and the blocks may already sit only in the other one of the two."""
    if not share_capital(f):
        return (f"{f.label} is not a share capital field, so a note is placed in it once: set double to false.")
    for n in held:
        other = _field_of(deps, n)
        if other is None or not share_capital(other) or (other.template == "ISSUED_CAPITAL") == (
                f.template == "ISSUED_CAPITAL"):
            return (f"Some of these blocks are already placed: {_held_text(deps, [n])}. Content is placed once: "
                    "move that note, or place it again from other blocks.")
    return None


def _other_part(n: dict, number: str, title: str, p: Placement) -> bool:
    return p.parts > 1 and n["parts"] > 1 and n["part"] != p.part and _is_note(n, number, title)


def _opening(deps: NotesDeps, blocks: list[tuple[int, int]], note: dict) -> set[tuple[int, int]]:
    """A part's opening: its blocks before its first heading other than the note's own."""
    out: set[tuple[int, int]] = set()
    for page, index in blocks:
        on_page = (deps.contents.get(page) or {}).get("blocks") or []
        data = on_page[index] if 0 <= index < len(on_page) else {}
        if data.get("type") == "heading" and not source.starts_note(data, note):
            break
        out.add((page, index))
    return out


def _not_opening(deps: NotesDeps, n: dict, number: str, title: str, p: Placement,
                 pairs: list[tuple[int, int]]) -> Optional[list[tuple[int, int]]]:
    """For `n`, another part of this split note: the blocks the two share that are not the opening both parts
    start with (empty when every shared block is). None when `n` is not another part of this note. The team
    repeats a split note's short, general opening paragraph in every part (owner, 24 November 2026); this is the
    one other content a note may hold twice, so code checks it is the opening and no more."""
    if not _other_part(n, number, title, p):
        return None
    theirs = [(b["source"]["page"], b["source"]["block"]) for b in n.get("blocks", [])]
    note = {"number": number, "title": title}
    allowed = _opening(deps, theirs, note) & _opening(deps, pairs, note)
    return sorted((set(theirs) & set(pairs)) - allowed)


def _held_text(deps: NotesDeps, held: list[dict]) -> str:
    return "; ".join(f"note id {n['id']} (note {n['number'] or '-'} {n['title']}) in "
                     f"{deps.outline.note_ids.get(n['field']['node_uuid'], n['field']['label'])}" for n in held)


def _place_one(conn, deps: NotesDeps, p: Placement) -> str:
    f = deps.outline.note_field(p.field)
    if f is None:
        return unknown_field(p.field)
    pairs, refusal = source.parse_refs(p.blocks, deps.contents)
    if refusal:
        return refusal
    if not pairs:
        return "Name the note's blocks, such as p23b4-p24b2."
    listed = coverage.find_listed(deps.notes_list, p.note or p.title)
    title = " ".join((p.title or (deps.notes_list[listed]["title"] if listed is not None else "")).split())
    number = " ".join(p.note.split())
    name = number or title
    reason = deps.outline.readable(p.reason)
    wanted = {f"p{page}b{index}" for page, index in pairs}
    notes = store.run_notes(conn, deps.run_id, blocks=True)
    mine = [n for n in notes if n["field"] and _same_note(n, number, title, p.part)]
    here = next((n for n in mine if n["field"]["node_uuid"] == f.field_id), None)
    if here is not None and {b["id"] for b in here["blocks"]} == wanted:   # a repeat reuses the placement
        return f"Note {name} is already in {p.field} as note id {here['id']} with these blocks."
    if p.double:
        # The allowed double is a second placement: it never moves the first one, and a repeat re-places its own.
        same = here
        held = [n for n in store.placed_elsewhere(conn, deps.run_id, pairs) if same is None or n["id"] != same["id"]]
        refusal = _double_refusal(deps, f, held)
        if refusal:
            return refusal
    else:
        same = here or next(iter(mine), None)
        held = [n for n in store.placed_elsewhere(conn, deps.run_id, pairs) if same is None or n["id"] != same["id"]]
        by_id = {n["id"]: n for n in notes}
        beyond = {n["id"]: _not_opening(deps, by_id.get(n["id"], n), number, title, p, pairs) for n in held}
        extra = sorted({b for blocks in beyond.values() if blocks for b in blocks})
        if extra:
            ids = ", ".join(f"p{page}b{index}" for page, index in extra)
            return (f"{ids} {'is' if len(extra) == 1 else 'are'} already in another part of this note and not part "
                    "of its opening, the blocks before its first sub-section heading. Only the opening may start "
                    "more than one part; give each part its own sub-section.")
        held = [n for n in held if beyond[n["id"]] is None]
        if held:
            return (f"Some of these blocks are already placed: {_held_text(deps, held)}. Content is placed once, "
                    "except a split note's opening paragraph at the start of each of its parts: "
                    "move that note, or place it again from other blocks.")
    if same is not None:
        if {b["id"] for b in same["blocks"]} != wanted:
            note = store.replace_sources(conn, deps.run_id, same["id"], pairs, f.field_id, actor(deps), reason)
            done = f"placed again from {len(pairs)} other blocks in {_chosen(deps, p.field, f)}"
        elif same["field"]["node_uuid"] == f.field_id:
            return f"Note {name} is already in {p.field} as note id {same['id']} with these blocks."
        else:
            note = store.move_note(conn, deps.run_id, same["id"], f.field_id, actor(deps), reason=reason)
            done = f"moved to {_chosen(deps, p.field, f)}"
        deps.touched.add(note["id"])
        deps.writes += 1
        return f"Note {name}: {done} (note id {note['id']})."
    note = store.place_note(conn, deps.run_id, store.NotePlacement(
        number=number, title=title, sources=pairs, node_uuid=f.field_id, part=p.part, parts=p.parts,
        certainty=p.certainty, certainty_reason=reason if p.certainty == "unsure" else "",
        reason=reason), actor(deps))
    deps.touched.add(note["id"])
    deps.writes += 1
    text = f"Note {name}: placed in {_chosen(deps, p.field, f)} as note id {note['id']} ({len(pairs)} blocks)."
    foreign = _foreign_heading(deps, pairs, number)
    if foreign:
        text += (f" Point to check: block {foreign} looks like another note's heading; make sure the note ends "
                 "before it.")
    return text


def place_note(ctx: RunContext[NotesDeps], placements: list[Placement], note: Optional[str] = None) -> str:
    """Place notes in note fields by id: name the source blocks and code copies their words, with the plain
    look. One note, one field: place a note whole in the field whose meaning covers all of it; split only when no
    single field does, at a first-level sub-section, giving each part with part and parts. A note already placed and named again moves to the new field, or, named with other blocks, is placed
    again from those blocks. Each placement is judged on its own, and the result says what of each note is
    still in no field.
    `note`: one plain sentence for the person following the run: what you are doing and why."""
    deps = ctx.deps
    if not placements:
        return "Give at least one placement."
    out = []
    for p in placements:
        try:
            with db.connect(immediate=True) as conn:   # one short write each
                out.append(f"- {_place_one(conn, deps, p)}")
        except store.Refused as exc:
            out.append(f"- Note {p.note or p.title}: not placed. {exc}")
    with db.connect() as conn:
        found = coverage.status(conn, deps)
    named = dict.fromkeys(i for p in placements if (i := coverage.find_listed(deps.notes_list, p.note or p.title))
                          is not None)
    still = [found.by_note[i] for i in named if i in found.by_note]
    if still:
        out += ["Still open for these notes:", *[f"- {x}" for x in still]]
    said = clean_note(note)
    if said:
        deps.event("note", said)
    return "\n".join(out)
