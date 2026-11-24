"""Copying note blocks from the Reader's page content (step 6b)."""
from __future__ import annotations

from collections import Counter

import pytest

from app import db
from app.notes import copy
from app.notes.blocks import Heading, ListBlock, Paragraph, Table, words
from app.reading.content import table_rows
from tests.notes_helpers import BORROWINGS_TABLE, PAGES, PPE_TABLE, RECEIVABLES_TABLE, notes_run, stored_page

TABLES = [PPE_TABLE, RECEIVABLES_TABLE, BORROWINGS_TABLE]


def all_sources():
    return [(page, i) for page, raw in PAGES.items() for i in range(len(raw["blocks"]))]


def test_copying_keeps_every_word_of_every_block_exactly():
    run_id = notes_run()
    with db.connect() as conn:
        blocks = copy.copy_blocks(conn, run_id, all_sources())
    for block, (page, index) in zip(blocks, all_sources()):
        stored = stored_page(PAGES[page])["blocks"][index]
        assert (block.source.page, block.source.block, block.id) == (page, index, f"p{page}b{index}")
        if isinstance(block, (Heading, Paragraph)):
            assert block.text == stored["text"]
        elif isinstance(block, ListBlock):
            assert [i.text for i in block.items] == stored["items"]
        else:
            assert isinstance(block, Table)
            # Every cell the Reader transcribed is in the note, once, word for word.
            printed = Counter(t for row in table_rows(stored) for t in row if t)
            copied = Counter(c.text for r in block.rows for c in r.cells if c.text)
            assert copied == printed


@pytest.mark.parametrize("html", TABLES)
def test_split_cells_leave_a_rectangular_table_and_keep_every_cell(html):
    table = copy.copy_block(stored_page({"folio": None, "rotation": 0, "kind": "notes",
                                         "blocks": [{"type": "table", "html": html}]})["blocks"][0], 9, 0)
    widths = {len(r.cells) for r in table.rows}
    assert widths == {len(table.columns)}
    reader_rows = table_rows({"type": "table", "html": html})
    assert sorted(c.text for r in table.rows for c in r.cells if c.text) == sorted(
        t for row in reader_rows for t in row if t)


def column_of(table: Table, text: str) -> list[int]:
    return [i for r in table.rows for i, c in enumerate(r.cells) if c.text == text]


def test_a_merged_header_puts_its_text_in_the_first_cell_and_amounts_stay_under_their_year():
    table = copy.copy_block({"type": "table", "html": stored_page({"folio": None, "rotation": 0, "kind": "notes",
                             "blocks": [{"type": "table", "html": PPE_TABLE}]})["blocks"][0]["html"]}, 23, 2)
    assert [c.text for c in table.rows[0].cells] == ["", "Group", "", "Company", ""]
    years = [c.text for c in table.rows[1].cells]
    assert years == ["", "2025 RM", "2024 RM", "2025 RM", "2024 RM"]
    assert [c.text for c in table.rows[2].cells] == ["Cost", "1,200,500", "1,000,000", "500,250", "400,000"]
    assert [c.text for c in table.rows[3].cells][4] == "-"
    assert [r.role for r in table.rows] == ["heading", "heading", "item", "item", "item"]
    assert [c.role for c in table.columns] == ["label", "amount", "amount", "amount", "amount"]


def test_a_row_span_label_does_not_push_the_next_rows_amounts_into_another_column():
    table = copy.copy_block({"type": "table", "html": RECEIVABLES_TABLE}, 23, 4)
    assert [c.text for c in table.rows[1].cells] == ["Trade receivables", "Third parties", "3,400", "2,900"]
    assert [c.text for c in table.rows[2].cells] == ["", "Related parties", "120", "(80)"]
    assert [c.text for c in table.rows[3].cells] == ["Less: Impairment", "", "(20)", "(15)"]
    for amount, column in (("3,400", 2), ("120", 2), ("(20)", 2), ("3,500", 2), ("2,900", 3), ("(80)", 3)):
        assert column_of(table, amount) == [column]


def test_a_row_span_in_a_middle_column_keeps_the_amounts_in_their_columns():
    table = copy.copy_block({"type": "table", "html": BORROWINGS_TABLE}, 24, 3)
    assert [c.text for c in table.rows[2].cells] == ["Hire purchase", "", "12,500", "30,000"]
    assert [c.text for c in table.rows[3].cells] == ["Bank overdraft", "", "8,000", "-"]
    assert column_of(table, "4.5% - 5.2%") == [1]
    assert column_of(table, "120,500") == [2] and column_of(table, "430,000") == [3]
    assert [c.role for c in table.columns] == ["label", "text", "amount", "amount"]


def test_ragged_rows_are_padded_and_a_span_past_the_last_row_adds_no_row():
    table = copy.copy_block({"type": "table", "html": "<table><tr><td rowspan=\"3\">A</td><td>1</td></tr>"
                             "<tr><td>2</td></tr></table>"}, 1, 0)
    assert [[c.text for c in r.cells] for r in table.rows] == [["A", "1"], ["", "2"]]
    table = copy.copy_block({"type": "table", "html": "<table><tr><td>A</td><td>1</td><td>2</td></tr>"
                             "<tr><td>B</td></tr></table>"}, 1, 0)
    assert [[c.text for c in r.cells] for r in table.rows] == [["A", "1", "2"], ["B", "", ""]]


def test_a_block_not_on_a_page_of_this_run_is_named_in_one_sentence():
    run_id = notes_run()
    with db.connect() as conn:
        for bad in ((23, 9), (2, 0), (99, 0)):
            with pytest.raises(copy.NotFromRun) as exc:
                copy.copy_blocks(conn, run_id, [bad])
            assert str(exc.value) == (f"Page {bad[0]} of this run has no block {bad[1]}, "
                                      "so place blocks shown on this run's pages.")
    other = notes_run()
    with db.connect() as conn:  # another run's pages are not this run's
        assert words_of(conn, other, [(23, 0)]) == ["4. Property, plant and equipment"]
        conn.execute("DELETE FROM pages WHERE document_id = (SELECT id FROM documents WHERE run_id = ?)", (run_id,))
        with pytest.raises(copy.NotFromRun):
            copy.copy_blocks(conn, run_id, [(23, 0)])


def words_of(conn, run_id, sources):
    from app.notes.blocks import NoteBody
    return words(NoteBody(blocks=copy.copy_blocks(conn, run_id, sources)))
