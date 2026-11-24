"""Step 12: the template toolkit, and the investigating agent on a deliberately altered template. A scripted
model stands in for the real one: it proposes places, a person uses one, and the next fill writes it.
Nothing is guessed: a formula, a locked cell or a cell the fill used is refused in code."""
from __future__ import annotations

import asyncio
import json
import shutil
from types import SimpleNamespace

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app import db
from app.filing.fill import fill_workbook
from app.filing.investigate import agent, job as investigate, store, tools
from app.jobs import worker
from app.workbook import offline_fill
from app.workbook.toolkit import compare, find, identify, list_rows, read, trial_fill
from app.workbook.toolkit.book import Book
from tests.conftest import OWNER, login
from tests.mtool_fill_helpers import matching_run, seed_input_figures
from tests.test_mtool_fill import COMPANY, _altered

SHEET = "SOFP-Sub-CuNonCu"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# The toolkit ----------------------------------------------------------------------------------------------

def test_the_toolkit_reads_a_template_and_never_changes_it(tmp_path):
    book = Book(COMPANY)
    before = COMPANY.read_bytes()
    assert identify.run(book).startswith("Known template:")
    assert "SOFP-Sub-CuNonCu: 475 rows" in list_rows.run(book)
    assert "r22 | - | C: #ENDT#, E: formula showing 31/12/" in list_rows.run(book, SHEET, 22, 1)
    land = find.run(book, ["freehold", "land"], SHEET)
    assert "r30 | D: Freehold land | SSM ssmt-mfrs_FreeholdLand | E: empty, F: empty" in land
    assert read.run(book, [f"{SHEET}!E30", f"{SHEET}!D30", "Nope!A1"]).splitlines() == [
        f"{SHEET}!E30: empty", f"{SHEET}!D30: text 'Freehold land', locked",
        "Nope!A1: The workbook has no sheet named Nope; list_rows with no sheet lists them."]
    assert trial_fill.run(book, [(f"{SHEET}!E30", 1200.0), (f"{SHEET}!E22", 1.0), (f"{SHEET}!D31", 1.0)]).splitlines() \
        == [f"{SHEET}!E30: written and read back", f"{SHEET}!E22: not written: it holds a formula",
            f"{SHEET}!D31: not written: the template locks it"]
    assert COMPANY.read_bytes() == before

    filled = tmp_path / "filled.xlsx"
    offline_fill.fill_workbook(str(COMPANY), {"writes": [{"sheet": SHEET, "cell": "E30", "value": 7}]}, str(filled))
    assert compare.run(book, Book(filled), SHEET) == f"{SHEET}!E30: empty -> 7"


# The investigation ---------------------------------------------------------------------------------------

def scripted(steps: list):
    async def answer(messages, info: AgentInfo) -> ModelResponse:
        done = sum(1 for m in messages if isinstance(m, ModelResponse))
        name, args = steps[done] if done < len(steps) else ("$final", {"summary": "Done.", "not_found": []})
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name if name == "$final" else name, args)])
    return FunctionModel(answer)


@pytest.fixture
def filled_altered(client, tmp_path):
    """A run whose fill of a template with the sub-sheet's SSM names removed has just finished."""
    run_id = matching_run(COMPANY)
    seed_input_figures(run_id, every=3)
    with db.connect() as conn:
        conn.execute("UPDATE runs SET status = 'in_review' WHERE id = ?", (run_id,))
    assert login(client, OWNER).status_code == 200
    data = _altered(tmp_path, SHEET, lambda t: ".xsd#" in t).read_bytes()
    fill = client.post(f"/api/runs/{run_id}/fills", files={"file": ("altered.xlsx", data, XLSX)}).json()["fill"]
    assert asyncio.run(worker.run_once())   # the fill
    with db.connect() as conn:
        # The queued investigation is run by each test with a scripted model, never by the worker.
        conn.execute("DELETE FROM jobs WHERE kind = ?", (investigate.JOB,))
        row = conn.execute("SELECT * FROM fills WHERE id = ?", (fill["id"],)).fetchone()
        report = json.loads(row["report_json"])
    # Where the genuine template keeps each figure: the cells a fill of it writes.
    genuine = fill_workbook(run_id, COMPANY, tmp_path / "genuine.xlsx")
    cells = {tuple(w[k] for k in store.KEY): w["cell"] for w in genuine["written"]}
    return SimpleNamespace(run_id=run_id, fill_id=fill["id"], row=row, report=report, cells=cells)


def _cell(f, line) -> str:
    """The cell the genuine template keeps this figure in."""
    return f.cells[tuple(line[k] for k in store.KEY)]


def test_a_fill_that_leaves_figures_queues_an_investigation_and_a_known_one_does_not(client, filled_altered):
    f = filled_altered
    assert f.row["compatibility"] == "unknown" and f.row["investigation"] == "queued"
    assert all(line["code"] in store.INVESTIGATED for line in store.to_place(f.report))
    known = matching_run(COMPANY)
    seed_input_figures(known, every=3)
    with db.connect() as conn:
        conn.execute("UPDATE runs SET status = 'in_review' WHERE id = ?", (known,))
    fill = client.post(f"/api/runs/{known}/fills", files={"file": ("t.xlsx", COMPANY.read_bytes(), XLSX)}).json()
    asyncio.run(worker.run_once())
    with db.connect() as conn:
        assert conn.execute("SELECT investigation FROM fills WHERE id = ?", (fill["fill"]["id"],)).fetchone()[0] is None


def test_a_proposal_is_refused_in_code_unless_the_cell_is_a_free_input(filled_altered, tmp_path):
    f = filled_altered
    deps, message = agent.build_deps(f.fill_id, tmp_path)
    assert "Unknown template." in message and "F1: " in message
    ctx = SimpleNamespace(deps=deps, run_step=1)
    first, second = deps.figures["F1"], deps.figures["F2"]
    written = next(iter(deps.written))
    said = tools.propose_places(ctx, [
        tools.Place(figure="F1", cell=f"{SHEET}!E22", evidence="Header row."),
        tools.Place(figure="F1", cell=f"{SHEET}!D30", evidence="The label."),
        tools.Place(figure="F1", cell=written, evidence="Looks free."),
        tools.Place(figure="F1", cell=_cell(f, first), evidence=" "),
        tools.Place(figure="F1", cell=_cell(f, first), evidence="The row's label matches; column E is this year."),
        tools.Place(figure="F2", cell=_cell(f, first), evidence="Same row."),
        tools.Place(figure="F9999", cell=_cell(f, second), evidence="?"),
    ]).splitlines()
    assert said[0] == f"F1: not proposed. {SHEET}!E22 holds a formula, so it is not an input cell."
    assert said[1] == f"F1: not proposed. {SHEET}!D30 is locked in the template, so nothing can be typed in it."
    assert said[2] == f"F1: not proposed. The fill already wrote another figure in {written}."
    assert said[3] == "F1: not proposed. Say in evidence what on the sheet shows this cell holds it."
    assert said[4] == f"F1: proposed {_cell(f, first)}."
    assert said[5] == f"F2: not proposed. {_cell(f, first)} is already proposed for F1; one cell holds one figure."
    assert said[6] == "F9999: there is no such figure; show_figures lists them."
    with db.connect() as conn:
        (row,) = store.for_fill(conn, f.fill_id)
    assert row["place"].startswith(f"{SHEET}, row {_cell(f, first).split('!E')[-1].split('!F')[-1]} \"")
    assert ", column " in row["place"]

    with pytest.raises(ModelRetry, match="F2"):
        tools.finish(ctx, tools.FinishInvestigation(summary="Done."))
    assert tools.finish(ctx, tools.FinishInvestigation(summary="Done.")).summary == "Done."   # sent back once


def test_a_person_uses_a_proposed_place_and_the_next_fill_writes_it(client, filled_altered):
    f = filled_altered
    first = store.to_place(f.report)[0]
    steps = [("find_rows", {"words": [first["field"]], "sheet": SHEET}),
             ("propose_places", {"places": [{"figure": "F1", "cell": _cell(f, first),
                                             "evidence": "The row's label matches; column E is this year."}]}),
             ("$final", {"summary": "One figure placed.", "not_found": [
                 {"figure": fid, "why": "Not looked at in this test."} for fid in
                 [f"F{i}" for i in range(2, len(store.to_place(f.report)) + 1)]]})]
    base = f"/api/runs/{f.run_id}/fills/{f.fill_id}"
    assert client.post(f"{base}/placements", json={"use": []}).status_code == 409   # not investigated yet
    asyncio.run(investigate.run_investigation(f.fill_id, f.run_id, model=scripted(steps)))

    listed = client.get(f"{base}/placements").json()
    assert listed["investigation"] == "done" and len(listed["placements"]) == 1
    (placement,) = listed["placements"]
    assert placement["figure"] == first["name"] and placement["status"] == "open"
    receipt = client.get(base).json()["fill"]["receipt"]
    reasons = {line["name"]: line["reason"] for line in receipt["lines"] if line["kind"] == "unresolved"}
    assert reasons[store.to_place(f.report)[1]["name"]] == store.NOT_FOUND
    assert reasons[first["name"]] != store.NOT_FOUND

    assert client.post(f"{base}/placements", json={"use": [placement["id"] + 1000]}).status_code == 422
    again = client.post(f"{base}/placements", json={"use": [placement["id"]]})
    assert again.status_code == 202 and again.json()["used"] == 1
    assert client.post(f"{base}/placements", json={"use": []}).json()["detail"] == "These places were already checked."
    assert asyncio.run(worker.run_once())   # the fill again
    with db.connect() as conn:
        new = conn.execute("SELECT * FROM fills WHERE id = ?", (again.json()["fill"]["id"],)).fetchone()
        queued = conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = ?", (investigate.JOB,)).fetchone()[0]
        mapping = conn.execute("SELECT confirmed_by FROM template_mappings WHERE fingerprint = ?",
                               (f.row["template_fingerprint"],)).fetchone()
    assert new["investigation"] is None and queued == 0   # the same template is investigated once
    report = json.loads(new["report_json"])
    assert new["compatibility"] == "known" and mapping["confirmed_by"] == OWNER
    assert not [m for m in report["mismatched"] if m["concept_uuid"] == first["concept_uuid"]]
    assert {w["cell"] for w in report["written"] if w["concept_uuid"] == first["concept_uuid"]
            and w["period"] == first["period"]} == {_cell(f, first)}


def test_a_saved_place_is_used_only_while_its_row_holds_the_same_words():
    from app.filing.mappings import still_fits
    saved = {"name": "t", "cells": {("a", "CY", "Company", ""): ("S", 30, "E"), ("b", "CY", "Company", ""): ("S", 31, "E")},
             "labels": {("a", "CY", "Company", ""): "Freehold land", ("b", "CY", "Company", ""): "Leasehold land"}}
    rows = {30: "Freehold  land", 31: "Motor vehicles"}   # row 31 moved since a person confirmed it
    kept = still_fits(saved, lambda sheet, row: rows[row])
    assert list(kept["cells"]) == [("a", "CY", "Company", "")]


def test_totals_are_not_looked_for_and_each_figure_says_its_headings_and_ssm_name(filled_altered, tmp_path):
    f = filled_altered
    assert not [line for line in store.to_place(f.report) if line.get("total")]
    assert [line for line in f.report["unresolved"] if line.get("total") and line["code"] in store.INVESTIGATED]
    deps, message = agent.build_deps(f.fill_id, tmp_path)
    first = deps.figures["F1"]
    assert first["section"] and first["ssm"]
    assert f"under {first['section']} (SSM {first['ssm']}) | this year, Company" in message or "last year" in message
    assert ", 2025" not in tools.figure_line("F1", first) and ", 2024" not in tools.figure_line("F1", first)


def test_only_figures_the_agent_looked_at_read_no_place_found_and_a_failed_search_blocks_nothing(client,
                                                                                                filled_altered):
    f = filled_altered
    # The agent is sent back once for the figures it left out, and answers the same way again.
    steps = [("$final", {"summary": "Looked at one.", "not_found": [{"figure": "F2", "why": "Two rows fit."}]})] * 2
    asyncio.run(investigate.run_investigation(f.fill_id, f.run_id, model=scripted(steps), max_steps=2))
    lines = store.to_place(f.report)
    receipt = client.get(f"/api/runs/{f.run_id}/fills/{f.fill_id}").json()["fill"]["receipt"]
    reasons = {line["name"]: line["reason"] for line in receipt["lines"] if line["kind"] == "unresolved"}
    assert reasons[lines[1]["name"]] == store.NOT_FOUND
    assert reasons[lines[2]["name"]] != store.NOT_FOUND   # never looked at, so its own reason stands

    # Saving with nothing used changes nothing and fills nothing.
    with db.connect() as conn:
        store.propose(conn, f.fill_id, lines[0], SHEET, "E30", "a place", "evidence")
        (placed,) = [r["id"] for r in store.for_fill(conn, f.fill_id)]
    skipped = client.post(f"/api/runs/{f.run_id}/fills/{f.fill_id}/placements", json={"use": []}).json()
    assert skipped["used"] == 0 and skipped["fill"]["id"] == f.fill_id

    # A failed investigation of a template leaves the next fill of it free to be investigated.
    with db.connect() as conn:
        conn.execute("UPDATE fills SET investigation = 'failed' WHERE id = ?", (f.fill_id,))
        assert store.looked_at(conn, f.row["template_fingerprint"]) == frozenset()
