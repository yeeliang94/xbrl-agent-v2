"""The figures agent's tools and finish check, called directly on a real run:
page checks on a save, advice given once, coverage of printed lines, and
when the finish is sent back. No model."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic_ai import ModelRetry

from app.extraction import agent, checking, coverage, tools
from app.extraction.tools import FigureSave, PrintedLine
from tests import reading_fakes as fakes
from tests.test_extraction_job import SETUP, read_run, signed_in  # noqa: F401 - the fixture


@pytest.fixture
def deps(signed_in):  # noqa: F811
    run_id = read_run(signed_in)
    assert signed_in.post(f"/api/runs/{run_id}/setup", json=SETUP).status_code == 200
    return agent.build_deps(run_id, "SOFP")[0]


def _save(deps, field: str, cy: float, page: int = 2) -> str:
    entry = FigureSave(field=field, lines=[PrintedLine(label="A line", page=page, cy=cy)])
    return tools.save_figures(SimpleNamespace(deps=deps, run_step=1), [entry])


def test_a_save_citing_a_page_outside_the_document_is_refused(deps):
    out = _save(deps, "FP-s28", 1200, page=99)
    assert f"FP-s28 Plant and equipment: not saved. Page 99 is outside the document, which has " \
           f"{deps.page_count} pages." in out
    assert deps.writes == 0


def test_advice_is_given_once_per_field_until_its_value_changes(deps):
    point = "FP-s147 Other current trade receivables is filled while the dedicated fields beside it are empty"
    assert point in _save(deps, "FP-s147", 30)
    assert point not in _save(deps, "FP-s147", 30)       # the same value: said already
    assert point in _save(deps, "FP-s147", 31)           # the value changed: said again


def test_blank_required_fields_are_information_only(deps):
    _save(deps, "FP-s28", 1200)
    out = checking.run_checks(SimpleNamespace(deps=deps))
    assert "For information, required fields blank this year (blank is right when the report does not show it):" \
        in out
    assert "unresolved" not in out and "coverage" not in out


def test_a_header_row_of_years_is_not_a_printed_line():
    page = fakes.good_page(2)
    page["blocks"][1]["html"] = ("<table><tr><td>ASSETS</td><td>2021</td><td>2020</td></tr>"
                                 "<tr><td>Plant and equipment</td><td>1,200</td><td>1,000</td></tr>"
                                 "<tr><td>Deposits</td><td>2021</td><td>-</td></tr></table>")
    printed = coverage.printed_lines({2: page}, [2])
    assert [p.label for p in printed] == ["Plant and equipment", "Deposits"]


def _finish_deps(**state) -> SimpleNamespace:
    base = dict(writes=2, checked_at=2, checks_open=[], coverage_open=[], coverage_at=2, refused_finish=False,
                max_steps=60, finish=None, event=lambda *a, **k: None)
    return SimpleNamespace(**{**base, **state})


def test_figures_changed_since_the_coverage_report_send_the_finish_back():
    deps = _finish_deps(coverage_at=1)
    with pytest.raises(ModelRetry) as refused:
        checking.finish(SimpleNamespace(deps=deps, run_step=5), checking.FinishReport(summary="x"))
    assert "Figures changed since your last report_coverage, so report coverage again." in str(refused.value)
    deps = _finish_deps()
    assert checking.finish(SimpleNamespace(deps=deps, run_step=5), checking.FinishReport(summary="x"))


def test_only_failing_checks_left_allows_an_honest_finish_at_once():
    honest = checking.FinishReport(summary="x", unresolved=["The report itself does not balance."])
    deps = _finish_deps(checks_open=["Balance: assets differ from equity and liabilities."])
    assert checking.finish(SimpleNamespace(deps=deps, run_step=5), honest) is honest
    # With coverage out of date as well, the finish is sent back first.
    stale = _finish_deps(checks_open=["Balance: differs."], coverage_at=1)
    with pytest.raises(ModelRetry):
        checking.finish(SimpleNamespace(deps=stale, run_step=5), honest)
