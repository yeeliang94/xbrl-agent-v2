"""The notes agent's look tools: set a note's look, preview its field as mTool
gets it, and flag what still differs for a person.

The look tools take no text, so they cannot change a note's words: the store
refuses a block list whose words or shape differ (`store.set_look`). Rows and
columns are numbered from 1, as `show_note_source` shows them.

The preview limits and messages are v1's (`notes/formatting_agent.py`
225-296): three previews a note, at most 12 pictures a call, and the table
font that fits when a table is too wide. Each picture is kept as a PNG in the
run's folder (`note-previews/`), so it is in the run's export.
"""
from __future__ import annotations

import asyncio
import copy
import logging
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field
from pydantic_ai import BinaryContent, RunContext

from app import db
from app.notes import blocks as note_blocks, render, store
from app.notes.coverage import MAX_PREVIEWS
from app.notes.state import NotesDeps
from app.notes.tools import actor
from app.utils.atomic_io import write_bytes_atomic
from app.utils.paths import output_dir

logger = logging.getLogger(__name__)

MAX_PREVIEW_PICTURES = 12
LOOKS = {
    "block": ("bold", "italic", "underline", "align", "indent"),
    "table": ("frame", "font_pt"),
    "row": ("role", "indent", "bold", "shaded", "line_below"),
    "column": ("role", "width", "align"),
    "cell": ("bold", "italic", "underline", "align", "valign"),
}
ROW_ROLES = ("heading", "item", "subtotal", "total")
COLUMN_ROLES = ("label", "amount", "text", "date")


class LookChange(BaseModel):
    note_id: int = Field(description="The note id.")
    block: str = Field(description="The block id, such as p23b4.")
    target: Literal["block", "table", "row", "column", "cell"] = Field(
        default="block", description="block for a heading, paragraph or list; table, row, column or cell for a "
                                     "table.")
    rows: list[int] = Field(default_factory=list, description="Row numbers from 1, for a row or cell target.")
    columns: list[int] = Field(default_factory=list, description="Column numbers from 1, for a column or cell "
                                                                 "target.")
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    underline: Optional[bool] = None
    align: Optional[Literal["left", "center", "right", "justify"]] = None
    valign: Optional[Literal["top", "middle", "bottom"]] = None
    indent: Optional[int] = Field(default=None, description="0 to 4 steps for a block, 0 to 3 for a row.")
    role: Optional[str] = Field(default=None, description="A row: heading, item, subtotal or total. A column: "
                                                          "label, amount, text or date.")
    shaded: Optional[bool] = None
    line_below: Optional[Literal["none", "single", "double"]] = Field(
        default=None, description="A rule below the row, as the source prints it.")
    line_columns: list[int] = Field(default_factory=list, description="The columns, from 1, the rule spans; empty "
                                                                      "for every column.")
    width: Optional[float] = Field(default=None, description="A column's width in percent of the table.")
    frame: Optional[Literal["none", "grid"]] = Field(default=None, description="grid only when the source boxes "
                                                                               "every cell.")
    font_pt: Optional[float] = Field(default=None, description="8 to 14, only when the preview says the table is "
                                                               "too wide.")
    unsure: list[str] = Field(default_factory=list, description="Looks you could not tell from the page, such as "
                                                                "line_below; the house style draws them.")


def not_mine(deps: NotesDeps, note_id: int) -> str:
    """Formatting sessions run side by side, each on its own notes: one plain sentence when this note is
    another session's, else empty."""
    if deps.group and note_id not in deps.group:
        return ("Another formatting session working beside this one has this note, so leave its look to that "
                "session; your notes are those in your first message.")
    return ""


def _given(change: LookChange) -> dict[str, Any]:
    keys = ("bold", "italic", "underline", "align", "valign", "indent", "role", "shaded", "line_below", "width",
            "frame", "font_pt")
    return {k: getattr(change, k) for k in keys if getattr(change, k) is not None}


def _apply_to(obj: dict, values: dict, unsure: list[str], change: LookChange) -> None:
    for key, value in values.items():
        if key == "line_below":
            value = None if value == "none" else {"style": value, "columns": [c - 1 for c in change.line_columns]}
        obj[key] = value
    obj["unsure"] = sorted((set(obj.get("unsure", [])) - set(values)) | set(unsure))


def _apply(blocks: list[dict], change: LookChange) -> Optional[str]:
    """Apply one change to the note's block list in place, or say in one sentence why it cannot be."""
    block = next((b for b in blocks if b["id"] == change.block.strip().lower()), None)
    if block is None:
        return (f"Note id {change.note_id} has no block {change.block}; its blocks are "
                f"{', '.join(b['id'] for b in blocks)}.")
    values, target = _given(change), change.target
    allowed = LOOKS[target]
    if block["kind"] == "table" and target == "block":
        return f"{block['id']} is a table, so set its look on the table, a row, a column or a cell."
    if block["kind"] != "table" and target != "block":
        return f"{block['id']} is a {block['kind']}, so it has no rows, columns or cells; use target block."
    wrong = [k for k in [*values, *change.unsure] if k not in allowed]
    if wrong:
        return f"{wrong[0]} is not a look of a {target}; a {target} takes {', '.join(allowed)}."
    if not values and not change.unsure:
        return "Give at least one look value."
    if target == "row" and values.get("role") not in (None, *ROW_ROLES):
        return f"A row's role is {', '.join(ROW_ROLES)}."
    if target == "column" and values.get("role") not in (None, *COLUMN_ROLES):
        return f"A column's role is {', '.join(COLUMN_ROLES)}."
    if target == "block":
        _apply_to(block["look"], values, change.unsure, change)
        return None
    if target == "table":
        _apply_to(block, values, change.unsure, change)
        return None
    height, width = len(block["rows"]), len(block["columns"])
    bad_row = next((r for r in change.rows if not 1 <= r <= height), None)
    if bad_row is not None:
        return f"Table {block['id']} has {height} rows, so row {bad_row} does not exist."
    bad_col = next((c for c in [*change.columns, *change.line_columns] if not 1 <= c <= width), None)
    if bad_col is not None:
        return f"Table {block['id']} has {width} columns, so column {bad_col} does not exist."
    if target in ("row", "cell") and not change.rows:
        return f"Name the rows, numbered from 1, for a {target} change."
    if target in ("column", "cell") and not change.columns:
        return f"Name the columns, numbered from 1, for a {target} change."
    if target == "row":
        for r in change.rows:
            _apply_to(block["rows"][r - 1], values, change.unsure, change)
    elif target == "column":
        for c in change.columns:
            _apply_to(block["columns"][c - 1], values, change.unsure, change)
    else:
        for r in change.rows:
            for c in change.columns:
                _apply_to(block["rows"][r - 1]["cells"][c - 1]["look"], values, change.unsure, change)
    return None


def apply_looks(conn, run_id: int, note_id: int, changes: list[LookChange], who: store.Actor, reason: str
                ) -> Optional[str]:
    """Apply look changes to one saved note and save them together, or say in one sentence why none is saved.
    Shared by the notes agent's and the Reviewer's look tools. Raises `store.Refused`."""
    blocks = copy.deepcopy(store.get_note(conn, run_id, note_id)["blocks"])
    problem = next((p for p in (_apply(blocks, c) for c in changes) if p), None)
    if problem is None:
        store.set_look(conn, run_id, note_id, blocks, who, reason=reason)
    return problem


def set_look(ctx: RunContext[NotesDeps], changes: list[LookChange], note: Optional[str] = None) -> str:
    """Set the look of placed notes: look values only, never words. A heading, paragraph or list takes
    bold, italic, underline, align and indent; a table takes frame and font_pt; a row takes role, indent, bold,
    shaded and line_below; a column takes role, width and align; a cell takes bold, italic, underline, align
    and valign. List a look you could not tell from the page in unsure. All changes to one note are saved
    together; one that cannot apply leaves that note unchanged.
    `note`: one plain sentence for the person following the run: what you are doing and why."""
    deps = ctx.deps
    if not changes:
        return "Give at least one change."
    by_note: dict[int, list[LookChange]] = {}
    for c in changes:
        by_note.setdefault(c.note_id, []).append(c)
    out = []
    for note_id, group in by_note.items():
        if not_mine(deps, note_id):
            out.append(f"- Note id {note_id}: not changed. {not_mine(deps, note_id)}")
            continue
        try:
            with db.connect(immediate=True) as conn:
                problem = apply_looks(conn, deps.run_id, note_id, group, actor(deps), deps.outline.readable(note or ""))
            if problem:
                out.append(f"- Note id {note_id}: not changed. {problem}")
                continue
        except store.Refused as exc:
            out.append(f"- Note id {note_id}: not changed. {exc}")
            continue
        deps.touched.add(note_id)
        deps.looked.add(note_id)
        deps.writes += 1
        out.append(f"- Note id {note_id}: look changed ({len(group)} change(s)). Preview it to check.")
    return "\n".join(out)


# Preview ---------------------------------------------------------------------

def _preview_folder(run_id: int):
    return output_dir() / "runs" / f"run-{int(run_id)}" / "note-previews"


def _fit_advice(pv: render.Preview) -> str:
    if not pv.overflow_mm:
        return ""
    fits = (f"It fits at {pv.fits_at_pt} pt: set font_pt {pv.fits_at_pt} on the wide table." if pv.fits_at_pt
            else f"It does not fit even at {pv.min_font_pt} pt: keep {pv.min_font_pt} pt and flag it.")
    return (f" A table is {pv.overflow_mm} mm wider than mTool's 170 mm text width even at its narrowest. The "
            f"picture is widened to show it whole, so the text wraps wider than in mTool. {fits}")


async def preview_note(ctx: RunContext[NotesDeps], note_ids: list[int], note: Optional[str] = None) -> Any:
    """Draw each note's field as mTool gets it, on mTool's page (A4, 20 mm margins), with every note placed
    in that field: the pictures, the characters used against mTool's limit, the size tier, and whether a
    table is too wide with the font at which it fits. Each note has three previews; the result says how many
    are left. At most 12 pictures a call. Compare the pictures with the source page.
    `note`: one plain sentence for the person following the run: what you are doing and why."""
    deps = ctx.deps
    if not note_ids:
        return "Name at least one note id."
    with db.connect() as conn:
        notes = store.run_notes(conn, deps.run_id, blocks=True)
    by_id = {n["id"]: n for n in notes}
    out: list[Any] = []
    fields: dict[str, list[int]] = {}
    for note_id in dict.fromkeys(note_ids):
        n = by_id.get(note_id)
        if n is None:
            out.append(f"There is no note id {note_id} in this run.")
        elif not n["field"]:
            out.append(f"Note id {note_id} is not placed, so there is no field to draw.")
        elif deps.previews.get(note_id, 0) >= MAX_PREVIEWS:
            out.append(f"Note id {note_id} has had its three previews, so {deps.PREVIEWS_USED}")
        else:
            fields.setdefault(n["field"]["node_uuid"], []).append(note_id)
    sent = 0
    for node_uuid, asked in fields.items():
        in_field = [n for n in notes if n["field"] and n["field"]["node_uuid"] == node_uuid]
        fid = deps.outline.note_ids.get(node_uuid, "the field")
        bodies = [note_blocks.parse({"blocks": n["blocks"]}) for n in in_field]
        try:
            prepared = render.prepare(bodies, render.house_style())
            pv = await asyncio.to_thread(render.preview, prepared)
        except Exception as exc:  # noqa: BLE001 - a failed drawing must not end the session
            logger.warning("Run %s: could not draw a note preview of %s.", deps.run_id, fid, exc_info=True)
            out.append(f"{fid} could not be drawn: {exc}")
            continue
        pictures = pv.pages
        if sent and sent + len(pictures) > MAX_PREVIEW_PICTURES:
            out.append(f"{fid} was not drawn in this call; preview it in a separate call.")
            continue
        cut = len(pictures) > MAX_PREVIEW_PICTURES
        pictures = pictures[:MAX_PREVIEW_PICTURES]
        sent += len(pictures)
        for n in in_field:
            deps.previewed_at[n["id"]] = n["revision"]
        for note_id in asked:
            deps.previews[note_id] = deps.previews.get(note_id, 0) + 1
        try_no = max(deps.previews[i] for i in asked)
        names = []
        for k, png in enumerate(pictures, 1):
            name = f"{fid}-notes-{'-'.join(map(str, asked))}-try-{try_no}-picture-{k}.png"
            try:
                write_bytes_atomic(_preview_folder(deps.run_id) / name, png)
                names.append(name)
            except Exception:  # noqa: BLE001 - the agent's look comes first
                logger.warning("Run %s: could not keep a preview picture.", deps.run_id, exc_info=True)
        size = (f"{prepared.chars:,} of {prepared.limit:,} characters, tier {prepared.tier}"
                + (": too long for mTool at every tier; nothing is cut, and a person decides how to split it"
                   if prepared.too_long else ""))
        left = ", ".join(f"note id {i}: {MAX_PREVIEWS - deps.previews[i]}" for i in asked)
        label = in_field[0]["field"]["label"]
        out.append(f"{fid} {label} ({len(in_field)} note(s)): {size}.{_fit_advice(pv)} Previews left: {left}."
                   + (f" Only its first {MAX_PREVIEW_PICTURES} pictures are shown." if cut else ""))
        for k, png in enumerate(pictures, 1):
            out += [f"=== {fid} as mTool gets it (picture {k} of {len(pictures)}) ===",
                    BinaryContent(png, media_type="image/png", vendor_metadata={"detail": "high"})]
        deps.event("previewed", f"Previewed {label} as mTool gets it.",
                   {"node_uuid": node_uuid, "note_ids": asked, "tier": prepared.tier, "chars": prepared.chars,
                    "overflow_mm": pv.overflow_mm, "pictures": names},
                   sorted({p for n in in_field for p in n["pages"]}))
    return out or ["Nothing to draw."]


class Flag(BaseModel):
    note_id: int
    reason: str = Field(description="One plain sentence: what still differs from the source, for a person.")


def flag_formatting(ctx: RunContext[NotesDeps], flags: list[Flag]) -> str:
    """Mark notes "Check formatting" for a person, with one sentence each on what still differs from the
    source, for example something mTool cannot draw or that is still wrong after the previews."""
    deps = ctx.deps
    if not flags:
        return "Give at least one note."
    out = []
    for f in flags:
        reason = deps.outline.readable(" ".join(f.reason.split()))
        if not_mine(deps, f.note_id):
            out.append(f"- Note id {f.note_id}: not flagged. {not_mine(deps, f.note_id)}")
            continue
        if not reason:
            out.append(f"- Note id {f.note_id}: give the reason in one plain sentence.")
            continue
        try:
            with db.connect(immediate=True) as conn:
                current = store.get_note(conn, deps.run_id, f.note_id)
                store.set_look(conn, deps.run_id, f.note_id, current["blocks"], actor(deps),
                               format_state="check_formatting", format_reason=reason, reason=reason)
        except store.Refused as exc:
            out.append(f"- Note id {f.note_id}: not flagged. {exc}")
            continue
        deps.touched.add(f.note_id)
        deps.writes += 1
        deps.event("flagged", f"Marked note {current['number'] or current['title']} for a formatting check: "
                              f"{reason}", {"note_id": f.note_id}, current["pages"])
        out.append(f"- Note id {f.note_id}: marked check formatting.")
    return "\n".join(out)
