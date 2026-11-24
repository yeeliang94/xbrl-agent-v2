"""Advice after a save: points to check, never refusals.

v1 kept these as tool feedback (docs/agent-lessons.md section 7): a sign
that looks wrong, a likely double booking, a catch-all filled beside empty
dedicated fields. v1 judged signs from phrase lists; here a sign is judged
from the template alone, through the outline's coefficients. Added in v2: a
face row fed by the sub-sheet whose lines are all empty.
"""
from __future__ import annotations

from typing import Mapping, Optional

from app.extraction.outline import LINE, TOTAL, Outline
from app.figures.sums import fmt_amount

PERIOD_WORDS = {"CY": "this year", "PY": "last year"}
MAX_NAMED = 8

# (concept_uuid, period) -> saved figure: {"value", "stated_value", "children_status"}
Saved = Mapping[tuple[str, str], dict]


def _value(saved: Saved, uuid: str, period: str) -> Optional[float]:
    row = saved.get((uuid, period))
    return None if row is None else row.get("value")


def _typed(outline: Outline, saved: Saved, fid: str, period: str) -> Optional[float]:
    """A figure the agent typed: a line's value, or a total kept with no breakdown."""
    f = outline.fields[fid]
    row = saved.get((f.concept_uuid, period))
    if row is None or row.get("value") is None:
        return None
    if f.kind == TOTAL and row.get("children_status") != "aggregate_only":
        return None
    return row["value"]


def _names(outline: Outline, ids: list[str]) -> str:
    shown = [f"{fid} {outline.fields[fid].name}" for fid in ids[:MAX_NAMED]]
    more = f" and {len(ids) - MAX_NAMED} more" if len(ids) > MAX_NAMED else ""
    return ", ".join(shown) + more


def sign_point(outline: Outline, fid: str, period: str, value: float) -> Optional[str]:
    """A negative figure, explained through the template's formula: either it
    is a deduction the total adds (right), or a field the total subtracts
    saved negative, which turns a deduction into an addition."""
    if value > -0.005:
        return None
    sign, top = outline.overall_sign(fid)
    if top is None:
        return None
    f, total = outline.fields[fid], outline.fields[top].name
    when = PERIOD_WORDS[period]
    if sign < 0:
        return (f"{fid} {f.name} is saved as {fmt_amount(value)} for {when}, but {total} subtracts this field, so "
                f"the negative value adds {fmt_amount(abs(value))} to it. If the report shows a deduction, save it "
                "positive.")
    return (f"{fid} {f.name} is saved as {fmt_amount(value)} for {when}, so it reduces {total}. That is right for "
            "a deduction, such as accumulated losses; otherwise check the sign.")


def _related(outline: Outline, a: str, b: str) -> bool:
    return b in outline.descendants(a) or a in outline.descendants(b)


def _totals_above(outline: Outline, fid: str) -> set[str]:
    """Every total a field adds into, directly or through other totals."""
    out: set[str] = set()
    stack = list(outline.fields[fid].used_by) + ([outline.fields[fid].parent] if outline.fields[fid].parent else [])
    while stack:
        total = stack.pop()
        if total in out:
            continue
        out.add(total)
        stack += outline.fields[total].used_by
    return out


def double_points(outline: Outline, saved: Saved, fid: str, period: str, value: float) -> list[str]:
    """The same amount typed in two fields of one statement that add into a common total, where it truly
    counts twice. Fields with no total in common (an asset and a liability) may well hold the same amount."""
    if abs(value) < 0.005:
        return []
    out = []
    statement, above = outline.fields[fid].statement, _totals_above(outline, fid)
    for other, f in outline.fields.items():
        if other == fid or f.statement != statement or f.kind not in (LINE, TOTAL):
            continue
        typed = _typed(outline, saved, other, period)
        if (typed is not None and abs(abs(typed) - abs(value)) < 0.005 and not _related(outline, fid, other)
                and above & _totals_above(outline, other)):
            first, second = sorted((fid, other), key=lambda i: (outline.fields[i].sheet, outline.fields[i].row))
            out.append(f"{first} {outline.fields[first].name} and {second} {outline.fields[second].name} both hold "
                       f"{fmt_amount(abs(value))} for {PERIOD_WORDS[period]}. If they are the same printed amount, "
                       "keep it in one field only.")
    return out


def _siblings(outline: Outline, fid: str) -> list[str]:
    f = outline.fields[fid]
    if f.parent:
        return outline.fields[f.parent].children
    if f.used_by:
        smallest = min(f.used_by, key=lambda t: len(outline.fields[t].parts))
        return [p for p, _ in outline.fields[smallest].parts]
    return []


def catch_all_point(outline: Outline, saved: Saved, fid: str, periods: tuple[str, ...]) -> Optional[str]:
    f = outline.fields[fid]
    if not f.catch_all:
        return None
    empty = [s for s in _siblings(outline, fid) if s != fid and outline.fields[s].kind == LINE
             and not outline.fields[s].catch_all
             and all(_value(saved, outline.fields[s].concept_uuid, p) is None for p in periods)]
    if not empty:
        return None
    return (f"{fid} {f.name} is filled while the dedicated fields beside it are empty: {_names(outline, empty)}. "
            "\"Other\" is a conclusion: check the note for a dedicated field first, and say in the reason what "
            "you looked for.")


def face_row_point(outline: Outline, saved: Saved, fid: str, period: str) -> Optional[str]:
    f = outline.fields[fid]
    if f.kind != TOTAL or not f.face_label:
        return None
    if any(_value(saved, outline.fields[d].concept_uuid, period) is not None for d in outline.descendants(fid)
           if outline.fields[d].kind == LINE):
        return None
    row = saved.get((f.concept_uuid, period)) or {}
    kept = " A total kept with no breakdown is replaced by the formula in mTool." \
        if row.get("children_status") == "aggregate_only" else ""
    return (f"{fid} {f.name} is a face row fed by its sub-sheet lines, and none of them is saved for "
            f"{PERIOD_WORDS[period]}, so the face row stays blank.{kept} Save the lines nested under it.")


def advice(outline: Outline, saved: Saved, written: list[tuple[str, str]],
           periods: tuple[str, ...]) -> list[tuple[str, str]]:
    """Points to check after a save, each with the field it is about. `written`
    lists (field id, period) saved just now."""
    out: list[tuple[str, str]] = []
    for fid, period in written:
        f = outline.fields[fid]
        typed = _typed(outline, saved, fid, period)
        if typed is not None:
            if f.kind == LINE:
                out += [(fid, p) for p in [sign_point(outline, fid, period, typed)] if p]
            out += [(fid, p) for p in double_points(outline, saved, fid, period, typed)]
        out += [(fid, p) for p in [face_row_point(outline, saved, fid, period)] if p]
    for fid in dict.fromkeys(fid for fid, _ in written):
        point = catch_all_point(outline, saved, fid, periods)
        if point:
            out.append((fid, point))
    return list(dict.fromkeys(out))


def points(outline: Outline, saved: Saved, written: list[tuple[str, str]], periods: tuple[str, ...]) -> list[str]:
    """The points' sentences, each once."""
    return list(dict.fromkeys(p for _, p in advice(outline, saved, written, periods)))
