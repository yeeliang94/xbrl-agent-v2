"""A note as blocks: the words, copied from the Reader's page content by code,
and the look beside them (docs/step-6-plan.md section 3; decision record 4).

Shared by the note store, the renderer, the notes agent and the review
screen. Nothing here writes to the database.

The look vocabulary holds only what mTool's note editor accepts. Each look
value is set, absent or "not sure":
- absent (None, or False for a switch) means the source shows the plain look;
- "not sure" means the agent could not tell. The look's key is listed in the
  owning object's `unsure`, and the house style from Settings draws it.
The house style never overrides a set value.

Words live only in `text` fields. A look change never touches them, and
`words()` lets a test or a write prove it. The look sits on a whole block,
row or cell, never on part of a text: the Reader transcribes words without
inline styling (app/reading/content.py), so there is no finer place to copy
it from. Merged cells are not stored: they are split when a note is made,
the text in the first cell (decision record 4, question 2).
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

Align = Literal["left", "center", "right", "justify"]
VAlign = Literal["top", "middle", "bottom"]
ColumnRole = Literal["label", "amount", "text", "date"]
RowRole = Literal["heading", "item", "subtotal", "total"]
LineStyle = Literal["single", "double"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(_Strict):
    """Where a block's words were copied from: a PDF page of this run and the
    block's position in that page's content."""
    page: int = Field(ge=1)
    block: int = Field(ge=0)


class TextLook(_Strict):
    bold: bool = False
    italic: bool = False
    underline: bool = False
    align: Optional[Align] = None
    indent: int = Field(default=0, ge=0, le=4, description="Steps of 2em.")
    unsure: list[str] = Field(default_factory=list, description="Look keys the agent could not tell from the page.")

    @model_validator(mode="after")
    def _known(self):
        _check_unsure(self, ("bold", "italic", "underline", "align", "indent"))
        return self


class Heading(_Strict):
    kind: Literal["heading"] = "heading"
    id: str
    source: Source
    level: int = Field(ge=1, le=3)
    text: str = Field(min_length=1)
    look: TextLook = Field(default_factory=TextLook)


class Paragraph(_Strict):
    kind: Literal["paragraph"] = "paragraph"
    id: str
    source: Source
    text: str = Field(min_length=1)
    look: TextLook = Field(default_factory=TextLook)


class ListItem(_Strict):
    text: str = Field(min_length=1, description="As printed, numbering included.")
    level: int = Field(default=0, ge=0, le=2)


class ListBlock(_Strict):
    kind: Literal["list"] = "list"
    id: str
    source: Source
    items: list[ListItem] = Field(min_length=1)
    look: TextLook = Field(default_factory=TextLook)


class Line(_Strict):
    """A rule below a row. `columns` are 0-based column numbers; empty means every column."""
    style: LineStyle = "single"
    columns: list[int] = Field(default_factory=list)


class CellLook(_Strict):
    bold: bool = False
    italic: bool = False
    underline: bool = False
    align: Optional[Align] = None
    valign: Optional[VAlign] = None
    unsure: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _known(self):
        _check_unsure(self, ("bold", "italic", "underline", "align", "valign"))
        return self


class Cell(_Strict):
    text: str = ""
    look: CellLook = Field(default_factory=CellLook)


class Row(_Strict):
    role: RowRole = "item"
    cells: list[Cell]
    indent: int = Field(default=0, ge=0, le=3)
    bold: bool = False
    shaded: bool = False
    line_below: Optional[Line] = None
    unsure: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _known(self):
        _check_unsure(self, ("role", "indent", "bold", "shaded", "line_below"))
        return self


class Column(_Strict):
    role: ColumnRole = "text"
    width: Optional[float] = Field(default=None, gt=0, le=100, description="Percent of the table's width.")
    align: Optional[Align] = None
    unsure: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _known(self):
        _check_unsure(self, ("role", "width", "align"))
        return self


class Table(_Strict):
    kind: Literal["table"] = "table"
    id: str
    source: Source
    columns: list[Column] = Field(min_length=1)
    rows: list[Row] = Field(min_length=1)
    frame: Literal["none", "grid"] = "none"
    font_pt: Optional[float] = Field(default=None, ge=8, le=14, description="Set only when the table is too wide.")
    unsure: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape(self):
        _check_unsure(self, ("frame", "font_pt"))
        width = len(self.columns)
        for n, row in enumerate(self.rows, 1):
            if len(row.cells) != width:
                raise ValueError(f"Row {n} has {len(row.cells)} cells but the table has {width} columns.")
            if row.line_below:
                bad = [c for c in row.line_below.columns if not 0 <= c < width]
                if bad:
                    raise ValueError(f"Row {n}'s line names column {bad[0]}, but the columns are 0 to {width - 1}.")
        widths = [c.width for c in self.columns if c.width is not None]
        if widths and sum(widths) > 100.5:
            raise ValueError(f"The column widths add up to {sum(widths):g}%, more than 100%.")
        return self


NoteBlock = Annotated[Union[Heading, Paragraph, ListBlock, Table], Field(discriminator="kind")]


class NoteBody(_Strict):
    """The blocks of one note, or of one part of a note split across fields."""
    blocks: list[NoteBlock] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self):
        seen: set[str] = set()
        for b in self.blocks:
            if b.id in seen:
                raise ValueError(f"Block id {b.id!r} is used twice.")
            seen.add(b.id)
        return self


def _check_unsure(obj: BaseModel, keys: tuple[str, ...]) -> None:
    unknown = [k for k in obj.unsure if k not in keys]
    if unknown:
        raise ValueError(f"{unknown[0]!r} is not a look that can be unsure here; use one of {', '.join(keys)}.")


# Reading a note back -------------------------------------------------------

def words(body: NoteBody) -> list[str]:
    """Every text of the note in reading order. Equal before and after a look change."""
    out: list[str] = []
    for b in body.blocks:
        if isinstance(b, (Heading, Paragraph)):
            out.append(b.text)
        elif isinstance(b, ListBlock):
            out.extend(i.text for i in b.items)
        else:
            out.extend(c.text for r in b.rows for c in r.cells)
    return out


def has_unsure(body: NoteBody) -> bool:
    """True when any look of the note is "not sure": the note is shown for checking."""
    for b in body.blocks:
        if isinstance(b, Table):
            if b.unsure or any(c.unsure for c in b.columns):
                return True
            if any(r.unsure or any(c.look.unsure for c in r.cells) for r in b.rows):
                return True
        elif b.look.unsure:
            return True
    return False


def settled(body: NoteBody) -> NoteBody:
    """The note with every "not sure" look marked done: a person checked it, so the look stands as it is."""
    def clear(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: ([] if k == "unsure" else clear(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [clear(v) for v in value]
        return value
    return NoteBody.model_validate(clear(body.model_dump(mode="json")))


def parse(data: dict) -> NoteBody:
    """A stored note's blocks (the `notes.blocks` JSON) as a model."""
    return NoteBody.model_validate(data)
