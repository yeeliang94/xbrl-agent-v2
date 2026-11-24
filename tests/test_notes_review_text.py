"""The review page draws the field's prepared text itself (docs/step-6-plan.md
6c, "one text"): the review variant only adds marks to select by, at the same
tier, so taking them off gives the prepared text back exactly."""
from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from app.notes import render, store
from tests.conftest import OWNER, login
from tests.notes_helpers import notes_run
from tests.test_note_store import PPE, place
from tests.test_notes_render import HOUSE, REVENUE, _big_table, _note, _row, _table

THICK = {**HOUSE, "double_underline": "thick_bottom_border", "bold_totals": True}
SINGLE = {**HOUSE, "double_underline": "single_bottom_border", "body_text": "left"}
GRID = _note({"kind": "paragraph", "text": "Boxed table."},
             _table([_row("", "2025", role="heading"), _row("Cash", "10"), _row("Total", "10", role="total",
                                                                                line_below={"style": "double"})],
                    frame="grid"))


def _same(review: str, prepared: str) -> bool:
    return render.without_review_marks(review) == str(BeautifulSoup(prepared, "html.parser"))


@pytest.mark.parametrize("house", [THICK, SINGLE])
def test_the_review_text_is_the_prepared_text_with_marks_in_every_house_style(house):
    notes = [REVENUE, GRID]
    prepared = render.prepare(notes, house)
    review = render.review_html(notes, [7, 8], prepared, house)
    assert _same(review, prepared.html)
    soup = BeautifulSoup(review, "html.parser")
    blocks = [(el["data-note"], el["data-block"]) for el in soup.find_all(attrs={"data-block": True})]
    assert blocks == [("7", "0"), ("7", "1"), ("7", "2"), ("8", "0"), ("8", "1")]
    cells = [(c["data-row"], c["data-col"]) for c in soup.find_all(["td", "th"]) if c.find_parent("table").get(
        "data-note") == "8"]
    assert cells == [("0", "0"), ("0", "1"), ("1", "0"), ("1", "1"), ("2", "0"), ("2", "1")]
    # The house style is in the text the review draws: the double line and the total's weight.
    total = next(c for c in soup.find_all("td") if c.get_text() == "1,265,564")
    line = "2.5px solid" if house is THICK else "0.75px solid"
    assert f"border-bottom: {line}" in total["style"]


@pytest.mark.parametrize("rows", [20, 120, 200, 400, 900])
def test_the_review_text_lands_on_the_prepared_texts_tier(rows):
    note = _big_table(rows)
    prepared = render.prepare([note], HOUSE)
    review = render.review_html([note], [1], prepared, HOUSE)
    assert _same(review, prepared.html), prepared.tier
    if prepared.tier == "flat":
        assert "style=" not in render.without_review_marks(review)


def test_the_review_route_draws_the_fields_prepared_text_and_a_note_not_placed_alone(client):
    run_id = notes_run()
    assert login(client, OWNER).status_code == 200
    ppe = place(run_id, PPE)
    second = place(run_id, store.NotePlacement("5", "Trade and other receivables", [(23, 3), (23, 4)], "test-ppe"))
    base = f"/api/runs/{run_id}/notes"
    assert client.get(f"{base}/{ppe['id']}/review").status_code == 200
    review = client.get(f"{base}/{second['id']}/review").json()["review"]
    prepared = client.get(f"{base}/{second['id']}/prepared").json()["prepared"]
    assert review["revision"] == prepared["revision"] and review["tier"] == prepared["tier"]
    assert _same(review["html"], prepared["html"])
    assert review["double_underline"] == "thick_bottom_border" and review["node_uuid"] == "test-ppe"
    notes = {el["data-note"] for el in BeautifulSoup(review["html"], "html.parser").find_all(attrs={"data-note": True})}
    assert notes == {str(ppe["id"]), str(second["id"])}
    client.post(f"{base}/{second['id']}/field", json={"node_uuid": None})
    alone = client.get(f"{base}/{second['id']}/review").json()["review"]
    assert alone["node_uuid"] is None and "Trade receivables" in alone["html"]
    assert {el["data-note"] for el in BeautifulSoup(alone["html"], "html.parser").find_all(
        attrs={"data-note": True})} == {str(second["id"])}
    client.cookies.clear()
    assert client.get(f"{base}/{second['id']}/review").status_code == 401
