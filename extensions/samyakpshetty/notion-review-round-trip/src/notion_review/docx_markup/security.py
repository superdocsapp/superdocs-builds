"""Safe handling of a .docx — an untrusted zip of XML from whoever reviewed the document.

Two attack surfaces are closed here before any parsing happens:

* **The zip** can be a bomb (a few KB that inflates to gigabytes) or carry path-traversal member
  names. We cap member count and total/per-member uncompressed size, and reject unsafe names.
* **The XML** can carry an XXE / billion-laughs payload via a DOCTYPE and entity definitions. We
  reject any DOCTYPE outright and parse with entity resolution, DTD loading, and network access
  all disabled.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

from lxml import etree
from lxml.etree import _Element

MAX_MEMBERS = 2000
MAX_TOTAL_UNCOMPRESSED = 50 * 1024 * 1024  # 50 MiB across the whole archive
MAX_MEMBER_UNCOMPRESSED = 25 * 1024 * 1024  # 25 MiB for any single part


class DocxError(Exception):
    """The file is not a usable .docx."""


class DocxSecurityError(DocxError):
    """The file tripped a safety guard (zip bomb, path traversal, or XXE)."""


def read_docx_parts(data: bytes, wanted: set[str]) -> dict[str, bytes]:
    """Return the requested archive members, enforcing zip-bomb and traversal guards."""
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise DocxError("not a valid .docx (bad zip)") from exc

    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        raise DocxSecurityError(f"docx has too many members ({len(infos)} > {MAX_MEMBERS})")

    total = 0
    for info in infos:
        segments = info.filename.split("/")
        if info.filename.startswith("/") or ".." in segments:
            raise DocxSecurityError(f"unsafe member path: {info.filename!r}")
        if info.file_size > MAX_MEMBER_UNCOMPRESSED:
            raise DocxSecurityError(f"member too large: {info.filename} ({info.file_size} bytes)")
        total += info.file_size
        if total > MAX_TOTAL_UNCOMPRESSED:
            raise DocxSecurityError("uncompressed size exceeds limit (possible zip bomb)")

    present = set(archive.namelist())
    return {name: archive.read(name) for name in wanted if name in present}


def secure_fromstring(data: bytes) -> _Element:
    """Parse OOXML with XXE defenses: no DOCTYPE, no entity resolution, no DTD, no network."""
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise DocxSecurityError("XML declares a DOCTYPE/ENTITY; refusing to parse")
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
    )
    try:
        return etree.fromstring(data, parser)
    except etree.XMLSyntaxError as exc:
        raise DocxError(f"invalid OOXML: {exc}") from exc
