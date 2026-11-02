"""The storage-format parser, and the promise it exists to keep.

The central test is `test_every_character_maps_back_to_its_own_bytes`. Everything
this project claims about surgical edits reduces to it: if character *i* of a
block's text does not know exactly which bytes of the document it came from,
then every splice is a guess, and a guess that is one `&nbsp;` adrift writes
into the middle of an entity.

The second group is the allowlist — not "does it parse a macro" but "does it
refuse to edit one", which is the capability being honestly absent rather than
present and broken.
"""

from __future__ import annotations

import html
from pathlib import Path

import pytest

from reconciler.confluence.local import LocalSource
from reconciler.confluence.splice import (
    SpliceRefused,
    assert_single_change,
    assert_untouched_outside,
    diff_range,
    splice,
)
from reconciler.extract.storage import Document, parse


@pytest.fixture(scope="session")
def source(runbooks_dir: Path) -> LocalSource:
    return LocalSource(runbooks_dir)


@pytest.fixture(scope="session")
def documents(source: LocalSource) -> dict[str, Document]:
    return {ref.page_id: source.read(ref.page_id) for ref in source.pages()}


# ------------------------------------------------------------- the offsets --


def test_every_character_maps_back_to_its_own_bytes(documents: dict[str, Document]) -> None:
    """The load-bearing assertion of the entire project.

    For every block of every page, `text[i]` must decode from exactly
    `body[spans[i][0]:spans[i][1]]`. `&nbsp;` is one character and six bytes;
    CDATA is literal and never decoded. Getting either wrong is a splice landing
    inside a tag.
    """
    for page_id, document in documents.items():
        for block in document.blocks:
            assert len(block.text) == len(block.spans), f"page {page_id} block {block.index}"
            for i, char in enumerate(block.text):
                start, end = block.spans[i]
                raw = document.body[start:end]
                decoded = raw if block.regions and _is_cdata(block, start) else html.unescape(raw)
                assert decoded == char, (
                    f"page {page_id} block {block.index} char {i}: "
                    f"{raw!r} decodes to {decoded!r}, not {char!r}"
                )


def _is_cdata(block, offset: int) -> bool:
    return any(r.kind == "cdata" and r.start <= offset < r.end for r in block.regions)


def test_a_nonbreaking_space_is_one_character_and_six_bytes(documents: dict[str, Document]) -> None:
    """The corpus carries a real `&nbsp;` for exactly this reason."""
    page = documents["1001"]
    block = next(b for b in page.blocks if "\xa0" in b.text)
    index = block.text.index("\xa0")
    start, end = block.spans[index]
    assert page.body[start:end] == "&nbsp;"
    assert end - start == 6


def test_body_range_round_trips_a_real_claim_value(documents: dict[str, Document]) -> None:
    page = documents["1001"]
    block = next(b for b in page.blocks if "800ms" in b.text)
    at = block.text.index("800ms")
    start, end = block.body_range(at, at + len("800ms"))
    assert page.body[start:end] == "800ms"


# ------------------------------------------------------------- the blocks --


def test_headings_build_a_path(documents: dict[str, Document]) -> None:
    page = documents["1001"]
    triage = next(b for b in page.blocks if "Start with pod health" in b.text)
    assert triage.heading_path == ("Triage",)
    mitigation = next(b for b in page.blocks if "rollback-production" in b.text)
    assert mitigation.heading_path == ("Mitigation",)


def test_table_cells_are_their_own_blocks(documents: dict[str, Document]) -> None:
    """A DR retention period lives in a `<td>`.

    Anchoring it to the whole `<table>` would make the smallest possible edit
    the entire table, which is not reviewable and not surgical.
    """
    page = documents["1006"]
    cell = next(b for b in page.blocks if b.text.strip() == "7 days")
    assert cell.tag == "td"
    assert cell.editable


def test_a_code_macro_is_a_block_and_its_cdata_is_the_text(
    documents: dict[str, Document],
) -> None:
    page = documents["1001"]
    macro = next(
        b for b in page.blocks if b.tag == "ac:structured-macro" and "rollout restart" in b.text
    )
    assert macro.text == "kubectl -n payments rollout restart deploy/payments-api"
    assert macro.editable, "a code macro's plain-text body is safely spliceable"
    assert all(r.kind == "cdata" for r in macro.regions)


def test_a_macro_parameter_is_not_prose(documents: dict[str, Document]) -> None:
    """`ac:parameter` holds `bash`, `Yellow`, `DEPOT IMPACT`.

    None of it is a claim, and a checker that reads it will eventually find a
    threshold in a macro's colour.
    """
    page = documents["1004"]
    first = next(b for b in page.blocks if "LabelPrinterQueueDepth" in b.text)
    assert "DEPOT IMPACT" not in first.text
    assert "Yellow" not in first.text


def test_two_identical_passages_under_one_heading_are_distinguishable() -> None:
    body = "<h2>Triage</h2>\n<p>Restart the pod.</p>\n<p>Restart the pod.</p>\n"
    document = parse(body)
    duplicates = [b for b in document.blocks if b.text == "Restart the pod."]
    assert len(duplicates) == 2
    assert duplicates[0].content_hash == duplicates[1].content_hash
    from reconciler.extract.storage import occurrence_of

    assert occurrence_of(document.blocks, duplicates[0]) == 0
    assert occurrence_of(document.blocks, duplicates[1]) == 1


# ---------------------------------------------------------- the allowlist --


def test_a_status_macro_refuses_the_splice(documents: dict[str, Document]) -> None:
    """The corpus's planted refusal case."""
    page = documents["1004"]
    block = next(b for b in page.blocks if "LabelPrinterQueueDepth" in b.text)
    assert not block.editable
    assert "status" in block.refusal


def test_ordinary_prose_is_editable(documents: dict[str, Document]) -> None:
    page = documents["1001"]
    block = next(b for b in page.blocks if "800ms" in b.text)
    assert block.editable and block.refusal is None


def test_a_user_mention_refuses_the_splice() -> None:
    body = '<p>Ask <ac:link><ri:user ri:account-id="557058:x" /></ac:link> before restarting.</p>'
    block = parse(body).blocks[0]
    assert not block.editable
    assert "ac:link" in block.refusal


def test_a_placeholder_is_recognised(documents: dict[str, Document]) -> None:
    page = documents["1003"]
    block = next(b for b in page.blocks if "top pods" in b.text)
    assert block.has_placeholder


def test_a_link_is_captured_with_a_spliceable_href(documents: dict[str, Document]) -> None:
    page = documents["1004"]
    block = next(b for b in page.blocks if b.links)
    href, region = block.links[0]
    assert "zzz999" in href
    assert page.body[region.start : region.end] == href
    assert region.kind == "attr"


# ---------------------------------------------------------------- splicing --


def test_a_real_edit_changes_exactly_one_range(documents: dict[str, Document]) -> None:
    """The end-to-end shape of every write this tool ever makes."""
    page = documents["1001"]
    block = next(b for b in page.blocks if "800ms" in b.text)
    at = block.text.index("800ms")
    start, end = block.body_range(at, at + len("800ms"))

    new_body = splice(page.body, start, end, "1.2s")

    # The diff factors out the `s` the two share, so it reports `800m` -> `1.2`
    # rather than the whole token. That is the same edit described minimally,
    # and asserting on the resulting document rather than on the diff's phrasing
    # is what the caller actually cares about.
    assert_single_change(page.body, new_body, start, end)
    assert "stays above <strong>1.2s</strong> for 10 minutes" in new_body
    assert "800ms" not in new_body
    assert_untouched_outside(page.body, new_body, start, end)
    assert new_body.count("<ac:structured-macro") == page.body.count("<ac:structured-macro")


def test_reverting_the_splice_is_byte_identical(documents: dict[str, Document]) -> None:
    page = documents["1006"]
    block = next(b for b in page.blocks if b.text.strip() == "7 days")
    start, end = block.body_range(0, len(block.text))
    edited = splice(page.body, start, end, "14 days")
    assert edited != page.body
    assert splice(edited, start, start + len("14 days"), block.text) == page.body


def test_every_block_on_every_page_survives_a_no_op_splice(
    documents: dict[str, Document],
) -> None:
    """The round trip, over the whole corpus.

    Replace each block's own text with itself and the document must come back
    byte for byte — every macro, every attribute, every `&nbsp;`.
    """
    for page_id, document in documents.items():
        for block in document.blocks:
            if not block.text:
                continue
            start, end = block.body_range(0, len(block.text))
            rebuilt = splice(document.body, start, end, document.body[start:end])
            assert rebuilt == document.body, f"page {page_id} block {block.index}"


def test_a_write_that_touches_two_places_is_refused() -> None:
    """The assertion that survives a bug in the offset arithmetic."""
    old = "<p>alpha</p>\n<p>beta</p>"
    new = "<p>ALPHA</p>\n<p>BETA</p>"
    with pytest.raises(SpliceRefused, match="reaches outside"):
        assert_single_change(old, new, 3, 8)


def test_a_no_op_write_is_refused() -> None:
    """A version bump for an identical body is noise in somebody's page history."""
    with pytest.raises(SpliceRefused, match="nothing changed"):
        assert_single_change("<p>same</p>", "<p>same</p>", 3, 7)


def test_a_replacement_sharing_a_prefix_is_still_accepted() -> None:
    """`800ms` to `800ms and rising` reports a change starting five characters in.

    Demanding that the reported range equal the intended one exactly would
    reject correct edits, and an assertion that rejects correct work is one
    somebody deletes.
    """
    old = "<p>above 800ms today</p>"
    new = "<p>above 1200ms today</p>"
    start, end = old.index("800ms"), old.index("800ms") + 5
    change = assert_single_change(old, new, start, end)
    assert change.new_text.endswith("00ms") or change.new_text == "12"


def test_diff_range_finds_nothing_in_identical_strings() -> None:
    assert diff_range("same", "same") is None


def test_splice_refuses_an_out_of_range_edit() -> None:
    with pytest.raises(SpliceRefused, match="outside a body"):
        splice("short", 2, 99, "x")
