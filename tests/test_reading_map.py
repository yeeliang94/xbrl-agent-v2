"""The save tool's refusals and points to check, and the history trimming."""
from __future__ import annotations

import copy
import json

import pytest
from pydantic_ai.messages import BinaryContent, ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from app.agents import history, loop
from app.reading import map_checks, reader
from app.reading.map_schema import DocumentMap
from tests import reading_fakes as fakes


def doc(**overrides) -> DocumentMap:
    return DocumentMap(**fakes.good_map(**overrides))


def note(number, first=3, last=3, title="A note"):
    return {"number": number, "title": title, "first_page": first, "last_page": last}


def contents(**extra) -> dict[int, dict]:
    pages = {p: fakes.good_page(p) for p in (1, 2, 3)}
    pages.update(extra)
    return pages


# Refusals ------------------------------------------------------------------

@pytest.mark.parametrize("overrides, sentence", [
    (dict(statements=fakes.statements(SOFP={"pages": [52]})),
     "Page 52 for SOFP is outside the document, which has 4 pages, so cite the PDF page number"),
    (dict(statements=fakes.statements(SOFP={"reason": ""})), "Give a one-sentence reason for SOFP"),
    (dict(statements=fakes.statements(SOCF={"pages": []})), "SOCF is marked found but has no page"),
    (dict(statements=fakes.statements(SOCI={"pages": [2]})), "SOCI is marked not printed but cites pages"),
    (dict(statements=fakes.statements(SOPL={"layout": "ByFunction"})), "The layout of SOPL must be Function or Nature"),
    (dict(statements=fakes.statements(SOCIE={"layout": "SoRE"})), "exists only under MPERS"),
    (dict(statements=fakes.statements()[:4]), "SOCIE is missing"),
    (dict(unit=fakes.finding("RM million")), "The unit must be RM or RM'000"),
    (dict(standard=fakes.finding("MFRS", reason="")), "Give a one-sentence reason for the standard"),
    (dict(year_end=fakes.finding("31 December 2021")), "YYYY-MM-DD"),
    (dict(notes=[note("4", first=3, last=2)]), "ends on page 2, before it starts on page 3"),
])
def test_the_save_tool_refuses_a_map_that_would_mislead_in_one_sentence(overrides, sentence):
    problems = map_checks.problems(doc(**overrides), page_count=4)
    assert len(problems) == 1 and sentence in problems[0]


def test_every_problem_is_listed_at_once():
    problems = map_checks.problems(doc(unit=fakes.finding("RM million"), year_end=fakes.finding("31 Dec 2021"),
                                       statements=fakes.statements(SOFP={"pages": [52]}, SOPL={"layout": "X"})),
                                   page_count=4)
    assert len(problems) == 4
    assert any("Page 52 for SOFP" in p for p in problems) and any("The layout of SOPL" in p for p in problems)
    assert any("The unit must be" in p for p in problems) and any("YYYY-MM-DD" in p for p in problems)


def test_a_good_map_is_accepted_and_spellings_are_made_canonical():
    doc_map = doc(unit=fakes.finding("RM '000", (2, 3)), standard=fakes.finding("mfrs"),
                  statements=fakes.statements(SOCI={"layout": "NetOfTax"}))
    assert map_checks.problems(doc_map, page_count=4) == []
    assert doc_map.unit.value == "RM'000" and doc_map.standard.value == "MFRS"
    assert next(s for s in doc_map.statements if s.statement == "SOCI").layout is None


def test_sore_is_accepted_under_mpers_only():
    doc_map = doc(standard=fakes.finding("MPERS"), statements=fakes.statements(SOCIE={"layout": "SoRE"}))
    assert map_checks.problems(doc_map, page_count=4) == []
    unknown = doc(standard=fakes.finding("unknown"), statements=fakes.statements(SOCIE={"layout": "SoRE"}))
    assert "exists only under MPERS" in map_checks.problems(unknown, page_count=4)[0]


# Points to check -------------------------------------------------------------

def test_a_complete_list_has_no_points():
    assert map_checks.points_to_check(doc(), contents()) == []


def test_a_gap_in_the_middle_of_the_numbering_is_reported():
    doc_map = doc(notes=[note(str(n)) for n in (1, 2, 3, 4, 5, 6, 8, 9)])
    assert "Note 7 is not in the list; find it or say why it is absent." in map_checks.points_to_check(
        doc_map, contents())


def test_the_first_and_last_notes_are_checked():
    doc_map = doc(notes=[note(str(n)) for n in (3, 4, 5)])
    points = map_checks.points_to_check(doc_map, contents())
    assert any("The list starts at note 3; check whether notes 1 to 2 exist" in p for p in points)
    heading = {"type": "heading", "level": 2, "text": "6. EVENTS AFTER THE REPORTING PERIOD"}
    page4 = {**fakes.good_page(3), "blocks": [heading]}
    points = map_checks.points_to_check(doc_map, contents() | {4: page4})
    assert any("The last note heading seen is note 6 on page 4, but the list ends at note 5" in p for p in points)


def test_a_note_cited_on_a_statement_but_not_listed_is_reported():
    doc_map = doc(notes=[note("1")])   # the statement cites 1 and 2
    points = map_checks.points_to_check(doc_map, contents())
    assert "Note 2 is cited on page 2 but is not in the notes list; find it or say why it is absent." in points


def test_an_amount_shifted_into_the_note_column_is_not_a_citation():
    table = ("<table><tr><th></th><th>Note</th><th>2024 RM</th></tr>"
             "<tr><td>Cash</td><td>280,605</td></tr><tr><td>Total</td><td>1858</td><td></td></tr></table>")
    page2 = {**fakes.good_page(2), "blocks": [{"type": "table", "html": table}]}
    assert map_checks.points_to_check(doc(), contents() | {2: page2}) == []


def test_a_heading_inside_the_range_that_is_not_listed_is_reported():
    doc_map = doc(notes=[note("1"), note("3"), note("5")])
    points = map_checks.points_to_check(doc_map, contents())
    assert "A heading on page 3 reads as note 2, which is not in the list; check it." in points
    assert "Note 2 is not in the list; find it or say why it is absent." in points
    assert "Note 4 is not in the list; find it or say why it is absent." in points


def test_a_reason_given_by_the_reader_answers_the_point():
    doc_map = doc(notes=[note("1"), note("3"), note("5")],
                  note_gaps=[{"note": "2", "reason": "Not used."}, {"note": "4", "reason": "Skipped."}])
    assert map_checks.points_to_check(doc_map, contents()) == []


def test_a_note_listed_twice_and_a_unit_on_one_page_are_reported():
    doc_map = doc(notes=[note("1"), note("1"), note("2")], unit=fakes.finding("RM", (2,)))
    points = map_checks.points_to_check(doc_map, contents())
    assert any("Note 1 is listed twice" in p for p in points)
    assert any("The unit rests on fewer than two pages" in p for p in points)


def test_note_numbers_are_read_as_printed():
    assert [map_checks.note_number(t) for t in ("4", "4.", "Note 12", "3(a)", "2.1", "", "A")] == \
        [4, 4, 12, 3, 2, None, None]


# History -------------------------------------------------------------------

def _request(tool: str, content, call_id: str) -> ModelRequest:
    return ModelRequest(parts=[ToolReturnPart(tool_name=tool, content=content, tool_call_id=call_id)])


def _picture():
    return BinaryContent(b"png", media_type="image/png")


def _contents(messages) -> list:
    return [m.parts[0].content for m in messages]


def test_pictures_are_kept_until_the_map_is_saved_and_old_text_is_cut_to_half_the_budget_at_once():
    big = "x" * 10_000                           # seven of them pass the 60,000 budget
    messages = [_request("view_pages", ["p1", _picture()], "a"),
                *[_request("read_pages", big, f"r{i}") for i in range(7)],
                _request("view_pages", ["p2", _picture()], "b")]
    original = copy.deepcopy(messages)
    trimmer = reader.trimmer()

    sent = trimmer(messages)

    assert messages == original                  # the stored conversation is never changed
    parts = [m.parts[0] for m in sent]
    assert all(any(isinstance(i, BinaryContent) for i in p.content) for p in parts if p.tool_name == "view_pages")
    texts = [p.content for p in parts if p.tool_name == "read_pages"]
    # One cut, down to half the budget (30,000): the four oldest go, the newest three stay.
    assert texts == [history.TRIMMED_TEXT] * 4 + [big] * 3


def test_after_a_cut_the_start_of_the_conversation_stays_the_same_for_the_next_requests():
    trimmer = reader.trimmer()
    messages = [_request("read_pages", "x" * 15_000, f"r{i}") for i in range(5)]
    first = trimmer(messages)
    for i in range(5, 8):                         # three more results, still under the budget
        messages.append(_request("search_pages", "y" * 2_000, f"s{i}"))
        later = trimmer(messages)
        assert _contents(later)[:len(first)] == _contents(first)


def test_after_the_first_save_older_pictures_are_dropped_once_and_later_ones_kept():
    trimmer = reader.trimmer()
    messages = [_request("view_pages", ["p1", _picture()], "a"), _request("view_pages", ["p2", _picture()], "b"),
                _request("save_map", "Saved. The code sees no gaps.", "s")]
    sent = trimmer(messages)
    first, second = _contents(sent)[:2]
    assert reader.DROPPED_PICTURE in first and not any(isinstance(i, BinaryContent) for i in first)
    assert any(isinstance(i, BinaryContent) for i in second)
    assert any(isinstance(i, BinaryContent) for i in messages[0].parts[0].content)   # the stored copy is whole

    messages += [_request("view_pages", ["p3", _picture()], "c"),
                 _request("save_map", "Saved. The code sees no gaps.", "t")]
    again = _contents(trimmer(messages))
    assert again[:3] == _contents(sent)                      # nothing earlier changes
    assert any(isinstance(i, BinaryContent) for i in again[1]) and any(isinstance(i, BinaryContent) for i in again[3])


async def test_the_transcript_keeps_the_whole_conversation_while_requests_are_trimmed(tmp_path):
    big = "z" * 40_000
    seen: list = []

    def read(page: int) -> str:
        """Read a page."""
        return big

    def answer(messages, info):
        seen.append(messages)
        if sum(isinstance(m, ModelResponse) for m in messages) < 5:
            return ModelResponse(parts=[ToolCallPart("read_pages", {"page": 1})])
        return ModelResponse(parts=[TextPart("Done.")])

    from pydantic_ai import Tool
    spec = loop.AgentSpec(name="trim-test", model_id="gpt-6-luna", instructions="Read.",
                          tools=[Tool(read, name="read_pages")], history_processor=reader.trimmer())
    outcome = await loop.run_agent(spec, "Go.", model=FunctionModel(answer))

    assert outcome.status == loop.COMPLETED
    last_sent = [p.content for m in seen[-1] for p in getattr(m, "parts", []) if isinstance(p, ToolReturnPart)]
    assert history.TRIMMED_TEXT in last_sent                 # the model saw a trimmed copy
    saved = json.loads(outcome.transcript_path.read_text(encoding="utf-8"))["messages"]
    kept = [p["content"] for m in saved for p in m["parts"] if p.get("part_kind") == "tool-return"]
    assert kept == [big] * 5                                 # the transcript holds every result whole


def test_an_agent_reading_a_page_sees_its_letterhead_and_search_finds_it():
    """Letterheads are kept out of the blocks but can hold facts (an audit firm's address), so step 10's
    reports agent, like every agent, sees them marked as such."""
    from app.reading.content import as_reading, plain_text
    page = {"blocks": [{"type": "paragraph", "text": "Ernst & Young PLT"}],
            "running_text": ["Level 23A, Menara Milenium", "50490 Kuala Lumpur, Malaysia"]}
    assert ("Printed around the page (letterhead, banners, page number): Level 23A, Menara Milenium | "
            "50490 Kuala Lumpur, Malaysia") in as_reading(page)
    assert "50490 Kuala Lumpur" in plain_text(page)
