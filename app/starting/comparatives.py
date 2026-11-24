"""The report's comparative against a last-year figure kept from the starting
workbook (step 10e).

Rebuilt from v1 `concept_model/prior_year.py` (`compare_value`,
`_sign_only_note`, `check_results`). v1 gave the agent a separate
`check_prior_year` tool. v2 needs none: the figures agent reads both years
of every line and saves them as it always does. When it saves last year's
amount on a field whose prior-year figure was imported, the save tool hands
that amount here instead of to the figure store. So:

- the agent cannot change an imported figure: nothing here writes one, and
  the store's own hard stop 7 still refuses any other route;
- the reading is kept (`prior_year_comparisons`), and the tool's answer
  says plainly whether it agrees;
- a difference in sign only marks the figure with a sign question
  (`store.mark_sign_question`). Only a person settles it (hard stop 8), so
  saving the workbook's sign again records the agent's reasoning and leaves
  the question open, as in v1.

The check `app/checks/comparatives_check.py` reads the comparisons
(`comparisons`) and shows every difference and how many imported figures
were compared.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Optional, Sequence

from app import db
from app.figures import store
from app.figures.sums import CENT, fmt_amount, money
from app.runs import events

logger = logging.getLogger(__name__)


def is_kept(figure: Optional[dict]) -> bool:
    """A last-year figure kept as filed in the starting workbook (`store.current_figures` shape)."""
    return bool(figure and figure["locked"] and figure["origin"] == "prior_workbook" and figure["period"] == "PY")


def compare(conn: sqlite3.Connection, run_id: int, figure: dict, report: float, lines: Sequence[store.Line],
            *, by: str, reason: str = "", sign_note: str = "") -> str:
    """Record the report's comparative for an imported figure and say how it compares, in plain sentences.
    `report` is in the sign the field stores. `sign_note` names the row's overall sign for a sign-only
    difference. Changes no figure's value."""
    kept = figure["value"]
    report = money(report)
    previous = conn.execute("SELECT * FROM prior_year_comparisons WHERE figure_id = ?", (figure["id"],)).fetchone()
    sign_only = kept is not None and abs(kept) >= CENT and abs(report + kept) < CENT
    agrees = kept is not None and abs(report - kept) < CENT
    # The open sign question is about this amount, either way round; a reading of another amount is an
    # ordinary difference and is shown as one.
    open_question = bool(figure["sign_question"]) and (sign_only or agrees)
    disputed = previous["disputed_value"] if previous is not None and open_question else None
    if open_question and disputed is None and sign_only:   # read another amount in between: the question again
        disputed = report
    # A person already settled this very sign difference: the same reading does not raise it again.
    settled = (sign_only and not open_question and previous is not None and previous["disputed_value"] is not None
               and abs(previous["disputed_value"] - report) < CENT)
    if settled:
        disputed = previous["disputed_value"]
    elif sign_only and not open_question:
        store.mark_sign_question(conn, run_id, figure["id"], (
            f"The report shows {fmt_amount(report)} for last year, the workbook's {fmt_amount(kept)} with the "
            "opposite sign; a person decides which is right."))
        disputed = report
    first = lines[0] if lines else None
    conn.execute(
        "INSERT INTO prior_year_comparisons(figure_id, run_id, report_value, disputed_value, page, printed_label, "
        "reason, compared_by, compared_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(figure_id) DO UPDATE SET "
        "report_value = excluded.report_value, disputed_value = excluded.disputed_value, page = excluded.page, "
        "printed_label = excluded.printed_label, reason = excluded.reason, compared_by = excluded.compared_by, "
        "compared_at = excluded.compared_at",
        (figure["id"], run_id, report, disputed, first.page if first else None,
         " / ".join(line.printed_label for line in lines)[:300], " ".join(reason.split())[:500], by, db.now()))
    if open_question and disputed is not None and agrees:
        answer = (f"Your reasoning is recorded. Both amounts stay on record (workbook {fmt_amount(kept)}, report "
                  f"first read as {fmt_amount(disputed)}), and the difference stays open until a person decides it.")
    elif agrees:
        answer = f"Last year's figure is kept as filed at {fmt_amount(kept)}, and the report agrees."
    elif settled:
        answer = (f"Last year's workbook holds {fmt_amount(kept)} and you read {fmt_amount(report)}; a person "
                  "already decided this sign difference, so it is left as they decided.")
    elif sign_only or (open_question and disputed is not None):
        answer = (f"Last year's workbook holds {fmt_amount(kept)} and you read {fmt_amount(report)}: the same "
                  f"amount with the opposite sign. {sign_note} The workbook figure is kept and the difference is "
                  "left for a person. If the workbook's sign is right for this field, save it again with that "
                  "sign and say why in the reason; that records your reasoning for the person who decides.")
    else:
        answer = (f"Last year's workbook holds {fmt_amount(kept)} but you read {fmt_amount(report)}, a difference "
                  f"of {fmt_amount(round(abs(report - kept), 2))}. The workbook figure is kept and the difference "
                  "is listed for review; leave a comment if the report restates last year.")
    events.insert(conn, "figures", "comparative", answer.split(". ")[0] + ".", run_id=run_id,
                  data={"figure_id": figure["id"], "workbook": kept, "report": report, "agrees": agrees,
                        "sign_only": disputed is not None, "by": by},
                  pages=[line.page for line in lines])
    logger.info("Run %s: comparative for figure %s recorded (%s).", run_id, figure["id"],
                "agrees" if agrees and disputed is None else "differs")
    return " ".join(answer.split())


def by_figure(conn: sqlite3.Connection, run_id: int) -> dict[int, dict]:
    """Each compared kept figure's latest reading, for the review screen: `{figure_id: {"report_value", "page",
    "open"}}`. `open` follows the comparatives check: the reading differs (or only its sign does) and no person
    confirmed the figure since."""
    out = {}
    for r in conn.execute(
            "SELECT c.figure_id, c.report_value, c.page, c.disputed_value, f.value, f.sign_question, "
            "EXISTS (SELECT 1 FROM figure_history h WHERE h.figure_id = f.id AND h.action = 'confirm' "
            "AND h.actor_kind = 'person' AND h.changed_at >= c.compared_at) AS accepted "
            "FROM prior_year_comparisons c JOIN figures f ON f.id = c.figure_id WHERE c.run_id = ?", (run_id,)):
        sign_open = bool(r["sign_question"]) and r["disputed_value"] is not None
        differs = r["value"] is None or abs(r["report_value"] - r["value"]) >= CENT
        out[r["figure_id"]] = {"report_value": r["report_value"], "page": r["page"],
                               "open": sign_open or (differs and not r["accepted"])}
    return out
