"""Write a parsed template into the catalogue tables.

Copied from v1 `concept_model/importer.py` (`import_template`,
`import_company_targets`, `import_group_targets`). v1 read the tree from a
temporary JSON file and opened its own connection; v2 takes the tree and the
caller's connection, so the whole catalogue loads in one transaction.

Concepts that disappear from a later import are retired (`is_current = 0`),
never deleted: saved figures keep their link to them.
"""
from __future__ import annotations

import json
import sqlite3

from app.catalog.parser import ConceptTree
from app.db import now

# Group templates: B = Group CY, C = Group PY, D = Company CY, E = Company PY.
_GROUP_COL_LAYOUT = [("CY", "Group", "B"), ("PY", "Group", "C"),
                     ("CY", "Company", "D"), ("PY", "Company", "E")]


def _is_canonical_home(sheet: str) -> bool:
    """Sub-sheets own the formula for a line that also shows on the face."""
    s = (sheet or "").lower()
    return "sub-" in s or "analysis" in s


def import_template(conn: sqlite3.Connection, tree: ConceptTree, source_path: str) -> str:
    template_id = tree.template_id
    is_matrix = tree.shape == "matrix"
    concepts = tree.concepts
    conn.execute("PRAGMA defer_foreign_keys = ON")
    conn.execute(
        "INSERT INTO concept_templates(template_id, source_path, imported_at, shape) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(template_id) DO UPDATE SET source_path = excluded.source_path, "
        "imported_at = excluded.imported_at, shape = excluded.shape",
        (template_id, source_path, now(), tree.shape),
    )

    # A face row that shares a sub-sheet total's identity becomes an alias;
    # the sub-sheet row (which owns the formula) is the primary.
    seen: dict[str, object] = {}
    aliases: list[tuple[str, str, int, str]] = []
    for c in concepts:
        existing = seen.get(c.concept_uuid)
        if existing is None:
            seen[c.concept_uuid] = c
            continue
        if _is_canonical_home(c.render_key.get("sheet", "")) and not _is_canonical_home(
                existing.render_key.get("sheet", "")):
            demoted = existing
            seen[c.concept_uuid] = c
        else:
            demoted = c
        rk = demoted.render_key
        aliases.append((c.concept_uuid, rk.get("sheet", ""), int(rk.get("row", 0) or 0), rk.get("col", "B")))

    conn.execute(
        "UPDATE concept_nodes SET is_current = 0, retired_at = COALESCE(retired_at, ?) "
        "WHERE template_id = ? AND is_current = 1", (now(), template_id))
    conn.executemany(
        """
        INSERT INTO concept_nodes(
            concept_uuid, template_id, parent_uuid, kind, canonical_label, render_sheet,
            render_row, render_col, matrix_col, matrix_col_label, is_current, retired_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, NULL)
        ON CONFLICT(concept_uuid) DO UPDATE SET
            template_id = excluded.template_id, parent_uuid = excluded.parent_uuid,
            kind = excluded.kind, canonical_label = excluded.canonical_label,
            render_sheet = excluded.render_sheet, render_row = excluded.render_row,
            render_col = excluded.render_col, matrix_col = excluded.matrix_col,
            matrix_col_label = excluded.matrix_col_label, is_current = 1, retired_at = NULL
        """,
        [(c.concept_uuid, template_id, c.parent_uuid, c.kind, c.canonical_label,
          c.render_key.get("sheet", ""), int(c.render_key.get("row", 0) or 0),
          c.render_key.get("col", "B"), c.render_key.get("matrix_col"),
          c.render_key.get("matrix_col_label")) for c in seen.values()],
    )
    current = "SELECT concept_uuid FROM concept_nodes WHERE template_id = ? AND is_current = 1"

    conn.execute(f"DELETE FROM concept_semantic_addresses WHERE concept_uuid IN ({current})", (template_id,))
    conn.executemany(
        "INSERT INTO concept_semantic_addresses(concept_uuid, primary_concept, dimensions_json, "
        "taxonomy_version, address_version) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(concept_uuid) DO UPDATE SET primary_concept = excluded.primary_concept, "
        "dimensions_json = excluded.dimensions_json, taxonomy_version = excluded.taxonomy_version, "
        "address_version = excluded.address_version",
        [(c.concept_uuid, sa["primary_concept"],
          json.dumps(sa.get("dimensions") or {}, sort_keys=True, separators=(",", ":")),
          sa.get("taxonomy_version", ""), sa.get("address_version", ""))
         for c in seen.values()
         if isinstance(sa := c.render_key.get("semantic_address"), dict) and sa.get("primary_concept")],
    )

    conn.execute(f"DELETE FROM concept_render_aliases WHERE concept_uuid IN ({current})", (template_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO concept_render_aliases(concept_uuid, alias_sheet, alias_row, alias_col) "
        "VALUES (?, ?, ?, ?)", aliases)

    # Edges: resolve each formula reference to a concept, face aliases included.
    coord_to_uuid: dict[tuple[str, int, str], str] = {}
    coord_no_col: dict[tuple[str, int], str] = {}
    for c in concepts:
        rk = c.render_key
        key = (rk.get("sheet", ""), int(rk.get("row", 0) or 0))
        coord_to_uuid[(*key, rk.get("col", "B"))] = c.concept_uuid
        coord_no_col.setdefault(key, c.concept_uuid)
    conn.execute(f"DELETE FROM concept_edges WHERE parent_uuid IN ({current})", (template_id,))
    edges = []
    for c in concepts:
        for edge in c.edges or []:
            ref = edge.get("ref") or {}
            r_sheet, r_row, r_col = ref.get("sheet", ""), int(ref.get("row", 0) or 0), ref.get("col", "")
            child = coord_to_uuid.get((r_sheet, r_row, r_col))
            if child is None and not is_matrix:
                child = coord_no_col.get((r_sheet, r_row))
            if child is None:
                sql = ("SELECT concept_uuid FROM concept_nodes WHERE template_id = ? AND render_sheet = ? "
                       "AND render_row = ? AND is_current = 1")
                params: tuple = (template_id, r_sheet, r_row)
                if is_matrix:
                    sql, params = sql + " AND render_col = ?", params + (r_col,)
                row = conn.execute(sql, params).fetchone()
                child = row[0] if row else None
            if child and child != c.concept_uuid:
                edges.append((c.concept_uuid, child, float(edge.get("coefficient", 1.0))))
    conn.executemany(
        "INSERT OR IGNORE INTO concept_edges(parent_uuid, child_uuid, coefficient) VALUES (?, ?, ?)", edges)

    if is_matrix:
        conn.execute(f"DELETE FROM concept_targets WHERE concept_uuid IN ({current})", (template_id,))
        conn.executemany(
            "INSERT INTO concept_targets(concept_uuid, entity_scope, period, target_sheet, target_row, "
            "target_col) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(concept_uuid, entity_scope, period) "
            "DO UPDATE SET target_sheet = excluded.target_sheet, target_row = excluded.target_row, "
            "target_col = excluded.target_col",
            [(c.concept_uuid, t["entity_scope"], t["period"], t.get("sheet", ""),
              int(t.get("row", 0) or 0), t.get("col", "B"))
             for c in concepts for t in c.render_key.get("targets") or []],
        )
    else:
        _import_linear_targets(conn, template_id, group="-group-" in template_id)
    return template_id


def _import_linear_targets(conn: sqlite3.Connection, template_id: str, *, group: bool) -> None:
    """Each line's cell per entity and period: Company B=CY, C=PY; Group B..E."""
    rows = conn.execute(
        "SELECT concept_uuid, render_sheet, render_row, render_col FROM concept_nodes "
        "WHERE template_id = ? AND is_current = 1 AND kind != 'ABSTRACT'", (template_id,)).fetchall()
    conn.execute(
        "DELETE FROM concept_targets WHERE concept_uuid IN (SELECT concept_uuid FROM concept_nodes "
        "WHERE template_id = ? AND is_current = 1)", (template_id,))
    out = []
    for concept_uuid, sheet, row, render_col in rows:
        if "socie" in (sheet or "").lower():
            continue
        layout = _GROUP_COL_LAYOUT if group else [("CY", "Company", render_col or "B"),
                                                  ("PY", "Company", "C")]
        out.extend((concept_uuid, scope, period, sheet, row, col) for period, scope, col in layout)
    conn.executemany(
        "INSERT OR REPLACE INTO concept_targets(concept_uuid, entity_scope, period, target_sheet, "
        "target_row, target_col) VALUES (?, ?, ?, ?, ?, ?)", out)
