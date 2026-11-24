"""Walk an SSM presentation role into display rows, with the SSM labels.

Copied from v1 `scripts/generate_mpers_templates.py` (`load_label_map`,
`walk_role`, `walk_role_for_taxonomy`, `mpers_socie_components` and their
helpers). v1's catalogue imported the whole generator script at run time;
v2 keeps only the read-only taxonomy walk. The template-writing half of the
generator is not copied.
"""
from __future__ import annotations

import re
import threading
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from app.catalog.statements import TAXONOMY_DIR
from app.utils.paths import safe_path

_NS = {
    "link": "http://www.xbrl.org/2003/linkbase",
    "xlink": "http://www.w3.org/1999/xlink",
    "xml": "http://www.w3.org/XML/1998/namespace",
}
_XLINK = "{http://www.w3.org/1999/xlink}"
_STANDARD_LABEL_ROLE = "http://www.xbrl.org/2003/role/label"
_REPORTING_LABEL_ROLE = re.compile(r"/ReportingLabel$")
_REPORTING_TOTAL_LABEL_ROLE = re.compile(r"/ReportingTotalLabel$")
# Without a preferredLabel, the SSM ReportingLabel wins, then the standard label.
_DEFAULT_LABEL_PRIORITY = ("ReportingLabel", _STANDARD_LABEL_ROLE)

_DISPLAY_LABEL_SUFFIXES = (
    "[text block]", "[textblock]", "[abstract]", "[axis]", "[member]", "[table]", "[line items]",
)
# Rows that are only XBRL scaffolding. v1's templates leave them out.
_STRUCTURAL_LABEL_SUFFIXES = ("[table]", "[axis]", "[member]", "[line items]")
_DISPLAY_SUFFIX_RE = re.compile(
    r"\s*(?:" + "|".join(re.escape(s) for s in _DISPLAY_LABEL_SUFFIXES) + r")\s*$",
    re.IGNORECASE,
)

_lock = threading.Lock()
_label_roles: dict[str, dict[str, str]] | None = None


def strip_display_suffix(text: str) -> str:
    return _DISPLAY_SUFFIX_RE.sub("", text) if isinstance(text, str) else text


def _is_structural_label(text: str) -> bool:
    return isinstance(text, str) and any(
        text.strip().lower().endswith(s) for s in _STRUCTURAL_LABEL_SUFFIXES)


def _concept_id_from_href(href: str) -> str:
    return href.split("#", 1)[-1]


def _normalise_label_role(raw_role: str) -> str:
    if _REPORTING_TOTAL_LABEL_ROLE.search(raw_role):
        return "ReportingTotalLabel"
    if _REPORTING_LABEL_ROLE.search(raw_role):
        return "ReportingLabel"
    return raw_role


def _load_label_roles() -> dict[str, dict[str, str]]:
    """{concept id: {label role: English label}} from every English label file."""
    global _label_roles
    with _lock:
        if _label_roles is not None:
            return _label_roles
        files = [
            *TAXONOMY_DIR.rglob("lab_en-*.xml"),
            *TAXONOMY_DIR.rglob("lab_en_*.xml"),
            *TAXONOMY_DIR.rglob("lab_ifrs_for_smes-en*.xml"),
        ]
        seen: set[Path] = set()
        result: dict[str, dict[str, str]] = defaultdict(dict)
        for lab_file in files:
            if lab_file in seen:
                continue
            seen.add(lab_file)
            try:
                root = ET.parse(safe_path(lab_file)).getroot()
            except ET.ParseError:
                continue
            locs: dict[str, str] = {}
            labels: dict[str, tuple[str, str]] = {}
            arcs: list[tuple[str, str]] = []
            for elem in root.iter():
                tag = elem.tag.split("}", 1)[-1]
                if tag == "loc":
                    key, href = elem.get(f"{_XLINK}label"), elem.get(f"{_XLINK}href")
                    if key and href:
                        locs[key] = _concept_id_from_href(href)
                elif tag == "label":
                    key, text = elem.get(f"{_XLINK}label"), (elem.text or "").strip()
                    if key and text:
                        labels[key] = (elem.get(f"{_XLINK}role") or "", text)
                elif tag == "labelArc":
                    frm, to = elem.get(f"{_XLINK}from"), elem.get(f"{_XLINK}to")
                    if frm and to:
                        arcs.append((frm, to))
            for frm, to in arcs:
                concept_id, info = locs.get(frm), labels.get(to)
                if concept_id and info:
                    result[concept_id].setdefault(_normalise_label_role(info[0]), info[1])
        _label_roles = {k: dict(v) for k, v in result.items()}
        return _label_roles


def resolve_label(concept_id: str, preferred_role: str | None) -> str:
    roles = _load_label_roles().get(concept_id, {})
    if preferred_role:
        if preferred_role in roles:
            return roles[preferred_role]
        short = _normalise_label_role(preferred_role)
        if short in roles:
            return roles[short]
    for fallback in _DEFAULT_LABEL_PRIORITY:
        if fallback in roles:
            return roles[fallback]
    return next(iter(roles.values()), concept_id)


def walk_role(pre_file: Path) -> list[tuple[int, str, str, bool]]:
    """A presentation linkbase as display rows: (depth, concept id, label, abstract)."""
    root = ET.parse(safe_path(pre_file)).getroot()
    rows: list[tuple[int, str, str, bool]] = []
    for pres_link in root.iter(f"{{{_NS['link']}}}presentationLink"):
        loc_map: dict[str, str] = {}
        children: dict[str, list[tuple[float, str, str | None]]] = defaultdict(list)
        froms: set[str] = set()
        tos: set[str] = set()
        for elem in pres_link:
            tag = elem.tag.split("}", 1)[-1]
            if tag == "loc":
                key, href = elem.get(f"{_XLINK}label"), elem.get(f"{_XLINK}href")
                if key and href:
                    loc_map[key] = _concept_id_from_href(href)
            elif tag == "presentationArc":
                frm, to = elem.get(f"{_XLINK}from"), elem.get(f"{_XLINK}to")
                if not (frm and to):
                    continue
                try:
                    order = float(elem.get("order", "0"))
                except ValueError:
                    order = 0.0
                children[frm].append((order, to, elem.get("preferredLabel")))
                froms.add(frm)
                tos.add(to)
        roots = [lbl for lbl in loc_map if lbl in froms and lbl not in tos] or [
            lbl for lbl in loc_map if lbl not in tos]

        def dfs(label: str, depth: int, preferred: str | None) -> None:
            concept_id = loc_map.get(label)
            if not concept_id:
                return
            text = resolve_label(concept_id, preferred)
            if not _is_structural_label(text):
                rows.append((depth, concept_id, strip_display_suffix(text),
                             concept_id.endswith("Abstract")))
            for _order, child, child_preferred in sorted(children[label], key=lambda x: x[0]):
                dfs(child, depth + 1, child_preferred)

        for root_label in roots:
            dfs(root_label, 0, None)
    return rows


def role_dir(standard: str) -> Path:
    return TAXONOMY_DIR / "rep" / "ssm" / "ca-2016" / "fs" / standard


def walk_role_for_taxonomy(standard: str, role_number: str) -> list[tuple[int, str, str, bool]]:
    standard = standard.lower()
    return walk_role(role_dir(standard) / f"pre_ssmt-fs-{standard}_2022-12-31_role-{role_number}.xml")


def mpers_socie_components() -> list[tuple[str, str, list[str]]]:
    """MPERS equity columns and their subtotal children, from role 610000's domain."""
    path = role_dir("mpers") / "def_ssmt-fs-mpers_2022-12-31_role-610000.xml"
    root = ET.parse(safe_path(path)).getroot()
    locators = {loc.get(_XLINK + "label"): loc.get(_XLINK + "href").split("#")[-1]
                for loc in root.findall(".//link:loc", _NS)}
    children: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for arc in root.findall(".//link:definitionArc", _NS):
        if not arc.get(_XLINK + "arcrole", "").endswith("/domain-member"):
            continue
        parent, child = locators[arc.get(_XLINK + "from")], locators[arc.get(_XLINK + "to")]
        if parent.endswith("Member") and child.endswith("Member"):
            children[parent].append((float(arc.get("order", 0)), child))
    result: list[tuple[str, str, list[str]]] = []

    def walk(member: str) -> None:
        descendants = [child for _, child in sorted(children.get(member, []))]
        for child in descendants:
            walk(child)
        label = "Total" if member == "ifrs-smes_EquityMember" else strip_display_suffix(
            resolve_label(member, None))
        result.append((member, label, descendants))

    walk("ifrs-smes_EquityMember")
    if len(result) != 14:
        raise ValueError("MPERS SOCIE component domain changed; review native column semantics")
    return result
