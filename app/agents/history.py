"""Keeps what an agent sends each request within bounds without blinding it.

v1's failure (owner's note "scanned_pdf_compaction_thrash"): once a run grew,
old page pictures were dropped, so the agent forgot pages it had just seen
and opened them again and again. Here pictures are never dropped before the
agent's first save.

Only each request's copy is shaped (`loop._RequestHistory`); the stored
conversation, and so the transcript, keeps every result whole.

Trimming is rare and done in large cuts, so the start of the conversation
stays the same from one request to the next and the provider's prompt cache
keeps serving it:

- Text results (transcriptions, search hits): when those not yet trimmed
  pass the budget, the oldest are trimmed in one go until they fill half of
  it. The newest few are always kept. A trimmed result stays trimmed.
- Pictures, the Reader's way (no picture budget): at the first request after
  the first save, every picture before the newest is dropped, once. Pictures
  viewed after that are kept, since the agent then only answers the save
  tool's points.
- Pictures, with a picture budget (the figures agent, which keeps reading
  pages after it starts saving): nothing is dropped before the first save.
  After it, when the pictures still kept pass the budget, the oldest are
  dropped in one go until half the budget is left. The newest is always kept.

Made for the Reader in step 3. Each agent passes its own text tools and its
own "has it saved yet" check (step 4); only the shared page tools' names
live here.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Optional

from pydantic_ai.messages import BinaryContent, ModelRequest, ToolReturnPart

PAGE_TEXT_TOOLS = frozenset({"read_pages", "search_pages"})
PICTURE_TOOLS = frozenset({"view_pages", "zoom_page"})
# The file tools of a run that started from a Word or Excel file (`file_tools.py`): text for every agent.
FILE_TEXT_TOOLS = frozenset({"read_file", "search_file"})
# Text results beyond this many characters in all are cut down to half of it.
TEXT_BUDGET_CHARS = 60_000
KEEP_NEWEST_TEXT = 3

TRIMMED_TEXT = "[This earlier result was trimmed to save space; call the tool again if you need it.]"
DROPPED_PICTURE = "[An earlier page picture was dropped to save space; view the page again if needed.]"


def tool_returns(messages: list) -> list[ToolReturnPart]:
    return [part for message in messages if isinstance(message, ModelRequest)
            for part in message.parts if isinstance(part, ToolReturnPart)]


def _has_picture(content: Any) -> bool:
    items = content if isinstance(content, list) else [content]
    return any(isinstance(item, BinaryContent) for item in items)


@dataclass
class Trimmer:
    """An agent's history processor, one per run. It remembers what it cut,
    so every later request is cut the same way. `saved` says, from the
    conversation, whether the agent has saved its work yet."""
    text_tools: frozenset
    saved: Callable[[list], bool]
    picture_tools: frozenset = PICTURE_TOOLS
    picture_budget: Optional[int] = None
    dropped_note: str = DROPPED_PICTURE
    trimmed: set[str] = field(default_factory=set)      # tool call ids of text results
    dropped: set[str] = field(default_factory=set)      # tool call ids of picture results
    pictures_done: bool = False

    def __call__(self, messages: list) -> list:
        returns = tool_returns(messages)
        self._cut_text(returns)
        self._cut_pictures(messages, returns)
        return [self._shaped(m) for m in messages]

    def _cut_text(self, returns: list[ToolReturnPart]) -> None:
        text = [p for p in returns if (p.tool_name in self.text_tools or p.tool_name in FILE_TEXT_TOOLS)
                and isinstance(p.content, str)
                and p.tool_call_id not in self.trimmed]
        total = sum(len(p.content) for p in text)
        if total <= TEXT_BUDGET_CHARS:
            return
        for part in text[:-KEEP_NEWEST_TEXT]:
            if total <= TEXT_BUDGET_CHARS // 2:
                break
            total -= len(part.content)
            self.trimmed.add(part.tool_call_id)

    def _cut_pictures(self, messages: list, returns: list[ToolReturnPart]) -> None:
        if self.picture_budget is None and self.pictures_done:
            return
        if not self.pictures_done and not self.saved(messages):
            return   # never before the first save
        self.pictures_done = True
        pictures = [p for p in returns if p.tool_name in self.picture_tools and _has_picture(p.content)
                    and p.tool_call_id not in self.dropped]
        if self.picture_budget is None:
            self.dropped.update(p.tool_call_id for p in pictures[:-1])
        elif len(pictures) > self.picture_budget:
            keep = max(1, self.picture_budget // 2)
            self.dropped.update(p.tool_call_id for p in pictures[:-keep])

    def _shaped(self, message: Any) -> Any:
        if not isinstance(message, ModelRequest):
            return message
        parts, changed = [], False
        for part in message.parts:
            if isinstance(part, ToolReturnPart) and part.tool_call_id in self.trimmed:
                part, changed = replace(part, content=TRIMMED_TEXT), True
            elif isinstance(part, ToolReturnPart) and part.tool_call_id in self.dropped and _has_picture(part.content):
                kept = [item for item in part.content if not isinstance(item, BinaryContent)]
                part, changed = replace(part, content=kept + [self.dropped_note]), True
            parts.append(part)
        # New message objects only where something changed: the stored ones are never touched.
        return replace(message, parts=parts) if changed else message
