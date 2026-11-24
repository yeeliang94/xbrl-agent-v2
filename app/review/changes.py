"""What a correction round changed, counted by the server from figure history
and note history (`note_changes.py`)
(decision record 3, item 7; document-agent-lessons 2.1).

Every write a round makes carries the round's id, and the comments it served,
in `figure_history`. From those rows: per comment, its own figures before
and after; every other figure the round changed; and the totals the template
added up again. The agent's own claim "changed" is never the proof. The same
report goes to the Reviewer after each save, clear or move, and to the
browser for a round.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from app.catalog import lookup
from app.checks.runner import read_checks
from app.figures import store
from app.figures.sums import fmt_amount
from app.notes import note_figures
from app.review import note_changes

PASSED = "passed"
ASSESSED = ("passed", "failed", "warning")


@dataclass
class _Touched:
    first_row: int
    last_row: int
    before: Optional[dict]          # the figure before the round; None when the round added it
    written: bool = False           # a save, clear, move or restore, not only a recalculation
    served: set = field(default_factory=set)


def _value(state: Optional[dict]) -> Optional[float]:
    if state is None or state.get("status") == "not_disclosed":
        return None
    return state.get("value")


def _lines(state: Optional[dict]) -> tuple:
    return tuple((line["printed_label"], line["page"], line["amount"], line["coefficient"])
                 for line in (state or {}).get("lines") or [])


def _shown(state: Optional[dict]) -> str:
    """How the figure reads to a person: blank, not disclosed, zero or a value."""
    if state is None or (state.get("value") is None and state.get("status") != "not_disclosed"):
        return "blank"
    if state.get("status") == "not_disclosed":
        return "not disclosed" if state.get("stated_value") is None else "printed total only"
    return "zero" if state.get("status") == "explicit_zero" else "a value"


def differences(before: Optional[dict], now: Optional[dict]) -> list[str]:
    """Every difference a person sees between two states of a figure, in plain words: the value, how it
    reads (blank or not disclosed), the printed amount, the certainty, the reason and the printed lines."""
    out = []
    if _value(before) != _value(now):
        out.append(f"value {_amount(_value(before))} → {_amount(_value(now))}")
    elif _shown(before) != _shown(now):
        out.append(f"shown as {_shown(before)} → {_shown(now)}")
    if (before or {}).get("stated_value") != (now or {}).get("stated_value"):
        out.append(f"printed amount {_amount((before or {}).get('stated_value'))} → "
                   f"{_amount((now or {}).get('stated_value'))}")
    if ((before or {}).get("certainty") or "sure") != ((now or {}).get("certainty") or "sure"):
        out.append(f"certainty {(before or {}).get('certainty') or 'sure'} → "
                   f"{(now or {}).get('certainty') or 'sure'}")
    if ((before or {}).get("reason") or "") != ((now or {}).get("reason") or ""):
        out.append("reason changed")
    if _lines(before) != _lines(now):
        out.append("printed lines changed")
    return out


def touched(conn: sqlite3.Connection, round_id: int) -> dict[int, _Touched]:
    """Every figure the round wrote or recalculated, by figure id."""
    out: dict[int, _Touched] = {}
    for r in conn.execute("SELECT id, figure_id, action, before_json, comment_ids_json FROM figure_history "
                          "WHERE round_id = ? ORDER BY id", (round_id,)):
        entry = out.get(r["figure_id"])
        if entry is None:
            entry = out[r["figure_id"]] = _Touched(r["id"], r["id"],
                                                   json.loads(r["before_json"]) if r["before_json"] else None)
        entry.last_row = r["id"]
        if r["action"] != "calculate":
            entry.written = True
            entry.served.update(json.loads(r["comment_ids_json"] or "[]"))
    return out


def round_comments(conn: sqlite3.Connection, round_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT c.*, rc.outcome AS round_outcome, rc.answer AS round_answer FROM round_comments rc "
        "JOIN comments c ON c.id = rc.comment_id WHERE rc.round_id = ? ORDER BY c.id", (round_id,)).fetchall()


def own_figures(conn: sqlite3.Connection, comment: sqlite3.Row) -> list[int]:
    """The figures a comment points at: one figure, every period of a line, or none for a statement."""
    if comment["target_kind"] == "figure":
        sql, params = ("SELECT id FROM figures WHERE run_id = ? AND concept_uuid = ? AND period = ? "
                       "AND entity_scope = ? AND dimension_key = ?",
                       (comment["run_id"], comment["concept_uuid"], comment["period"], comment["entity_scope"],
                        comment["dimension_key"]))
    elif comment["target_kind"] == "line":
        sql, params = ("SELECT id FROM figures WHERE run_id = ? AND concept_uuid = ? AND entity_scope = ? "
                       "AND dimension_key = ? ORDER BY period",
                       (comment["run_id"], comment["concept_uuid"], comment["entity_scope"],
                        comment["dimension_key"]))
    else:
        return []
    return [int(r[0]) for r in conn.execute(sql, params)]


class Describe:
    """Turns a figure id into a `Change`, reading each field once."""

    def __init__(self, conn: sqlite3.Connection, run_id: int, seen: dict[int, _Touched]):
        self.conn, self.run_id, self.seen = conn, run_id, seen
        self.family = lookup.run_family(conn, run_id)
        self.concepts: dict[str, Optional[lookup.Concept]] = {}

    def change(self, figure_id: int) -> dict:
        row = self.conn.execute("SELECT * FROM figures WHERE id = ?", (figure_id,)).fetchone()
        uuid = row["concept_uuid"]
        if uuid not in self.concepts:
            self.concepts[uuid] = lookup.concept(self.conn, uuid)
        concept = self.concepts[uuid]
        statement = self.family.statement_of(concept.template_id) if concept and self.family else None
        code = statement.value if statement else note_figures.numeric_code(self.family,
                                                                           concept.template_id if concept else None)
        now_state = store.figure_state(self.conn, self.run_id, figure_id)
        entry = self.seen.get(figure_id)
        before = entry.before if entry else now_state
        found = differences(before, now_state) if entry is not None else []
        return {"figure_id": figure_id, "statement": code, "concept_uuid": uuid,
                "field_label": concept.plain_label if concept else "", "period": row["period"],
                "entity_scope": row["entity_scope"], "dimension_key": row["dimension_key"],
                "was": _value(before), "is_now": _value(now_state),
                "changed": bool(found), "differences": found,
                "served": sorted(entry.served) if entry else []}


def _check_counts(checks: list[dict]) -> dict:
    out: dict[str, int] = {}
    for c in checks:
        out[c["status"]] = out.get(c["status"], 0) + 1
    return out


FAILING = ("failed", "warning")


def check_summary(before: list[dict], now: list[dict], relevant=lambda name: True) -> dict:
    """Counts before and now, and the newly failing checks: relevant ones that passed before and now fail or
    warn. A check that could no longer be assessed is not "newly failing", and `assessed` false says no check
    could be assessed at all, which is never shown as passed."""
    passed_before = {(c["name"], c["entity_scope"]) for c in before if c["status"] == PASSED}
    newly = [{"name": c["name"], "entity_scope": c["entity_scope"], "title": c["title"], "status": c["status"],
              "message": c["message"]}
             for c in now if (c["name"], c["entity_scope"]) in passed_before and c["status"] in FAILING
             and relevant(c["name"])]
    return {"before": _check_counts(before), "now": _check_counts(now), "newly_failing": newly,
            "assessed": any(c["status"] in ASSESSED for c in now)}


def report(conn: sqlite3.Connection, run_id: int, round_id: int) -> dict:
    """`RoundReport` (docs/api-contract.md, Step 5a)."""
    seen = touched(conn, round_id)
    notes_seen = note_changes.touched(conn, round_id)
    note_change = {n: note_changes.change(conn, n, t) for n, t in notes_seen.items()}
    describe = Describe(conn, run_id, seen)
    claimed: set[int] = set()
    claimed_notes: set[int] = set()
    per_comment = []
    for c in round_comments(conn, round_id):
        ids = list(dict.fromkeys(own_figures(conn, c) + [f for f, t in seen.items() if c["id"] in t.served]))
        own = set(own_figures(conn, c))
        claimed |= own
        figures = [describe.change(f) for f in ids]
        own_note = note_changes.own_note(c)
        claimed_notes |= {own_note} if own_note else set()
        note_ids = list(dict.fromkeys(([own_note] if own_note else [])
                                      + [n for n, t in notes_seen.items() if c["id"] in t.served]))
        notes = [note_change.get(n) or note_changes.change(conn, n, None) for n in note_ids]
        changed = any(f["changed"] for f in figures) or any(n["changed"] for n in notes)
        outcome = c["round_outcome"]
        per_comment.append({"comment_id": c["id"], "outcome": outcome, "answer": c["round_answer"],
                            "changed": changed, "verified": outcome == "changed" and changed, "figures": figures,
                            "notes": notes})
    written_for = {f for entry in per_comment for f in (x["figure_id"] for x in entry["figures"])}
    other = [describe.change(f) for f, t in seen.items() if t.written and f not in claimed]
    totals = [describe.change(f) for f, t in seen.items() if not t.written and f not in written_for]
    totals = [t for t in totals if t["changed"]]
    other = [o for o in other if o["changed"]]
    checks_before = json.loads(conn.execute("SELECT checks_before_json FROM rounds WHERE id = ?",
                                            (round_id,)).fetchone()[0] or "[]")
    notes_other = [c for n, c in note_change.items() if n not in claimed_notes and c["changed"]]
    notes_changed = sum(1 for c in note_change.values() if c["changed"])
    return {"round_id": round_id, "comments": per_comment, "other": other, "totals_recalculated": totals,
            "notes_other": notes_other,
            "counts": {"comments": len(per_comment), "changed": sum(1 for c in per_comment if c["changed"]),
                       "other": len(other), "totals_recalculated": len(totals), "notes": notes_changed},
            "checks": check_summary(checks_before, read_checks(conn, run_id),
                                    _relevant_for(conn, describe.family, round_id))}


def _relevant_for(conn: sqlite3.Connection, family, round_id: int):
    """The Reviewer's own filter (`state.check_filter`): the same checks its run_checks shows."""
    from app.review.state import check_filter, round_statements

    if family is None:
        return lambda name: False
    comments = round_comments(conn, round_id)
    numeric = any(c["statement"] in ("ISSUED_CAPITAL", "RELATED_PARTY") for c in comments)
    return check_filter(family, round_statements(family, comments), numeric)


# The agent's view ----------------------------------------------------------------

def _amount(value: Optional[float]) -> str:
    return "blank" if value is None else fmt_amount(value)


def _name(change: dict, field_id) -> str:
    fid = field_id(change["concept_uuid"])
    return f"{fid + ' ' if fid else ''}{change['field_label']} {change['period']}"


def _said(change: dict, field_id) -> str:
    """One figure's change: its value before and now, then anything else a person would see differ."""
    rest = [d for d in change["differences"] if not d.startswith("value ")]
    return (f"{_name(change, field_id)} was {_amount(change['was'])}, is now {_amount(change['is_now'])}"
            + (f" ({', '.join(rest)})" if rest else ""))


def report_text(rep: dict, field_id=lambda uuid: None) -> str:
    """The report as the Reviewer reads it after each change. `field_id` gives an outline id for a field."""
    out = ["What this round has changed so far, counted by the server from the figure and note history:"]
    for c in rep["comments"]:
        moved = [f for f in c["figures"] if f["changed"]]
        if not moved:
            if not any(n["changed"] for n in c.get("notes", [])):
                out.append(f"- Comment {c['comment_id']}: nothing has changed for it yet.")
            continue
        parts = "; ".join(_said(f, field_id) for f in moved)
        out.append(f"- Comment {c['comment_id']}: {parts}.")
    if rep["other"]:
        out.append("Other figures changed, which no comment points at:")
        out += [f"- {_said(o, field_id)}"
                + (f" (written for comment {', '.join(map(str, o['served']))})" if o["served"]
                   else " (written for no comment)") for o in rep["other"]]
    out += note_changes.text_lines({c["comment_id"]: c.get("notes", []) for c in rep["comments"]},
                                   rep.get("notes_other", []))
    if rep["totals_recalculated"]:
        out.append("Totals recalculated: " + "; ".join(
            f"{_name(t, field_id)} {_amount(t['was'])} to {_amount(t['is_now'])}" for t in rep["totals_recalculated"])
            + ".")
    return "\n".join(out)
