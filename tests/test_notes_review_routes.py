"""The routes and fields the notes screens use (docs/api-contract.md, Step
6e): note fields, reports, the prepared text, fit and figures, comments on
part of a note, the notes' Needs you items and the citation check."""
from __future__ import annotations

from app import db
from app.catalog.note_fields import run_note_fields
from app.checks.runner import read_checks
from app.figures import store as figures
from app.notes import store, store_reports
from tests.conftest import OWNER, login
from tests.notes_helpers import notes_run
from tests.test_note_store import BORROWINGS, PPE, RECEIVABLES, place

AGENT = ("agent", "notes")


def _fields(run_id: int) -> dict[str, str]:
    """Field label -> node_uuid, for the run's real note fields."""
    with db.connect() as conn:
        return {f.label: f.field_id for f in run_note_fields(conn, run_id) if not f.heading}


def _review_run(client) -> int:
    run_id = notes_run()
    assert login(client, OWNER).status_code == 200
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE runs SET status = 'in_review' WHERE id = ?", (run_id,))
    return run_id


def _report(run_id: int, kind: str, **kwargs) -> int:
    with db.connect(immediate=True) as conn:
        return store_reports.add_report(conn, run_id, kind, reason="Test reason.", actor_name="notes", **kwargs)


def test_every_new_route_needs_a_session_and_an_existing_run(client):
    run_id = notes_run()
    note = place(run_id)
    report = _report(run_id, "missing_mandatory_field", node_uuid="test-other")
    base = f"/api/runs/{run_id}/notes"
    routes = (("get", f"{base}/fields"), ("get", f"{base}/reports"), ("get", f"{base}/{note['id']}/prepared"),
              ("post", f"{base}/reports/{report}/leave-empty"), ("post", f"{base}/reports/{report}/reopen"))
    for method, path in routes:
        assert getattr(client, method)(path).status_code == 401, path
    assert login(client, OWNER).status_code == 200
    for method, path in routes:
        missing = getattr(client, method)(path.replace(f"/runs/{run_id}/", "/runs/999/"))
        assert missing.status_code == 404 and missing.json()["detail"] == "There is no such run.", path


def test_the_fields_list_holds_the_numeric_notes_text_fields_and_share_capital_can_sit_in_two_fields(client):
    run_id = _review_run(client)
    fields = client.get(f"/api/runs/{run_id}/notes/fields").json()["fields"]
    templates = {f["template"] for f in fields}
    assert {"CORP_INFO", "ACC_POLICIES", "LIST_OF_NOTES", "ISSUED_CAPITAL", "RELATED_PARTY"} <= templates
    text_field = next(f for f in fields if f["template"] == "ISSUED_CAPITAL")
    assert set(text_field) == {"field_id", "template", "template_name", "template_id", "label", "path", "heading",
                               "mandatory", "catch_all"}
    from app.notes import agent
    deps, message = agent.build_deps(run_id, "placing")   # the notes agent places the text by id too
    text_id = deps.outline.note_ids[text_field["field_id"]]
    assert text_id.startswith("SCT-") and text_id in message
    assert deps.outline.readable(f"Placed in {text_id}.") == f"Placed in {text_field['label']}."
    note = place(run_id, PPE)
    moved = client.post(f"/api/runs/{run_id}/notes/{note['id']}/field", json={"node_uuid": text_field["field_id"]})
    assert moved.status_code == 200, moved.json()
    shown = moved.json()["note"]
    assert shown["field"]["label"] == text_field["label"] and shown["template_id"] == text_field["template_id"]
    # A numeric note shows its figures, Unsure ones counted.
    with db.connect(immediate=True) as conn:
        uuid = conn.execute(
            "SELECT n.concept_uuid FROM concept_nodes n JOIN template_slots s ON s.canonical_target_id = n.concept_uuid "
            "WHERE n.template_id = ? AND s.value_kind != 'html' AND s.validation_status = 'writable' "
            "AND n.kind != 'ABSTRACT' AND NOT EXISTS (SELECT 1 FROM concept_edges e WHERE e.parent_uuid = n.concept_uuid) "
            "ORDER BY n.render_row LIMIT 1", (text_field["template_id"],)).fetchone()[0]
        figures.save_figure(conn, run_id, figures.FigureWrite(uuid, "CY", "Company", 1000,
                                                              [figures.Line("Ordinary shares", 24, 1000)],
                                                              certainty="unsure", reason="Printed in thousands."),
                            figures.Actor("agent", "notes"))
    numeric = client.get(f"/api/runs/{run_id}/notes/{note['id']}").json()["note"]["figures"]
    assert numeric["unsure"] == 1 and numeric["rows"][0]["cells"]["Company:CY"]["value"] == 1000
    assert [c["key"] for c in numeric["columns"]] == ["Company:CY", "Company:PY"]
    other = place(run_id, BORROWINGS)
    assert client.get(f"/api/runs/{run_id}/notes/{other['id']}").json()["note"]["figures"] is None


def test_reports_list_settle_and_reopen(client):
    run_id = _review_run(client)
    receivables = place(run_id, RECEIVABLES)
    gap = _report(run_id, "source_gap", note_number="5", pages=[24], after_block="P24B0")
    missing = _report(run_id, "missing_mandatory_field", node_uuid="test-other")
    base = f"/api/runs/{run_id}/notes/reports"
    reports = {r["id"]: r for r in client.get(base).json()["reports"]}
    assert reports[gap]["note_id"] == receivables["id"] and reports[gap]["after_block"] == "p24b0"
    assert reports[gap]["status"] == "open" and reports[gap]["settled_by"] is None
    assert reports[missing]["field_label"] == "Disclosure of other notes to accounts"
    assert reports[missing]["template_id"] == "TEST-NOTES" and reports[missing]["note_id"] is None

    routed = _report(run_id, "routed_elsewhere", note_number="6")
    refused = client.post(f"{base}/{routed}/leave-empty")
    assert refused.status_code == 422
    assert refused.json()["detail"] == "Only a missing required field or a capture problem can be settled."
    assert client.post(f"{base}/9999/reopen").json()["detail"] == "There is no such report in this run."
    orphan = _report(run_id, "source_gap", note_number="9", pages=[24])   # no note 9: no confirm reaches it
    assert client.post(f"{base}/{orphan}/leave-empty").json()["report"]["status"] == "settled"
    left = client.post(f"{base}/{missing}/leave-empty").json()["report"]
    assert left["status"] == "settled" and left["settled_by"] == OWNER
    assert client.post(f"{base}/{missing}/reopen").json()["report"]["status"] == "open"

    # Confirm settles the note's gaps and sets its formatting fine.
    with db.connect(immediate=True) as conn:
        store.set_look(conn, run_id, receivables["id"], receivables["blocks"], store.Actor(*AGENT),
                       format_state="check_formatting", format_reason="A rule looks off.")
    confirmed = client.post(f"/api/runs/{run_id}/notes/{receivables['id']}/confirm").json()["note"]
    assert confirmed["format_state"] == "fine" and confirmed["format_reason"] == ""
    assert {r["id"]: r["status"] for r in client.get(base).json()["reports"]}[gap] == "settled"


def test_the_prepared_text_and_fit_are_the_fields_whole_text(client):
    run_id = _review_run(client)
    ppe = place(run_id, PPE)
    second = place(run_id, store.NotePlacement("5", "Trade and other receivables", [(23, 3), (23, 4)], "test-ppe"))
    prepared = client.get(f"/api/runs/{run_id}/notes/{ppe['id']}/prepared").json()["prepared"]
    assert prepared == client.get(f"/api/runs/{run_id}/notes/{second['id']}/prepared").json()["prepared"]
    assert prepared["node_uuid"] == "test-ppe" and prepared["tier"] == "full" and prepared["limit"] == 32767
    assert "Carrying amount" in prepared["html"] and "Trade receivables" in prepared["html"]
    listed = {n["id"]: n for n in client.get(f"/api/runs/{run_id}/notes").json()["notes"]}
    assert listed[ppe["id"]]["fit"] == {"tier": "full", "chars": prepared["chars"], "limit": 32767}
    client.post(f"/api/runs/{run_id}/notes/{second['id']}/field", json={"node_uuid": None})
    assert client.get(f"/api/runs/{run_id}/notes/{second['id']}").json()["note"]["fit"] is None
    refused = client.get(f"/api/runs/{run_id}/notes/{second['id']}/prepared")
    assert refused.status_code == 409
    assert refused.json()["detail"] == "This note is not placed, so there is no field text to copy."


def test_a_comment_on_part_of_a_note_is_named_and_checked(client):
    run_id = _review_run(client)
    note = place(run_id, BORROWINGS)
    table = next(b for b in note["blocks"] if b["kind"] == "table")
    paragraph = note["blocks"][0]

    def post(part):
        return client.post(f"/api/runs/{run_id}/comments", json={
            "target": {"kind": "note", "note_id": note["id"], "note_part": part}, "text": "Look at this."})

    cases = [(None, "Note 6 Borrowings"),
             ({"block": table["id"], "scope": "row", "row": 4, "column": None}, "Note 6 Borrowings › Row: Total"),
             ({"block": table["id"], "scope": "cell", "row": 1, "column": 2},
              "Note 6 Borrowings › Term loan, Within 1 year RM"),
             ({"block": table["id"], "scope": "column", "row": None, "column": 0}, "Note 6 Borrowings › Column: Borrowings"),
             ({"block": table["id"], "scope": "table", "row": None, "column": None}, "Note 6 Borrowings › Table")]
    for part, label in cases:
        response = post(part)
        assert response.status_code == 201, response.json()
        target = response.json()["comment"]["target"]
        assert target["kind"] == "note" and target["note_id"] == note["id"] and target["field_label"] == label
        assert target["note_part"] == part
    refusals = [({"block": "p99b9", "scope": "block"}, "Note 6 Borrowings has no block p99b9."),
                ({"block": paragraph["id"], "scope": "row", "row": 0}, None),
                ({"block": table["id"], "scope": "row", "row": 9}, "The table has 5 rows, so row 10 does not exist."),
                ({"block": table["id"], "scope": "cell", "row": 1}, "Name the column for a column or cell comment."),
                ({"block": table["id"], "scope": "corner"},
                 "A comment on part of a note is on a block, a table, a row, a column or a cell.")]
    for part, sentence in refusals:
        response = post(part)
        assert response.status_code == 422
        if sentence:
            assert response.json()["detail"] == sentence
    listed = client.get(f"/api/runs/{run_id}/comments").json()["comments"]
    assert len(listed) == len(cases) and all(c["target"]["kind"] == "note" for c in listed)


def test_the_notes_needs_you_items_appear_and_clear(client):
    run_id = _review_run(client)
    receivables = place(run_id, RECEIVABLES)
    loose = place(run_id, BORROWINGS)
    gap = _report(run_id, "source_gap", note_number="5", pages=[24])
    missing = _report(run_id, "missing_mandatory_field", node_uuid="test-ppe")
    with db.connect(immediate=True) as conn:
        store.set_look(conn, run_id, receivables["id"], receivables["blocks"], store.Actor(*AGENT),
                       format_state="check_formatting", format_reason="A rule looks off.")
        store.clear_note(conn, run_id, loose["id"], store.Actor(*AGENT))

    def items():
        found = client.get(f"/api/runs/{run_id}/needs-you").json()["items"]
        return [(i["kind"], i.get("note_id"), i.get("report_id")) for i in found if i["kind"].startswith(("note", "unplaced", "missing"))]

    assert items() == [("note_to_check", receivables["id"], None), ("unplaced_note", loose["id"], None),
                       ("note_gap", receivables["id"], gap), ("missing_field", None, missing)]
    item = next(i for i in client.get(f"/api/runs/{run_id}/needs-you").json()["items"] if i["kind"] == "note_to_check")
    assert item["title"] == "Note 5 Trade and other receivables" and item["message"] == "A rule looks off."

    client.post(f"/api/runs/{run_id}/notes/{receivables['id']}/confirm")   # settles the check and the gap
    client.post(f"/api/runs/{run_id}/notes/{loose['id']}/field", json={"node_uuid": "test-ppe"})   # fills the field
    assert items() == []


def test_a_field_too_long_for_mtool_is_a_needs_you_item(client, monkeypatch):
    from app.notes.render import fit

    run_id = _review_run(client)
    note = place(run_id, PPE)
    monkeypatch.setattr(fit, "EXCEL_CELL_CHAR_LIMIT", 100)
    from app.notes import field_text
    field_text._KEPT.clear()
    found = [i for i in client.get(f"/api/runs/{run_id}/needs-you").json()["items"] if i["kind"] == "note_too_long"]
    assert [(i["note_id"], i["node_uuid"], i["title"]) for i in found] == [
        (note["id"], "test-ppe", "Disclosure of property, plant and equipment")]
    assert client.get(f"/api/runs/{run_id}/notes").json()["notes"][0]["fit"]["tier"] == "too_long"


def test_note_citations_say_why_they_are_not_assessed(client):
    run_id = _review_run(client)
    fields = _fields(run_id)
    with db.connect(immediate=True) as conn:
        store.place_note(conn, run_id, store.NotePlacement("4", "Property, plant and equipment", [(23, 0), (23, 1)],
                                                           fields["Disclosure of property, plant and equipment"]),
                         store.Actor(*AGENT))
        store.place_note(conn, run_id, store.NotePlacement(
            "2", "Accounting policies", [(24, 0)],
            fields["Description of accounting policy for property, plant and equipment"]), store.Actor(*AGENT))
        from app.catalog.lookup import run_family
        from app.checks.runner import run_checks
        run_checks(conn, run_family(conn, run_id))
        found = next(c for c in read_checks(conn, run_id) if c["name"] == "notes_citation_consistency")
    assert found["status"] == "not_assessed" and "placed once" in found["message"]


def test_an_existing_database_gains_the_note_comment_and_report_columns():
    with db.connect() as conn:
        conn.execute("DROP TABLE note_reports")
        conn.execute("CREATE TABLE note_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL, "
                     "kind TEXT NOT NULL, note_number TEXT NOT NULL DEFAULT '', node_uuid TEXT, "
                     "pages_json TEXT NOT NULL DEFAULT '[]', reason TEXT NOT NULL, actor_name TEXT NOT NULL DEFAULT '', "
                     "created_at TEXT NOT NULL)")
        conn.execute("ALTER TABLE comments DROP COLUMN note_part_json")
    db.init_db()
    with db.connect() as conn:
        reports = {r["name"] for r in conn.execute("PRAGMA table_info(note_reports)")}
        comments = {r["name"] for r in conn.execute("PRAGMA table_info(comments)")}
    assert {"status", "settled_by", "settled_at", "after_block"} <= reports
    assert {"note_id", "note_part_json"} <= comments
