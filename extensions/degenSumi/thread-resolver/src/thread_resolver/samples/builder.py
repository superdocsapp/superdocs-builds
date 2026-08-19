"""Builds .docx files carrying real Word comment threads.

Fixtures are generated rather than committed as binaries so that the thread
structure under test is readable in source and in review.

A .docx is a zip of XML parts. Comment threads are spread across three of them:

    word/document.xml           the body, and the ranges comments are anchored to
    word/comments.xml           comment text, author and date
    word/commentsExtended.xml   reply parentage and resolved state

Reply structure and resolved state exist only in the third part. A reader that
only parses comments.xml sees a flat list of comments and no threads at all.

Comments are linked across the parts by two different identifiers:

    w:id        an integer, links a comment to its anchor in the body
    w14:paraId  an 8-digit hex value on the comment's last paragraph, used by
                commentsExtended to name a comment and to point at its parent
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from lxml import etree

from thread_resolver.adapters.ooxml import CT, NSMAP, PR, XML, R, qn

# Fixed so that two builds of the same fixture produce identical bytes, which is
# what allows a test to assert that untouched content did not change.
FIXED_DATE = "2026-01-15T09:00:00Z"


@dataclass(frozen=True, slots=True)
class CommentSpec:
    """One comment. A thread is a root plus the comments that name it as parent."""

    author: str
    text: str
    parent: str | None = None
    """`key` of the comment this replies to. None makes this a thread root."""

    done: bool = False
    """Resolved state. Word records this on the thread root."""

    key: str = ""
    """Handle used by other specs to refer to this comment."""


@dataclass(frozen=True, slots=True)
class ParagraphSpec:
    """One body paragraph, and the comment threads anchored to it."""

    text: str
    anchors: tuple[str, ...] = ()
    """`key` of each thread root whose range covers this paragraph."""


@dataclass(frozen=True, slots=True)
class DocumentSpec:
    """A whole fixture document."""

    paragraphs: tuple[ParagraphSpec, ...]
    comments: tuple[CommentSpec, ...] = field(default_factory=tuple)


def _para_id(index: int) -> str:
    """Deterministic 8-digit hex paraId.

    Word requires the value to be non-zero and to fit in 32 bits.
    """
    return f"{index + 1:08X}"


def _element(tag: str, **attrs: str) -> etree._Element:
    el = etree.Element(qn(tag), nsmap=NSMAP)
    for name, value in attrs.items():
        el.set(qn(name.replace("__", ":")), value)
    return el


def _text_run(text: str) -> etree._Element:
    run = _element("w:r")
    node = etree.SubElement(run, qn("w:t"))
    node.text = text
    # Without this, Word discards leading and trailing spaces.
    node.set(f"{{{XML}}}space", "preserve")
    return run


def _build_document(spec: DocumentSpec, ids: dict[str, int]) -> bytes:
    root = etree.Element(qn("w:document"), nsmap=NSMAP)
    body = etree.SubElement(root, qn("w:body"))

    for index, para in enumerate(spec.paragraphs):
        p = etree.SubElement(body, qn("w:p"))
        p.set(qn("w14:paraId"), _para_id(1000 + index))

        for key in para.anchors:
            p.append(_element("w:commentRangeStart", w__id=str(ids[key])))

        p.append(_text_run(para.text))

        for key in para.anchors:
            p.append(_element("w:commentRangeEnd", w__id=str(ids[key])))
            run = _element("w:r")
            run.append(_element("w:commentReference", w__id=str(ids[key])))
            p.append(run)

    return _serialise(root)


def _build_comments(spec: DocumentSpec, ids: dict[str, int], para_ids: dict[str, str]) -> bytes:
    root = etree.Element(qn("w:comments"), nsmap=NSMAP)

    for comment in spec.comments:
        node = _element(
            "w:comment",
            w__id=str(ids[comment.key]),
            w__author=comment.author,
            w__date=FIXED_DATE,
            w__initials="".join(word[0] for word in comment.author.split()).upper(),
        )
        p = etree.SubElement(node, qn("w:p"))
        p.set(qn("w14:paraId"), para_ids[comment.key])
        p.append(_text_run(comment.text))
        root.append(node)

    return _serialise(root)


def _build_comments_extended(spec: DocumentSpec, para_ids: dict[str, str]) -> bytes:
    """The part carrying reply parentage and resolved state."""
    root = etree.Element(qn("w15:commentsEx"), nsmap=NSMAP)

    for comment in spec.comments:
        attrs = {"w15__paraId": para_ids[comment.key], "w15__done": "1" if comment.done else "0"}
        if comment.parent is not None:
            attrs["w15__paraIdParent"] = para_ids[comment.parent]
        root.append(_element("w15:commentEx", **attrs))

    return _serialise(root)


def _serialise(root: etree._Element) -> bytes:
    data: bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    return data


_CONTENT_TYPES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="{CT}">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>
  <Override PartName="/word/commentsExtended.xml" ContentType="application/vnd.ms-word.commentsExtended+xml"/>
</Types>"""  # noqa: E501

_ROOT_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{PR}">
  <Relationship Id="rId1" Type="{R}/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_DOCUMENT_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{PR}">
  <Relationship Id="rId1" Type="{R}/comments" Target="comments.xml"/>
  <Relationship Id="rId2" Type="http://schemas.microsoft.com/office/2011/relationships/commentsExtended" Target="commentsExtended.xml"/>
</Relationships>"""  # noqa: E501


def build_docx(spec: DocumentSpec) -> bytes:
    """Render a spec into .docx bytes.

    Zip entries are written with a fixed timestamp so that building the same
    spec twice produces identical bytes.
    """
    keys = [c.key for c in spec.comments]
    if len(set(keys)) != len(keys):
        raise ValueError("comment keys must be unique")

    ids = {c.key: index for index, c in enumerate(spec.comments)}
    para_ids = {c.key: _para_id(index) for index, c in enumerate(spec.comments)}

    for comment in spec.comments:
        if comment.parent is not None and comment.parent not in ids:
            raise ValueError(f"comment {comment.key!r} replies to unknown {comment.parent!r}")
    for para in spec.paragraphs:
        for key in para.anchors:
            if key not in ids:
                raise ValueError(f"paragraph anchors unknown comment {key!r}")

    parts = {
        "[Content_Types].xml": _CONTENT_TYPES.encode(),
        "_rels/.rels": _ROOT_RELS.encode(),
        "word/_rels/document.xml.rels": _DOCUMENT_RELS.encode(),
        "word/document.xml": _build_document(spec, ids),
        "word/comments.xml": _build_comments(spec, ids, para_ids),
        "word/commentsExtended.xml": _build_comments_extended(spec, para_ids),
    }

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 15, 9, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


def write_docx(spec: DocumentSpec, path: Path) -> Path:
    path.write_bytes(build_docx(spec))
    return path
