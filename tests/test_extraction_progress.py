"""Which statements are finished (`progress`): a setup change drops only the
marks of the statements whose figures it cleared. No network."""
from __future__ import annotations

from app import db
from app.extraction import progress
from app.runs.events import insert
from tests.conftest import make_run


def _changed(conn, run_id: int, field: str, statement=None) -> None:
    insert(conn, "scope", "setup_changed", "Setup changed.", run_id=run_id,
           data={"field": field, "statement": statement})


def test_a_layout_change_drops_only_that_statements_mark_and_a_whole_run_change_drops_all():
    run_id = make_run((("SOFP", "CuNonCu"), ("SOPL", "Function")), level="Group")
    with db.connect(immediate=True) as conn:
        progress.mark(conn, run_id, None, ("SOFP", "SOPL"), "Group", "Filled.", {})
        progress.mark(conn, run_id, None, ("SOFP", "SOPL"), "Company", "Filled.", {})
        _changed(conn, run_id, "layout", "SOPL")
        assert progress.finished(conn, run_id) == {("SOFP", "Group"), ("SOFP", "Company")}
        progress.mark(conn, run_id, None, ("SOPL",), "Company", "Filled again.", {})
        assert progress.finished_for(conn, run_id, "Company") == ("SOFP", "SOPL")
        assert progress.finished_for(conn, run_id, "Group") == ("SOFP",)
        _changed(conn, run_id, "unit")
        assert progress.finished(conn, run_id) == set()


def test_a_step_4_mark_counts_for_the_company():
    run_id = make_run()
    with db.connect(immediate=True) as conn:
        insert(conn, "extraction", "finished", "The balance sheet is filled.", run_id=run_id,
               data={"statement": "SOFP"})
        assert progress.finished(conn, run_id) == {("SOFP", "Company")}
