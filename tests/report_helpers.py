"""A confirmed run whose document holds the three reports, for the report
store, route and agent tests. No model is called.

Pages 2-5 are transcriptions as the Reader stores them: the directors'
report (2-3), the statement by directors (4) and the auditors' report (5).
The document map names the three sections, as the Reader saves it.
"""
from __future__ import annotations

import json

from app import db
from app.reading import store as reading
from tests.conftest import make_run
from tests.notes_helpers import stored_page

PAGES = {
    1: {"folio": "1", "rotation": 0, "kind": "cover", "title": "", "blocks": [
        {"type": "heading", "level": 1, "text": "Example Sdn. Bhd. Financial statements 2025"}]},
    2: {"folio": "2", "rotation": 0, "kind": "directors_report", "title": "Directors' report", "blocks": [
        {"type": "heading", "level": 1, "text": "Directors' report"},
        {"type": "paragraph", "text": "The directors present their report with the audited financial statements "
                                      "for the financial year ended 31 December 2025."},
        {"type": "paragraph", "text": "No dividend has been paid or declared since the end of the previous "
                                      "financial year."},
        {"type": "paragraph", "text": "No contingent or other liability has become enforceable within twelve "
                                      "months after the end of the financial year."},
    ]},
    3: {"folio": "3", "rotation": 0, "kind": "directors_report", "title": "", "blocks": [
        {"type": "paragraph", "text": "Signed in accordance with a resolution of the directors."},
        {"type": "paragraph", "text": "Tan Ah Kow (900101-14-5678) Director, Lim Mei Ling (880202-10-1234) "
                                      "Director, Kuala Lumpur, 30 April 2026"},
    ]},
    4: {"folio": "4", "rotation": 0, "kind": "statement_by_directors", "title": "Statement by directors", "blocks": [
        {"type": "heading", "level": 1, "text": "Statement by directors"},
        {"type": "paragraph", "text": "In the opinion of the directors, the financial statements give a true and "
                                      "fair view in accordance with MFRS."},
    ]},
    5: {"folio": "5", "rotation": 0, "kind": "auditors_report", "title": "Independent auditors' report", "blocks": [
        {"type": "heading", "level": 1, "text": "Independent auditors' report to the members"},
        {"type": "paragraph", "text": "Opinion. We have audited the financial statements ... In our opinion the "
                                      "financial statements give a true and fair view."},
        {"type": "paragraph", "text": "Example & Co. AF 0001, Chartered Accountants. Wong Kar Wai 03339/12/2025 J, "
                                      "Chartered Accountant. Kuala Lumpur, 30 April 2026"},
    ]},
}

SECTIONS = [
    {"kind": "directors_report", "title": "Directors' report", "first_page": 2, "last_page": 3},
    {"kind": "statement_by_directors", "title": "Statement by directors", "first_page": 4, "last_page": 4},
    {"kind": "statutory_declaration", "title": "Statutory declaration", "first_page": 4, "last_page": 4},
    {"kind": "auditors_report", "title": "Independent auditors' report", "first_page": 5, "last_page": 5},
]


def reports_run(*, standard: str = "MFRS", level: str = "Company", sections=SECTIONS) -> int:
    """A confirmed run with the report pages read and the document map saved."""
    run_id = make_run(standard=standard, level=level)
    stamp = db.now()
    with db.connect(immediate=True) as conn:
        conn.execute("UPDATE runs SET status = 'ready' WHERE id = ?", (run_id,))
        conn.execute("UPDATE run_setup SET year_end = '2025-12-31' WHERE run_id = ?", (run_id,))
        doc = conn.execute(
            "INSERT INTO documents(run_id, filename, stored_path, sha256, size_bytes, page_count, uploaded_by, "
            "uploaded_at) VALUES (?, 'fs.pdf', 'x/fs.pdf', 'abc', 1, ?, 'test', ?)",
            (run_id, max(PAGES), stamp)).lastrowid
        for page, raw in PAGES.items():
            conn.execute("INSERT INTO pages(document_id, page, width, height, rotation, has_text_layer, "
                         "content_json, read_at) VALUES (?, ?, 595, 842, 0, 1, ?, ?)",
                         (doc, page, json.dumps(stored_page(raw)), stamp))
        reading.save_map(conn, run_id, {"statements": [], "notes": [], "other_sections": list(sections)}, [])
    return run_id
