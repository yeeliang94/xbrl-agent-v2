"""What kind of file an upload is, and the uploads that are refused.

A run starts from one file: a PDF, a Word document (.docx) or an Excel
workbook (.xlsx) (owner, 25 November 2026). The kind is decided from the
file's content, never from its name alone. Old Word and Excel files and
files protected by a password are refused, each with one plain sentence that
names the file, so a person who dropped several knows which one it means.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

PDF, WORD, EXCEL = "pdf", "word", "excel"
KIND_WORDS = {PDF: "PDF", WORD: "Word file", EXCEL: "Excel workbook"}

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"            # old .doc and .xls, and any Office file with a password
_ZIP_MAGIC = b"PK\x03\x04"
_ENCRYPTED = "EncryptedPackage".encode("utf-16-le")       # a .docx or .xlsx saved with a password
_OLD_WORD = "WordDocument".encode("utf-16-le")
_OLD_EXCEL = "Workbook".encode("utf-16-le")
_OLD_WORD_SUFFIXES = (".doc", ".dot")
_OLD_EXCEL_SUFFIXES = (".xls", ".xlt")


class Refused(ValueError):
    """An upload a run cannot start from. `str()` is one plain sentence."""


def locked(filename: str) -> Refused:
    return Refused(f"{filename} is protected by a password. Remove the password and upload it again.")


def unreadable(filename: str, kind: str) -> Refused:
    return Refused(f"{filename} could not be read as {'an' if kind == EXCEL else 'a'} {KIND_WORDS[kind]}.")


def _old_word(filename: str) -> Refused:
    return Refused(f"{filename} is in the old Word format. Save it as .docx and upload that.")


def _old_excel(filename: str) -> Refused:
    return Refused(f"{filename} is in the old Excel format. Save it as .xlsx and upload that.")


def _not_taken(filename: str) -> Refused:
    return Refused(f"{filename} is not a PDF, a Word document (.docx) or an Excel workbook (.xlsx).")


def refused_by_name(filename: str) -> Refused | None:
    """The refusal a file's name alone settles, so an old file is turned away before it is read."""
    suffix = Path(filename).suffix.lower()
    if suffix in _OLD_WORD_SUFFIXES:
        return _old_word(filename)
    if suffix in _OLD_EXCEL_SUFFIXES:
        return _old_excel(filename)
    return None


def kind_of(filename: str, data: bytes) -> str:
    """`pdf`, `word` or `excel`, or Refused saying why the file was not taken."""
    by_name = refused_by_name(filename)
    if by_name is not None:
        raise by_name
    suffix = Path(filename).suffix.lower()
    if data.startswith(_OLE_MAGIC):
        if _ENCRYPTED in data:
            raise locked(filename)
        if _OLD_WORD in data:
            raise _old_word(filename)
        if _OLD_EXCEL in data:
            raise _old_excel(filename)
        raise _not_taken(filename)
    if b"%PDF-" in data[:1024]:
        return PDF
    if data.startswith(_ZIP_MAGIC):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile as exc:
            raise _not_taken(filename) from exc
        # A macro or template file (.docm, .xlsm, .dotx) holds the same parts, so the name decides.
        if "word/document.xml" in names:
            if suffix != ".docx":
                raise Refused(f"{filename} is not a .docx file. Save it as .docx and upload that.")
            return WORD
        if "xl/workbook.xml" in names:
            if suffix != ".xlsx":
                raise Refused(f"{filename} is not an .xlsx file. Save it as .xlsx and upload that.")
            return EXCEL
    raise _not_taken(filename)
