"""Prose-note templates in the catalogue (step 6a) and a run's note fields.

v1's `tests/test_notes_registry_import.py` and `tests/test_notes_types.py`,
rewritten for v2's database: every prose template loads into `notes_nodes`
and nowhere else, IDs are template-scoped and equal v1's, a rebuild keeps
them, and the registry finds every file.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from app import db
from app.catalog import loader
from app.catalog.note_fields import run_note_fields
from app.catalog.statements import NOTE_TEMPLATES, prose_note_path, prose_note_paths
from tests.conftest import make_run

# sha256 of v1's notes_nodes rows for the 12 prose templates (v1's
# output/xbrl_agent.db, 23 November 2026): node_uuid, template_id, sheet, row,
# label, kind, slot_role, taxonomy_element_id, sorted as JSON lines.
V1_PROSE_DIGEST = (688, "d1671a202d8cb7682daf98b16da344b8a73fd6f87b2d78f6700325e53bfeb277")
_DIGEST_SQL = ("SELECT node_uuid, template_id, sheet, row, label, kind, slot_role, taxonomy_element_id "
               "FROM notes_nodes WHERE template_id NOT LIKE '%-report-%'")   # the report narratives: test_reports.py


def _digest(conn) -> tuple[int, str]:
    rows = sorted(json.dumps(list(r)) for r in conn.execute(_DIGEST_SQL))
    return len(rows), hashlib.sha256("\n".join(rows).encode()).hexdigest()


def test_every_prose_template_file_exists_under_its_standard_and_level():
    paths = prose_note_paths()
    assert len(paths) == 12 and all(p.exists() for p in paths)
    assert prose_note_path("LIST_OF_NOTES", "group", "mpers").name == "13-Notes-ListOfNotes.xlsx"
    with pytest.raises(ValueError, match="filing level"):
        prose_note_path("CORP_INFO", "consolidated")


def test_all_12_prose_templates_load_into_notes_nodes_only_with_v1s_ids():
    with db.connect() as conn:
        templates = {r[0] for r in conn.execute("SELECT DISTINCT template_id FROM notes_nodes "
                                                 "WHERE template_id NOT LIKE '%-report-%'")}
        leaked = conn.execute("SELECT COUNT(*) FROM concept_nodes WHERE template_id IN "
                              "(SELECT template_id FROM notes_nodes)").fetchone()[0]
        assert _digest(conn) == V1_PROSE_DIGEST
    assert len(templates) == 12 and leaked == 0


def test_the_same_row_in_each_family_gets_its_own_id():
    with db.connect() as conn:
        ids = [r[0] for r in conn.execute(
            "SELECT node_uuid FROM notes_nodes WHERE sheet = 'Notes-CI' AND label = 'Corporate information'")]
    assert len(ids) == len(set(ids)) == 4


def test_ids_stay_the_same_across_a_restart_and_a_rebuild():
    assert loader.load_catalogue() == 0
    with db.connect() as conn:
        before = _digest(conn)
        conn.execute("UPDATE catalogue_sources SET sha256 = 'old' WHERE template_id LIKE '%-notes-%'")
    assert loader.load_catalogue() == 20      # 12 prose and 8 numeric note templates
    with db.connect() as conn:
        assert _digest(conn) == before


@pytest.mark.parametrize(("standard", "level"), [("MFRS", "Company"), ("MFRS", "Group"),
                                                 ("MPERS", "Company"), ("MPERS", "Group")])
def test_a_runs_note_fields_come_back_in_one_call(standard, level):
    run_id = make_run(standard=standard, level=level)
    with db.connect() as conn:
        fields = run_note_fields(conn, run_id)
    assert [f.template for f in fields] == sorted((f.template for f in fields), key=list(NOTE_TEMPLATES).index)
    assert all(f.template_id.startswith(f"{standard.lower()}-{level.lower()}-") for f in fields)
    assert len({f.field_id for f in fields}) == len(fields)
    # Exactly one catch-all in each prose template, never a heading.
    catch_alls = [f for f in fields if f.catch_all]
    assert sorted(f.template for f in catch_alls) == ["ACC_POLICIES", "CORP_INFO", "LIST_OF_NOTES"]
    assert not any(f.heading for f in catch_alls)
    # The numeric notes add their one text field each.
    numeric = [f for f in fields if f.template in ("ISSUED_CAPITAL", "RELATED_PARTY")]
    assert len(numeric) == 2 and not any(f.heading for f in numeric)


def test_headings_are_marked_and_each_field_carries_its_path():
    with db.connect() as conn:
        fields = {f.row: f for f in run_note_fields(conn, make_run()) if f.template == "CORP_INFO"}
    assert [r for r, f in sorted(fields.items()) if f.heading] == [3, 4, 6]
    assert fields[5].path == ("Notes - Corporate information", "Corporate information")
    assert fields[7].path == ("Notes - Corporate information", "Financial reporting status")
    assert (fields[5].label, fields[5].mandatory, fields[7].mandatory) == (
        "Disclosure of corporate information", True, False)


def test_mpers_has_no_capital_management_field_and_mfrs_has_one():
    def capital_management(standard):
        with db.connect() as conn:
            return [f for f in run_note_fields(conn, make_run(standard=standard))
                    if "capital management" in f.label.lower()]
    assert len(capital_management("MFRS")) == 1
    assert capital_management("MPERS") == []


def test_a_run_that_does_not_exist_has_no_fields():
    with db.connect() as conn:
        assert run_note_fields(conn, 999_999) == []
