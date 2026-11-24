"""SSM taxonomy identity for template cells (the official field names).

Copied from v1 `concept_model/taxonomy_semantics.py`. `semantic_addresses_for`
returns, for one template, the taxonomy element (and fixed categories) of
each cell, keyed by (sheet, row, matrix column). A template that has drifted
from its presentation role gets no address and stays usable; only filing
readiness depends on the address.

Changes from v1: the report roles are left out (step 10), the generator
script is replaced by `taxonomy_walk`, and the standard and level are read
from the template's own two folders. `field_depths` is new: how deep each
prose-note field sits under its headings, from the same role walk.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import openpyxl

from app.catalog.statements import TAXONOMY_DIR
from app.catalog.taxonomy_walk import mpers_socie_components, walk_role_for_taxonomy
from app.utils.paths import safe_path

TAXONOMY_VERSION = "SSMxT_2022v1.0"
ADDRESS_VERSION = "2022-v2"

# The presentation roles that generated each template file.
_ROLES_BY_FILE: dict[str, tuple[str, ...]] = {
    "01-SOFP-CuNonCu.xlsx": ("210000", "210100"),
    "02-SOFP-OrderOfLiquidity.xlsx": ("220000", "220100"),
    "03-SOPL-Function.xlsx": ("310000", "310100"),
    "04-SOPL-Nature.xlsx": ("320000", "320100"),
    "05-SOCI-BeforeTax.xlsx": ("420000",),
    "06-SOCI-NetOfTax.xlsx": ("410000",),
    "07-SOCF-Indirect.xlsx": ("520000",),
    "08-SOCF-Direct.xlsx": ("510000",),
    "09-SOCIE.xlsx": ("610000",),
    "10-SoRE.xlsx": ("620000",),
    # Prose notes: MFRS files 10-12, MPERS 11-13.
    "10-Notes-CorporateInfo.xlsx": ("710000",),
    "11-Notes-CorporateInfo.xlsx": ("710000",),
    "11-Notes-AccountingPolicies.xlsx": ("720000",),
    "12-Notes-AccountingPolicies.xlsx": ("720000",),
    "12-Notes-ListOfNotes.xlsx": ("730000",),
    "13-Notes-ListOfNotes.xlsx": ("730000",),
    "13-Notes-IssuedCapital.xlsx": ("740000",),
    "14-Notes-RelatedParty.xlsx": ("750000",),
    "14-Notes-IssuedCapital.xlsx": ("740000",),
    "15-Notes-RelatedParty.xlsx": ("750000",),
}

# Presentation wrappers in the MFRS roles with no physical row in the SSM
# workbooks. Naming them keeps later fields from shifting by one row.
_REVIEWED_ROLE_OMISSIONS: dict[tuple[str, str], frozenset[str]] = {
    ("mfrs", "13-Notes-IssuedCapital.xlsx"): frozenset({
        "ifrs-full_DisclosureOfClassesOfShareCapitalAbstract",
    }),
    ("mfrs", "14-Notes-RelatedParty.xlsx"): frozenset({
        "ifrs-full_DisclosureOfTransactionsBetweenRelatedPartiesAbstract",
    }),
}

# MFRS SOCIE columns are members of ComponentsOfEquityAxis, in column order B..X.
_MFRS_SOCIE_COMPONENTS: tuple[str, ...] = (
    "ifrs-full_IssuedCapitalMember",
    "ifrs-full_RetainedEarningsMember",
    "ifrs-full_TreasurySharesMember",
    "ifrs-full_CapitalReserveMember",
    "ifrs-full_ReserveOfGainsAndLossesOnHedgingInstrumentsThatHedgeInvestmentsInEquityInstrumentsMember",
    "ssmt-mfrs_ForeignCurrencyTranslationReserveMember",
    "ifrs-full_ReserveOfSharebasedPaymentsMember",
    "ifrs-full_RevaluationSurplusMember",
    "ifrs-full_StatutoryReserveMember",
    "ifrs-full_WarrantReserveMember",
    "ssmt-mfrs_OtherNondistributableReserveMember",
    "ssmt_NonDistributableReservesMember",
    "ssmt-mfrs_FairValueAdjustmentReserveMember",
    "ssmt_ReserveOfNoncurrentAssetsClassifiedAsHeldForSaleMember",
    "ssmt-mfrs_ConsolidatedReserveMember",
    "ssmt-mfrs_WarrantyReserveMember",
    "ssmt-mfrs_OtherDistributableReserveMember",
    "ssmt_DistributableReservesMember",
    "ifrs-full_OtherReservesMember",
    "ifrs-full_EquityAttributableToOwnersOfParentMember",
    "ssmt-mfrs_OtherComponentsOfEquityMember",
    "ifrs-full_NoncontrollingInterestsMember",
    "ifrs-full_EquityMember",
)


@dataclass(frozen=True)
class TaxonomyConcept:
    taxonomy_version: str
    namespace_uri: str
    local_name: str
    source_element_id: str
    abstract: bool
    concept_role: str
    data_type: str | None
    period_type: str | None
    balance: str | None
    substitution_group: str | None

    @property
    def reportable(self) -> bool:
        return self.concept_role == "PRIMARY_ITEM" and not self.abstract


def _concept_role(element_id: str, attrs: dict[str, str]) -> str:
    if attrs.get("abstract", "false").lower() == "true":
        return "ABSTRACT"
    substitution = attrs.get("substitutionGroup", "")
    local_name = attrs.get("name", "")
    if substitution.endswith("dimensionItem") or local_name.endswith("Axis"):
        return "DIMENSION"
    if substitution.endswith("hypercubeItem") or local_name.endswith("Table"):
        return "HYPERCUBE"
    if local_name.endswith("Member") or element_id.endswith("Member"):
        return "MEMBER"
    if local_name.endswith("LineItems") or element_id.endswith("LineItems"):
        return "LINE_ITEMS"
    return "PRIMARY_ITEM"


@lru_cache(maxsize=1)
def taxonomy_registry() -> dict[str, TaxonomyConcept]:
    """Every element in the SSM schemas, by element id."""
    xs_element = "{http://www.w3.org/2001/XMLSchema}element"
    xbrli = "{http://www.xbrl.org/2003/instance}"
    out: dict[str, TaxonomyConcept] = {}
    for path in TAXONOMY_DIR.rglob("*.xsd"):
        try:
            schema = ET.parse(safe_path(path)).getroot()
        except ET.ParseError:
            continue
        namespace_uri = schema.attrib.get("targetNamespace", "")
        for element in schema.findall(xs_element):
            element_id = element.attrib.get("id")
            local_name = element.attrib.get("name")
            if not element_id or not local_name:
                continue
            attrs = dict(element.attrib)
            concept = TaxonomyConcept(
                taxonomy_version=TAXONOMY_VERSION,
                namespace_uri=namespace_uri,
                local_name=local_name,
                source_element_id=element_id,
                abstract=attrs.get("abstract", "false").lower() == "true",
                concept_role=_concept_role(element_id, attrs),
                data_type=attrs.get("type"),
                period_type=attrs.get(f"{xbrli}periodType"),
                balance=attrs.get(f"{xbrli}balance"),
                substitution_group=attrs.get("substitutionGroup"),
            )
            previous = out.get(element_id)
            if previous is not None and previous != concept:
                raise ValueError(f"Taxonomy element id {element_id!r} is defined inconsistently")
            out[element_id] = concept
    return out


def taxonomy_concept(source_element_id: str) -> TaxonomyConcept | None:
    return taxonomy_registry().get(source_element_id)


def _standard_and_level(path: Path) -> tuple[str, str] | None:
    """Read from the template's own two folders only (v1 read every folder in
    the path, so a checkout under a folder named "group" was misread)."""
    family, level = path.parent.parent.name.lower(), path.parent.name.lower()
    standard = "mpers" if "xbrl-template-mpers" in family else "mfrs" if "xbrl-template-mfrs" in family else None
    if standard is None or level not in ("company", "group"):
        return None
    return standard, level


@lru_cache(maxsize=64)
def _role_rows(standard: str, role: str) -> tuple[tuple[int, str, str, bool], ...]:
    return tuple(walk_role_for_taxonomy(standard, role))


def _address(primary: str, dimensions: dict[str, str] | None = None) -> dict[str, Any]:
    concept = taxonomy_concept(primary)
    address: dict[str, Any] = {
        "primary_concept": primary,
        "dimensions": dict(sorted((dimensions or {}).items())),
        "taxonomy_version": TAXONOMY_VERSION,
        "address_version": ADDRESS_VERSION,
    }
    if concept is not None:
        address.update({
            "namespace_uri": concept.namespace_uri,
            "local_name": concept.local_name,
            "concept_role": concept.concept_role,
            "abstract": concept.abstract,
            "reportable": concept.reportable,
            "data_type": concept.data_type,
            "period_type": concept.period_type,
            "balance": concept.balance,
        })
    return address


def _aligned_rows(path: Path, standard: str) -> list[tuple[str, int, tuple[int, str, str, bool]]]:
    """Each labelled row of a linear template beside the taxonomy row that
    generated it: (sheet, row, (depth, element id, label, abstract)). A sheet
    whose row count differs from its role is left out (the template drifted)."""
    roles = _ROLES_BY_FILE.get(path.name)
    if not roles:
        return []
    wb = openpyxl.load_workbook(safe_path(path), read_only=True, data_only=False)
    try:
        if len(wb.worksheets) != len(roles):
            return []
        out: list[tuple[str, int, tuple[int, str, str, bool]]] = []
        for ws, role in zip(wb.worksheets, roles):
            sheet_rows = [
                row for row, (value,) in enumerate(
                    ws.iter_rows(min_col=1, max_col=1, values_only=True), start=1)
                if value not in (None, "")
            ]
            taxonomy_rows = list(_role_rows(standard, role))
            if path.name in {"13-Notes-IssuedCapital.xlsx", "14-Notes-RelatedParty.xlsx"}:
                omissions = _REVIEWED_ROLE_OMISSIONS.get((standard, path.name), frozenset())
                taxonomy_rows = [
                    item for item in taxonomy_rows
                    if not item[1].lower().endswith(("table", "axis", "member", "lineitems"))
                    and item[1] not in omissions
                ]
            # One MFRS SOCI template carries a display-only title above the
            # linkbase rows. A larger difference means the template drifted.
            if (standard == "mfrs" and path.name == "05-SOCI-BeforeTax.xlsx"
                    and len(sheet_rows) == len(taxonomy_rows) + 1):
                sheet_rows = sheet_rows[1:]
            if len(sheet_rows) != len(taxonomy_rows):
                continue
            out.extend((ws.title, row, item) for row, item in zip(sheet_rows, taxonomy_rows))
        return out
    finally:
        wb.close()


def _linear_addresses(path: Path, standard: str) -> dict[tuple[str, int, str | None], dict[str, Any]]:
    return {(sheet, row, None): _address(item[1]) for sheet, row, item in _aligned_rows(path, standard)}


def _matrix_addresses(path: Path, standard: str, level: str) -> dict[tuple[str, int, str | None], dict[str, Any]]:
    wb = openpyxl.load_workbook(safe_path(path), read_only=True, data_only=False)
    try:
        ws = wb["SOCIE"] if "SOCIE" in wb.sheetnames else wb[wb.sheetnames[0]]
        taxonomy_rows = list(_role_rows(standard, "610000"))
        if standard == "mpers":
            line_items = taxonomy_rows[2:]
            matrix = bool(ws.cell(2, 2).value and ws.cell(2, 15).value == "Total")
            base_row = 6 if matrix or level == "group" else 5
            rows = range(base_row, base_row + len(line_items))
            if matrix:
                return {
                    (ws.title, row, openpyxl.utils.get_column_letter(col)): _address(
                        primary, {"ifrs-smes_ComponentsOfEquityAxis": member})
                    for row, (_, primary, _, _) in zip(rows, line_items)
                    for col, (member, _, _) in enumerate(mpers_socie_components(), 2)
                }
            return {
                (ws.title, row, "B"): _address(concept_id)
                for row, (_depth, concept_id, _label, _abstract) in zip(rows, line_items)
            }
        marker = "ifrs-full_StatementOfChangesInEquityLineItems"
        try:
            start = next(i for i, item in enumerate(taxonomy_rows) if item[1] == marker) + 1
        except StopIteration:
            return {}
        line_items = taxonomy_rows[start:]
        # The first current-year block, rows 6..25, is the concept home.
        rows = list(range(6, 6 + len(line_items)))
        if len(line_items) != 20 or ws.max_column < 24:
            return {}
        axis = "ifrs-full_ComponentsOfEquityAxis"
        out: dict[tuple[str, int, str | None], dict[str, Any]] = {}
        for row, (_depth, primary, _label, _abstract) in zip(rows, line_items):
            for offset, member in enumerate(_MFRS_SOCIE_COMPONENTS, start=2):
                out[(ws.title, row, openpyxl.utils.get_column_letter(offset))] = _address(
                    primary, {axis: member})
        return out
    finally:
        wb.close()


@lru_cache(maxsize=64)
def semantic_addresses_for(path_value: str) -> dict[tuple[str, int, str | None], dict[str, Any]]:
    """Taxonomy addresses keyed by (sheet, row, matrix column or None)."""
    path = Path(path_value).resolve()
    family = _standard_and_level(path)
    if family is None or path.name not in _ROLES_BY_FILE:
        return {}
    standard, level = family
    if path.name == "09-SOCIE.xlsx":
        return _matrix_addresses(path, standard, level)
    return _linear_addresses(path, standard)


@lru_cache(maxsize=64)
def field_depths(path_value: str) -> dict[tuple[str, int], int]:
    """How deep each labelled row sits in its role, keyed by (sheet, row):
    0 for the template's title, 1 for the rows under it, and so on. Empty for
    a template with no role or one that has drifted from it."""
    path = Path(path_value).resolve()
    family = _standard_and_level(path)
    if family is None or path.name == "09-SOCIE.xlsx":
        return {}
    return {(sheet, row): item[0] for sheet, row, item in _aligned_rows(path, family[0])}
