"""Build the template catalogue from the template files, only when they change.

Copied in purpose from v1 `concept_model/bootstrap.py`, which re-imported
every template at every start. v2 records each template's file hash and the
taxonomy's hash in `catalogue_sources`, and rebuilds only the templates whose
file, the taxonomy or this loader changed. An unchanged start-up reads the
files' hashes and stops.

Loaded: the 38 statement templates and the 8 numeric-note templates (issued
capital, related parties) into the concept tables, and the 12 prose-note
templates into `notes_nodes`. From step 10 the 12 report templates too: only
each one's narrative row, into `notes_nodes` (`app/catalog/reports.py`); a
report's other fields come from the taxonomy role, not the catalogue.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from functools import lru_cache
from pathlib import Path

from app import db
from app.catalog.importer import import_template
from app.catalog.manifest import persist_template_manifest
from app.catalog.notes_parser import NotesNode, import_notes_template, parse_notes_template
from app.catalog.parser import ConceptTree, derive_template_id, parse_template
from app.catalog.reports import narrative_node, report_for_path, report_template_paths
from app.catalog.statements import (
    CATCH_ALL_ELEMENTS,
    PROSE_NOTES,
    TAXONOMY_DIR,
    numeric_note_paths,
    prose_note_paths,
    statement_template_paths,
)
from app.utils.paths import PROJECT_ROOT, safe_path

logger = logging.getLogger(__name__)

# Change this when the parser, importer or manifest change what they write.
LOADER_VERSION = "v2-catalogue-2"   # 2: the report narratives (step 10)


def catalogue_paths() -> list[Path]:
    return statement_template_paths() + numeric_note_paths() + prose_note_paths() + report_template_paths()


def _prose_note(path: Path) -> str | None:
    return next((note for note, files in PROSE_NOTES.items() if path.name in files.values()), None)


@lru_cache(maxsize=1)
def _taxonomy_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in sorted(TAXONOMY_DIR.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(TAXONOMY_DIR).as_posix().encode())
            digest.update(safe_path(path).read_bytes())
    return digest.hexdigest()


def built_with() -> str:
    return f"{LOADER_VERSION}:{_taxonomy_fingerprint()[:16]}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(safe_path(path).read_bytes()).hexdigest()


@lru_cache(maxsize=64)
def _parsed(path_text: str, sha: str) -> ConceptTree:
    """Parse once per file version per process (keeps tests and restarts fast)."""
    del sha  # part of the cache key only
    return parse_template(Path(path_text))


@lru_cache(maxsize=64)
def _parsed_notes(path_text: str, sha: str) -> tuple[str, list[NotesNode]]:
    del sha  # part of the cache key only
    return parse_notes_template(Path(path_text))


def _check_catch_all(note: str, template_id: str, nodes: list[NotesNode]) -> None:
    """A changed template must still have its one catch-all field, or notes
    with nowhere else to go would have nowhere at all."""
    suffix = "_" + CATCH_ALL_ELEMENTS[note]
    found = [n for n in nodes if n.kind == "LEAF" and (n.taxonomy_element_id or "").endswith(suffix)]
    if len(found) != 1:
        raise ValueError(f"Template {template_id} has {len(found)} catch-all fields; it needs exactly one.")


def _load_prose(conn: sqlite3.Connection, path: Path, note: str, sha: str) -> str:
    template_id, nodes = _parsed_notes(str(path), sha)
    _check_catch_all(note, template_id, nodes)
    import_notes_template(conn, template_id, nodes)
    return template_id


def stale_templates(conn: sqlite3.Connection) -> list[tuple[Path, str]]:
    """The templates whose catalogue rows are missing or out of date."""
    stored = {r["template_id"]: (r["sha256"], r["built_with"])
              for r in conn.execute("SELECT template_id, sha256, built_with FROM catalogue_sources")}
    version = built_with()
    stale = []
    for path in catalogue_paths():
        sha = _sha256(path)
        if stored.get(derive_template_id(path)) != (sha, version):
            stale.append((path, sha))
    return stale


def load_catalogue() -> int:
    """Rebuild the changed templates. Returns how many were rebuilt."""
    with db.connect(immediate=True) as conn:
        stale = stale_templates(conn)
        if not stale:
            return 0
        version = built_with()
        for path, sha in stale:
            note = _prose_note(path)
            if note is not None:
                template_id = _load_prose(conn, path, note, sha)
            elif report_for_path(path) is not None:
                node = narrative_node(path)
                import_notes_template(conn, node.template_id, [node])
                template_id = node.template_id
            else:
                tree = _parsed(str(path), sha)
                import_template(conn, tree, path.relative_to(PROJECT_ROOT).as_posix())
                persist_template_manifest(conn, path, tree, sha)
                template_id = tree.template_id
            conn.execute(
                "INSERT INTO catalogue_sources(template_id, source_path, sha256, built_with, built_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(template_id) DO UPDATE SET "
                "source_path = excluded.source_path, sha256 = excluded.sha256, "
                "built_with = excluded.built_with, built_at = excluded.built_at",
                (template_id, path.relative_to(PROJECT_ROOT).as_posix(), sha, version, db.now()),
            )
    logger.info("Template catalogue: rebuilt %d template(s).", len(stale))
    return len(stale)
