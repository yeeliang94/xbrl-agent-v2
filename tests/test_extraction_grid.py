"""The equity statement as a grid (step 7a): the outline lists its columns and
rows once, show_section and find_fields work on a row or a column, and a fake
agent that saves the equity cells gets every row and column total right.
No network."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import db
from app.catalog import lookup
from app.extraction import agent, outline as ol, outline_text, tools
from app.figures import store
from app.figures.sums import fmt_amount
from tests.conftest import make_run
from tests.test_extraction_job import FINAL, SETUP, read_run, returns, script, signed_in  # noqa: F401 - the fixture

FIVE = (("SOFP", "CuNonCu"), ("SOPL", "Function"), ("SOCI", "NetOfTax"), ("SOCF", "Indirect"),
        ("SOCIE", "Default"))


@pytest.fixture
def five():
    run_id = make_run(FIVE)
    with db.connect() as conn:
        return ol.build(conn, lookup.run_family(conn, run_id))


def test_the_equity_outline_lists_every_column_and_row_once_and_names_a_cell(five):
    text = outline_text.render(five, "SOCIE")
    cells = [f for f in five.fields.values() if f.statement == "SOCIE" and f.column_label]
    columns = {f.id.rsplit("-", 1)[1]: f.column_label for f in cells}
    assert len(columns) == 23
    for letter, label in columns.items():
        assert f"- {letter} {label}: " in text, letter
    assert "- C Retained earnings: line" in text
    assert "- T Reserves: total = M + S" in text and "- X Total: total = U + V + W" in text
    assert "  CE-11 *Profit (loss): line" in text
    assert "  CE-24 *Total increase (decrease) in equity: total = CE-13 + CE-15 + CE-16 - CE-17 +" in text
    assert "  CE-25 *Equity at end of period: total = CE-8 + CE-24" in text
    assert "A cell's id is CE-<row>-<column>." in text
    assert text.count("Retained earnings") == 1   # each column once, not once per row
    assert "Cells that do not follow" not in text
    # The ids stay those of the outline, one per cell.
    assert five.get("CE-11-C").column_label == "Retained earnings" and five.get("CE-11-C").kind == ol.LINE
    assert five.get("CE-25-X").kind == ol.TOTAL


def test_the_other_statements_keep_their_outline_view(five):
    for statement in ("SOFP", "SOPL", "SOCI", "SOCF"):
        text = outline_text.render(five, statement)
        assert text.startswith(f"Template outline: {five.titles[statement]}\n{outline_text.LEGEND}")
        assert "grid" not in text
    assert set(five.grids) == {"SOCIE"}


def test_an_equity_row_id_reads_as_its_label_for_a_person(five):
    assert five.readable("Moved the profit in CE-11 to CE-11-C.") == (
        "Moved the profit in Profit (loss) to Profit (loss) (Retained earnings).")


@pytest.fixture
def equity_deps(signed_in):  # noqa: F811
    run_id = read_run(signed_in)
    setup = {**SETUP, "statements": [*SETUP["statements"][:4],
                                     {"statement": "SOCIE", "layout": "Default", "included": True, "pages": [2]}]}
    assert signed_in.post(f"/api/runs/{run_id}/setup", json=setup).status_code == 200
    return agent.build_deps(run_id, "SOCIE")


def test_show_section_and_find_fields_work_on_a_row_or_a_column(equity_deps):
    deps, first = equity_deps
    assert "This statement is a grid" in first and "- W Non-controlling interests: line" in first
    ctx = SimpleNamespace(deps=deps, run_step=1)
    row, column = tools.show_section(ctx, ["CE-17", "ce-c"]).split("\n\n")
    assert row.startswith("CE-17 is a line row of the grid: Contributions by and distributions to owners › "
                          "Dividends paid.")
    assert "  CE-17-C line: Retained earnings; saved CY blank, PY blank" in row
    assert row.count("\n  CE-17-") == 23
    assert column.startswith("CE-C is a line column of the grid: Retained earnings.")
    assert "  CE-25-C total: Equity at end of period; saved" in column and "CE-9" not in column
    assert tools.show_section(ctx, ["CE-99"]) == "CE-99 is not a field id in the outline; find the field with find_fields."
    found = tools.find_fields(ctx, ["dividends paid", "retained earnings", "profit retained earnings"])
    dividends, retained, profit = found.split("\n'")
    assert dividends.split("\n")[1] == "- CE-17 line row: Contributions by and distributions to owners › Dividends paid"
    assert retained.split("\n")[1] == "- CE-C line column: Retained earnings"
    assert "- CE-11-C line: Comprehensive income › Profit (loss) (Retained earnings)" in profit.split("\n")[1]


# Opening equity, the year's profit and revaluation gain, a dividend and a share issue.
CELLS = {"CE-6-B": 1000, "CE-6-C": 500, "CE-11-C": 200, "CE-12-I": 50, "CE-17-C": 80, "CE-18-B": 100}
TOTALS = {"CE-6-X": 1500, "CE-8-B": 1000, "CE-8-X": 1500, "CE-13-C": 200, "CE-13-I": 50, "CE-13-M": 50,
          "CE-13-T": 50, "CE-13-U": 250, "CE-13-X": 250, "CE-24-B": 100, "CE-24-C": 120, "CE-24-X": 270,
          "CE-25-B": 1100, "CE-25-C": 620, "CE-25-I": 50, "CE-25-U": 1770, "CE-25-X": 1770, "CE-17-X": 80}


async def test_a_fake_agent_saving_the_equity_cells_gets_every_row_and_column_total_right(equity_deps):
    deps, _ = equity_deps
    seen: list = []
    figures = [{"field": fid, "lines": [{"label": "Equity", "page": 2, "cy": amount}], "reason": "As printed."}
               for fid, amount in CELLS.items()]
    steps = [("show_section", {"fields": ["CE-11", "CE-C"]}), ("save_figures", {"figures": figures}),
             ("run_checks", {}), ("report_coverage", {"lines": [
                 {"label": label, "page": 2, "action": "skipped", "reason": "A balance sheet line."}
                 for label in ("Plant and equipment", "Trade payables")]}),
             (FINAL, {"summary": "Saved the equity grid.", "unresolved": ["The test page prints no equity."]})]
    outcome, deps, _ = await agent.run_figures(deps.run_id, "SOCIE", "gpt-6-luna", model=script(steps, seen))
    assert outcome.status == "completed"
    assert returns(seen[-1], "save_figures")[0].startswith(f"Saved {len(CELLS)} of {len(CELLS)} figure(s)")
    with db.connect() as conn:
        saved = store.current_figures(conn, deps.run_id, "Company")
    got = {fid: saved[(deps.outline.get(fid).concept_uuid, "CY")]["value"] for fid in TOTALS}
    assert {fid: fmt_amount(v) for fid, v in got.items()} == {fid: fmt_amount(v) for fid, v in TOTALS.items()}
