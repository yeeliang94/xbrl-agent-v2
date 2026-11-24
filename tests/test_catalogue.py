"""The template catalogue: every template loads, IDs match v1, unchanged
start-ups skip the rebuild. The parser tests are v1's
`tests/test_concept_parser.py`, brought across."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import openpyxl
import pytest

from app import db
from app.catalog import loader
from app.catalog import parser as concept_parser
from app.catalog.section_headers import discover_section_headers, keyword_fallback_for_sheet
from app.catalog.statements import TEMPLATE_DIRS, numeric_note_paths, statement_template_paths
from app.catalog.taxonomy import taxonomy_concept

V1_DIGEST = json.loads((Path(__file__).parent / "data" / "v1_catalogue_digest.json").read_text())
MFRS_COMPANY = TEMPLATE_DIRS["mfrs"] / "Company"
FIXTURES = {
    "mfrs_company_sofp_cunoncu": MFRS_COMPANY / "01-SOFP-CuNonCu.xlsx",
    "mfrs_group_sofp_cunoncu": TEMPLATE_DIRS["mfrs"] / "Group" / "01-SOFP-CuNonCu.xlsx",
    "mfrs_company_sopl_function": MFRS_COMPANY / "03-SOPL-Function.xlsx",
    "mpers_company_sofp_cunoncu": TEMPLATE_DIRS["mpers"] / "Company" / "01-SOFP-CuNonCu.xlsx",
    "mpers_group_socie": TEMPLATE_DIRS["mpers"] / "Group" / "09-SOCIE.xlsx",
}


@pytest.fixture(scope="module")
def parsed_trees():
    return {name: concept_parser.parse_template(path) for name, path in FIXTURES.items()}


def _by_render(tree, sheet, row):
    return next((n for n in tree.concepts if n.render_key["sheet"] == sheet and n.render_key["row"] == row), None)


def test_all_38_statement_templates_and_8_numeric_notes_load():
    assert len(statement_template_paths()) == 38
    assert len(numeric_note_paths()) == 8
    with db.connect() as conn:
        templates = [r[0] for r in conn.execute("SELECT template_id FROM concept_templates")]
        fields = conn.execute("SELECT COUNT(*) FROM concept_nodes WHERE template_id NOT LIKE '%-notes-%'").fetchone()[0]
        aliases = conn.execute(
            "SELECT COUNT(*) FROM concept_render_aliases a JOIN concept_nodes n USING (concept_uuid) "
            "WHERE n.template_id NOT LIKE '%-notes-%'").fetchone()[0]
    assert len(templates) == 46
    assert sum("-notes-" not in t for t in templates) == 38
    # 6,520 statement lines, as the reuse map counted. 206 face lines show a
    # sub-sheet total and share its identity, so 6,314 distinct fields.
    assert (fields, aliases) == (6314, 206)


def test_statement_lines_by_kind_match_the_reuse_map():
    trees = [concept_parser.parse_template(p) for p in statement_template_paths()]
    concepts = [n for tree in trees for n in tree.concepts]
    count = {k: sum(1 for n in concepts if n.kind == k) for k in ("ABSTRACT", "COMPUTED", "LEAF", "MATRIX_CELL")}
    assert len(concepts) == 6520
    # v1's 986 / 3400, plus the four SoRE lines v2 works out as mTool does (see _as_v1).
    assert count == {"ABSTRACT": 876, "COMPUTED": 990, "LEAF": 3396, "MATRIX_CELL": 1258}
    assert sum(1 for n in concepts if n.render_key.get("semantic_address")) == 6506


# v2's one departure from v1's catalogue (step 9): the SoRE templates work out the restated opening and the
# closing balance with formulas, as the genuine mTool SoRE sheet does (StatementofRetainedEarnings rows 41
# and 48). v1 typed both. `_as_v1` undoes exactly that, so every other row must still match v1.
SORE_TEMPLATES = {"mpers-company-sore-v1": "d1f4f454a99612adcc04ade77921df8a3aaaa56f73cbaaa3893042ae92c9b3f6",
                  "mpers-group-sore-v1": "1b125f899f6e90b624379c5b73c3e2307ccf4ddd7fe6ac5d2b32b8475f92e208"}
SORE_WORKED_OUT = ("Retained earnings at beginning of period, restated", "Retained earnings at end of period")


def _as_v1(conn, table: str, rows: list[list]) -> list[list]:
    worked = {r[0] for r in conn.execute(
        f"SELECT concept_uuid FROM concept_nodes WHERE template_id IN ({','.join('?' * len(SORE_TEMPLATES))}) "
        f"AND LTRIM(canonical_label, '*') IN (?, ?)", (*SORE_TEMPLATES, *SORE_WORKED_OUT))}
    assert len(worked) == 4
    if table == "concept_nodes":
        return [[*r[:3], "LEAF", *r[4:]] if r[0] in worked else r for r in rows]
    if table == "concept_edges":
        return [r for r in rows if r[0] not in worked]
    if table == "template_slots":
        out = []
        for r in rows:
            if r[2] in SORE_TEMPLATES:
                r = [*r[:13], SORE_TEMPLATES[r[2]], *r[14:]]          # the workbook's own fingerprint
                if r[1] in worked:
                    r = [*r[:7], "INPUT", *r[8:14], "writable", *r[15:]]
            out.append(r)
        return out
    return rows


@pytest.mark.parametrize("table", sorted(V1_DIGEST["tables"]))
def test_catalogue_tables_are_identical_to_v1(table):
    """Same field IDs, sums, cells, SSM names and writable slots as v1's bootstrap, apart from the SoRE
    formulas above."""
    with db.connect() as conn:
        raw = [list(r) for r in conn.execute(V1_DIGEST["queries"][table])]
        rows = sorted(json.dumps(r) for r in _as_v1(conn, table, raw))
    expected = V1_DIGEST["tables"][table]
    assert len(rows) == expected["rows"]
    assert hashlib.sha256("\n".join(rows).encode()).hexdigest() == expected["sha256"]


def test_an_unchanged_start_up_skips_the_rebuild():
    assert loader.load_catalogue() == 0


def test_a_changed_template_is_rebuilt_alone():
    with db.connect() as conn:
        conn.execute("UPDATE catalogue_sources SET sha256 = 'old' WHERE template_id = 'mfrs-company-sofp-cunoncu-v1'")
    assert loader.load_catalogue() == 1
    assert loader.load_catalogue() == 0


def test_a_fresh_database_builds_the_whole_catalogue(tmp_path, monkeypatch):
    monkeypatch.setenv("XBRL_OUTPUT_DIR", str(tmp_path / "fresh"))
    db.init_db()
    assert loader.load_catalogue() == 70   # 58 statement and note templates, 12 reports
    with sqlite3.connect(db.db_path()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM concept_nodes").fetchone()[0] == 6592


def test_template_id_reads_only_the_templates_own_folders(tmp_path):
    path = tmp_path / "mpers-group-checkout" / "XBRL-template-MFRS" / "Company" / "01-SOFP-CuNonCu.xlsx"
    assert concept_parser.derive_template_id(path) == "mfrs-company-sofp-cunoncu-v1"


# v1 tests/test_concept_parser.py ------------------------------------------

@pytest.mark.parametrize("name", [n for n in FIXTURES if n != "mpers_group_socie"])
def test_abstract_rows_include_style_headers_and_taxonomy_structures(name, parsed_trees):
    tree = parsed_trees[name]
    wb = openpyxl.load_workbook(str(FIXTURES[name]), data_only=False)
    expected = {(sheet, h.row) for sheet in wb.sheetnames
                for h in discover_section_headers(wb[sheet], extra_keywords=keyword_fallback_for_sheet(sheet))}
    actual = {(n.render_key["sheet"], n.render_key["row"]) for n in tree.concepts if n.kind == "ABSTRACT"}
    assert expected <= actual
    for node in tree.concepts:
        primary = (node.render_key.get("semantic_address") or {}).get("primary_concept")
        concept = taxonomy_concept(primary) if primary else None
        if concept is not None and not concept.reportable:
            assert node.kind == "ABSTRACT"


def test_computed_rows_have_formulas_leaves_are_empty(parsed_trees):
    tree = parsed_trees["mfrs_company_sofp_cunoncu"]
    for row in (10, 17, 41):
        assert _by_render(tree, "SOFP-CuNonCu", row).kind == "LEAF"
    for row in (23, 37, 60):
        assert _by_render(tree, "SOFP-CuNonCu", row).kind == "COMPUTED"


def test_signed_sum_formula_yields_dependency_edges(parsed_trees):
    node = _by_render(parsed_trees["mfrs_company_sofp_cunoncu"], "SOFP-CuNonCu", 44)
    coeff = {e["ref"]["row"]: e["coefficient"] for e in node.edges}
    assert (coeff[40], coeff[41], coeff[42], coeff[43]) == (1, 1, -1, 1)


def test_cross_sheet_ref_becomes_render_edge_not_concept(parsed_trees):
    tree = parsed_trees["mfrs_company_sofp_cunoncu"]
    face, sub = _by_render(tree, "SOFP-CuNonCu", 8), _by_render(tree, "SOFP-Sub-CuNonCu", 39)
    assert face.concept_uuid == sub.concept_uuid
    assert face.edges


def test_sum_range_formula_expands_to_edges():
    node = concept_parser.ConceptNode("u-1", None, "COMPUTED", "Total", {"sheet": "S", "row": 1, "col": "B"})
    concept_parser.collect_edges(node, "S", "=SUM(B10:B14)", [])
    assert sorted(e["ref"]["row"] for e in node.edges) == [10, 11, 12, 13, 14]
    assert all(e["coefficient"] == 1 for e in node.edges)


def test_concept_tree_parent_links_match_indentation(parsed_trees):
    tree = parsed_trees["mfrs_company_sofp_cunoncu"]
    non_current = _by_render(tree, "SOFP-CuNonCu", 7)
    assert non_current.kind == "ABSTRACT"
    assert _by_render(tree, "SOFP-CuNonCu", 10).parent_uuid == non_current.concept_uuid


def test_serialization_is_deterministic_for_same_template():
    first = concept_parser.parse_template(FIXTURES["mfrs_company_sofp_cunoncu"])
    second = concept_parser.parse_template(FIXTURES["mfrs_company_sofp_cunoncu"])
    assert [(n.concept_uuid, n.kind, n.edges) for n in first.concepts] == \
        [(n.concept_uuid, n.kind, n.edges) for n in second.concepts]


def test_mpers_group_socie_is_a_grid_with_four_blocks(parsed_trees):
    tree = parsed_trees["mpers_group_socie"]
    assert tree.shape == "matrix"
    cell = next(n for n in tree.concepts if n.kind == "MATRIX_CELL")
    assert {(t["period"], t["entity_scope"]) for t in cell.render_key["targets"]} == {
        ("CY", "Group"), ("PY", "Group"), ("CY", "Company"), ("PY", "Company")}
