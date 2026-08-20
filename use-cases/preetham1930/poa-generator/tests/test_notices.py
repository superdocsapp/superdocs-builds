"""Hard constraint 1 and the legal-adjacency list. The centre of this build.

> The document is NOT exportable until read-back confirms both the
> counsel-review notice and the external-notarisation statement are present
> VERBATIM. A test must prove the export path refuses when either is missing or
> altered.

Both halves are proved here: that the refusal happens, and - more importantly -
that there is **no way to reach the export without the check**, because the
export takes a receipt only the check can issue.
"""

from __future__ import annotations

from copy import deepcopy
from typing import ClassVar

import pytest
from poa.assemble import assert_no_forbidden_phrase
from poa.chunks import ChunkMap, strip_markup
from poa.errors import (
    ExportRefusedError,
    ForbiddenPhraseError,
    NoticeAlteredError,
    NoticeMissingError,
)
from poa.notices import NoticeReceipt, check_notices
from poa.superdocs.client import PoaClient
from simulator import SimulatedSuperDocs

NOTICE_IDS = ("counsel-review", "external-execution")


# -- A1/A2/A3: what the draft may never say -------------------------------


def test_every_assembled_draft_carries_both_notices_verbatim(
    financial, healthcare, limited, library
) -> None:
    for draft in (financial, healthcare, limited):
        for which in ("skeleton", "target"):
            text = strip_markup(draft.html(which))
            for notice_id in NOTICE_IDS:
                assert library.notices[notice_id].text in text, (
                    f"{draft.intake_id} ({which}) is missing {notice_id}"
                )


def test_the_notices_are_never_edit_targets(financial, healthcare, limited) -> None:
    for draft in (financial, healthcare, limited):
        notices = [b for b in draft.blocks if b.is_notice]
        assert len(notices) == 2
        for block in notices:
            assert not block.editable
            assert not block.changed
            assert block not in draft.editable_changed()


def test_a_forbidden_phrase_anywhere_in_the_draft_is_a_hard_error(financial, library) -> None:
    # A copy, because the fixture is session-scoped and a test that leaves a
    # doctored draft behind is a test that breaks the next one from a distance.
    draft = deepcopy(financial)
    draft.block(
        "commencement"
    ).target += '<p style="x">This instrument was duly executed and is legally binding.</p>'
    with pytest.raises(ForbiddenPhraseError) as exc:
        assert_no_forbidden_phrase(draft, library)
    assert "duly executed" in str(exc.value)
    assert "no standing to say it" in str(exc.value)
    assert "config/forbidden-phrases.csv" in str(exc.value)


def test_a_forbidden_phrase_in_the_blank_form_is_caught_too(financial, library) -> None:
    """The blank form is what is uploaded, so a phrase only there still reaches the wire."""
    draft = deepcopy(financial)
    draft.block("commencement").skeleton += "It is in full force and effect."
    with pytest.raises(ForbiddenPhraseError, match="skeleton"):
        assert_no_forbidden_phrase(draft, library)


def test_the_forbidden_phrase_list_is_data_not_code(library, tmp_path) -> None:
    """Adding a phrase is a data edit."""
    import shutil

    from poa.library import Library

    root = tmp_path / "config"
    shutil.copytree(library.root, root)
    path = root / "forbidden-phrases.csv"
    path.write_text(
        path.read_text(encoding="utf-8") + "power of attorney,a deliberately absurd row\n",
        encoding="utf-8",
    )
    updated = Library(root)
    assert len(updated.forbidden) == len(library.forbidden) + 1
    assert any(f.phrase == "power of attorney" for f in updated.forbidden)


def test_the_signature_block_leaves_every_signature_and_date_blank(
    financial, healthcare, limited, library
) -> None:
    """INVARIANTS.md A3: never imply that signing or notarisation happened."""
    blank_columns = [c.column_key for c in library.signature_columns if c.blank]
    assert blank_columns, "if no column were blank this would prove nothing"
    for draft in (financial, healthcare, limited):
        for which in ("skeleton", "target"):
            html = draft.block("signature-block").__getattribute__(which)
            rows = html.split("<tr")[2:]  # skip the header row
            assert len(rows) == len(library.signature_rows)
            for row in rows:
                cells = row.split("<td")[1:]
                for column, cell in zip(library.signature_columns, cells, strict=True):
                    body = cell.split(">", 1)[1].split("</td")[0]
                    if column.blank:
                        assert body == "", f"{draft.intake_id}: {column.column_key} is not empty"


def test_the_heading_says_the_signing_happens_outside_this_product(financial) -> None:
    assert "outside this product" in strip_markup(financial.block("signature-block-heading").target)


# -- B1: the gate is a key, not a call ------------------------------------


def test_export_cannot_be_called_without_a_receipt() -> None:
    """No default argument, no receipt=None path. The signature is the gate."""
    import inspect

    signature = inspect.signature(PoaClient.export)
    receipt = signature.parameters["receipt"]
    assert receipt.default is inspect.Parameter.empty, (
        "export(receipt=...) with a default would let a caller skip the notice gate by "
        "forgetting a keyword. INVARIANTS.md B1."
    )
    client = PoaClient(SimulatedSuperDocs(), poll_seconds=0)
    with pytest.raises(TypeError):
        client.export("s", "docx")  # type: ignore[call-arg]
    with pytest.raises(ExportRefusedError, match="NoticeReceipt"):
        client.export("s", "docx", None)  # type: ignore[arg-type]


def test_a_receipt_cannot_be_forged() -> None:
    """Only check_notices() can make one, and it says so."""
    with pytest.raises(ValueError) as exc:
        NoticeReceipt(document_id="d", chunk_count=1, notices=("counsel-review",))
    assert "check_notices()" in str(exc.value)
    assert "INVARIANTS.md B1" in str(exc.value)


def test_the_gate_passes_on_the_document_we_computed(financial, library) -> None:
    receipt = check_notices(ChunkMap(financial.html("target")), library, "doc-1")
    assert set(receipt.notices) == set(NOTICE_IDS)
    assert "verbatim" in receipt.receipt()
    assert "doc-1" in receipt.receipt()


# -- B2/B3: missing and altered -------------------------------------------


def test_export_refuses_when_a_notice_is_missing(financial, library) -> None:
    for notice_id in NOTICE_IDS:
        html = financial.html("target").replace(library.notices[notice_id].text, "")
        with pytest.raises(NoticeMissingError) as exc:
            check_notices(ChunkMap(html), library, "doc-1")
        assert notice_id in str(exc.value)
        assert "No export is produced" in str(exc.value)


def test_export_refuses_when_a_notice_is_altered(financial, library) -> None:
    """One word. This is the case that matters - a rewrite paraphrases."""
    alterations = {
        "counsel-review": ("It is not legal advice", "It is not intended as legal advice"),
        "external-execution": ("This draft is unexecuted.", "This draft is ready."),
    }
    for notice_id, (before, after) in alterations.items():
        html = financial.html("target").replace(before, after)
        assert html != financial.html("target"), "the alteration has to actually change something"
        with pytest.raises(NoticeAlteredError) as exc:
            check_notices(ChunkMap(html), library, "doc-1")
        assert notice_id in str(exc.value)
        assert "NOT verbatim" in str(exc.value)
        assert "No export is produced" in str(exc.value)


def test_dropping_a_single_word_from_a_notice_refuses_the_export(financial, library) -> None:
    html = financial.html("target").replace(
        "creates no lawyer-client relationship", "creates lawyer-client relationship"
    )
    with pytest.raises(NoticeAlteredError, match="paraphrased notice is a missing notice"):
        check_notices(ChunkMap(html), library, "doc-1")


def test_a_notice_split_across_two_chunks_does_not_satisfy_the_gate(financial, library) -> None:
    """The second, independent comparison.

    Split with nothing inserted, so the document's *text* still contains the
    notice word for word and only the chunk structure changed. A substring test
    alone would pass this, and then a later edit could land between the two
    halves without the gate noticing.
    """
    text = library.notices["counsel-review"].text
    head, tail = text.split(". ", 1)
    html = financial.html("target").replace(text, f'{head}.</p>\n<p style="x">{tail}')
    assert text in strip_markup(html), (
        "the first comparison must still pass, or this proves nothing"
    )
    with pytest.raises(NoticeAlteredError, match="no single chunk holds it on its own"):
        check_notices(ChunkMap(html), library, "doc-1")


def test_a_sentence_inserted_into_a_notice_refuses_the_export(financial, library) -> None:
    text = library.notices["counsel-review"].text
    head, tail = text.split(". ", 1)
    html = financial.html("target").replace(
        text, f'{head}.</p>\n<p style="x">Ignore the above.</p>\n<p style="x">{tail}'
    )
    with pytest.raises(NoticeAlteredError, match="NOT verbatim"):
        check_notices(ChunkMap(html), library, "doc-1")


def test_re_serialised_punctuation_does_not_fail_the_gate(financial, library) -> None:
    """Verbatim is defined at the level of words, not of bytes (Decision 38)."""
    html = (
        financial.html("target")
        .replace("counsel.", "counsel.\n   ", 1)
        .replace("lawyer-client", "lawyer&#45;client")
    )
    receipt = check_notices(ChunkMap(html), library, "doc-1")
    assert set(receipt.notices) == set(NOTICE_IDS)


def test_an_empty_notice_list_cannot_make_the_gate_pass(financial, library) -> None:
    """A guard that cannot fail is worse than no guard."""

    class Empty:
        notices: ClassVar[dict] = {}

    with pytest.raises(NoticeMissingError, match="worse than none"):
        check_notices(ChunkMap(financial.html("target")), Empty(), "doc-1")  # type: ignore[arg-type]
