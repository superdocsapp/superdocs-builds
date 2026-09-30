"""Task 2.2's whole claim: *"Nothing duplicated, nothing dropped."*

Driven on the recorded master — `04_document_html.json`, the real parsed HTML
SuperDocs returned for a 24-block, 12-heading MSA. No key, no network.

**The tests that matter are the ones that break the slicer on purpose.** A
coverage check that only ever sees correct input proves nothing about what it
would say when a block goes missing, and "we verify completeness" is exactly the
kind of claim that is true of the happy path and false of the code.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from service import blocks as block_reader
from service import slicing
from service.cutting import Cut, relabel, split_html, text_length

# Vendored beside the tests, not read from a repository root. This project
# ships as a standalone pull request, so it may not assume anything exists
# outside its own folder — the same reason `_portable/` holds a copy of the
# shared client rather than importing it.
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "superdocs_responses"
MASTER = json.loads((FIXTURES / "04_document_html.json").read_text())["body"]["html"]


@pytest.fixture
def blocks() -> list[block_reader.Block]:
    return block_reader.parse(MASTER)


@pytest.fixture
def headings(blocks: list[block_reader.Block]) -> list[str]:
    return [block.chunk_id for block in blocks if block.heading_level]


class TestParsing:
    def test_the_recorded_master_parses_to_what_the_audit_measured(
        self, blocks: list[block_reader.Block]
    ) -> None:
        """24 blocks and 12 headings — the numbers in
        `docs/SUPERDOCS_CONTRACT.md` §8, measured against the live API before a
        line of this app existed. If parsing drifts, this is where it shows."""
        assert len(blocks) == 24
        assert sum(1 for block in blocks if block.heading_level) == 12

    def test_every_block_is_addressable(self, blocks: list[block_reader.Block]) -> None:
        """A block with no chunk id cannot be a split point, so it cannot be
        part of a document this tool claims to split exactly."""
        assert all(block.chunk_id for block in blocks)
        assert len({block.chunk_id for block in blocks}) == len(blocks)

    def test_nested_elements_do_not_become_blocks(self) -> None:
        """A `<header>` contains a `<p>`; only the header carries a chunk id and
        only the header is a block. Descending would count the same text twice
        and make every coverage number meaningless."""
        html = (
            '<header data-chunk-id="h1" data-part-type="header">'
            "<p>CONFIDENTIAL — prepared for Jonathan</p></header>\n"
            '<p data-chunk-id="b1">Body text.</p>'
        )

        parsed = block_reader.parse(html)

        assert [block.chunk_id for block in parsed] == ["h1", "b1"]
        assert parsed[0].text == "CONFIDENTIAL — prepared for Jonathan"

    def test_a_void_tag_does_not_swallow_the_document(self) -> None:
        """`<br/>` has no closing tag. Counted as an open element, every block
        after it would look nested and the whole document would parse as one."""
        html = '<p data-chunk-id="a">One<br/>two</p>\n<p data-chunk-id="b">Three</p>'

        assert len(block_reader.parse(html)) == 2


class TestTheSplit:
    def test_three_marks_make_three_parts(
        self, blocks: list[block_reader.Block], headings: list[str]
    ) -> None:
        parts = slicing.split(blocks, [Cut(headings[3]), Cut(headings[7])])

        assert len(parts) == 3
        assert sum(len(part.blocks) for part in parts) == 24

    def test_the_parts_are_contiguous_and_in_order(
        self, blocks: list[block_reader.Block], headings: list[str]
    ) -> None:
        """"Split exactly at the boundaries" — the concatenated parts must be
        the master in its original order, not a reshuffle that happens to
        contain the same blocks."""
        parts = slicing.split(blocks, [Cut(headings[3]), Cut(headings[7])])

        rebuilt = [block.chunk_id for part in parts for block in part.blocks]
        assert rebuilt == [block.chunk_id for block in blocks]

    def test_a_part_is_titled_by_its_first_heading(
        self, blocks: list[block_reader.Block], headings: list[str]
    ) -> None:
        parts = slicing.split(blocks, [Cut(headings[3])])

        assert parts[0].title == "1. Parties and Agreement"

    def test_marks_out_of_order_or_repeated_still_split_cleanly(
        self, blocks: list[block_reader.Block], headings: list[str]
    ) -> None:
        """A reviewer clicks headings in whatever order they read them, and
        clicks the same one twice. Neither should produce an empty part."""
        parts = slicing.split(blocks, [Cut(headings[7]), Cut(headings[3]), Cut(headings[7])])

        assert len(parts) == 3
        assert all(part.blocks for part in parts)

    def test_no_marks_means_one_part_covering_everything(
        self, blocks: list[block_reader.Block]
    ) -> None:
        parts = slicing.split(blocks, [])

        assert len(parts) == 1
        assert len(parts[0].blocks) == 24

    def test_an_unknown_chunk_id_is_ignored_rather_than_cutting_wrongly(
        self, blocks: list[block_reader.Block]
    ) -> None:
        parts = slicing.split(blocks, [Cut("not-a-block-in-this-document")])

        assert len(parts) == 1


class TestCoverage:
    def test_a_correct_split_reports_complete(
        self, blocks: list[block_reader.Block], headings: list[str]
    ) -> None:
        parts = slicing.split(blocks, [Cut(headings[3]), Cut(headings[7])])

        report = slicing.coverage(blocks, parts)

        assert report.complete is True
        assert report.part_blocks == report.master_blocks == 24
        assert report.blocks_cut == 0
        assert report.part_headings == report.master_headings == 12
        assert report.part_chars == report.master_chars
        assert "nothing dropped, nothing duplicated" in report.summary

    @pytest.mark.parametrize("marks", [0, 1, 2, 5, 11])
    def test_it_holds_however_the_document_is_cut(
        self, blocks: list[block_reader.Block], headings: list[str], marks: int
    ) -> None:
        """The claim is about every split, not the one in the demo."""
        parts = slicing.split(blocks, [Cut(h) for h in headings[1 : marks + 1]])

        assert slicing.coverage(blocks, parts).complete is True

    def test_a_dropped_block_is_caught(
        self, blocks: list[block_reader.Block], headings: list[str]
    ) -> None:
        """**The test that makes the claim mean something.** Slice correctly,
        then delete a block from a part and confirm the checker says so."""
        parts = slicing.split(blocks, [Cut(headings[3]), Cut(headings[7])])
        damaged = [
            slicing.Part(
                number=parts[0].number, title=parts[0].title, blocks=parts[0].blocks[:-1]
            ),
            *parts[1:],
        ]

        report = slicing.coverage(blocks, damaged)

        assert report.complete is False
        assert len(report.dropped) == 1
        assert "missing from every part" in report.summary

    def test_a_duplicated_block_is_caught(
        self, blocks: list[block_reader.Block], headings: list[str]
    ) -> None:
        parts = slicing.split(blocks, [Cut(headings[3]), Cut(headings[7])])
        damaged = [
            parts[0],
            slicing.Part(
                number=2, title=parts[1].title, blocks=[parts[0].blocks[0], *parts[1].blocks]
            ),
            parts[2],
        ]

        report = slicing.coverage(blocks, damaged)

        assert report.complete is False
        assert len(report.duplicated) == 1
        assert "more than one part" in report.summary

    def test_text_lost_inside_a_block_is_caught_by_the_character_count(
        self, blocks: list[block_reader.Block], headings: list[str]
    ) -> None:
        """The check the block count cannot make. A slice that mangled markup
        keeps every block and loses words inside one."""
        parts = slicing.split(blocks, [Cut(headings[3])])
        gutted = block_reader.Block(
            index=parts[0].blocks[0].index,
            chunk_id=parts[0].blocks[0].chunk_id,
            tag=parts[0].blocks[0].tag,
            html="<h2>x</h2>",
            part_type="body",
        )
        damaged = [
            slicing.Part(
                number=1, title="t", blocks=[gutted, *parts[0].blocks[1:]]
            ),
            parts[1],
        ]

        report = slicing.coverage(blocks, damaged)

        assert report.complete is False
        assert "characters lost" in report.summary


class TestPageFurniture:
    """A header is not *at* a position — it repeats on every page."""

    HTML = (
        '<header data-chunk-id="hd" data-part-type="header"><p>Letterhead</p></header>\n'
        '<h2 data-chunk-id="h1">One</h2>\n<p data-chunk-id="p1">Alpha</p>\n'
        '<h2 data-chunk-id="h2">Two</h2>\n<p data-chunk-id="p2">Beta</p>\n'
        '<footer data-chunk-id="ft" data-part-type="footer"><p>Page</p></footer>'
    )

    def test_it_is_carried_into_every_part_not_sliced_into_one(self) -> None:
        """Slicing the letterhead into part 2 alone would leave parts 1 and 3
        with no letterhead — three documents where one is right."""
        parsed = block_reader.parse(self.HTML)

        parts = slicing.split(parsed, [Cut("h2")])

        assert len(parts) == 2
        for part in parts:
            assert "Letterhead" in part.html
            assert "Page" in part.html

    def test_repeating_it_is_not_reported_as_duplication(self) -> None:
        """It would be, on a naive count — and "2 blocks duplicated" on a
        correct split is a false alarm a reviewer learns to ignore."""
        parsed = block_reader.parse(self.HTML)
        parts = slicing.split(parsed, [Cut("h2")])

        report = slicing.coverage(parsed, parts)

        assert report.complete is True
        assert report.duplicated == []
        assert report.repeated_furniture == 4  # 2 furniture blocks in each of 2 parts

    def test_only_content_is_counted_as_the_master(self) -> None:
        parsed = block_reader.parse(self.HTML)

        report = slicing.coverage(parsed, slicing.split(parsed, [Cut("h2")]))

        assert report.master_blocks == 4  # not 6


class TestCuttingMidParagraph:
    """The reviewer points at a word, not at a paragraph.

    A marker dropped on line 8 of page 2 usually lands inside a sentence, and
    that is where the cut goes — so a block becomes two, and the completeness
    proof has to keep working across the seam.
    """

    PARA = '<p data-chunk-id="p">Fees are due <b>Net 30</b> from invoice.</p>'

    def test_tags_open_at_the_cut_are_closed_and_reopened(self) -> None:
        """A naive slice yields `<b>Net` with no closing tag — markup SuperDocs
        either rejects or silently repairs into something nobody asked for."""
        before, after = split_html(self.PARA, 17)

        assert before.endswith("</b></p>")
        assert after.startswith('<p data-chunk-id="p"><b>')
        assert before.count("<b>") == before.count("</b>") == 1
        assert after.count("<b>") == after.count("</b>") == 1

    @pytest.mark.parametrize("offset", [1, 5, 13, 17, 20, 26, 32])
    def test_no_character_is_lost_or_gained_wherever_it_is_cut(
        self, offset: int
    ) -> None:
        import re as regex

        before, after = split_html(self.PARA, offset)
        plain = lambda html: regex.sub(r"<[^>]+>", "", html)  # noqa: E731

        assert plain(before) + plain(after) == plain(self.PARA)

    def test_an_entity_is_never_cut_in_half(self) -> None:
        """`&amp;` sliced down the middle is `&am` — not a character, not
        valid, and invisible until the export renders it."""
        html = "<p>Acme &amp; Co</p>"

        for offset in range(1, text_length(html)):
            before, after = split_html(html, offset)
            assert "&am" not in before or "&amp;" in before
            assert not after.startswith("p;")

    def test_a_cut_block_still_reconciles(
        self, blocks: list[block_reader.Block]
    ) -> None:
        paragraph = next(block for block in blocks if not block.heading_level)

        parts = slicing.split(blocks, [Cut(paragraph.chunk_id, 120)])
        report = slicing.coverage(blocks, parts)

        assert report.complete is True
        assert report.blocks_cut == 1
        # One more block than the master: expected, and counted rather than
        # waved away.
        assert report.part_blocks == report.master_blocks + 1
        assert report.part_chars == report.master_chars

    def test_one_paragraph_can_be_cut_more_than_once(
        self, blocks: list[block_reader.Block]
    ) -> None:
        """Three exhibits inside one long recital. Fragments are numbered, not
        lettered — `#a`/`#b` collided the moment a second cut landed in the
        same block, and two fragments sharing an id read as a duplicate."""
        paragraph = next(block for block in blocks if not block.heading_level)

        parts = slicing.split(
            blocks, [Cut(paragraph.chunk_id, 40), Cut(paragraph.chunk_id, 120)]
        )
        report = slicing.coverage(blocks, parts)

        assert len(parts) == 3
        assert report.complete is True
        assert report.duplicated == []
        assert report.blocks_cut == 2

    def test_a_cut_at_the_very_start_of_the_document_is_ignored(
        self, blocks: list[block_reader.Block]
    ) -> None:
        """It would open an empty first part."""
        assert len(slicing.split(blocks, [Cut(blocks[0].chunk_id, 0)])) == 1

    def test_an_offset_past_the_end_of_a_block_is_clamped(
        self, blocks: list[block_reader.Block]
    ) -> None:
        """A stale outline in the browser must not cut at a position the block
        no longer has."""
        paragraph = next(block for block in blocks if not block.heading_level)

        parts = slicing.split(blocks, [Cut(paragraph.chunk_id, 10_000)])

        assert slicing.coverage(blocks, parts).complete is True

    def test_the_halves_get_their_own_ids(self) -> None:
        assert 'data-chunk-id="p#1"' in relabel(self.PARA, "#1")
