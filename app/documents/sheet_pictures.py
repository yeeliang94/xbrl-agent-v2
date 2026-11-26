"""The pictures placed on a workbook's sheets, read straight from the .xlsx file.

openpyxl keeps pictures only when an image library is installed, and none is,
so the file's own parts are read: each sheet's drawing, and the pictures that
drawing places, with the cell each picture's top-left corner sits on. A
statement pasted into a sheet as a picture is then drawn in the reading copy
rather than lost. Pictures in a format the reading copy cannot draw (such as
EMF) are left out.
"""
from __future__ import annotations

import io
import posixpath
import zipfile
from dataclasses import dataclass

from lxml import etree
from openpyxl.utils import get_column_letter

_KINDS = {".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".gif": "gif", ".bmp": "bmp"}
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


@dataclass
class Picture:
    name: str            # the name the reading copy's <img> uses
    cell: str            # where its top-left corner sits, such as "B12"; empty when the file does not say
    data: bytes


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


def sheet_pictures(data: bytes) -> dict[str, list[Picture]]:
    """Each sheet's pictures by sheet name, in the file's order. Empty for a file whose parts cannot be read:
    the workbook reader refuses a broken file in its own words."""
    out: dict[str, list[Picture]] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            book = "xl/workbook.xml"
            sheets = _links(archive, book)
            for number, sheet in enumerate(_xml(archive, book).iter("{*}sheet"), start=1):
                path = sheets.get(sheet.get(f"{{{_R}}}id"))
                found = []
                for drawing in _links(archive, path).values() if path else []:
                    if "/drawings/" not in drawing or drawing not in archive.namelist():
                        continue
                    media = _links(archive, drawing)
                    for anchor in _xml(archive, drawing):
                        blip = anchor.find(f".//{{{_A}}}blip")
                        target = media.get(blip.get(f"{{{_R}}}embed")) if blip is not None else None
                        kind = _KINDS.get(posixpath.splitext(target or "")[1].lower())
                        if kind and target in archive.namelist():
                            found.append(Picture(f"sheet{number}-{len(found) + 1}.{kind}", _cell(anchor),
                                                 archive.read(target)))
                if found:
                    out[sheet.get("name") or ""] = found
    except (KeyError, zipfile.BadZipFile, etree.XMLSyntaxError):
        return {}
    return out
