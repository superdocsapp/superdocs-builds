"""What the pane can see — measured on a recorded file, not asserted in prose.

`13_hidden_export.docx` is a real SuperDocs export carrying an SSN inside a
tracked deletion and a card number inside `word/comments.xml`. Neither is
visible in Word's default view and neither is in `word/document.xml`'s ordinary
text, so it is exactly the document that separates a pane that reads the
package from one that reads the body.

The first test in here is the important one, and it is written backwards on
purpose: it first shows that the body-only view **misses** both strings, and
only then that `blocks.read` finds them. A coverage claim that is not measured
against the thing it is better than is not a measurement.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

from service import blocks
from service.pii.patterns import find

# Vendored beside the tests, not read from a repository root. This project
# ships as a standalone pull request, so it may not assume anything exists
# outside its own folder — the same reason `_portable/` holds a copy of the
# shared client rather than importing it.
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "superdocs_responses"

HIDDEN_SSN = "123-45-6789"
HIDDEN_CARD = "4111 1111 1111 1111"


def body_only(data: bytes) -> str:
    """The view every obvious implementation has: `word/document.xml`, `<w:t>`.

    This is what `python-docx` gives you, what `Office.js` `body.text` gives
    you, and what `_portable/document_text.extract_docx` deliberately gives you
    for the analyst's flow. Reproduced here so the comparison below is against
    the real alternative rather than a straw one.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        root = ElementTree.fromstring(package.read(blocks.BODY))
    return "".join(node.text or "" for node in root.iter(f"{blocks.W}t"))


@pytest.fixture
def hidden() -> bytes:
    return (FIXTURES / "13_hidden_export.docx").read_bytes()


class TestWhatTheBodyMisses:
    def test_the_body_alone_does_not_contain_either_identifier(self, hidden: bytes) -> None:
        """The premise. If this ever fails, the test below proves nothing."""
        text = body_only(hidden)

        assert HIDDEN_SSN not in text
        assert HIDDEN_CARD not in text

    def test_reading_the_package_finds_both(self, hidden: bytes) -> None:
        found = {block.part_type: block.text for block in blocks.read(hidden)}

        assert HIDDEN_SSN in found["tracked_del"]
        assert HIDDEN_CARD in found["comment"]

    def test_each_is_labelled_with_where_it_lives(self, hidden: bytes) -> None:
        """`part_type` is what the row shows, and it is the difference between
        "delete this" and "this cannot be deleted from here"."""
        by_text = {block.text: block for block in blocks.read(hidden)}

        deletion = next(block for text, block in by_text.items() if HIDDEN_SSN in text)
        comment = next(block for text, block in by_text.items() if HIDDEN_CARD in text)

        assert deletion.part_type == blocks.TRACKED_DELETION
        assert deletion.chunk_id.endswith("#del")
        assert comment.part_type == "comment"


class TestHeadersAndFooters:
    def test_header_and_footer_arrive_as_their_own_blocks(self) -> None:
        """`12_redacted.docx` carries both. A name on a letterhead repeats on
        every page and is the single most-missed piece of personal data."""
        found = blocks.read((FIXTURES / "12_redacted.docx").read_bytes())
        parts = blocks.coverage(found)

        assert parts["header"] == 1
        assert parts["footer"] == 1
        assert parts["body"] > 1


class TestOffsets:
    def test_a_span_found_in_a_block_is_at_the_offsets_it_reports(
        self, hidden: bytes
    ) -> None:
        """The contract every detector relies on: `text[start:end] == span.text`.

        It is worth asserting here rather than only in the pattern tests,
        because this is where it could break. Interleaving visible and deleted
        text into one string would produce a block that reads correctly and
        indexes wrongly, and every candidate would then quote something the
        reviewer cannot find in their document.
        """
        checked = 0
        for block in blocks.read(hidden):
            for span in find(block.text):
                assert block.text[span.start : span.end] == span.text
                checked += 1

        assert checked >= 2, "the fixture carries an SSN and a card — both must be located"

    def test_visible_and_deleted_text_are_never_mixed(self, hidden: bytes) -> None:
        for block in blocks.read(hidden):
            if block.part_type == blocks.TRACKED_DELETION:
                assert HIDDEN_SSN in block.text
            else:
                assert "DELETEDNAME" not in block.text


class TestIdentity:
    def test_the_same_document_produces_the_same_ids(self, hidden: bytes) -> None:
        """Re-scan depends on this. Ids that moved between two reads of one
        unchanged file would present every finding again as new."""
        first = [block.chunk_id for block in blocks.read(hidden)]
        second = [block.chunk_id for block in blocks.read(hidden)]

        assert first == second
        assert len(set(first)) == len(first), "ids must be unique within a document"


class TestOtherInput:
    def test_plain_text_is_accepted(self) -> None:
        """`FakeHost` hands the pane text outside Word. A scan that only worked
        on a real package could not be exercised at all without one."""
        found = blocks.read(b"First paragraph.\n\nSecond paragraph.")

        assert [block.text for block in found] == ["First paragraph.", "Second paragraph."]
        assert all(block.part_type == "body" for block in found)

    def test_a_zip_that_is_not_a_word_document_is_refused_by_name(self) -> None:
        import io

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as package:
            package.writestr("hello.txt", "not a document")

        with pytest.raises(blocks.UnreadableDocument, match=r"word/document\.xml"):
            blocks.read(buffer.getvalue())
