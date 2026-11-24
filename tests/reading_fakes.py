"""Fake model answers for reading tests: transcription of a small PDF, and
a scripted Reader. No network."""
from __future__ import annotations

import json
import re

import pymupdf
from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from tests import pdf_samples

TITLES = {1: "Contents", 2: "Statement of financial position", 3: "Notes to the financial statements"}


def build_pdf(blank_last: bool = True) -> bytes:
    """Three text pages and, by default, a blank fourth page."""
    doc = pymupdf.open()
    for _ in range(3):
        pdf_samples.add_text_page(doc)
    if blank_last:
        doc.new_page(width=595, height=842)
    data = doc.tobytes()
    doc.close()
    return data


def page_of(messages) -> int:
    for message in messages:
        for part in getattr(message, "parts", []):
            content = getattr(part, "content", None)
            items = content if isinstance(content, list) else [content]
            for item in items:
                found = re.search(r"PDF page (\d+) of", item) if isinstance(item, str) else None
                if found:
                    return int(found.group(1))
    raise AssertionError("no page in the prompt")


def good_page(page: int) -> dict:
    blocks = [{"type": "heading", "level": 1, "text": TITLES.get(page, "Page")}]
    if page == 2:
        blocks.append({"type": "table", "html": "<table><tr><th>　</th><th>Note</th><th>2021 RM</th></tr>"
                                                "<tr><td>Plant and equipment</td><td>1</td><td>1,200</td></tr>"
                                                "<tr><td>Trade payables</td><td>2</td><td>(300)</td></tr></table>"})
    if page == 3:
        blocks += [{"type": "heading", "level": 2, "text": "1. PLANT AND EQUIPMENT"},
                   {"type": "paragraph", "text": "Cost and depreciation."},
                   {"type": "heading", "level": 2, "text": "2. TRADE PAYABLES"}]
    return {"folio": str(page + 2) if page > 1 else None, "rotation": 0,
            "kind": {1: "contents", 2: "statement", 3: "notes"}.get(page, "other"),
            "title": TITLES.get(page, ""), "blocks": blocks, "running_text": ["TEST SDN. BHD."],
            "uncertain": [{"seen": "Cos?", "reading": "Cost"}] if page == 3 else [], "marks": []}


BAD_PAGE = {"folio": None, "rotation": 0, "kind": "notes", "title": "",
            "blocks": [{"type": "table", "html": "<table><td>loose</td></table>"}]}


def transcriber(*, malformed_once: set[int] = frozenset(), always_bad: set[int] = frozenset(),
                calls: list | None = None):
    """A transcription model. `malformed_once` pages answer badly first and
    are fixed on the retry; `always_bad` pages never answer well."""
    def answer(messages, info: AgentInfo) -> ModelResponse:
        page = page_of(messages)
        if calls is not None:
            calls.append(page)
        retried = any(isinstance(p, RetryPromptPart) or getattr(p, "outcome", None) == "retried"
                      for m in messages for p in getattr(m, "parts", []))
        bad = page in always_bad or (page in malformed_once and not retried)
        args = BAD_PAGE if bad else good_page(page)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(args))])
    return FunctionModel(answer)


def statements(**overrides) -> list[dict]:
    base = [
        {"statement": "SOFP", "found": True, "pages": [2], "title": "Statement of financial position",
         "layout": "CuNonCu", "reason": "Current and non-current sections are shown.", "unsure": False},
        {"statement": "SOPL", "found": True, "pages": [2], "layout": "Function",
         "reason": "Costs are grouped by function.", "unsure": True},
        {"statement": "SOCI", "found": False, "pages": [], "layout": None,
         "reason": "No comprehensive income statement is printed.", "unsure": False},
        {"statement": "SOCF", "found": True, "pages": [2], "layout": "Indirect",
         "reason": "It starts from profit before tax.", "unsure": False},
        {"statement": "SOCIE", "found": True, "pages": [2], "layout": "Default",
         "reason": "Columns per equity component.", "unsure": False},
    ]
    for item in base:
        item.update(overrides.get(item["statement"], {}))
    return base


def finding(value, pages=(2,), reason="Shown on the statement heading.", unsure=False) -> dict:
    return {"value": value, "pages": list(pages), "reason": reason, "unsure": unsure}


def good_map(**overrides) -> dict:
    doc_map = {
        "company": finding("Test Sdn. Bhd."), "year_end": finding("2021-12-31"),
        "standard": finding("MFRS", (3,)), "level": finding("Company"), "unit": finding("RM", (2, 3)),
        "statements": statements(),
        "notes": [{"number": "1", "title": "Plant and equipment", "first_page": 3, "last_page": 3},
                  {"number": "2", "title": "Trade payables", "first_page": 3, "last_page": 3}],
        # Not a report the reports agent fills (step 10), so these runs queue no reports stage.
        "other_sections": [{"kind": "statutory_declaration", "title": "Statutory declaration", "first_page": 1,
                            "last_page": 1}],
        "note_gaps": [],
    }
    doc_map.update(overrides)
    return doc_map


def _tool_returns(messages, name: str) -> list:
    return [p for m in messages for p in getattr(m, "parts", [])
            if isinstance(p, ToolReturnPart) and p.tool_name == name]


def reader_script(steps: list, seen: list | None = None):
    """A Reader model that makes the calls in `steps` in order, one per
    request, then finishes. A step is (tool name, args) or a text answer."""
    def answer(messages, info: AgentInfo) -> ModelResponse:
        if seen is not None:
            seen.append(messages)
        done = sum(1 for m in messages if isinstance(m, ModelResponse))
        step = steps[done] if done < len(steps) else "Done."
        if isinstance(step, str):
            return ModelResponse(parts=[TextPart(step)])
        return ModelResponse(parts=[ToolCallPart(step[0], step[1])])
    return FunctionModel(answer)


def world(reader_steps: list):
    """One model for the whole job, chosen by the tools it is offered: the
    factory hands it out for both transcription and the Reader."""
    transcription = transcriber()
    reader = reader_script(reader_steps)

    async def answer(messages, info: AgentInfo):
        names = {t.name for t in info.function_tools}
        model = reader if "save_map" in names else transcription
        return model.function(messages, info)
    return FunctionModel(answer)
