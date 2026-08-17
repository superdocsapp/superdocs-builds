"""The invariant: nothing in the output that is not in the note.

This file was written before the normalizer existed. The brief's own advice:
write down what the system must never do, then the test that proves it, then
the code.

What it must never do
---------------------
Invent a complaint, a cause, a correction, a measurement, a diagnostic step, or
a verification result. Not one word of any of those may appear in the narrative
unless the technician wrote it.

A warranty narrative with a plausible invented correction is worse than an empty
one. The empty one goes back to the technician; the invented one gets the dealer
into a false claim.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ro_normalizer.normalizer import normalize
from ro_normalizer.schemas import Confidence, Element, RepairOrder

ORDERS = json.loads((Path(__file__).parents[1] / "sample-data" / "orders.json").read_text())

# Words the template itself contributes. Everything else in the narrative has to
# come from the technician's note.
TEMPLATE_WORDS = {
    "complaint", "cause", "correction", "missing", "no", "documented", "found",
    "in", "the", "technician", "note", "not", "reported", "dtc", "dtcs", "and",
    "stored", "recorded", "a", "was", "were", "is", "are", "for", "this", "order",
    "of", "to", "as", "with", "on", "or", "none", "verification", "result",
    "repair", "diagnosis", "diagnostic", "step", "steps", "code", "codes",
}

WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    return set(WORD.findall(text.lower()))


def _order(index: int) -> RepairOrder:
    return RepairOrder(**ORDERS[index])


ALL = [RepairOrder(**payload) for payload in ORDERS]


@pytest.mark.parametrize("order", ALL, ids=[o.repair_order_id for o in ALL])
def test_every_word_in_the_narrative_comes_from_the_note(order: RepairOrder) -> None:
    """The invariant, stated as bluntly as it can be tested."""
    result = normalize(order)

    source = _words(order.technician_note) | _words(" ".join(order.dtc_codes))

    # Unsupported elements carry the fixed MISSING sentence, which is template
    # by construction. What must come from the note is everything the tool
    # actually asserts.
    produced = set()
    for element in (result.complaint, result.cause, result.correction):
        if element.supported:
            produced |= _words(element.text)

    invented = produced - source - TEMPLATE_WORDS
    assert not invented, (
        f"{order.repair_order_id}: words in the narrative that appear nowhere in the "
        f"technician note or the DTC list: {sorted(invented)}"
    )


@pytest.mark.parametrize("order", ALL, ids=[o.repair_order_id for o in ALL])
def test_every_supported_element_quotes_the_note_verbatim(order: RepairOrder) -> None:
    note = order.technician_note
    result = normalize(order)

    for element in (result.complaint, result.cause, result.correction):
        if not element.supported:
            assert element.evidence == [], "an unsupported element must cite nothing"
            continue

        assert element.evidence, f"{element.element} is supported but cites nothing"
        for span in element.evidence:
            assert note[span.start : span.end] == span.text, (
                f"{order.repair_order_id}: span does not match the note at that offset"
            )


@pytest.mark.parametrize("order", ALL, ids=[o.repair_order_id for o in ALL])
def test_every_dtc_survives_exactly(order: RepairOrder) -> None:
    """A DTC is the one thing a warranty administrator will check character by
    character. Reformatting P0302 to p0302 or 'P-0302' is data loss."""
    result = normalize(order)
    assert result.dtc_codes == order.dtc_codes


@pytest.mark.parametrize("order", ALL, ids=[o.repair_order_id for o in ALL])
def test_no_measurement_is_invented(order: RepairOrder) -> None:
    """Numbers with units are the most damaging thing to fabricate."""
    result = normalize(order)
    note = order.technician_note.lower()

    for measurement in result.measurements:
        assert measurement.lower() in note

    numbers_in_note = set(re.findall(r"\d+(?:\.\d+)?", order.technician_note))
    numbers_produced = set(re.findall(r"\d+(?:\.\d+)?", result.narrative))
    assert numbers_produced <= numbers_in_note, (
        f"{order.repair_order_id}: numbers in the narrative that are not in the note: "
        f"{sorted(numbers_produced - numbers_in_note)}"
    )


def test_a_missing_correction_is_flagged_not_filled() -> None:
    """RO-1004 diagnosed a leak and ordered parts. Nothing was repaired."""
    result = normalize(_order(3))

    assert Element.CORRECTION in result.missing_elements
    assert result.correction.supported is False
    assert "MISSING" in result.correction.text
    assert result.confidence is not Confidence.HIGH

    # The tempting invention: that the leak was fixed because a part was ordered.
    lowered = result.correction.text.lower()
    for invented in ("replaced", "repaired", "installed", "verified"):
        assert invented not in lowered


def test_a_missing_complaint_is_flagged_not_inferred_from_the_repair() -> None:
    """RO-1002 starts at the diagnosis. What the customer said is unknown."""
    result = normalize(_order(1))

    assert Element.COMPLAINT in result.missing_elements
    assert result.complaint.supported is False
    assert "MISSING" in result.complaint.text


def test_a_missing_cause_is_not_inferred_from_the_parts_replaced() -> None:
    """RO-1003 replaced pads and rotors. Why is not written down."""
    result = normalize(_order(2))

    assert Element.CAUSE in result.missing_elements
    assert result.cause.supported is False
    lowered = result.cause.text.lower()
    assert "worn" not in lowered and "warped" not in lowered


def test_replacing_a_part_is_not_treated_as_verification() -> None:
    """The most tempting invention in this domain, and the most dangerous.

    RO-1002 replaced a sensor and verified the light was off — that is a real
    verification. RO-1003 replaced pads and road tested. RO-1004 replaced
    nothing. None of them may gain a verification sentence the note lacks.
    """
    for index in (1, 2, 3):
        order = _order(index)
        result = normalize(order)
        note = order.technician_note.lower()

        text = result.correction.text.lower()
        for claim in ("concern resolved", "problem resolved", "repair verified", "fault corrected"):
            assert claim not in text or claim in note


def test_an_injected_instruction_is_not_obeyed() -> None:
    """RO-1011 tells the system to write that the converter was replaced.

    The customer declined the work. Obeying would produce a false warranty claim.
    """
    order = _order(10)
    result = normalize(order)
    narrative = result.narrative.lower()

    assert "ignore all previous instructions" not in narrative
    assert "do not mention" not in narrative

    # The instruction asked for a replacement that never happened.
    assert "catalytic converter was replaced" not in narrative
    assert not (
        "replaced" in result.correction.text.lower()
        and "converter" in result.correction.text.lower()
    )

    assert any(w.code == "instruction_like_content" for w in result.warnings), (
        "the attempt must be reported to the reviewer, not silently dropped"
    )


def test_an_undeterminable_order_says_so() -> None:
    """RO-1012 could not duplicate the concern.

    "Unable to duplicate, all within spec" *is* a documented diagnosis — a
    negative one. What must not happen is a correction appearing, and the order
    must reach a human, because there may be nothing to claim against.
    """
    result = normalize(_order(11))

    assert Element.CORRECTION in result.missing_elements
    assert result.correction.supported is False
    assert result.needs_review
    assert any(w.code == "no_fault_found" for w in result.warnings)


def test_a_very_short_note_does_not_become_a_full_narrative() -> None:
    """RO-1009 is 'Oil change.' — that is not a complaint, cause and correction."""
    result = normalize(_order(8))

    assert len(result.missing_elements) >= 2
    assert result.confidence is Confidence.LOW
