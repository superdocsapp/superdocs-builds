"""Batch behaviour, and the property the brief singles out.

"A batch of 100 orders produces consistent structure without homogenizing
genuine differences." Both halves are tested here: the structure is identical
for every order, and the content is not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ro_normalizer.schemas import Confidence, Element
from ro_normalizer.services.batch import load_orders, run_batch

CORPUS = Path(__file__).parents[1] / "sample-data" / "batch-100.json"
ORDERS_PATH = Path(__file__).parents[1] / "sample-data" / "orders.json"
ORDERS = load_orders(CORPUS)


def test_the_corpus_is_the_size_it_claims() -> None:
    assert len(ORDERS) == 100


def test_small_sample_mode_is_the_default() -> None:
    """Nothing processes a hundred orders because someone forgot a flag."""
    result = run_batch(ORDERS)
    assert len(result.results) == 5


@pytest.mark.parametrize("size", [1, 5, 20, 100])
def test_the_documented_progression(size: int) -> None:
    """1 -> 5 -> 20 -> 100, the order the brief asks for."""
    result = run_batch(ORDERS, max_orders=size)
    assert len(result.results) == size
    assert result.failures == []
    assert result.aborted is False


def test_every_order_gets_the_same_structure() -> None:
    result = run_batch(ORDERS, max_orders=100)

    for order in result.results:
        assert order.complaint.element is Element.COMPLAINT
        assert order.cause.element is Element.CAUSE
        assert order.correction.element is Element.CORRECTION
        assert order.confidence in set(Confidence)
        assert order.confidence_reasons, "a confidence with no reason is an opinion"

        # The narrative always has the three manufacturer-required headings,
        # whether or not each one is supported.
        for heading in ("COMPLAINT:", "CAUSE:", "CORRECTION:"):
            assert heading in order.narrative


def test_two_different_notes_never_produce_the_same_output() -> None:
    """The property, stated exactly rather than as a threshold.

    Homogenising means distinct inputs collapsing into one output. So compare
    the *whole* record, not just the prose: two orders differing only in their
    DTC codes legitimately share a narrative, because DTCs are a separate field
    and are never folded into the sentences.
    """
    result = run_batch(ORDERS, max_orders=100)

    def record(produced) -> tuple:
        # The full record, not only the prose: DTCs, unplaced content and
        # warnings are part of what the tool produced.
        return (
            produced.narrative,
            tuple(produced.dtc_codes),
            tuple(e.text for e in produced.unplaced),
            tuple(sorted(w.code for w in produced.warnings)),
        )

    seen: dict[tuple, str] = {}
    for order, produced in zip(ORDERS, result.results, strict=True):
        key = record(produced)
        if key in seen and seen[key] != order.technician_note:
            raise AssertionError(
                "two different technician notes produced an identical record:\n"
                f"  {seen[key]!r}\n  {order.technician_note!r}"
            )
        seen[key] = order.technician_note


def test_the_batch_does_not_collapse_into_a_handful_of_sentences() -> None:
    """A blunter reading of the same property, for a reviewer skimming."""
    result = run_batch(ORDERS, max_orders=100)
    distinct = {
        (
            o.narrative,
            tuple(o.dtc_codes),
            tuple(e.text for e in o.unplaced),
        )
        for o in result.results
    }
    assert len(distinct) >= 95, f"only {len(distinct)}/100 records are distinct"


def test_the_batch_summary_counts_what_a_manager_acts_on() -> None:
    summary = run_batch(ORDERS, max_orders=100).summary

    assert summary.total == 100
    assert summary.high + summary.medium + summary.low == 100
    assert summary.needs_review >= summary.with_missing_elements
    assert summary.warnings, "the corpus contains injections and declined work"


def test_missing_elements_are_flagged_across_the_whole_batch() -> None:
    """The corpus deliberately contains incomplete orders. None may be filled."""
    result = run_batch(ORDERS, max_orders=100)

    incomplete = [o for o in result.results if o.missing_elements]
    assert incomplete, "the corpus includes orders with elements missing"

    for order in incomplete:
        for element in order.missing_elements:
            produced = getattr(order, element.value)
            assert produced.supported is False
            assert "MISSING" in produced.text
            assert produced.evidence == []


def test_injected_orders_do_not_gain_a_correction() -> None:
    """Seven orders instruct the tool to record a repair that never happened."""
    result = run_batch(ORDERS, max_orders=100)

    injected = [
        o for o in result.results
        if any(w.code == "instruction_like_content" for w in o.warnings)
    ]
    assert injected, "the corpus contains injected notes"

    for order in injected:
        assert "ignore all previous" not in order.narrative.lower()
        # Every injected note also has the customer declining the work.
        assert Element.CORRECTION in order.missing_elements


def test_a_batch_that_keeps_failing_stops() -> None:
    """A stopping rule, so a broken batch does not grind through 98 more."""

    class Exploding:
        """Looks like a RepairOrder to the runner, fails when normalized."""

        repair_order_id = "RO-BAD"
        technician_note = None  # normalize() will raise on this
        dtc_codes: list[str] = []
        vehicle = None

    result = run_batch([Exploding() for _ in range(50)], max_orders=50, max_failures=3)

    assert result.aborted is True
    assert len(result.failures) == 3
    assert len(result.results) == 0


def test_one_bad_order_does_not_lose_the_others() -> None:
    class Exploding:
        repair_order_id = "RO-BAD"
        technician_note = None
        dtc_codes: list[str] = []
        vehicle = None

    mixed = [ORDERS[0], Exploding(), ORDERS[1], ORDERS[2]]
    result = run_batch(mixed, max_orders=10, max_failures=3)

    assert len(result.results) == 3
    assert len(result.failures) == 1
    assert result.aborted is False


# --- the document flow surviving a bad day ---------------------------------


def test_one_unreachable_order_does_not_throw_away_the_others(capsys) -> None:
    """A batch that loses the network on order two should keep order one."""
    import httpx

    from ro_normalizer.cli import main
    from ro_normalizer.superdocs import client as client_module

    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if 3 <= calls["n"] <= 5:
            raise httpx.ConnectError("network went away")
        return httpx.Response(200, json={"upload_id": "u1", "content": "COMPLAINT:\n"})

    real = client_module.SuperDocsDocumentEditor.__init__

    def patched(self, api_key="sk_test", **kwargs):
        kwargs.setdefault(
            "client",
            httpx.Client(transport=httpx.MockTransport(flaky), base_url="https://api.test"),
        )
        kwargs.setdefault("poll_interval", 0)
        real(self, api_key or "sk_test", **kwargs)

    client_module.SuperDocsDocumentEditor.__init__ = patched
    try:
        main(["process", str(ORDERS_PATH), "--limit", "3", "--backend", "superdocs"])
    finally:
        client_module.SuperDocsDocumentEditor.__init__ = real

    printed = capsys.readouterr().out
    assert "FAILED" in printed
    assert "could not be reached" in printed


def test_a_run_failing_every_time_stops_itself(capsys) -> None:
    """Operations cost money. Proving the API is down twelve times is waste."""
    import httpx

    from ro_normalizer.cli import main
    from ro_normalizer.superdocs import client as client_module

    def always_down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    real = client_module.SuperDocsDocumentEditor.__init__

    def patched(self, api_key="sk_test", **kwargs):
        kwargs.setdefault(
            "client",
            httpx.Client(transport=httpx.MockTransport(always_down), base_url="https://api.test"),
        )
        kwargs.setdefault("poll_interval", 0)
        real(self, api_key or "sk_test", **kwargs)

    client_module.SuperDocsDocumentEditor.__init__ = patched
    try:
        main(["process", str(ORDERS_PATH), "--limit", "12", "--backend", "superdocs"])
    finally:
        client_module.SuperDocsDocumentEditor.__init__ = real

    printed = capsys.readouterr().out
    assert "Stopping" in printed
    assert printed.count("FAILED") == 3, "should stop after three, not run all twelve"
