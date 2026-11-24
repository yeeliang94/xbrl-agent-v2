"""Step 9: MPERS, the second accounting standard, with fake models.

An MPERS run with the statement of retained earnings (SoRE) in SOCIE's
place is named as printed, filled by one agent and checked; its template
works out restated and closing retained earnings as mTool does. MPERS Group
runs fill and check both entities. No network."""
from __future__ import annotations

import pytest

from app import db
from app.catalog.lookup import run_family
from app.extraction import agent, outline as ol
from app.figures import store
from app.jobs import worker
from app.runs.events import list_events
from app.runs.store import run_detail
from conftest import field_by_label, make_run
from tests.test_checks import check, save
from tests.test_extraction_job import signed_in  # noqa: F401 - the fixture
from tests.test_extraction_statements import ALL_FIVE, ORDER, Fake, _saved_statements, _stage
from tests.test_extraction_statements import run as _run  # noqa: F401 - the fixture's own fixture

SORE = "mpers-company-sore-v1"
SOPL = "mpers-company-sopl-function-v1"
MPERS_SORE = {**ALL_FIVE, "standard": "MPERS", "statements": [
    {**s, "layout": "SoRE"} if s["statement"] == "SOCIE" else s for s in ALL_FIVE["statements"]]}


class SoREFake(Fake):
    """The step 7 fake, reading the retained earnings statement as the SOCIE slot it files in."""

    @staticmethod
    def which(prompt: str):
        head = prompt.split(" of Test", 1)[0]
        statements = tuple(s for s in ORDER if agent.NAMES[s] in head
                           or (s == "SOCIE" and "statement of retained earnings" in head))
        return statements, "Group" if "Group figures only" in prompt else "Company"


@pytest.fixture
def run(signed_in, monkeypatch):  # noqa: F811
    from app.models import factory
    from tests.test_extraction_job import read_run

    def make(setup):
        run_id = read_run(signed_in)
        assert signed_in.post(f"/api/runs/{run_id}/setup", json=setup).status_code == 200
        fake = SoREFake(run_id)
        monkeypatch.setattr(factory, "build_model", lambda model_id: FunctionModel(fake))
        monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
        return run_id, fake
    from pydantic_ai.models.function import FunctionModel
    return make


def _sore(run_id: int, opening=None, policy=None, profit=None, dividends=None, closing=None, period="CY"):
    for label, value in (("Retained earnings at beginning of period", opening),
                         ("Impact of changes in accounting policies", policy), ("Profit (loss)", profit),
                         ("Dividends paid", dividends), ("Retained earnings at end of period", closing)):
        if value is not None:   # "Profit (loss)" is a heading first, then the line under it
            save(run_id, field_by_label(SORE, label, 1 if label == "Profit (loss)" else 0), value, period)


async def test_an_mpers_run_names_the_retained_earnings_statement_and_one_agent_fills_all_five(run):
    run_id, fake = run(MPERS_SORE)
    assert ("Extraction is queued: the statement of financial position, statement of profit or loss, statement of "
            "comprehensive income, statement of retained earnings and statement of cash flows."
            in [e["message"] for e in list_events(run_id=run_id)])
    assert await worker.run_once()
    assert _stage(run_id) == ("in_review", "done", None)
    ((statements, entity, prompt),) = fake.runs
    assert statements == tuple(ORDER) and entity == "Company"
    assert "statement of retained earnings" in prompt and "statement of changes in equity" not in prompt
    assert ": MPERS, Company figures only." in prompt
    assert "total: Retained earnings at end of period = " in prompt and "This statement is a grid" not in prompt
    assert _saved_statements(run_id) == set(ORDER)
    for title in ("Retained earnings agree to financial position", "Profit for the year agrees to retained earnings"):
        assert title in fake.checks["Company"], title
    assert "Profit for the year agrees to changes in equity" not in fake.checks["Company"]
    with db.connect() as conn:
        names = {s["statement"]: s["name"] for s in run_detail(conn, run_id)["statements"]}
    assert names["SOCIE"] == "statement of retained earnings"


async def test_an_mpers_group_run_fills_and_checks_both_entities_on_the_equity_grid(run):
    run_id, fake = run({**ALL_FIVE, "standard": "MPERS", "level": "Group"})
    assert await worker.run_once()
    assert _stage(run_id) == ("in_review", "done", None)
    assert [(s, e) for s, e, _ in fake.runs] == [(tuple(ORDER), "Group"), (tuple(ORDER), "Company")]
    assert "MPERS, Group figures only." in fake.runs[0][2] and "This statement is a grid" in fake.runs[0][2]
    assert _saved_statements(run_id, "Group") == _saved_statements(run_id, "Company") == set(ORDER)
    for entity in ("Group", "Company"):
        assert "Closing equity agrees to financial position" in fake.checks[entity]
        assert "Profit for the year agrees to retained earnings" not in fake.checks[entity]


def test_the_template_works_out_restated_and_closing_retained_earnings_as_mtool_does():
    """mTool's SoRE calculates both lines, so the outline shows them as totals: the agent saves the movements,
    and the closing balance it works out is what the balance sheet check compares."""
    run_id = make_run([("SOFP", "CuNonCu"), ("SOCIE", "SoRE")], standard="MPERS")
    with db.connect() as conn:
        outline = ol.build(conn, run_family(conn, run_id))
    closing = next(f for f in outline.fields.values() if f.statement == "SOCIE"
                   and f.name.lstrip("*").startswith("Retained earnings at end of period"))
    restated = next(f for f in outline.fields.values() if f.statement == "SOCIE"
                    and f.name.lstrip("*").startswith("Retained earnings at beginning of period, restated"))
    assert closing.kind == restated.kind == ol.TOTAL
    _sore(run_id, opening=1000, policy=-50, profit=300, dividends=100)
    save(run_id, field_by_label("mpers-company-sofp-cunoncu-v1", "Retained earnings"), 1150)
    found = check(run_id, "sore_to_sofp_retained_earnings")
    assert found["status"] == "passed", found["message"]
    save(run_id, field_by_label(SORE, "Dividends paid"), 150)   # a misread movement shows on the balance sheet tie
    assert check(run_id, "sore_to_sofp_retained_earnings")["status"] == "failed"


def test_a_typed_closing_balance_is_refused_and_the_agent_is_told_to_save_its_lines():
    run_id = make_run([("SOCIE", "SoRE")], standard="MPERS")
    with pytest.raises(store.Refused, match="is added up from the lines under it"):
        save(run_id, field_by_label(SORE, "Retained earnings at end of period"), 1250)


def test_profit_in_the_retained_earnings_statement_is_checked_against_profit_or_loss():
    run_id = make_run([("SOPL", "Function"), ("SOCIE", "SoRE")], standard="MPERS")
    save(run_id, field_by_label(SOPL, "Profit (loss)"), 300, total="no_breakdown")
    _sore(run_id, profit=310)
    assert check(run_id, "sopl_to_sore_profit")["status"] == "failed"
    _sore(run_id, profit=300)
    assert check(run_id, "sopl_to_sore_profit")["status"] == "passed"
    assert check(run_id, "sopl_to_socie_profit")["status"] == "not_applicable"


def test_the_retained_earnings_checks_do_not_apply_to_an_equity_grid():
    run_id = make_run([("SOFP", "CuNonCu"), ("SOPL", "Function"), ("SOCIE", "Default")], standard="MPERS")
    save(run_id, field_by_label(SOPL, "Profit (loss)"), 300, total="no_breakdown")   # saving runs the checks
    assert check(run_id, "sopl_to_sore_profit")["status"] == "not_applicable"
    assert check(run_id, "sore_to_sofp_retained_earnings")["status"] == "not_applicable"


async def test_an_mpers_group_run_with_retained_earnings_fills_both_entities(run):
    run_id, fake = run({**MPERS_SORE, "level": "Group"})
    assert await worker.run_once()
    assert _stage(run_id) == ("in_review", "done", None)
    assert [(s, e) for s, e, _ in fake.runs] == [(tuple(ORDER), "Group"), (tuple(ORDER), "Company")]
    assert "statement of retained earnings" in fake.runs[0][2]
    assert _saved_statements(run_id, "Group") == _saved_statements(run_id, "Company") == set(ORDER)
    for entity in ("Group", "Company"):
        assert "Profit for the year agrees to retained earnings" in fake.checks[entity]
