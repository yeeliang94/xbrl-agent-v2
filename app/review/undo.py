"""Undo a comment's changes: every figure and every note the round changed for
it goes back, exactly, to its state just before the round, through the figure
store's and the note store's restore paths (a "restore" history row each,
then totals and checks again).

One write can serve two comments, so a figure changed for this comment and
another of the same round undoes that comment too. Changes the round made
for no comment are left: they are not this comment's to undo.
"""
from __future__ import annotations

import sqlite3

from app.figures import store
from app.notes import store as note_store
from app.review import changes, comments, note_changes, note_parts
from app.review.comments import CommentRefused
from app.review.rounds import active


_WORDS = {"accepted": "already accepted", "open": "being answered again after a reply",
          "sent": "in a round now", "done": "marked done"}


def _written_for(conn: sqlite3.Connection, comment: sqlite3.Row, seen: dict) -> set[int]:
    """Figures the round wrote (not only recalculated) for this comment, or at its own target."""
    own = set(changes.own_figures(conn, comment))
    return {f for f, t in seen.items() if t.written and (comment["id"] in t.served or f in own)}


def _notes_for(comment: sqlite3.Row, seen: dict) -> set[int]:
    """Notes the round wrote for this comment, or at its own note."""
    own = note_changes.own_note(comment)
    return {n for n, t in seen.items() if comment["id"] in t.served or n == own}


def undo(conn: sqlite3.Connection, run_id: int, comment_id: int, email: str
         ) -> tuple[list[dict], list[dict], list[dict]]:
    """Returns (every comment undone, the figures put back, the notes put back). Use inside
    `db.connect(immediate=True)`. Raises CommentRefused or store.Refused."""
    first = comments.row(conn, run_id, comment_id)
    if first["status"] != "answered" or first["round_id"] is None:
        raise CommentRefused("Only an answered comment can be undone.", 409)
    if active(conn, run_id) is not None:
        raise CommentRefused("A correction round is running, so undo when it ends.", 409)
    status = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()["status"]
    if status != "in_review":   # extraction running again after Try again, or waiting for an answer
        raise CommentRefused("Undo once the run is back in review.", 409)
    round_id = first["round_id"]
    seen = changes.touched(conn, round_id)
    seen_notes = note_changes.touched(conn, round_id)
    others = [c for c in changes.round_comments(conn, round_id) if c["status"] != "undone"]
    figures = _written_for(conn, first, seen)
    notes = _notes_for(first, seen_notes)
    if not figures and not notes:
        raise CommentRefused("Nothing changed for this comment, so there is nothing to undo.", 409)
    undone = {first["id"]}
    grew = True
    while grew:   # comments sharing a figure or a note are undone together
        grew = False
        for c in others:
            if c["id"] not in undone and (_written_for(conn, c, seen) & figures or _notes_for(c, seen_notes) & notes):
                if c["status"] != "answered":
                    # Reversing its change would leave that comment saying something no longer true.
                    state = _WORDS.get(c["status"], c["status"])
                    raise CommentRefused(f"This would also reverse comment {c['id']}'s change, which is {state}, "
                                         "so restore the figure from its history instead.", 409)
                undone.add(c["id"])
                figures |= _written_for(conn, c, seen)
                notes |= _notes_for(c, seen_notes)
                grew = True
    for figure_id in sorted(figures):
        # Anything outside this round since its first write on the figure, a person's edit made while the
        # round worked included, would be wiped by putting the figure back.
        later = conn.execute(
            "SELECT 1 FROM figure_history WHERE figure_id = ? AND id > ? AND action NOT IN ('calculate', 'confirm') "
            "AND (round_id IS NULL OR round_id != ?) LIMIT 1", (figure_id, seen[figure_id].first_row, round_id)
        ).fetchone()
        if later is not None:
            label = changes.Describe(conn, run_id, seen).change(figure_id)["field_label"]
            raise CommentRefused(f"{label} was changed outside this round after the round first wrote it, so "
                                 "restore it from its history instead.", 409)
    for note_id in sorted(notes):
        later = conn.execute(
            # A person's confirm counts: it settles the note's gaps, so putting the note back would undo half of it.
            "SELECT 1 FROM note_history WHERE note_id = ? AND id > ? AND NOT (action = 'confirm' AND "
            "actor_kind = 'agent') AND (round_id IS NULL OR round_id != ?) LIMIT 1",
            (note_id, seen_notes[note_id].first_row, round_id)
        ).fetchone()
        if later is not None:
            name = note_parts.note_title(conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone())
            raise CommentRefused(f"{name} was changed outside this round after the round first wrote it, so "
                                 "restore it from its history instead.", 409)
    actor = store.Actor("person", email)
    put_back = store.put_back(conn, run_id, [(f, seen[f].before) for f in sorted(figures)], actor) if figures else []
    notes_back = note_store.put_back(conn, run_id, [(n, seen_notes[n].before) for n in sorted(notes)], actor)
    comments.mark_undone(conn, sorted(undone), email)
    return [comments.get(conn, run_id, c) for c in sorted(undone)], put_back, notes_back
