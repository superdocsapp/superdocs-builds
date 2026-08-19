"""Checks the fixture builder before anything is built on top of it.

A parser tested against fixtures that are themselves wrong proves nothing, so
the structure of the generated parts is asserted directly here.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest
from lxml import etree

from thread_resolver.adapters.ooxml import NSMAP, XML, qn
from thread_resolver.samples import catalogue
from thread_resolver.samples.builder import CommentSpec, DocumentSpec, ParagraphSpec, build_docx

EXPECTED_PARTS = {
    "[Content_Types].xml",
    "_rels/.rels",
    "word/_rels/document.xml.rels",
    "word/document.xml",
    "word/comments.xml",
    "word/commentsExtended.xml",
}


def parts_of(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def parse(data: bytes, name: str) -> etree._Element:
    return etree.fromstring(parts_of(data)[name])


class TestPackage:
    def test_contains_every_required_part(self) -> None:
        assert set(parts_of(build_docx(catalogue.MIXED_DOCUMENT))) == EXPECTED_PARTS

    def test_is_byte_identical_across_builds(self) -> None:
        """Determinism is what lets a later test claim untouched content did not change."""
        assert build_docx(catalogue.MIXED_DOCUMENT) == build_docx(catalogue.MIXED_DOCUMENT)

    def test_every_part_is_well_formed_xml(self) -> None:
        for name, data in parts_of(build_docx(catalogue.MIXED_DOCUMENT)).items():
            assert etree.fromstring(data) is not None, f"{name} is not well-formed"


class TestComments:
    def test_writes_one_comment_per_spec(self) -> None:
        root = parse(build_docx(catalogue.CONTESTED_THREAD), "word/comments.xml")

        assert len(root.findall(qn("w:comment"))) == 3

    def test_preserves_author_and_text(self) -> None:
        root = parse(build_docx(catalogue.SINGLE_ACTIONABLE), "word/comments.xml")
        comment = root.findall(qn("w:comment"))[0]

        assert comment.get(qn("w:author")) == "Ada Whitfield"
        assert comment.findtext(f"{qn('w:p')}/{qn('w:r')}/{qn('w:t')}") == (
            "Thirty days is too long. Make it fifteen."
        )

    def test_escapes_markup_in_comment_text(self) -> None:
        spec = DocumentSpec(
            paragraphs=(ParagraphSpec(text="body", anchors=("c",)),),
            comments=(CommentSpec(key="c", author="Ada", text="replace <b> & </b> here"),),
        )
        root = parse(build_docx(spec), "word/comments.xml")

        assert root.findtext(f"{qn('w:comment')}/{qn('w:p')}/{qn('w:r')}/{qn('w:t')}") == (
            "replace <b> & </b> here"
        )


class TestThreadStructure:
    """Reply parentage and resolved state live only in commentsExtended.xml."""

    def _extended(self, spec: DocumentSpec) -> list[etree._Element]:
        root = parse(build_docx(spec), "word/commentsExtended.xml")
        entries: list[etree._Element] = root.findall(qn("w15:commentEx"))
        return entries

    def test_root_has_no_parent(self) -> None:
        entries = self._extended(catalogue.CONTESTED_THREAD)

        assert entries[0].get(qn("w15:paraIdParent")) is None

    def test_replies_point_at_the_root(self) -> None:
        entries = self._extended(catalogue.CONTESTED_THREAD)
        root_para_id = entries[0].get(qn("w15:paraId"))

        assert [e.get(qn("w15:paraIdParent")) for e in entries[1:]] == [root_para_id, root_para_id]

    def test_resolved_thread_is_marked_done(self) -> None:
        entries = self._extended(catalogue.RESOLVED_THREAD)

        assert [e.get(qn("w15:done")) for e in entries] == ["1", "1"]

    def test_open_thread_is_not_marked_done(self) -> None:
        entries = self._extended(catalogue.SINGLE_ACTIONABLE)

        assert entries[0].get(qn("w15:done")) == "0"


class TestAnchoring:
    def _body(self, spec: DocumentSpec) -> etree._Element:
        return parse(build_docx(spec), "word/document.xml")

    def test_anchored_comment_has_a_range_in_the_body(self) -> None:
        body = self._body(catalogue.SINGLE_ACTIONABLE)

        assert len(body.findall(f".//{qn('w:commentRangeStart')}")) == 1
        assert len(body.findall(f".//{qn('w:commentRangeEnd')}")) == 1

    def test_range_sits_on_the_paragraph_it_was_attached_to(self) -> None:
        body = self._body(catalogue.SINGLE_ACTIONABLE)
        paragraphs = body.findall(f".//{qn('w:p')}")
        commented = [
            index
            for index, p in enumerate(paragraphs)
            if p.find(qn("w:commentRangeStart")) is not None
        ]

        assert commented == [3]
        assert paragraphs[3].findtext(f"{qn('w:r')}/{qn('w:t')}", "").startswith("3. Delivery.")

    def test_unanchored_comment_has_no_range(self) -> None:
        body = self._body(catalogue.UNANCHORED_COMMENT)

        assert body.findall(f".//{qn('w:commentRangeStart')}") == []

    def test_one_paragraph_can_carry_two_threads(self) -> None:
        body = self._body(catalogue.MIXED_DOCUMENT)
        paragraphs = body.findall(f".//{qn('w:p')}")
        starts = paragraphs[3].findall(qn("w:commentRangeStart"))

        assert len(starts) == 2

    def test_leading_and_trailing_space_is_preserved(self) -> None:
        spec = DocumentSpec(paragraphs=(ParagraphSpec(text="  padded  "),))
        body = self._body(spec)
        node = body.find(f".//{qn('w:t')}")

        assert node is not None
        assert node.get(f"{{{XML}}}space") == "preserve"
        assert node.text == "  padded  "


class TestValidation:
    def test_rejects_duplicate_keys(self) -> None:
        spec = DocumentSpec(
            paragraphs=(ParagraphSpec(text="body"),),
            comments=(
                CommentSpec(key="a", author="Ada", text="one"),
                CommentSpec(key="a", author="Grace", text="two"),
            ),
        )

        _assert_raises(spec, "comment keys must be unique")

    def test_rejects_a_reply_to_a_missing_comment(self) -> None:
        spec = DocumentSpec(
            paragraphs=(ParagraphSpec(text="body"),),
            comments=(CommentSpec(key="a", parent="ghost", author="Ada", text="one"),),
        )

        _assert_raises(spec, "replies to unknown")

    def test_rejects_an_anchor_to_a_missing_comment(self) -> None:
        spec = DocumentSpec(paragraphs=(ParagraphSpec(text="body", anchors=("ghost",)),))

        _assert_raises(spec, "anchors unknown comment")


def _assert_raises(spec: DocumentSpec, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_docx(spec)


def test_namespace_map_covers_every_prefix_used() -> None:
    assert set(NSMAP) == {"w", "w14", "w15", "r"}
