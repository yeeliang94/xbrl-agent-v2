"""A run with notes pages read, and note fields to place notes in, for the
note store tests. No model is called.

The pages are realistic transcriptions of notes pages, as the Reader stores
them (validated through `PageContent`), with merged table cells. The note
fields are put straight into `notes_nodes` under a test template, so these
tests do not wait for the prose-note catalogue (step 6a).
"""
from __future__ import annotations

import json

from app import db
from app.reading.content import PageContent
from tests.conftest import make_run

TEMPLATE = "TEST-NOTES"
AGENT = ("agent", "notes")

# node_uuid: (row, label, kind)
FIELDS = {
    "test-heading": (1, "Notes to the financial statements", "ABSTRACT"),
    "test-ppe": (2, "Disclosure of property, plant and equipment", "LEAF"),
    "test-receivables": (3, "Disclosure of trade and other receivables", "LEAF"),
    "test-borrowings": (4, "Disclosure of borrowings", "LEAF"),
    "test-other": (5, "*Disclosure of other notes to accounts", "LEAF"),
}

PPE_TABLE = (
    "<table><tr><th></th><th colspan=\"2\">Group</th><th colspan=\"2\">Company</th></tr>"
    "<tr><th></th><th>2025<br>RM</th><th>2024<br>RM</th><th>2025<br>RM</th><th>2024<br>RM</th></tr>"
    "<tr><td>Cost</td><td>1,200,500</td><td>1,000,000</td><td>500,250</td><td>400,000</td></tr>"
    "<tr><td>Accumulated depreciation</td><td>(320,100)</td><td>(250,000)</td><td>(90,000)</td><td>-</td></tr>"
    "<tr><td>Carrying amount</td><td>880,400</td><td>750,000</td><td>410,250</td><td>400,000</td></tr></table>")

RECEIVABLES_TABLE = (
    "<table><tr><th colspan=\"2\"></th><th>2025 RM</th><th>2024 RM</th></tr>"
    "<tr><td rowspan=\"2\">Trade receivables</td><td>Third parties</td><td>3,400</td><td>2,900</td></tr>"
    "<tr><td>Related parties</td><td>120</td><td>(80)</td></tr>"
    "<tr><td colspan=\"2\">Less: Impairment</td><td>(20)</td><td>(15)</td></tr>"
    "<tr><td colspan=\"2\">Total</td><td>3,500</td><td>2,805</td></tr></table>")

BORROWINGS_TABLE = (
    "<table><tr><th>Borrowings</th><th>Rate</th><th>Within 1 year RM</th><th>1 to 5 years RM</th></tr>"
    "<tr><td>Term loan</td><td rowspan=\"3\">4.5% - 5.2%</td><td>100,000</td><td>400,000</td></tr>"
    "<tr><td>Hire purchase</td><td>12,500</td><td>30,000</td></tr>"
    "<tr><td>Bank overdraft</td><td>8,000</td><td>-</td></tr>"
    "<tr><td>Total</td><td></td><td>120,500</td><td>430,000</td></tr></table>")

PAGES = {
    23: {"folio": "21", "rotation": 0, "kind": "notes", "title": "Notes to the financial statements", "blocks": [
        {"type": "heading", "level": 2, "text": "4. Property, plant and equipment"},
        {"type": "paragraph", "text": "Property, plant and equipment are stated at cost less accumulated "
                                      "depreciation and any impairment losses."},
        {"type": "table", "html": PPE_TABLE},
        {"type": "heading", "level": 2, "text": "5. Trade and other receivables"},
        {"type": "table", "html": RECEIVABLES_TABLE},
    ]},
    24: {"folio": "22", "rotation": 0, "kind": "notes", "title": "", "blocks": [
        {"type": "paragraph", "text": "The normal trade credit terms range from 30 to 90 days."},
        {"type": "heading", "level": 2, "text": "6. Borrowings"},
        {"type": "list", "items": ["(a) The term loan is secured by a charge over the land.",
                                   "(b) The hire purchase is repayable in monthly instalments."]},
        {"type": "table", "html": BORROWINGS_TABLE},
    ]},
}


def add_fields() -> None:
    with db.connect() as conn:
        for uuid, (row, label, kind) in FIELDS.items():
            conn.execute("INSERT OR IGNORE INTO notes_nodes(node_uuid, template_id, sheet, row, label, kind) "
                         "VALUES (?, ?, 'Notes-Listofnotes', ?, ?, ?)", (uuid, TEMPLATE, row, label, kind))


def stored_page(raw: dict) -> dict:
    """A page as the Reader stores it."""
    return PageContent.model_validate(raw).model_dump(mode="json")


def notes_run(pages: dict = PAGES) -> int:
    """A run whose document has these pages read, plus the test note fields."""
    run_id = make_run()
    add_fields()
    stamp = db.now()
    with db.connect() as conn:
        doc = conn.execute(
            "INSERT INTO documents(run_id, filename, stored_path, sha256, size_bytes, page_count, uploaded_by, "
            "uploaded_at) VALUES (?, 'fs.pdf', 'x/fs.pdf', 'abc', 1, ?, 'test', ?)",
            (run_id, max(pages), stamp)).lastrowid
        for page in range(1, max(pages) + 1):
            content = stored_page(pages[page]) if page in pages else None
            conn.execute("INSERT INTO pages(document_id, page, width, height, rotation, has_text_layer, "
                         "content_json, read_at) VALUES (?, ?, 595, 842, 0, 1, ?, ?)",
                         (doc, page, json.dumps(content) if content else None, stamp if content else None))
    return run_id
