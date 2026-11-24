"""The `placements` table: the cells the investigating agent proposed for one fill, and a person's Use or
Skip of each (docs/api-contract.md, Step 12)."""
from __future__ import annotations

import sqlite3

from app import db
from app.filing import mappings
from app.filing.mappings import KEY, key

# The receipt codes the agent investigates: the fill found no single cell, or what it wrote did not read back.
INVESTIGATED = frozenset({"no_cell", "no_sheet", "ambiguous", "columns_not_marked", "shared_cell", "not_written",
                          "read_back"})
from app.filing.receipts import NOT_FOUND  # noqa: E402 - one sentence, shared with the receipt


def to_place(report: dict, looked_at: frozenset = frozenset()) -> list[dict]:
    """The figures of a fill's report the agent looks for a place for, each once: not a total (the template
    works totals out itself), and not one an earlier investigation of this template already looked at."""
    seen, out = set(looked_at), []
    for line in (report.get("unresolved") or []) + (report.get("mismatched") or []):
        if line.get("concept_uuid") and line.get("code") in INVESTIGATED and not line.get("total") \
                and key(line) not in seen:
            seen.add(key(line))
            out.append(line)
    return out


def looked_at(conn: sqlite3.Connection, fingerprint: str) -> frozenset:
    """The figures any finished investigation of this template proposed a place for or found none for."""
    return frozenset(key(dict(r)) for r in conn.execute(
        "SELECT p.concept_uuid, p.period, p.entity_scope, p.dimension_key FROM placements p JOIN fills f ON "
        "f.id = p.fill_id WHERE f.template_fingerprint = ? AND f.investigation = 'done'", (fingerprint,)))


def not_found(conn: sqlite3.Connection, fill_id: int, line: dict, why: str) -> None:
    """Record that the agent looked for this figure and found no single cell, with its reason."""
    conn.execute(
        "INSERT INTO placements(fill_id, concept_uuid, period, entity_scope, dimension_key, figure_name, sheet, "
        "cell, place, evidence, status, created_at) VALUES (?, ?, ?, ?, ?, ?, '', '', '', ?, 'not_found', ?) "
        "ON CONFLICT(fill_id, concept_uuid, period, entity_scope, dimension_key) DO NOTHING",
        (fill_id, *key(line), line.get("name") or line.get("field") or "A figure", why, db.now()))


def not_found_keys(conn: sqlite3.Connection, fill_id: int) -> frozenset:
    return frozenset(key(dict(r)) for r in conn.execute(
        "SELECT concept_uuid, period, entity_scope, dimension_key FROM placements WHERE fill_id = ? AND "
        "status = 'not_found'", (fill_id,)))


def open_count(conn: sqlite3.Connection, fill_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM placements WHERE fill_id = ? AND status = 'open'",
                        (fill_id,)).fetchone()[0]


def propose(conn: sqlite3.Connection, fill_id: int, line: dict, sheet: str, cell: str, place: str,
            evidence: str) -> None:
    """Save the agent's proposal for a figure; a second proposal for the same figure replaces the first."""
    conn.execute(
        "INSERT INTO placements(fill_id, concept_uuid, period, entity_scope, dimension_key, figure_name, sheet, "
        "cell, place, evidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(fill_id, concept_uuid, period, entity_scope, dimension_key) DO UPDATE SET "
        "sheet = excluded.sheet, cell = excluded.cell, place = excluded.place, evidence = excluded.evidence, "
        "status = 'open', decided_by = NULL, decided_at = NULL",
        (fill_id, *key(line), line.get("name") or line.get("field") or "A figure", sheet,
         cell, place, evidence, db.now()))


def public(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "figure": row["figure_name"], "place": row["place"], "evidence": row["evidence"],
            "status": row["status"]}


def for_fill(conn: sqlite3.Connection, fill_id: int) -> list[sqlite3.Row]:
    """The places proposed for the fill, decided or not; never the figures it found no place for."""
    return conn.execute("SELECT * FROM placements WHERE fill_id = ? AND status != 'not_found' ORDER BY id",
                        (fill_id,)).fetchall()


def decide(conn: sqlite3.Connection, fill: sqlite3.Row, use: set[int], email: str, labels) -> int:
    """Mark each open placement of the fill used or skipped, and save the used ones as the template's mapping,
    each with its row's words now (`labels(sheet, row)`) so a later fill can tell the row has not moved.
    Returns how many were used."""
    rows = [r for r in for_fill(conn, fill["id"]) if r["status"] == "open"]
    chosen = [r for r in rows if r["id"] in use]
    stamp = db.now()
    for r in rows:
        conn.execute("UPDATE placements SET status = ?, decided_by = ?, decided_at = ? WHERE id = ?",
                     ("used" if r["id"] in use else "skipped", email, stamp, r["id"]))
    if chosen:
        cells = []
        for r in chosen:
            col = "".join(ch for ch in r["cell"] if ch.isalpha())
            row = int(r["cell"][len(col):])
            cells.append({**{k: r[k] for k in KEY}, "sheet": r["sheet"], "row": row, "col": col,
                          "label": labels(r["sheet"], row)})
        mappings.save(conn, fill["template_fingerprint"], fill["template_filename"], cells, email)
    return len(chosen)
