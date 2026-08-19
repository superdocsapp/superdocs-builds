"""Reads comment threads out of a .docx and writes their resolution back.

Reading joins three parts of the package. Writing touches exactly one of them:
resolution lives in commentsExtended.xml, so every other entry in the zip is
copied through unchanged and the rest of the document is provably untouched.
"""

from __future__ import annotations

import zipfile
from collections.abc import Collection
from datetime import datetime
from io import BytesIO
from pathlib import Path

from lxml import etree

from thread_resolver.adapters.ooxml import (
    COMMENTS_EXTENDED_PART,
    COMMENTS_PART,
    DOCUMENT_PART,
    qn,
    text_of,
)
from thread_resolver.domain.models import Anchor, Comment, DocumentPayload, Thread
from thread_resolver.ports.thread_source import ThreadSource


class UnsupportedDocument(Exception):
    """Raised when a document cannot support an operation the caller asked for."""


class _RawComment:
    """A comment as it appears in the package, before threads are reconstructed."""

    __slots__ = ("author", "comment_id", "created", "para_id", "text")

    def __init__(
        self, comment_id: str, para_id: str | None, author: str, text: str, created: datetime | None
    ) -> None:
        self.comment_id = comment_id
        self.para_id = para_id
        self.author = author
        self.text = text
        self.created = created

    def to_comment(self) -> Comment:
        return Comment(
            comment_id=self.comment_id,
            para_id=self.para_id,
            author=self.author,
            text=self.text,
            created=self.created,
        )


class DocxThreadSource(ThreadSource):
    """A .docx held in memory, exposing its comment threads."""

    def __init__(self, data: bytes, name: str) -> None:
        self._data = data
        self._name = name

    @classmethod
    def from_path(cls, path: Path) -> DocxThreadSource:
        return cls(data=path.read_bytes(), name=path.name)

    @property
    def name(self) -> str:
        return self._name

    def payload(self) -> DocumentPayload:
        return DocumentPayload(filename=self._name, data=self._data)

    # -- reading ------------------------------------------------------------

    def read_threads(self) -> tuple[Thread, ...]:
        parts = self._parts()
        if COMMENTS_PART not in parts:
            return ()

        raw = self._read_comments(parts[COMMENTS_PART])
        parents, done = self._read_thread_structure(parts.get(COMMENTS_EXTENDED_PART))
        anchors = self._read_anchors(parts.get(DOCUMENT_PART))

        return self._assemble(raw, parents, done, anchors)

    def _parts(self) -> dict[str, bytes]:
        with zipfile.ZipFile(BytesIO(self._data)) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    def _read_comments(self, data: bytes) -> list[_RawComment]:
        root = etree.fromstring(data)
        comments: list[_RawComment] = []

        for node in root.findall(qn("w:comment")):
            comment_id = node.get(qn("w:id"))
            if comment_id is None:
                continue

            paragraphs = node.findall(qn("w:p"))
            # commentsExtended names a comment by the paraId of its last
            # paragraph, so that is the one that has to be carried forward.
            para_id = paragraphs[-1].get(qn("w14:paraId")) if paragraphs else None

            comments.append(
                _RawComment(
                    comment_id=comment_id,
                    para_id=para_id,
                    author=node.get(qn("w:author")) or "",
                    text="\n".join(text_of(p) for p in paragraphs).strip(),
                    created=_parse_date(node.get(qn("w:date"))),
                )
            )

        return comments

    def _read_thread_structure(self, data: bytes | None) -> tuple[dict[str, str], dict[str, bool]]:
        """Map each comment's paraId to its parent, and to its resolved flag.

        Returns empty maps when the part is absent, which leaves every comment a
        thread of one rather than inventing structure that is not there.
        """
        if data is None:
            return {}, {}

        root = etree.fromstring(data)
        parents: dict[str, str] = {}
        done: dict[str, bool] = {}

        for node in root.findall(qn("w15:commentEx")):
            para_id = node.get(qn("w15:paraId"))
            if para_id is None:
                continue
            parent = node.get(qn("w15:paraIdParent"))
            if parent is not None:
                parents[para_id] = parent
            done[para_id] = node.get(qn("w15:done")) == "1"

        return parents, done

    def _read_anchors(self, data: bytes | None) -> dict[str, Anchor]:
        """Find the passage each comment range covers.

        A range can span several paragraphs, so open ranges are tracked as the
        body is walked and every paragraph inside a range contributes its text.
        """
        if data is None:
            return {}

        root = etree.fromstring(data)
        body = root.find(qn("w:body"))
        if body is None:
            return {}

        covered: dict[str, list[str]] = {}
        first_index: dict[str, int] = {}
        open_ids: set[str] = set()

        for index, paragraph in enumerate(body.findall(qn("w:p"))):
            starts = _range_ids(paragraph, "w:commentRangeStart")
            ends = _range_ids(paragraph, "w:commentRangeEnd")

            active = open_ids | starts
            if active:
                text = text_of(paragraph)
                for comment_id in active:
                    covered.setdefault(comment_id, []).append(text)
                    first_index.setdefault(comment_id, index)

            open_ids = active - ends

        return {
            comment_id: Anchor(
                text="\n".join(texts).strip(), paragraph_index=first_index[comment_id]
            )
            for comment_id, texts in covered.items()
        }

    def _assemble(
        self,
        raw: list[_RawComment],
        parents: dict[str, str],
        done: dict[str, bool],
        anchors: dict[str, Anchor],
    ) -> tuple[Thread, ...]:
        by_para_id = {c.para_id: c for c in raw if c.para_id is not None}

        def root_of(comment: _RawComment) -> _RawComment:
            """Walk up to the thread root.

            Word's interface only offers flat threads, but the format permits a
            reply to name another reply as its parent, so the chain is followed
            rather than assumed to be one deep. A cycle would otherwise hang the
            run, so visited ids are tracked.
            """
            current = comment
            seen = {current.para_id}
            while current.para_id is not None:
                parent_id = parents.get(current.para_id)
                if parent_id is None or parent_id in seen:
                    break
                parent = by_para_id.get(parent_id)
                if parent is None:
                    break
                seen.add(parent_id)
                current = parent
            return current

        grouped: dict[str, list[_RawComment]] = {}
        roots: dict[str, _RawComment] = {}

        for comment in raw:
            root = root_of(comment)
            roots[root.comment_id] = root
            if comment.comment_id != root.comment_id:
                grouped.setdefault(root.comment_id, []).append(comment)

        threads = []
        for root_id, root in roots.items():
            replies = sorted(grouped.get(root_id, []), key=lambda c: _sort_key(c.comment_id))
            threads.append(
                Thread(
                    root=root.to_comment(),
                    replies=tuple(r.to_comment() for r in replies),
                    anchor=anchors.get(root_id),
                    resolved=done.get(root.para_id or "", False),
                )
            )

        return tuple(sorted(threads, key=lambda t: _sort_key(t.thread_id)))

    # -- writing ------------------------------------------------------------

    def close_threads(self, thread_ids: Collection[str]) -> DocumentPayload:
        """Mark the given threads resolved, rewriting only commentsExtended.xml."""
        wanted = set(thread_ids)
        if not wanted:
            return self.payload()

        parts = self._parts()
        if COMMENTS_EXTENDED_PART not in parts:
            raise UnsupportedDocument(
                f"{self._name} has no {COMMENTS_EXTENDED_PART}, so resolution cannot be recorded. "
                "Open and re-save the file in Word, which writes that part, then run again."
            )

        threads = {t.thread_id: t for t in self.read_threads()}
        unknown = wanted - threads.keys()
        if unknown:
            raise UnsupportedDocument(
                f"{self._name} has no threads with ids {sorted(unknown)}. "
                "Thread ids come from read_threads() on this same document."
            )

        para_ids = {
            comment.para_id
            for thread_id in wanted
            for comment in threads[thread_id].comments
            if comment.para_id is not None
        }

        updated = _mark_done(parts[COMMENTS_EXTENDED_PART], para_ids)
        return DocumentPayload(
            filename=self._name,
            data=_replace_part(self._data, COMMENTS_EXTENDED_PART, updated),
        )


def _mark_done(data: bytes, para_ids: set[str]) -> bytes:
    root = etree.fromstring(data)
    for node in root.findall(qn("w15:commentEx")):
        if node.get(qn("w15:paraId")) in para_ids:
            node.set(qn("w15:done"), "1")
    result: bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    return result


def _replace_part(archive_bytes: bytes, part_name: str, data: bytes) -> bytes:
    """Rebuild the package with one part replaced.

    Every other entry is copied with its original metadata so that parts the run
    did not touch stay byte-identical.
    """
    buffer = BytesIO()
    with (
        zipfile.ZipFile(BytesIO(archive_bytes)) as source,
        zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for info in source.infolist():
            payload = data if info.filename == part_name else source.read(info.filename)
            target.writestr(info, payload)
    return buffer.getvalue()


def _range_ids(paragraph: etree._Element, tag: str) -> set[str]:
    """Comment ids carried by one kind of range marker in a paragraph."""
    ids: set[str] = set()
    for element in paragraph.findall(qn(tag)):
        value = element.get(qn("w:id"))
        if value is not None:
            ids.add(value)
    return ids


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _sort_key(comment_id: str) -> tuple[int, str]:
    """Order by numeric id where possible, so 2 sorts before 10."""
    return (int(comment_id), "") if comment_id.isdigit() else (1 << 31, comment_id)
