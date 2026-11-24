"""What a notes session is given in its first message, so it need not fetch it:
every listed note's transcribed text with block ids, the candidate fields for
each note from every template with their meanings, and for a formatting
session its own notes. Also how the formatting work is split into groups that
run side by side (`look_groups`).

Candidates are a search over field labels, places and definitions, the same
search find_note_fields runs; they are a starting point, never a rule.
"""
from __future__ import annotations

import math

from app.catalog.statements import NOTE_TEMPLATES
from app.extraction.tools import _match as match_score
from app.notes import source, store, tools
from app.notes.state import NotesDeps

CANDIDATES = 4
MIN_SCORE = 0.6
LOOK_NOTES = 4          # notes holding a table per formatting session, about
MAX_LOOK_SESSIONS = 4   # formatting sessions at once
PROSE = ("CORP_INFO", "ACC_POLICIES", "LIST_OF_NOTES", "ISSUED_CAPITAL", "RELATED_PARTY")


def notes_text(conn, deps: NotesDeps) -> str:
    """Every listed note's source blocks, as show_note_source gives them now."""
    holder = tools.holders(conn, deps)
    return "\n\n".join(tools.note_text(deps, i, holder) for i in range(len(deps.notes_list)))


def candidate_lines(deps: NotesDeps) -> list[str]:
    """For each listed note, the fields from every template whose label, place or meaning best match its
    title, with their meanings, so a policy field and the disclosure field beside it are seen together."""
    standard = deps.family.standard
    fields = [(fid, f, tools.definition(standard, f.taxonomy_element_id)) for fid, f in deps.outline.notes.items()
              if not f.heading and f.template in PROSE]
    out = []
    for n in deps.notes_list:
        scored = sorted(((s, fid, f, meaning) for fid, f, meaning in fields
                         if (s := match_score(n["title"], f.label, " ".join(f.path), meaning)) > MIN_SCORE),
                        key=lambda x: -x[0])[:CANDIDATES]
        out.append(f"- Note {n['number'] or '(no number)'} {n['title']}:")
        for _, fid, f, meaning in scored:
            short = meaning if len(meaning) <= tools.MAX_MEANING else meaning[:tools.MAX_MEANING - 1] + "…"
            out.append(f"    {fid} ({NOTE_TEMPLATES[f.template]}) {f.label}" + (f": {short}" if short else ""))
        if not scored:
            out.append("    no field matches the title; search with find_note_fields or use a catch-all.")
    return out


def _has_table(note: dict) -> bool:
    return any(b["kind"] == "table" for b in note["blocks"])


def look_groups(conn, run_id: int) -> list[list[int]]:
    """The placed notes split for formatting sessions that run side by side: whole fields only (a preview
    draws the whole field), only fields holding a table, balanced by the number of table notes. Plain prose
    keeps the house look and needs no session."""
    by_field: dict[str, list[dict]] = {}
    for n in store.run_notes(conn, run_id, blocks=True):
        if n["field"]:
            by_field.setdefault(n["field"]["node_uuid"], []).append(n)
    work = [(sum(_has_table(n) for n in notes), [n["id"] for n in notes]) for notes in by_field.values()
            if any(_has_table(n) for n in notes)]
    if not work:
        return []
    total = sum(w for w, _ in work)
    count = min(MAX_LOOK_SESSIONS, max(1, math.ceil(total / LOOK_NOTES)), len(work))
    groups: list[tuple[int, list[int]]] = [(0, []) for _ in range(count)]
    for weight, ids in sorted(work, key=lambda x: -x[0]):
        k = min(range(count), key=lambda i: groups[i][0])
        groups[k] = (groups[k][0] + weight, groups[k][1] + ids)
    return [sorted(ids) for _, ids in groups if ids]


def group_text(conn, deps: NotesDeps) -> str:
    """A formatting session's own notes: each with its id and field, and its placed blocks as the agent reads
    them, tables row by row."""
    out = []
    for n in store.run_notes(conn, deps.run_id, blocks=True):
        if n["id"] not in deps.group or not n["field"]:
            continue
        fid = deps.outline.note_ids.get(n["field"]["node_uuid"], "?")
        split = f", part {n['part']} of {n['parts']}" if n["parts"] > 1 else ""
        lines = [f"=== Note id {n['id']}: note {n['number'] or '-'} {n['title']}{split}, in {fid} "
                 f"{n['field']['label']} (pages {', '.join(map(str, n['pages']))}):"]
        for b in n["blocks"]:
            page, index = b["source"]["page"], b["source"]["block"]
            data = ((deps.contents.get(page) or {}).get("blocks") or [])
            if index < len(data):
                lines += source.describe(source.Block(page, index, data[index]))
        out.append("\n".join(lines))
    return "\n\n".join(out)
