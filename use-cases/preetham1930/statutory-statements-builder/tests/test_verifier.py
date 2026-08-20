"""The three failure classes, each driven by a response the product actually gave.

Nothing here is hand-written HTML. `read0`..`read3` are four recorded
`GET /v1/documents/{id}?include_html=true` bodies from 2026-08-09:

- read0 -> read1  a single-value targeted edit that worked
- read1 -> read2  a mid-document insertion that silently did not happen, while
                  five heading chunks nobody targeted were rewritten around it
- read2 -> read3  one `create` that appended six sections, four of them invented

So the verifier is tested against the real shapes of the real failures.
"""

from __future__ import annotations

from recorded import read_back_html
from statutory.chunks import ChunkMap
from statutory.superdocs.verifier import verify, verify_upload_verbatim

TARGET = "8ec79daa-5de5-4973-84a5-1d1139da29be"


def _maps(*names: str) -> list[ChunkMap]:
    return [ChunkMap(read_back_html(name)) for name in names]


def test_a_clean_single_target_replacement_verifies() -> None:
    before, after = _maps("read0-baseline", "read1-after-A")
    expected = after.by_id[TARGET].html
    result = verify(1, TARGET, before, after, expected)
    assert result.ok
    assert "matches the computed post-state" in result.receipt
    assert "17 non-target chunk(s) unchanged" in result.receipt
    assert result.exact_bytes


def test_a_reply_claiming_success_does_not_make_a_step_ok() -> None:
    """The chat reply for the failing turn read 'nothing actually changed'.

    Five changes had been auto-approved and were in the document. The verifier
    never sees a reply, so it cannot be wrong in either direction.
    """
    before, after = _maps("read1-after-A", "read2-after-B")
    result = verify(2, TARGET, before, after, before.by_id[TARGET].html + "<!--x-->")
    assert not result.ok
    kinds = {p.kind for p in result.problems}
    assert "not_applied" in kinds, "the target chunk came back untouched"
    assert "collateral_damage" in kinds, "five heading chunks moved"
    detail = next(p for p in result.problems if p.kind == "collateral_damage").detail
    assert "5 chunk(s) we did not target changed" in detail


def test_collateral_damage_is_caught_when_the_requested_change_also_succeeded() -> None:
    """The dangerous one: the append worked *and* four fabricated sections arrived.

    A verifier checking only its own target would report success here.
    """
    before, after = _maps("read2-after-B", "read3-after-C")
    # Pretend our step targeted a chunk in the document; the requested append
    # also succeeded, which is exactly what makes this class dangerous.
    changed = before.ids[0]
    result = verify(3, changed, before, after, after.by_id[changed].html)
    assert not result.ok
    problem = next(p for p in result.problems if p.kind == "collateral_damage")
    assert "the chunk set changed" in problem.detail
    assert "18 chunk(s) before, 19 after" in problem.detail
    assert "Quality Assurance" in problem.diff or "Humidity" in problem.diff


def test_applied_wrong_is_its_own_class() -> None:
    before, after = _maps("read0-baseline", "read1-after-A")
    expected = after.by_id[TARGET].html.replace("750", "751")
    result = verify(4, TARGET, before, after, expected)
    assert not result.ok
    assert [p.kind for p in result.problems] == ["applied_wrong"]
    assert "751" in result.problems[0].diff


def test_a_missing_target_chunk_is_not_applied_rather_than_a_crash() -> None:
    before, after = _maps("read0-baseline", "read1-after-A")
    result = verify(5, "no-such-chunk", before, after, "<p>x</p>")
    assert not result.ok
    assert any(p.kind == "not_applied" for p in result.problems)


def test_the_upload_is_checked_verbatim_rather_than_assumed() -> None:
    """Decision 29 rests on a measured property, so it is re-measured every run."""
    uploaded = ChunkMap(read_back_html("read0-baseline"))
    blocks = [chunk.html for chunk in uploaded.chunks]
    receipt = verify_upload_verbatim(uploaded, blocks)
    assert "18 chunk(s)" in receipt

    tampered = list(blocks)
    tampered[3] = tampered[3].replace("</p>", " and one more sentence.</p>")
    try:
        verify_upload_verbatim(uploaded, tampered)
    except AssertionError as exc:
        assert "was not verbatim" in str(exc)
        assert "first difference at block 3" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a non-verbatim upload must stop the run")
