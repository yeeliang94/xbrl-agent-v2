"""The page tools every agent shares: see a page, look closer, read its
transcription, search the document.

Moved here from the Reader in step 4 so the figures agent uses the same
code. Every tool answers a bad request with plain sentences as its result,
so a refusal costs none of the tool's retries. A deps object needs the
fields of `PageSource`; agents subclass it.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional

from pydantic_ai import BinaryContent, RunContext

from app.documents import pdf_viewer
from app.runs.events import clean_note
from app.reading.content import as_reading, plain_text

MAX_VIEW = 8
MAX_READ = 6
MAX_HITS = 20


@dataclass
class PageSource:
    run_id: int
    pdf_path: str
    page_count: int
    contents: dict[int, dict]                 # {PDF page: stored content}

    def rotation(self, page: int) -> int:
        return int((self.contents.get(page) or {}).get("rotation") or 0)

    def folio(self, page: int) -> str:
        folio = (self.contents.get(page) or {}).get("folio")
        return f"printed folio {folio}" if folio else "no printed folio"


def bad_pages(deps: PageSource, pages: list[int], limit: int) -> Optional[str]:
    if not pages:
        return "Name at least one page."
    if len(pages) > limit:
        return f"Ask for at most {limit} pages at a time."
    outside = [p for p in pages if not 1 <= p <= deps.page_count]
    if outside:
        return f"Page {outside[0]} is outside the document, which has {deps.page_count} pages."
    return None


async def view_pages(ctx: RunContext[PageSource], pages: list[int], note: Optional[str] = None) -> Any:
    """See whole pages as pictures, turned upright. At most 8 PDF pages per call.
    `note`: one plain sentence for the person following the run: what you are doing and why."""
    deps = ctx.deps
    problem = bad_pages(deps, pages, MAX_VIEW)
    if problem:
        return problem
    out: list[Any] = []
    for page in dict.fromkeys(pages):
        png = await asyncio.to_thread(pdf_viewer.render_page_png, deps.pdf_path, page, rotate=deps.rotation(page))
        out += [f"PDF page {page} ({deps.folio(page)}):", BinaryContent(png, media_type="image/png",
                                                                       vendor_metadata={"detail": "high"})]
    return out


async def zoom_page(ctx: RunContext[PageSource], page: int, left: float, top: float, right: float,
                    bottom: float, note: Optional[str] = None) -> Any:
    """See part of a page closely. The region is fractions (0 to 1) of the upright page:
    left, top, right, bottom, for example 0, 0.5, 1, 1 for the lower half.
    `note`: one plain sentence for the person following the run: what you are doing and why."""
    deps = ctx.deps
    problem = bad_pages(deps, [page], 1)
    if problem:
        return problem
    try:
        clip = pdf_viewer.validate_clip((left, top, right, bottom))
    except pdf_viewer.BadClip:
        return "Give the region as four page fractions from 0 to 1, with left below right and top below bottom."
    png = await asyncio.to_thread(pdf_viewer.render_page_png, deps.pdf_path, page, clip=clip,
                                  rotate=deps.rotation(page))
    return [f"PDF page {page}, region {left:g}-{right:g} across, {top:g}-{bottom:g} down:",
            BinaryContent(png, media_type="image/png", vendor_metadata={"detail": "high"})]


def read_pages(ctx: RunContext[PageSource], pages: list[int], note: Optional[str] = None) -> str:
    """Read the transcription of up to 6 PDF pages: headings marked #, tables as HTML,
    uncertain words listed. The picture is the authority when they differ.
    `note`: one plain sentence for the person following the run: what you are doing and why."""
    deps = ctx.deps
    problem = bad_pages(deps, pages, MAX_READ)
    if problem:
        return problem
    parts = []
    for page in dict.fromkeys(pages):
        content = deps.contents.get(page)
        if content is None:
            parts.append(f"=== PDF page {page}: not transcribed; view the page to read it.")
        elif content.get("blank"):
            parts.append(f"=== PDF page {page}: blank.")
        else:
            parts.append(f"=== PDF page {page} ({deps.folio(page)}, {content.get('kind')}):\n{as_reading(content)}")
    return "\n\n".join(parts)


def search_pages(ctx: RunContext[PageSource], text: str, note: Optional[str] = None) -> str:
    """Find words across every page's transcription, ignoring case. A hit says where to
    look; read or view the page before relying on it.
    `note`: one plain sentence for the person following the run: what you are doing and why."""
    needle = " ".join(text.split()).lower()
    if len(needle) < 2:
        return "Search for at least two characters."
    hits = []
    for page, content in sorted(ctx.deps.contents.items()):
        flat = " ".join(plain_text(content).split())
        at = flat.lower().find(needle)
        if at >= 0:
            snippet = flat[max(0, at - 80): at + len(needle) + 80]
            hits.append(f"- PDF page {page} ({ctx.deps.folio(page)}, {content.get('kind')}): ...{snippet}...")
    if not hits:
        return f"No transcription holds {text!r}. Scans can be misread, so try another wording or view the pages."
    more = f"\n({len(hits) - MAX_HITS} more pages hold it.)" if len(hits) > MAX_HITS else ""
    return f"{len(hits)} page(s) hold {text!r}:\n" + "\n".join(hits[:MAX_HITS]) + more


PAGE_TOOLS = (view_pages, zoom_page, read_pages, search_pages)
# Their calls are visible activity rows ("looked"), with the pages they name and the agent's note.
LOOKING = frozenset(t.__name__ for t in PAGE_TOOLS)


def looked_row(part: Any) -> tuple[str, list[int]]:
    """The visible activity row of a page tool's call: the agent's note (or a plain default) and its pages."""
    try:
        args = part.args_as_dict()
    except Exception:  # noqa: BLE001 - an unreadable argument names no page
        args = {}
    pages = args.get("pages")
    pages = sorted({p for p in (pages if isinstance(pages, list) else [args.get("page")]) if type(p) is int})
    said = (f"Looked at page{'s' if len(pages) > 1 else ''} {', '.join(map(str, pages))}." if pages
            else "Searched the pages.")
    return clean_note(args.get("note")) or said, pages
