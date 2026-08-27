"""Make the reviewer's Word file carry its own review-round id.

The document leaves as an email attachment and comes back days later — possibly forwarded,
renamed, or re-attached — and something has to say *which review round it belongs to*. Asking a
person to quote a round id does not survive contact with reality, so the file answers for itself:
the id is written into the document's custom properties, which Word preserves across an edit and
save, and mirrored in the suggested filename as a fallback for editors that drop properties.

That is what makes the return path channel-agnostic: an email reply, an upload link, a watched
Drive folder or a Slack thread can all hand us bytes, and the round is identified from the bytes.
"""

from __future__ import annotations

import re
import zipfile
from io import BytesIO

from lxml import etree

from notion_review.docx_markup.security import DocxError, read_docx_parts, secure_fromstring

PROPERTY_NAME = "SuperDocsReviewRound"

_CONTENT_TYPES = "[Content_Types].xml"
_ROOT_RELS = "_rels/.rels"
_CUSTOM = "docProps/custom.xml"
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CUSTOM_CT = "application/vnd.openxmlformats-officedocument.custom-properties+xml"
_CUSTOM_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties"
)
_VT = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
_PROPS_NS = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
_ROUND_IN_NAME = re.compile(r"(round_[0-9a-f]{6,})", re.I)


def _custom_xml(round_id: str) -> bytes:
    nsmap: dict[str | None, str] = {None: _PROPS_NS, "vt": _VT}
    root = etree.Element(f"{{{_PROPS_NS}}}Properties", nsmap=nsmap)  # type: ignore[arg-type]
    prop = etree.SubElement(
        root,
        f"{{{_PROPS_NS}}}property",
        fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}",
        pid="2",
        name=PROPERTY_NAME,
    )
    value = etree.SubElement(prop, f"{{{_VT}}}lpwstr")
    value.text = round_id
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _with_content_type(data: bytes) -> bytes:
    root = secure_fromstring(data)
    for override in root.findall(f"{{{_CT_NS}}}Override"):
        if override.get("PartName") == f"/{_CUSTOM}":
            return data
    etree.SubElement(root, f"{{{_CT_NS}}}Override", PartName=f"/{_CUSTOM}", ContentType=_CUSTOM_CT)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _with_relationship(data: bytes) -> bytes:
    root = secure_fromstring(data)
    used = set()
    for rel in root.findall(f"{{{_REL_NS}}}Relationship"):
        if rel.get("Target") in (_CUSTOM, f"/{_CUSTOM}"):
            return data
        used.add(rel.get("Id") or "")
    next_id = next(f"rId{n}" for n in range(100, 1000) if f"rId{n}" not in used)
    etree.SubElement(
        root, f"{{{_REL_NS}}}Relationship", Id=next_id, Type=_CUSTOM_REL, Target=_CUSTOM
    )
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def stamp_round_id(data: bytes, round_id: str) -> bytes:
    """Return the .docx with its review-round id written into the document's custom properties."""
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
    except zipfile.BadZipFile as exc:
        raise DocxError("not a valid .docx (bad zip)") from exc
    if _CONTENT_TYPES not in parts or _ROOT_RELS not in parts:
        raise DocxError("not a valid .docx (missing content types or relationships)")

    parts[_CONTENT_TYPES] = _with_content_type(parts[_CONTENT_TYPES])
    parts[_ROOT_RELS] = _with_relationship(parts[_ROOT_RELS])
    parts[_CUSTOM] = _custom_xml(round_id)

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
        for name, content in parts.items():
            out.writestr(name, content)
    return buffer.getvalue()


def read_round_id(data: bytes) -> str | None:
    """The review-round id stamped into a returned .docx, or ``None`` if it carries none."""
    parts = read_docx_parts(data, {_CUSTOM})
    raw = parts.get(_CUSTOM)
    if raw is None:
        return None
    root = secure_fromstring(raw)
    for prop in root.findall(f"{{{_PROPS_NS}}}property"):
        if prop.get("name") != PROPERTY_NAME:
            continue
        for child in prop:
            if child.text:
                return child.text.strip()
    return None


def round_id_from_filename(filename: str) -> str | None:
    """Fallback for editors that drop custom properties: the id carried in the file's name."""
    match = _ROUND_IN_NAME.search(filename)
    return match.group(1) if match else None


def identify_round(data: bytes, filename: str = "") -> str | None:
    """Which review round a returned file belongs to — from its properties, else its name."""
    try:
        stamped = read_round_id(data)
    except DocxError:
        stamped = None
    return stamped or (round_id_from_filename(filename) if filename else None)
