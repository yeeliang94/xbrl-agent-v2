"""Which template cells can be written, and their SSM field names.

Copied from v1 `concept_model/filing_targets.py` (`FilingTarget`,
`_numeric_targets`, `_reviewed_exception`, `persist_template_manifest`).
A slot is writable only when its role is an input and its taxonomy element is
reportable. Not copied: the prose-note targets (step 6) and the queries that
repaired v1's historical facts and notes rows, which v2 does not have.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import openpyxl

from app.catalog.parser import ConceptNode, ConceptTree
from app.catalog.taxonomy import taxonomy_concept
from app.utils.paths import safe_path

MANIFEST_VERSION = "2022-v1-slot-semantics-3"
WRITABLE_SLOT_ROLES = frozenset({"INPUT", "MATRIX_INPUT"})


@dataclass(frozen=True)
class FilingTarget:
    template_id: str
    sheet: str
    row: int
    col: str | None
    target_id: str
    canonical_target_id: str
    label: str
    slot_role: str
    value_kind: str
    taxonomy_element_id: str | None
    reportable: bool
    dimensions: dict[str, str]
    mapping_source: str
    exception_code: str | None = None

    @property
    def writable(self) -> bool:
        return self.slot_role in WRITABLE_SLOT_ROLES and self.reportable



def _reviewed_exception(path: Path, node: ConceptNode | None = None) -> str | None:
    is_mfrs = any(part == "XBRL-template-MFRS" for part in path.parts)
    if node is None and path.name == "13-Notes-IssuedCapital.xlsx" and is_mfrs:
        return "MFRS_ISSUED_CAPITAL_WRAPPER_OMITTED"
    if node is None and path.name == "14-Notes-RelatedParty.xlsx" and is_mfrs:
        return "MFRS_RELATED_PARTY_WRAPPER_OMITTED"
    if node is not None and node.render_key.get("semantic_address") is None:
        if path.name == "05-SOCI-BeforeTax.xlsx" and node.render_key.get("row") == 3:
            return "PRESENTATION_TITLE_WITHOUT_TAXONOMY_SLOT"
        if path.name == "09-SOCIE.xlsx" and node.kind == "ABSTRACT":
            return "SOCIE_SECTION_HEADER_WITHOUT_TAXONOMY_SLOT"
    return None


def numeric_targets(path: Path, tree: ConceptTree) -> list[FilingTarget]:
    """One target per physical cell. SOCIE cells have one per block."""
    targets: list[FilingTarget] = []
    wb = openpyxl.load_workbook(safe_path(path), read_only=False, data_only=False)
    try:
        for node in tree.concepts:
            rk = node.render_key
            address = rk.get("semantic_address") or {}
            element_id = address.get("primary_concept")
            concept = taxonomy_concept(element_id) if element_id else None
            base_role = str(rk.get("slot_role") or "UNMAPPED")
            exception = _reviewed_exception(path, node)
            if base_role == "UNMAPPED" and exception:
                base_role = "PRESENTATION_ONLY"
            physical = list(rk.get("targets") or []) or [{
                "sheet": rk.get("sheet") or "", "row": int(rk.get("row") or 0),
                "col": rk.get("matrix_col") or rk.get("col")}]
            for spot in physical:
                sheet = str(spot.get("sheet") or rk.get("sheet") or "")
                row = int(spot.get("row") or 0)
                col = spot.get("col") or rk.get("matrix_col") or rk.get("col")
                if rk.get("targets") and base_role in {"MATRIX_INPUT", "MATRIX_FORMULA"}:
                    value = wb[sheet].cell(row=row, column=openpyxl.utils.column_index_from_string(str(col))).value
                    is_formula = isinstance(value, str) and value.startswith("=")
                    if is_formula != (base_role == "MATRIX_FORMULA"):
                        raise ValueError(
                            f"SOCIE physical-slot role drift: {tree.template_id} {sheet}!{col}{row} is "
                            f"{'formula' if is_formula else 'input'} but its slot is {base_role}.")
                dimensions = dict(address.get("dimensions") or {})
                for dimension in ("period", "entity_scope"):
                    if spot.get(dimension):
                        dimensions[dimension] = str(spot[dimension])
                targets.append(FilingTarget(
                    template_id=tree.template_id, sheet=sheet, row=row,
                    col=str(col) if col is not None else None,
                    target_id=f"{node.concept_uuid}:{sheet}:{row}:{col}",
                    canonical_target_id=node.concept_uuid, label=node.canonical_label,
                    slot_role=base_role,
                    value_kind=("html" if concept and (concept.data_type or "").lower().endswith(
                        "textblockitemtype") else "numeric"),
                    taxonomy_element_id=element_id,
                    reportable=bool(concept and concept.reportable),
                    dimensions=dimensions,
                    mapping_source=("reviewed_exception" if exception and element_id
                                    else "presentation_linkbase" if element_id else "none"),
                    exception_code=exception,
                ))
    finally:
        wb.close()
    slots = [(t.sheet, t.row, t.col) for t in targets]
    if len(slots) != len(set(slots)):
        raise ValueError(f"Template {tree.template_id} contains duplicate physical filing slots.")
    return targets


def persist_template_manifest(conn: sqlite3.Connection, path: Path, tree: ConceptTree,
                              fingerprint: str) -> int:
    """Replace one template's taxonomy elements and slot list."""
    template_id = tree.template_id
    targets = numeric_targets(path, tree)
    linked = {t.taxonomy_element_id for t in targets if t.taxonomy_element_id} | {
        element for t in targets for key, value in t.dimensions.items()
        if key not in {"period", "entity_scope"} for element in (key, value)}
    rows = []
    for element_id in sorted(linked):
        c = taxonomy_concept(element_id)
        if c is None:
            raise ValueError(f"Template {template_id} references unknown taxonomy element {element_id!r}")
        rows.append((c.source_element_id, c.taxonomy_version, c.namespace_uri, c.local_name,
                     int(c.abstract), c.concept_role, c.data_type, c.period_type, c.balance,
                     c.substitution_group))
    conn.executemany(
        """
        INSERT INTO taxonomy_concepts(source_element_id, taxonomy_version, namespace_uri, local_name,
            abstract, concept_role, data_type, period_type, balance, substitution_group)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_element_id) DO UPDATE SET
            taxonomy_version = excluded.taxonomy_version, namespace_uri = excluded.namespace_uri,
            local_name = excluded.local_name, abstract = excluded.abstract,
            concept_role = excluded.concept_role, data_type = excluded.data_type,
            period_type = excluded.period_type, balance = excluded.balance,
            substitution_group = excluded.substitution_group
        """, rows)
    conn.execute("DELETE FROM template_slots WHERE template_id = ?", (template_id,))
    conn.execute("DELETE FROM template_manifest_exceptions WHERE template_id = ?", (template_id,))
    conn.executemany(
        """
        INSERT INTO template_slots(target_id, canonical_target_id, template_id, sheet, row, col, label,
            slot_role, value_kind, taxonomy_element_id, dimensions_json, mapping_source,
            manifest_version, workbook_fingerprint, validation_status, exception_code)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [(t.target_id, t.canonical_target_id, t.template_id, t.sheet, t.row, t.col or "", t.label,
          t.slot_role, t.value_kind, t.taxonomy_element_id,
          json.dumps(t.dimensions, sort_keys=True, separators=(",", ":")), t.mapping_source,
          MANIFEST_VERSION, fingerprint,
          "writable" if t.writable else "non_writable" if (t.taxonomy_element_id or t.exception_code)
          else "unresolved", t.exception_code) for t in targets],
    )
    exception = _reviewed_exception(path)
    if exception:
        conn.execute(
            "INSERT INTO template_manifest_exceptions(template_id, exception_code, manifest_version, "
            "workbook_fingerprint) VALUES (?, ?, ?, ?)", (template_id, exception, MANIFEST_VERSION, fingerprint))
    return len(targets)
