"""The step 1 routes, read against the seeded demo run."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app import db
from app.runs.events import add_event
from conftest import OWNER, field, login, make_run, make_user

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import seed_demo_run  # noqa: E402

SOFP = "mfrs-company-sofp-cunoncu-v1"


@pytest.fixture
def demo(client):
    make_user(OWNER)
    run_id = seed_demo_run.seed(OWNER)
    login(client, OWNER)
    return run_id


def _rows(client, run_id, statement="SOFP", order="report"):
    response = client.get(f"/api/runs/{run_id}/statements/{statement}?order={order}")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_demo_run_reads_back_in_report_order(client, demo):
    view = _rows(client, demo)
    assert [c["key"] for c in view["columns"]] == ["Company:CY", "Company:PY"]
    lines = [r for r in view["rows"] if r["kind"] != "heading"]
    assert lines[0]["label"] == "Property, plant and equipment"
    assert [r["label"] for r in view["rows"] if r["kind"] == "heading"][:2] == ["Non-current assets", "Current assets"]
    payables = next(r for r in lines if r["label"] == "Other payables and accruals")
    assert payables["field_label"] == "Other current non-trade payables"
    assert payables["page"] == 7 and payables["cells"]["Company:PY"]["value"] == 389200
    receivables = next(r for r in lines if r["label"] == "Other receivables, deposits and prepayments")
    assert receivables["status"] == "unsure" and "director" in receivables["reason"]
    total = next(r for r in lines if r["label"] == "Total equity and liabilities")
    assert total["kind"] == "total" and total["status"] == "does_not_tally"
    assert total["cells"]["Company:PY"]["value"] == 10029100
    assert total["cells"]["Company:PY"]["stated"] == 10038100
    assert [r["print_order"] for r in lines] == sorted(r["print_order"] for r in lines)


def test_the_demo_run_reads_back_in_template_order_with_every_field(client, demo):
    view = _rows(client, demo, order="template")
    rows = view["rows"]
    assert rows[0]["sheet"] == "SOFP-CuNonCu" and rows[-1]["sheet"] == "SOFP-Sub-CuNonCu"
    empty = next(r for r in rows if r["label"] == "Biological assets")
    assert empty["cells"]["Company:CY"]["value"] is None and empty["cells"]["Company:CY"]["writable"]
    ppe_face = next(r for r in rows if r["sheet"] == "SOFP-CuNonCu" and r["row"] == 8)
    assert ppe_face["label"] == "Property, plant and equipment" and ppe_face["kind"] == "total"
    assert ppe_face["cells"]["Company:CY"]["value"] == 4812300
    heading = next(r for r in rows if r["label"] == "Non-current assets")
    assert heading["kind"] == "heading" and heading["cells"] == {}
    for statement in ("SOPL", "SOCF"):
        assert _rows(client, demo, statement, "template")["rows"]
    profit = next(r for r in _rows(client, demo, "SOPL")["rows"] if r["field_label"] == "Profit (loss)")
    assert profit["cells"]["Company:CY"]["value"] == 915650


def test_the_demo_checks_show_one_failure(client, demo):
    checks = client.get(f"/api/runs/{demo}/checks").json()["checks"]
    failed = [c for c in checks if c["status"] == "failed"]
    assert [c["name"] for c in failed] == ["sofp_balance"]
    assert failed[0]["period"] == "PY" and failed[0]["diff"] == 9000
    assert {c["name"]: c["status"] for c in checks}["socf_articulation"] == "passed"


def test_a_person_corrects_the_misread_figure_and_the_check_passes(client, demo):
    concept = field(SOFP, "SOFP-Sub-CuNonCu", 434)
    body = {"concept_uuid": concept, "period": "PY", "entity_scope": "Company", "value": 398200}
    edited = client.post(f"/api/runs/{demo}/figures", json=body)
    assert edited.status_code == 200, edited.text
    figure = edited.json()["figure"]
    assert figure["person_edited"] and figure["lines"][0]["amount"] == 398200
    checks = client.get(f"/api/runs/{demo}/checks").json()["checks"]
    assert not [c for c in checks if c["status"] == "failed"]
    history = client.get(f"/api/runs/{demo}/figures/{figure['id']}/history").json()["history"]
    restored = client.post(f"/api/runs/{demo}/figures/{figure['id']}/restore", json={"history_id": history[0]["id"]})
    assert restored.json()["figure"]["value"] == 389200
    assert [c["name"] for c in client.get(f"/api/runs/{demo}/checks").json()["checks"]
            if c["status"] == "failed"] == ["sofp_balance"]


def test_a_refused_edit_returns_one_sentence(client, demo):
    body = {"concept_uuid": field(SOFP, "SOFP-CuNonCu", 7), "period": "CY", "entity_scope": "Company", "value": 5}
    response = client.post(f"/api/runs/{demo}/figures", json=body)
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Non-current assets is a heading")


def test_move_and_confirm(client, demo):
    view = _rows(client, demo)
    receivables = next(r for r in view["rows"] if r["label"] == "Other receivables, deposits and prepayments")
    figure_id = receivables["cells"]["Company:CY"]["figure_id"]
    confirmed = client.post(f"/api/runs/{demo}/figures/{figure_id}/confirm").json()["figure"]
    assert confirmed["certainty"] == "sure"
    target = field(SOFP, "SOFP-Sub-CuNonCu", 155)  # other receivables due from other related parties
    moved = client.post(f"/api/runs/{demo}/figures/{figure_id}/move", json={"to_concept_uuid": target, "whole_row": True})
    assert moved.status_code == 200, moved.text
    assert sorted(f["value"] for f in moved.json()["figures"]) == [276900, 318450]


def test_activity_pages_forward_with_a_row_limit_and_no_payloads(client, demo):
    for n in range(5):
        add_event("agent", "step", f"Step {n}", run_id=demo, data={"big": "x" * 1000})
    first = client.get(f"/api/runs/{demo}/events?after_id=0&limit=3").json()
    assert len(first["events"]) == 3 and first["has_more"] is True
    assert "data" not in first["events"][0] and first["events"][0]["has_data"] is True
    rest = client.get(f"/api/runs/{demo}/events?after_id={first['last_id']}&limit=3").json()
    assert [e["message"] for e in rest["events"]] == ["Step 3", "Step 4"] and rest["has_more"] is False
    detail = client.get(f"/api/runs/{demo}/events/{rest['events'][0]['id']}").json()["event"]
    assert detail["data"]["big"].startswith("x")
    assert client.get(f"/api/runs/{demo}/events?limit=0").status_code == 422


def test_routes_need_a_session_and_an_existing_run(client):
    run_id = make_run()
    assert client.get(f"/api/runs/{run_id}/checks").status_code == 401
    make_user("bo@firm.com")
    login(client, "bo@firm.com")
    assert client.get(f"/api/runs/{run_id}/checks").status_code == 200  # runs are shared
    assert client.get("/api/runs/999/statements/SOFP").status_code == 404
    assert client.get(f"/api/runs/{run_id}/statements/SOCF").status_code == 404
    assert client.get(f"/api/runs/{run_id}/statements/SOFP?order=sideways").status_code == 422


def test_run_list_reads_owner_names_through_the_login_store(client, demo):
    runs = client.get("/api/runs").json()["runs"]
    assert runs[0]["owner_name"] == "ana" and runs[0]["company"] == seed_demo_run.COMPANY
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM figures WHERE run_id = ?", (demo,)).fetchone()[0] > 100


def test_the_equity_statement_is_a_grid_with_a_block_per_entity_and_year(client):
    from app.figures import store

    run_id = make_run([("SOCIE", "Default")], level="Group")
    socie = "mfrs-group-socie-v1"
    with db.connect() as conn:
        for scope in ("Group", "Company"):
            store.save_figure(conn, run_id, store.FigureWrite(
                _socie_cell(conn, socie, "Profit (loss)", "C"),
                "CY", scope, 100, [store.Line("Profit for the year", 9, 100, 2)]), store.Actor("agent", "t"))
    make_user("bo@firm.com")
    login(client, "bo@firm.com")
    view = _rows(client, run_id, "SOCIE")
    assert [c["label"] for c in view["columns"]] == ["Retained earnings", "Equity attributable to owners", "Total"]
    assert [(r["kind"], r["label"]) for r in view["rows"]] == [
        ("heading", "Group, this year"), ("line", "Profit for the year"),
        ("heading", "Company, this year"), ("line", "Profit for the year")]
    assert view["rows"][1]["cells"]["C"]["value"] == 100
    assert len(_rows(client, run_id, "SOCIE", "template")["columns"]) == 23


def _socie_cell(conn, template_id, label, col):
    return conn.execute(
        "SELECT concept_uuid FROM concept_nodes WHERE template_id = ? AND matrix_col = ? "
        "AND LTRIM(canonical_label, '*') = ?", (template_id, col, label)).fetchone()[0]


def test_a_total_given_with_no_breakdown_can_be_edited(client, demo):
    ppe = next(r for r in _rows(client, demo)["rows"] if r["label"] == "Property, plant and equipment")
    assert ppe["kind"] == "total" and ppe["cells"]["Company:CY"]["writable"]
    body = {"concept_uuid": ppe["concept_uuid"], "period": "CY", "entity_scope": "Company", "value": 4800000}
    edited = client.post(f"/api/runs/{demo}/figures", json=body)
    assert edited.status_code == 200, edited.text
    assert edited.json()["figure"]["children_status"] == "aggregate_only"


def test_a_value_that_is_not_a_number_is_refused_and_the_statement_still_opens(client, demo):
    concept = field(SOFP, "SOFP-Sub-CuNonCu", 434)
    for raw in ('1e999', 'Infinity', 'NaN'):
        response = client.post(f"/api/runs/{demo}/figures", headers={"content-type": "application/json"},
                               content='{"concept_uuid": "%s", "period": "PY", "entity_scope": "Company", '
                                       '"value": %s}' % (concept, raw))
        assert response.status_code == 422, raw
        assert response.json() == {"detail": "The value must be an ordinary number."}
    assert _rows(client, demo)["rows"] and _rows(client, demo, order="template")["rows"]


def test_an_edit_finds_the_figure_by_its_category(client):
    from app.figures import store

    run_id = make_run()
    note = "mfrs-company-notes-issuedcapital-v1"
    closing = field(note, "Notes-Issuedcapital", 18)
    axis = "ifrs-full_ClassesOfShareCapitalAxis"
    ordinary, redeemable = ({axis: "ifrs-full_OrdinarySharesMember"},
                            {axis: "ssmt-mfrs_RedeemablePreferenceSharesMember"})
    with db.connect() as conn:
        for dims, value, reason in ((ordinary, 1000, "Ordinary shares, note 14."),
                                    (redeemable, 200, "Redeemable shares, note 14.")):
            store.save_figure(conn, run_id, store.FigureWrite(
                closing, "CY", "Company", value, [store.Line("Balance at end of year", 30, value)], dims,
                reason=reason), store.Actor("agent", "t"))
    make_user("bo@firm.com")
    login(client, "bo@firm.com")
    response = client.post(f"/api/runs/{run_id}/figures", json={
        "concept_uuid": closing, "period": "CY", "entity_scope": "Company", "value": 250, "dimensions": redeemable})
    assert response.status_code == 200, response.text
    figure = response.json()["figure"]
    assert (figure["value"], figure["reason"]) == (250, "Redeemable shares, note 14.")
    assert figure["lines"][0]["printed_label"] == "Balance at end of year"
    with db.connect() as conn:
        values = sorted(f["value"] for f in store.run_figures(conn, run_id) if f["concept_uuid"] == closing)
    assert values == [250, 1000]


def test_an_edit_that_sends_only_the_page_keeps_the_printed_label(client, demo):
    concept = field(SOFP, "SOFP-Sub-CuNonCu", 434)
    body = {"concept_uuid": concept, "period": "PY", "entity_scope": "Company", "value": 398200, "page": 8}
    figure = client.post(f"/api/runs/{demo}/figures", json=body).json()["figure"]
    assert (figure["lines"][0]["printed_label"], figure["lines"][0]["page"]) == ("Other payables and accruals", 8)
