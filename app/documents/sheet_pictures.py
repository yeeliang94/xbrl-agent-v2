"""The pictures placed on a workbook's sheets, read straight from the .xlsx file.

openpyxl keeps pictures only when an image library is installed, and none is,
so the file's own parts are read: each sheet's drawing, and the pictures that
drawing places, with the cell each picture's top-left corner sits on. A
statement pasted into a sheet as a picture is then drawn in the reading copy
rather than lost. A picture in a format the reading copy cannot draw (such as
EMF) is kept without its data, so the reading copy says a picture is missing
there instead of leaving it out unseen.
"""
from __future__ import annotations

import io
import posixpath
import zipfile
from dataclasses import dataclass

from lxml import etree
from openpyxl.utils import get_column_letter

from app.documents.reading_copy import picture_format

_KINDS = {".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".gif": "gif", ".bmp": "bmp"}
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


@dataclass
class Picture:
    name: str            # the name the reading copy's <img> uses
    cell: str            # where its top-left corner sits, such as "B12"; empty when the file does not say
    data: bytes          # empty for a picture the reading copy cannot draw
    format: str = ""     # that picture's format, such as "EMF"


def _xml(archive: zipfile.ZipFile, part: str):
    return etree.fromstring(archive.read(part), _PARSER)


def _links(archive: zipfile.ZipFile, part: str) -> dict[str, str]:
    """A part's relationships: id to the linked part's full path."""
    folder, name = posixpath.split(part)
    rels = posixpath.join(folder, "_rels", name + ".rels")
    if rels not in archive.namelist():
        return {}
    out = {}
    for rel in _xml(archive, rels):
        target = rel.get("Target") or ""
        out[rel.get("Id")] = target.lstrip("/") if target.startswith("/") else \
            posixpath.normpath(posixpath.join(folder, target))
    return out


def _cell(anchor) -> str:
    start = anchor.find(f"{{{_XDR}}}from")
    if start is None:
        return ""
    col, row = start.findtext(f"{{{_XDR}}}col"), start.findtext(f"{{{_XDR}}}row")
    if not (col or "").isdigit() or not (row or "").isdigit():
        return ""
    return f"{get_column_letter(int(col) + 1)}{int(row) + 1}"


def sheet_parts(archive: zipfile.ZipFile) -> list[tuple[str, str | None]]:
    """Each sheet's name and the part holding it, as the workbook links them, in the workbook's order. The
    part is None when the link names none. Raises KeyError or XMLSyntaxError for a file without a readable
    workbook part."""
    book = "xl/workbook.xml"
    links = _links(archive, book)
    return [(sheet.get("name") or "", links.get(sheet.get(f"{{{_R}}}id")))
            for sheet in _xml(archive, book).iter("{*}sheet")]


def sheet_pictures(data: bytes) -> dict[str, list[Picture]]:
    """Each sheet's pictures by sheet name, in the file's order. Empty for a file whose parts cannot be read:
    the workbook reader refuses a broken file in its own words."""
    out: dict[str, list[Picture]] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for number, (name, path) in enumerate(sheet_parts(archive), start=1):
                found = []
                for drawing in _links(archive, path).values() if path else []:
                    if "/drawings/" not in drawing or drawing not in archive.namelist():
                        continue
                    media = _links(archive, drawing)
                    for anchor in _xml(archive, drawing):
                        blip = anchor.find(f".//{{{_A}}}blip")
                        target = media.get(blip.get(f"{{{_R}}}embed")) if blip is not None else None
                        if not target or target not in archive.namelist():
                            continue
                        kind = _KINDS.get(posixpath.splitext(target)[1].lower())
                        if kind:
                            found.append(Picture(f"sheet{number}-{len(found) + 1}.{kind}", _cell(anchor),
                                                 archive.read(target)))
                        else:
                            found.append(Picture("", _cell(anchor), b"", picture_format(target)))
                if found:
                    out[name] = found
    except (KeyError, zipfile.BadZipFile, etree.XMLSyntaxError):
        return {}
    return out
