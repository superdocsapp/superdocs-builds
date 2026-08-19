"""Reading threads out of a .docx, and writing resolution back into one."""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest
from lxml import etree

from thread_resolver.adapters.docx_source import DocxThreadSource, UnsupportedDocument
from thread_resolver.adapters.ooxml import COMMENTS_EXTENDED_PART, qn
from thread_resolver.domain.models import DocumentPayload
from thread_resolver.samples import catalogue
from thread_resolver.samples.builder import (
    CommentSpec,
    DocumentSpec,
    ParagraphSpec,
    build_docx,
)


def source(spec: DocumentSpec, name: str = "contract.docx") -> DocxThreadSource:
    return DocxThreadSource(data=build_docx(spec), name=name)


class TestReadingThreads:
    def test_single_comment_is_a_thread_of_one(self) -> None:
        threads = source(catalogue.SINGLE_ACTIONABLE).read_threads()

        assert len(threads) == 1
        assert threads[0].root.author == "Ada Whitfield"
        assert threads[0].root.text == "Thirty days is too long. Make it fifteen."
        assert threads[0].replies == ()

    def test_replies_are_grouped_under_their_root(self) -> None:
        threads = source(catalogue.CONTESTED_THREAD).read_threads()

        assert len(threads) == 1
        thread = threads[0]
        assert thread.root.author == "Ada Whitfield"
        assert [r.author for r in thread.replies] == ["Grace Okonjo", "Ada Whitfield"]

    def test_replies_keep_document_order(self) -> None:
        threads = source(catalogue.AGREEING_THREAD).read_threads()

        assert [r.text for r in threads[0].replies] == [
            "Agreed, thirty is standard for us.",
            "Good, please make that change.",
        ]

    def test_resolved_state_is_read(self) -> None:
        threads = source(catalogue.RESOLVED_THREAD).read_threads()

        assert threads[0].resolved is True
        assert threads[0].is_open is False

    def test_open_thread_is_not_resolved(self) -> None:
        assert source(catalogue.SINGLE_ACTIONABLE).read_threads()[0].is_open is True

    def test_author_is_captured_for_every_participant(self) -> None:
        threads = source(catalogue.CONTESTED_THREAD).read_threads()

        assert threads[0].participants == frozenset({"Ada Whitfield", "Grace Okonjo"})

    def test_document_without_comments_yields_no_threads(self) -> None:
        spec = DocumentSpec(paragraphs=(ParagraphSpec(text="No comments here."),))

        assert source(spec).read_threads() == ()

    def test_mixed_document_yields_every_thread(self) -> None:
        threads = source(catalogue.MIXED_DOCUMENT).read_threads()

        assert len(threads) == 5
        assert sum(1 for t in threads if t.is_open) == 4
        assert sum(1 for t in threads if t.has_replies) == 1


class TestAnchors:
    def test_anchor_carries_the_commented_passage(self) -> None:
        threads = source(catalogue.SINGLE_ACTIONABLE).read_threads()
        anchor = threads[0].anchor

        assert anchor is not None
        assert anchor.text.startswith("3. Delivery.")
        assert anchor.paragraph_index == 3

    def test_comment_with_no_range_has_no_anchor(self) -> None:
        """The passage it referred to is gone, so no edit can be grounded in it."""
        threads = source(catalogue.UNANCHORED_COMMENT).read_threads()

        assert threads[0].anchor is None

    def test_anchor_spanning_two_paragraphs_captures_both(self) -> None:
        spec = DocumentSpec(
            paragraphs=(
                ParagraphSpec(text="First paragraph.", anchors=("span",)),
                ParagraphSpec(text="Second paragraph."),
            ),
            comments=(CommentSpec(key="span", author="Ada", text="covers both"),),
        )
        # The range opens on the first paragraph and is closed on the second.
        data = _reopen_range_across_paragraphs(build_docx(spec))
        anchor = DocxThreadSource(data, "spanning.docx").read_threads()[0].anchor

        assert anchor is not None
        assert anchor.text == "First paragraph.\nSecond paragraph."
        assert anchor.paragraph_index == 0


class TestDegradedDocuments:
    """A document missing the extended part still reads, without invented structure."""

    def _without_extended_part(self, spec: DocumentSpec) -> bytes:
        return _drop_part(build_docx(spec), COMMENTS_EXTENDED_PART)

    def test_comments_still_read_without_the_extended_part(self) -> None:
        data = self._without_extended_part(catalogue.CONTESTED_THREAD)
        threads = DocxThreadSource(data, "legacy.docx").read_threads()

        assert len(threads) == 3

    def test_no_thread_structure_is_invented(self) -> None:
        data = self._without_extended_part(catalogue.CONTESTED_THREAD)
        threads = DocxThreadSource(data, "legacy.docx").read_threads()

        assert all(t.replies == () for t in threads)
        assert all(t.resolved is False for t in threads)

    def test_closing_is_refused_with_a_message_naming_the_fix(self) -> None:
        data = self._without_extended_part(catalogue.SINGLE_ACTIONABLE)
        legacy = DocxThreadSource(data, "legacy.docx")

        with pytest.raises(UnsupportedDocument, match="re-save the file in Word"):
            legacy.close_threads(["0"])

    def test_reply_to_a_missing_parent_becomes_its_own_thread(self) -> None:
        """Structure that points nowhere is dropped rather than guessed at."""
        data = _rewrite_parent(build_docx(catalogue.CONTESTED_THREAD), "DEADBEEF")
        threads = DocxThreadSource(data, "broken.docx").read_threads()

        assert len(threads) == 3


class TestClosingThreads:
    def test_approved_thread_is_marked_resolved(self) -> None:
        original = source(catalogue.SINGLE_ACTIONABLE)
        closed = DocxThreadSource(original.close_threads(["0"]).data, "closed.docx")

        assert closed.read_threads()[0].resolved is True

    def test_every_comment_in_the_thread_is_marked(self) -> None:
        original = source(catalogue.CONTESTED_THREAD)
        updated = original.close_threads(["0"]).data
        entries = _extended_entries(updated)

        assert [e.get(qn("w15:done")) for e in entries] == ["1", "1", "1"]

    def test_threads_not_named_are_left_open(self) -> None:
        original = source(catalogue.MIXED_DOCUMENT)
        threads = original.read_threads()
        target = next(t for t in threads if t.root.text.startswith("Thirty days"))

        closed = DocxThreadSource(original.close_threads([target.thread_id]).data, "closed.docx")
        by_id = {t.thread_id: t for t in closed.read_threads()}

        assert by_id[target.thread_id].resolved is True
        assert [t.resolved for t in closed.read_threads() if t.thread_id != target.thread_id] == [
            True,  # the thread that was already resolved before the run
            False,
            False,
            False,
        ]

    def test_closing_nothing_returns_the_document_unchanged(self) -> None:
        original = source(catalogue.MIXED_DOCUMENT)

        assert original.close_threads([]).data == original.payload().data

    def test_unknown_thread_id_is_refused(self) -> None:
        with pytest.raises(UnsupportedDocument, match="no threads with ids"):
            source(catalogue.SINGLE_ACTIONABLE).close_threads(["999"])

    def test_result_is_a_valid_document_that_reads_back(self) -> None:
        payload = source(catalogue.MIXED_DOCUMENT).close_threads(["1"])

        assert isinstance(payload, DocumentPayload)
        assert payload.filename == "contract.docx"
        assert len(DocxThreadSource(payload.data, "x.docx").read_threads()) == 5


class TestSurgicalPrecision:
    """Closing a thread must touch commentsExtended.xml and nothing else."""

    def test_only_the_resolution_part_changes(self) -> None:
        original = source(catalogue.MIXED_DOCUMENT)
        before = _parts(original.payload().data)
        after = _parts(original.close_threads(["1"]).data)

        changed = {name for name in before if before[name] != after[name]}

        assert changed == {COMMENTS_EXTENDED_PART}

    def test_body_text_is_byte_identical(self) -> None:
        original = source(catalogue.MIXED_DOCUMENT)
        before = _parts(original.payload().data)
        after = _parts(original.close_threads(["1"]).data)

        assert before["word/document.xml"] == after["word/document.xml"]

    def test_comment_text_is_byte_identical(self) -> None:
        original = source(catalogue.MIXED_DOCUMENT)
        before = _parts(original.payload().data)
        after = _parts(original.close_threads(["1"]).data)

        assert before["word/comments.xml"] == after["word/comments.xml"]

    def test_no_part_is_added_or_removed(self) -> None:
        original = source(catalogue.MIXED_DOCUMENT)
        before = _parts(original.payload().data)
        after = _parts(original.close_threads(["1"]).data)

        assert before.keys() == after.keys()

    def test_closing_is_idempotent(self) -> None:
        original = source(catalogue.MIXED_DOCUMENT)
        once = original.close_threads(["1"]).data
        twice = DocxThreadSource(once, "once.docx").close_threads(["1"]).data

        assert once == twice


# -- helpers ----------------------------------------------------------------


def _parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _replace(data: bytes, part: str, new: bytes) -> bytes:
    buffer = BytesIO()
    with (
        zipfile.ZipFile(BytesIO(data)) as src,
        zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as dst,
    ):
        for info in src.infolist():
            dst.writestr(info, new if info.filename == part else src.read(info.filename))
    return buffer.getvalue()


def _drop_part(data: bytes, part: str) -> bytes:
    buffer = BytesIO()
    with (
        zipfile.ZipFile(BytesIO(data)) as src,
        zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as dst,
    ):
        for info in src.infolist():
            if info.filename != part:
                dst.writestr(info, src.read(info.filename))
    return buffer.getvalue()


def _extended_entries(data: bytes) -> list[etree._Element]:
    root = etree.fromstring(_parts(data)[COMMENTS_EXTENDED_PART])
    entries: list[etree._Element] = root.findall(qn("w15:commentEx"))
    return entries


def _rewrite_parent(data: bytes, missing_para_id: str) -> bytes:
    """Point every reply at a parent that does not exist."""
    root = etree.fromstring(_parts(data)[COMMENTS_EXTENDED_PART])
    for node in root.findall(qn("w15:commentEx")):
        if node.get(qn("w15:paraIdParent")) is not None:
            node.set(qn("w15:paraIdParent"), missing_para_id)
    return _replace(data, COMMENTS_EXTENDED_PART, etree.tostring(root, encoding="UTF-8"))


def _reopen_range_across_paragraphs(data: bytes) -> bytes:
    """Move the range end from the first paragraph to the second."""
    root = etree.fromstring(_parts(data)["word/document.xml"])
    body = root.find(qn("w:body"))
    assert body is not None
    paragraphs = body.findall(qn("w:p"))

    end = paragraphs[0].find(qn("w:commentRangeEnd"))
    assert end is not None
    paragraphs[0].remove(end)
    paragraphs[1].append(end)

    return _replace(data, "word/document.xml", etree.tostring(root, encoding="UTF-8"))
