"""The figure store: every read and write of a run's figures goes through here.

Agents and people call the same functions. Every write adds a history row,
recalculates the totals and re-runs the run's checks. A refused write raises
`Refused` with one plain sentence; nothing is saved.

A figure is identified as v1 identifies it: run, template field (which, on
the equity statement, includes the equity column), period, entity and
category. Its value is blank when the line is missing, never zero.

Totals: an ordinary total's value is always the sum of its lines. A write to
a total says what it is: `total="printed"` records the amount the report
prints (kept in `stated_value`, never forced to agree), and
`total="no_breakdown"` keeps a typed total when the report gives no lines.
A no-breakdown total and lines saved under it later are never forced to
agree either: the printed-totals check flags the difference.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from app.catalog import lookup
from app.catalog.dimensions import DimensionError, instance_key
from app.figures import _hard_stops as stops
from app.figures import _rows
from app.figures._hard_stops import Line
from app.figures._reads import current_figures, public as _public, run_figures
from app.figures._totals import parts_sum, recalculate_totals

__all__ = ["Actor", "Line", "Refused", "FigureWrite", "save_figure", "save_figures", "edit_by_person",
           "import_figure", "import_figures", "clear_figure", "move_figure", "confirm_figure", "restore_figure",
           "mark_sign_question", "run_figures", "current_figures", "get_figure", "figure_history", "recalculate",
           "put_back", "figure_state", "tagged", "NOT_A_NUMBER"]

NOT_A_NUMBER = "The value must be an ordinary number."
NO_PAGE = "Give the page this amount is printed on."


class Refused(ValueError):
    """A write the store will not make. `str()` is one plain sentence."""


@dataclass(frozen=True)
class Actor:
    kind: str   # "agent" or "person"
    name: str   # the agent's name or the person's email


@dataclass
class FigureWrite:
    concept_uuid: str
    period: str
    entity_scope: str
    value: Optional[float]
    lines: Optional[Sequence[Line]] = None   # None keeps the figure's current lines
    dimensions: Optional[dict[str, str]] = None
    certainty: str = "sure"
    reason: str = ""
    total: Optional[str] = None              # None, "printed" or "no_breakdown"


def _one_line(text: str) -> str:
    return " ".join(str(text or "").split())[:500]


def _family(conn: sqlite3.Connection, run_id: int) -> lookup.RunFamily:
    family = lookup.run_family(conn, run_id)
    if family is None:
        raise Refused("There is no such run.")
    return family


def _field(conn: sqlite3.Connection, family: lookup.RunFamily, concept_uuid: str) -> lookup.Concept:
    concept = lookup.concept(conn, concept_uuid)
    if concept is None or concept.template_id not in family.all_template_ids():
        raise Refused("That field is not in this run's templates.")
    return concept


def _key(conn: sqlite3.Connection, family: lookup.RunFamily, w: FigureWrite) -> tuple[str, str, str, str]:
    if w.period not in ("CY", "PY"):
        raise Refused("The period is CY (this year) or PY (last year).")
    if w.entity_scope not in family.entity_scopes:
        raise Refused("This run saves figures for Group and Company." if family.level == "group"
                      else "This run saves figures for the Company only.")
    try:
        dims = instance_key(conn, w.concept_uuid, w.dimensions)
    except DimensionError as exc:
        raise Refused(str(exc)) from exc
    return (w.concept_uuid, w.period, w.entity_scope, dims)


def _apply(conn: sqlite3.Connection, family: lookup.RunFamily, w: FigureWrite, actor: Actor,
           action: str = "save", *, kept: Optional[dict[str, Any]] = None) -> int:
    """Check one write against the hard stops and save it. No recalculation.

    `kept` holds fields set as given after the checks: an import's origin and
    lock, or a restored total's printed amount and how it is added up."""
    refusal = stops.not_a_number(w.value, w.lines or [])
    if refusal:
        raise Refused(refusal)
    concept = _field(conn, family, w.concept_uuid)
    key = _key(conn, family, w)
    label = concept.plain_label
    existing = _rows.get(conn, family.run_id, *key)
    if w.certainty not in ("sure", "unsure"):
        raise Refused("Certainty is sure or unsure.")
    if w.total not in (None, "printed", "no_breakdown"):
        raise Refused("A total is saved as printed or as a total with no breakdown.")
    value = None if w.value is None else float(w.value)
    clearing = value is None

    refusal = _field_refusal(concept)
    refusal = refusal or stops.prior_year(w.period, family.first_statements,
                                          bool(existing and existing["locked"]) and actor.kind != "import")
    refusal = refusal or stops.typed_in_workbook(existing["origin"] if existing else None, actor.kind,
                                                 _rows.typed_import(existing))
    refusal = refusal or stops.sign_question(bool(existing and existing["sign_question"]), actor.kind)
    if refusal is None and not clearing:
        refusal = stops.calculated_total(label, concept.is_total, w.total)
    # An import keeps a typed total as the workbook holds it, whatever its lines add up to: the printed-totals
    # check shows the difference (step 10d).
    if refusal is None and concept.is_total and w.total == "no_breakdown" and actor.kind != "import":
        refusal = stops.total_without_parts_agreeing(label, w.total, value, parts_sum(
            conn, family.run_id, *key))
    lines = list(w.lines) if w.lines is not None else (
        _rows.lines_of(conn, existing["id"]) if existing is not None else [])
    if actor.kind == "person" and w.lines is None and len(lines) == 1 and value is not None:
        # A person correcting a one-line figure corrects the reading of that line.
        lines = [Line(lines[0].printed_label, lines[0].page, value, lines[0].print_order,
                      lines[0].coefficient, lines[0].section)]
    refusal = refusal or stops.label_too_long(lines)
    if actor.kind != "import":  # an imported figure's source is its workbook cell
        refusal = refusal or stops.no_source(value, lines)
    if actor.kind == "agent":
        refusal = refusal or stops.zero_without_printed_zero(value, lines)
        refusal = refusal or stops.forced_balance(value, lines)
    if refusal:
        raise Refused(refusal)

    fields: dict[str, Any] = {"certainty": w.certainty, "reason": _one_line(w.reason)}
    if actor.kind == "person":
        fields["person_edited"] = 1
    if concept.is_total and w.total == "printed":
        fields["stated_value"] = value
        if existing is None:
            fields.update(origin="calculated", value=None, status="not_disclosed")
    elif clearing:
        fields.update(value=None, status="not_disclosed", stated_value=None,
                      children_status=None if not concept.is_total else "itemised")
        lines = []
    else:
        fields.update(value=value, origin=actor.kind,
                      status="explicit_zero" if abs(value) < stops.CENT
                      else "user_override" if actor.kind == "person" else "observed",
                      children_status="aggregate_only" if concept.is_total else None)
    fields.update(kept or {})
    return _rows.write(conn, family.run_id, key, fields, lines, action=action,
                       actor_kind=actor.kind, actor_name=actor.name)


def _field_refusal(concept: lookup.Concept) -> Optional[str]:
    """A field that takes no figure at all: a heading, a text field or one the template does not fill."""
    label = concept.plain_label
    refusal = stops.heading(label, concept.kind)
    if refusal is None and concept.text:
        refusal = f"{label} holds text, so save it as a note rather than a figure."
    if refusal is None and not concept.is_total and not concept.writable:
        refusal = f"{label} is not a field that takes a figure."
    return refusal


def recalculate(conn: sqlite3.Connection, run_id: int) -> None:
    """Recompute the run's totals, then its checks."""
    from app.checks.runner import run_checks

    family = _family(conn, run_id)
    recalculate_totals(conn, family)
    run_checks(conn, family)


def save_figure(conn: sqlite3.Connection, run_id: int, write: FigureWrite, actor: Actor) -> dict:
    """Save one figure. Raises `Refused`."""
    family = _family(conn, run_id)
    figure_id = _apply(conn, family, write, actor, "edit" if actor.kind == "person" else "save")
    recalculate(conn, run_id)
    return get_figure(conn, run_id, figure_id)


def edit_by_person(conn: sqlite3.Connection, run_id: int, actor: Actor, *, concept_uuid: str, period: str,
                   entity_scope: str, value: Optional[float], dimensions: Optional[dict[str, str]] = None,
                   page: Optional[int] = None, printed_label: Optional[str] = None,
                   reason: Optional[str] = None) -> dict:
    """A person's edit of one figure, found by its whole key, categories included.

    An existing figure keeps its printed lines. On a one-line figure a sent
    page or label corrects that line, and the line's amount follows the
    value. A figure with no lines yet gets one from `page` and
    `printed_label`. A total the report gives with no breakdown stays one."""
    family = _family(conn, run_id)
    concept = _field(conn, family, concept_uuid)
    key = _key(conn, family, FigureWrite(concept_uuid, period, entity_scope, value, dimensions=dimensions))
    existing = _rows.get(conn, run_id, *key)
    lines = _rows.lines_of(conn, existing["id"]) if existing is not None else []
    if not lines and value is not None:
        # A wholly blank field: the person names where the amount is printed. The label defaults to the field's.
        if type(page) is not int or page < 1:
            raise Refused(_field_refusal(concept) or NO_PAGE)
        lines = [Line(" ".join((printed_label or "").split()) or concept.plain_label, page, value)]
    elif len(lines) == 1:
        old = lines[0]
        lines = [Line(old.printed_label if printed_label is None else printed_label,
                      old.page if page is None else page, old.amount if value is None else value,
                      old.print_order, old.coefficient, old.section)]
    if reason is None:
        reason = existing["reason"] if existing is not None else ""
    total = "no_breakdown" if existing is not None and existing["children_status"] == "aggregate_only" else None
    return save_figure(conn, run_id, FigureWrite(concept_uuid, period, entity_scope, value, lines, dimensions,
                                                 "sure", reason, total), actor)


def import_figure(conn: sqlite3.Connection, run_id: int, write: FigureWrite, source_ref: str, *,
                  origin: str = "prior_workbook") -> dict:
    """Save a figure read from last year's workbook. `source_ref` names the
    workbook and cell it came from.

    `prior_workbook`: a prior-year figure kept as filed, locked for everyone.
    `typed_in_workbook`: a figure a person typed there, kept fixed against agents."""
    result = import_figures(conn, run_id, [(write, source_ref, origin)])[0]
    if not result["ok"]:
        raise Refused(result["refused"])
    return result["figure"]


def import_figures(conn: sqlite3.Connection, run_id: int,
                   items: Sequence[tuple[FigureWrite, str, str]]) -> list[dict]:
    """Import several figures, each `(write, source_ref, origin)`, with one
    recalculation at the end. Each is judged on its own, as in `save_figures`.
    A total imported with no breakdown before its lines keeps its amount."""
    family = _family(conn, run_id)
    results: list[dict] = []
    for write, source_ref, origin in items:
        if origin not in ("prior_workbook", "typed_in_workbook"):
            raise ValueError(f"Unknown import origin {origin!r}")
        conn.execute("SAVEPOINT one_import")
        try:
            if origin == "prior_workbook" and write.period != "PY":
                raise Refused("Only last year's figures are kept as filed in last year's workbook.")
            figure_id = _apply(conn, family, write, Actor("import", ""), "import", kept={
                "origin": origin, "locked": int(origin == "prior_workbook"), "source_ref": source_ref})
            conn.execute("RELEASE one_import")
            results.append({"ok": True, "figure_id": figure_id})
        except Refused as exc:
            conn.execute("ROLLBACK TO one_import")
            conn.execute("RELEASE one_import")
            results.append({"ok": False, "refused": str(exc)})
    recalculate(conn, run_id)
    for result in results:
        if result["ok"]:
            result["figure"] = get_figure(conn, run_id, result.pop("figure_id"))
    return results


def save_figures(conn: sqlite3.Connection, run_id: int, writes: Sequence[FigureWrite],
                 actor: Actor) -> list[dict]:
    """Save several figures. Each is judged on its own: a refused one does not
    stop the others. Returns one result per write, in order:
    `{"ok": True, "figure": ...}` or `{"ok": False, "refused": sentence}`."""
    family = _family(conn, run_id)
    results: list[dict] = []
    saved: list[int] = []
    for w in writes:
        conn.execute("SAVEPOINT one_figure")
        try:
            saved.append(_apply(conn, family, w, actor))
            conn.execute("RELEASE one_figure")
            results.append({"ok": True, "figure_id": saved[-1]})
        except Refused as exc:
            conn.execute("ROLLBACK TO one_figure")
            conn.execute("RELEASE one_figure")
            results.append({"ok": False, "refused": str(exc)})
    recalculate(conn, run_id)
    for result in results:
        if result["ok"]:
            result["figure"] = get_figure(conn, run_id, result.pop("figure_id"))
    return results


def clear_figure(conn: sqlite3.Connection, run_id: int, figure_id: int, actor: Actor,
                 reason: str = "") -> dict:
    row = _existing(conn, run_id, figure_id)
    return save_figure(conn, run_id, _write_from(row, value=None, reason=reason, lines=[]), actor)


def _existing(conn: sqlite3.Connection, run_id: int, figure_id: int) -> sqlite3.Row:
    row = _rows.by_id(conn, run_id, figure_id)
    if row is None:
        raise Refused("There is no such figure in this run.")
    return row


def _write_from(row: sqlite3.Row, **changes: Any) -> FigureWrite:
    dims = json.loads(row["dimension_key"]) if row["dimension_key"] else None
    base = FigureWrite(row["concept_uuid"], row["period"], row["entity_scope"], row["value"],
                       dimensions=dims, certainty=row["certainty"], reason=row["reason"])
    for name, value in changes.items():
        setattr(base, name, value)
    return base


def move_figure(conn: sqlite3.Connection, run_id: int, figure_id: int, to_concept_uuid: str,
                actor: Actor, *, whole_row: bool = False) -> list[dict]:
    """Move a figure to another field. A field that already holds a figure
    for that period gets the two added together, with both sets of lines.
    `whole_row` moves every period of the same field and entity."""
    family = _family(conn, run_id)
    first = _existing(conn, run_id, figure_id)
    rows = [first] if not whole_row else [
        r for r in conn.execute(
            "SELECT * FROM figures WHERE run_id = ? AND concept_uuid = ? AND entity_scope = ? "
            "AND dimension_key = ? AND value IS NOT NULL ORDER BY period",
            (run_id, first["concept_uuid"], first["entity_scope"], first["dimension_key"]))]
    source = _field(conn, family, first["concept_uuid"])
    if not any(row["value"] is not None and row["status"] != "not_disclosed" for row in rows):
        raise Refused("This figure is blank, so there is nothing to move.")
    if to_concept_uuid == first["concept_uuid"]:
        return [get_figure(conn, run_id, figure_id)]
    if source.is_total:
        raise Refused(stops.calculated_total(source.plain_label, True, None))
    for row in rows:  # judged before anything is written, so a refused move changes nothing
        target = _rows.get(conn, run_id, to_concept_uuid, row["period"], row["entity_scope"], row["dimension_key"])
        refusal = (stops.typed_in_workbook(row["origin"], actor.kind, _rows.typed_import(row))
                   or stops.typed_in_workbook(target["origin"] if target is not None else None, actor.kind,
                                              _rows.typed_import(target)))
        if refusal:
            raise Refused(refusal)
    moved: list[int] = []
    for row in rows:
        if row["value"] is None:
            continue
        lines = _rows.lines_of(conn, row["id"])
        target = _rows.get(conn, run_id, to_concept_uuid, row["period"], row["entity_scope"],
                           row["dimension_key"])
        value = float(row["value"])
        if target is not None and target["value"] is not None:
            value += float(target["value"])
            lines = _rows.lines_of(conn, target["id"]) + lines
        certainty = "unsure" if "unsure" in (row["certainty"], target["certainty"] if target else "") else "sure"
        moved.append(_apply(conn, family, FigureWrite(
            to_concept_uuid, row["period"], row["entity_scope"], value, lines,
            json.loads(row["dimension_key"]) if row["dimension_key"] else None,
            certainty, row["reason"]), actor, "move"))
        _apply(conn, family, _write_from(row, value=None, lines=[]), actor, "move")
    recalculate(conn, run_id)
    return [get_figure(conn, run_id, fid) for fid in moved]


def confirm_figure(conn: sqlite3.Connection, run_id: int, figure_id: int, actor: Actor, *,
                   settle: bool = True) -> dict:
    """Mark a figure as checked. A person's confirm also settles a sign-only
    difference with last year's workbook and makes it sure. With `settle`
    false only the confirm is recorded: certainty and any sign question stay."""
    from app.checks.runner import run_checks

    family = _family(conn, run_id)
    row = _existing(conn, run_id, figure_id)
    refusal = stops.sign_question(bool(row["sign_question"]), actor.kind) if settle else None
    if refusal:
        raise Refused(refusal)
    key = (row["concept_uuid"], row["period"], row["entity_scope"], row["dimension_key"])
    _rows.write(conn, run_id, key, {"certainty": "sure", "sign_question": 0} if settle else {}, None,
                action="confirm", actor_kind=actor.kind, actor_name=actor.name)
    run_checks(conn, family)
    return get_figure(conn, run_id, figure_id)


def restore_figure(conn: sqlite3.Connection, run_id: int, history_id: int, actor: Actor) -> dict:
    """Put a figure back to how it was after an earlier change: its value, its
    printed lines and, on a total, the printed amount and whether it is added
    up from its lines or given with no breakdown. Then recalculate."""
    entry = conn.execute("SELECT * FROM figure_history WHERE run_id = ? AND id = ?",
                         (run_id, history_id)).fetchone()
    if entry is None:
        raise Refused("There is no such change in this run's history.")
    if entry["action"] == "calculate":
        raise Refused("That value was added up from other lines, so restore those lines instead.")
    family = _family(conn, run_id)
    figure_id = _put_back(conn, family, _existing(conn, run_id, entry["figure_id"]),
                          json.loads(entry["after_json"]), actor)
    recalculate(conn, run_id)
    return get_figure(conn, run_id, figure_id)


def put_back(conn: sqlite3.Connection, run_id: int, states: Sequence[tuple[int, Optional[dict]]],
             actor: Actor) -> list[dict]:
    """Undo: put each figure back exactly to a state history recorded (its
    `before`), origin and edit mark included, or clear it when that state is
    None (the figure was new). One "restore" history row each, then one
    recalculation. Raises `Refused` and changes nothing if any is refused."""
    family = _family(conn, run_id)
    done = [_put_back(conn, family, _existing(conn, run_id, fid), state, actor, exact=True) for fid, state in states]
    recalculate(conn, run_id)
    return [get_figure(conn, run_id, fid) for fid in dict.fromkeys(done)]


def _put_back(conn: sqlite3.Connection, family: lookup.RunFamily, row: sqlite3.Row, snapshot: Optional[dict],
              actor: Actor, *, exact: bool = False) -> int:
    if snapshot is None:   # the figure was new: cleared, and still not a person's edit
        return _apply(conn, family, _write_from(row, value=None, lines=[], certainty="sure", reason=""),
                      actor, "restore", kept={"person_edited": 0, "origin": row["origin"]} if exact else None)
    lines = [Line(**line) for line in snapshot["lines"]]
    write = _write_from(row, value=snapshot["value"], lines=lines, certainty=snapshot["certainty"],
                        reason=snapshot["reason"])
    kept: dict[str, Any] = {}
    if exact:
        kept = {"origin": snapshot["origin"], "person_edited": snapshot["person_edited"]}
        if snapshot["value"] is not None:
            kept["status"] = snapshot["status"]
    if _field(conn, family, row["concept_uuid"]).is_total:
        if snapshot["children_status"] == "aggregate_only":
            write.total = "no_breakdown"
            kept["stated_value"] = snapshot["stated_value"]
        else:
            # Added up from its lines: the recalculation brings back its value.
            write.total, write.value = "printed", snapshot["stated_value"]
            kept["children_status"] = "itemised"
            kept.pop("status", None)
    return _apply(conn, family, write, actor, "restore", kept=kept or None)


def mark_sign_question(conn: sqlite3.Connection, run_id: int, figure_id: int, reason: str) -> dict:
    """Record an open sign-only difference with last year's workbook (step 10's comparison)."""
    row = _existing(conn, run_id, figure_id)
    key = (row["concept_uuid"], row["period"], row["entity_scope"], row["dimension_key"])
    _rows.write(conn, run_id, key, {"sign_question": 1, "certainty": "unsure", "reason": _one_line(reason)},
                None, action="flag", actor_kind="import", actor_name="")
    return get_figure(conn, run_id, figure_id)


# Reads ------------------------------------------------------------------

def get_figure(conn: sqlite3.Connection, run_id: int, figure_id: int) -> dict:
    return _public(conn, _existing(conn, run_id, figure_id))


def figure_state(conn: sqlite3.Connection, run_id: int, figure_id: int) -> Optional[dict]:
    """A figure as history records it (fields and printed lines), or None."""
    return _rows.state(conn, _rows.by_id(conn, run_id, figure_id))


tagged = _rows.tagged   # writes in the block carry a correction round and its comments


def figure_history(conn: sqlite3.Connection, run_id: int, figure_id: int) -> list[dict]:
    _existing(conn, run_id, figure_id)
    return [{"id": r["id"], "action": r["action"], "actor_kind": r["actor_kind"],
             "actor_name": r["actor_name"], "changed_at": r["changed_at"],
             "before": json.loads(r["before_json"]) if r["before_json"] else None,
             "after": json.loads(r["after_json"])}
            for r in conn.execute("SELECT * FROM figure_history WHERE run_id = ? AND figure_id = ? "
                                  "ORDER BY id", (run_id, figure_id))]
