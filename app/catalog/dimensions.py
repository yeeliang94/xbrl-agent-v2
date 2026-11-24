"""The category part of a figure's identity (share classes, related parties).

Copied from v1 `concept_model/dimensions.py` (`numeric_category_catalog`,
`dimension_key`, `instance_key`). An empty category keeps the plain identity.
A category already fixed by the concept (the equity column of a SOCIE cell)
is checked and then left out of the key, so one figure cannot have two keys.
Only the share-capital and related-party note sheets accept a category.
"""
from __future__ import annotations

import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from functools import lru_cache

from app.catalog.taxonomy_walk import role_dir
from app.utils.paths import safe_path

CATEGORY_SHEETS = {"Notes-Issuedcapital": "ClassesOfShareCapitalAxis",
                   "Notes-RelatedPartytran": "CategoriesOfRelatedPartiesAxis"}
_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")


class DimensionError(ValueError):
    """A category that cannot be part of this figure's identity."""


@lru_cache(maxsize=4)
def numeric_category_catalog(standard: str, *, roots_only: bool = False) -> dict[str, list[str]]:
    """Valid category members, from SSM's definition linkbases 740000 and 750000."""
    if standard not in {"mfrs", "mpers"}:
        raise ValueError("Unknown filing standard")
    xlink = "{http://www.w3.org/1999/xlink}"
    catalog: dict[str, list[str]] = {}
    for role in ("740000", "750000"):
        path, = role_dir(standard).glob(f"def_*role-{role}.xml")
        for link in ET.parse(safe_path(path)).getroot():
            locators = {e.get(xlink + "label"): e.get(xlink + "href", "").split("#")[-1]
                        for e in link if e.tag.endswith("}loc")}
            edges: dict[str, list[str]] = {}
            axes: dict[str, str] = {}
            for arc in link:
                kind = arc.get(xlink + "arcrole", "").rsplit("/", 1)[-1]
                source, target = (locators.get(arc.get(xlink + k)) for k in ("from", "to"))
                if source and target and kind in {"dimension-domain", "domain-member"}:
                    edges.setdefault(source, []).append(target)
                    if kind == "dimension-domain" and "ConsolidatedAndSeparate" not in source:
                        axes[source] = target
            for axis in axes:
                members: set[str] = set()
                pending = list(edges.get(axis, []))
                while pending:
                    member = pending.pop()
                    if member in members:
                        continue
                    members.add(member)
                    pending.extend(edges.get(member, []))
                catalog[axis] = [axes[axis]] if roots_only else sorted(members)
    return catalog


def dimension_key(dimensions: dict[str, str] | None = None) -> str:
    if not dimensions:
        return ""
    clean: dict[str, str] = {}
    for axis, member in dimensions.items():
        if not isinstance(axis, str) or not isinstance(member, str):
            raise DimensionError("A category maps a taxonomy axis to a member.")
        axis, member = axis.strip(), member.strip()
        if not _ID.fullmatch(axis) or not _ID.fullmatch(member):
            raise DimensionError("A category needs exact taxonomy names.")
        if axis in clean and clean[axis] != member:
            raise DimensionError("A category axis cannot have two members.")
        clean[axis] = member
    return json.dumps(clean, sort_keys=True, separators=(",", ":"))


def instance_key(conn: sqlite3.Connection, concept_uuid: str, dimensions: dict[str, str] | None) -> str:
    supplied = json.loads(dimension_key(dimensions) or "{}")
    row = conn.execute("SELECT dimensions_json FROM concept_semantic_addresses WHERE concept_uuid = ?",
                       (concept_uuid,)).fetchone()
    fixed = json.loads(row[0] or "{}") if row else {}
    for axis, member in fixed.items():
        if axis in supplied and supplied.pop(axis) != member:
            raise DimensionError("That category conflicts with this field's own category.")
    if supplied:
        node = conn.execute("SELECT template_id, render_sheet FROM concept_nodes WHERE concept_uuid = ?",
                            (concept_uuid,)).fetchone()
        if not node or node[1] not in CATEGORY_SHEETS:
            raise DimensionError("This field does not take a category.")
        catalog = numeric_category_catalog(node[0].split("-")[0])
        for axis, member in supplied.items():
            if not axis.endswith(CATEGORY_SHEETS[node[1]]) or member not in catalog.get(axis, []):
                raise DimensionError("That category does not belong to this note.")
    return dimension_key(supplied)
