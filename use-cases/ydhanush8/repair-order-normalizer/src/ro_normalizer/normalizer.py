"""Turn a technician note into a complaint / cause / correction narrative.

The whole design follows from one rule: **nothing may appear in the output that
the technician did not write.** So the narrative is assembled from verbatim spans
of the note rather than rewritten. Sentences are classified, not paraphrased.

That costs some polish — the output reads like a tidied note, not like prose —
and it buys the only property that matters for a warranty claim. A plausible
invented correction is worse than an empty one: the empty one goes back to the
technician, the invented one becomes a false claim.

Where a required element is absent, the output says so and stops.
"""

from __future__ import annotations

import re

from ro_normalizer.schemas import (
    Confidence,
    Element,
    ElementResult,
    Evidence,
    NormalizedOrder,
    RepairOrder,
    Warning,
)

# --- what a sentence is ------------------------------------------------------

_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?", re.MULTILINE)

# --- signals -----------------------------------------------------------------
# Deliberately explicit. A warranty administrator can read this table and predict
# what the tool will do, which matters more here than breadth.

COMPLAINT_SIGNALS = (
    "cust states", "customer states", "c/s", "cust reports", "customer reports",
    "complains of", "concern:", "reported", "states that", "customer concern",
)

CAUSE_SIGNALS = (
    "found", "fnd", "diagnosed", "traced to", "cause", "due to", "determined",
    "inspected", "tested", "test showed", "smoke test", "smk tst", "stuck",
    "leak at", "worn", "damaged", "failed", "open circuit", "short",
    "carbon tracking", "unable to duplicate", "no codes stored", "within spec",
)

CORRECTION_SIGNALS = (
    "replaced", "repl", "repaired", "installed", "cleaned", "adjusted",
    "tightened", "torqued", "reprogrammed", "flashed",
    "cleared code", "clr code", "topped up", "refilled",
    "road tested", "rt ok", "retested", "verified",
)

# Work that was proposed rather than performed. These are NOT corrections, and
# reading them as one is the invention this tool exists to prevent: RO-1004
# ordered a part and repaired nothing; RO-1011's customer declined the repair.
NOT_PERFORMED_SIGNALS = (
    "parts on order", "part on order", "recommend", "recommended",
    "customer declined", "cust declined", "declined repair", "quoted",
    "pending approval", "awaiting parts", "will return",
)

# A diagnosis that found nothing is still a documented diagnosis, but the order
# needs a human: there is no fault to claim against.
NO_FAULT_SIGNALS = (
    "unable to duplicate", "could not duplicate", "no fault found",
    "no codes stored", "operating as designed", "within spec",
)

# Verification is tracked separately: it is a claim about outcome, not about
# work performed, and inventing one is the failure mode this domain punishes.
VERIFICATION_SIGNALS = (
    "road tested", "rt ok", "retested", "verified", "no misfire", "cel off",
    "mil off", "light off", "clunk gone", "confirmed",
)

_INJECTION = re.compile(
    r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?"
    r"|disregard\s+(?:all\s+)?(?:previous|prior)"
    r"|do\s+not\s+mention"
    r"|write\s+that\s+the"
    r"|system\s+(?:prompt|message|override)"
    r"|you\s+are\s+now",
    re.IGNORECASE,
)

_MEASUREMENT = re.compile(
    r"\b\d+(?:\.\d+)?\s*"
    r"(?:mm|cm|in|inch|inches|nm|ft-?lbs?|lbs?|psi|bar|kpa|"
    r"v|volts?|mv|a|amps?|ohms?|k?ohms?|"
    r"c|f|deg|degrees?|°c|°f|"
    r"rpm|km|miles?|mi|hrs?|hours?|minutes?|min|%|percent)\b",
    re.IGNORECASE,
)

MISSING = {
    Element.COMPLAINT: "MISSING — no customer complaint or reported symptom is documented in the technician note.",
    Element.CAUSE: "MISSING — no cause or diagnostic finding is documented in the technician note.",
    Element.CORRECTION: "MISSING — no correction or repair is documented in the technician note.",
}


class Sentence:
    __slots__ = ("text", "start", "end", "lower")

    def __init__(self, text: str, start: int, end: int) -> None:
        self.text = text
        self.start = start
        self.end = end
        self.lower = text.lower()

    def evidence(self) -> Evidence:
        return Evidence(text=self.text, start=self.start, end=self.end)


def _sentences(note: str) -> list[Sentence]:
    out: list[Sentence] = []
    for match in _SENTENCE.finditer(note):
        raw = match.group(0)
        stripped = raw.strip()
        if not stripped:
            continue
        start = match.start() + (len(raw) - len(raw.lstrip()))
        out.append(Sentence(stripped, start, start + len(stripped)))
    return out


def _matches(sentence: Sentence, signals: tuple[str, ...]) -> bool:
    return any(signal in sentence.lower for signal in signals)


def _classify(sentence: Sentence) -> Element | None:
    """First match wins, in the order a repair actually happens.

    A sentence naming both a finding and a repair is a correction: "found and
    replaced the coil" is work done, and the finding is already implied by the
    cause sentences around it.
    """
    if _matches(sentence, COMPLAINT_SIGNALS):
        return Element.COMPLAINT
    # Checked before the correction signals: "recommend replacement" contains
    # "replacement", and proposing work is not doing it.
    if _matches(sentence, NOT_PERFORMED_SIGNALS):
        return None
    if _matches(sentence, CORRECTION_SIGNALS):
        return Element.CORRECTION
    if _matches(sentence, CAUSE_SIGNALS):
        return Element.CAUSE
    return None


def _assemble(element: Element, sentences: list[Sentence]) -> ElementResult:
    if not sentences:
        return ElementResult(
            element=element,
            supported=False,
            text=MISSING[element],
            evidence=[],
            reason="nothing in the note documents this element",
        )

    # Verbatim, joined. Not rewritten, not summarised, not smoothed.
    text = " ".join(sentence.text.rstrip(".") + "." for sentence in sentences)
    return ElementResult(
        element=element,
        supported=True,
        text=text,
        evidence=[sentence.evidence() for sentence in sentences],
    )


def _score(
    grouped: dict[Element, list[Sentence]],
    warnings: list[Warning],
    verified: bool,
) -> tuple[Confidence, list[str]]:
    """Confidence is evidence completeness, not a model's opinion of itself."""
    present = [element for element in Element if grouped[element]]
    missing = [element for element in Element if not grouped[element]]
    reasons: list[str] = []

    if missing:
        reasons.append(
            f"{len(missing)} required element(s) not documented: "
            + ", ".join(element.value for element in missing)
        )
    contradictions = [w for w in warnings if w.code == "possible_contradiction"]
    if contradictions:
        reasons.append(f"{len(contradictions)} possible contradiction(s) in the note")

    if len(missing) >= 2:
        level = Confidence.LOW
    elif missing or contradictions:
        level = Confidence.MEDIUM
    else:
        level = Confidence.HIGH

    if level is Confidence.HIGH and not verified:
        level = Confidence.MEDIUM
        reasons.append("no verification of the repair is documented")

    if not reasons:
        reasons.append("complaint, cause and correction are all documented and verified")
    if present and not missing:
        reasons.insert(0, "all three required elements are documented")

    return level, reasons


def _contradictions(sentences: list[Sentence]) -> list[Warning]:
    """Report, never resolve. Which statement is right is the shop's call."""
    warnings: list[Warning] = []
    text = " ".join(s.lower for s in sentences)

    pairs = [
        ("no leak found", "leak", "the note reports both a leak and no leak found"),
        ("unable to duplicate", "found", "the note says the concern could not be duplicated but also reports a finding"),
        ("cel returned", "cel off", "the note reports the light both returning and off"),
        ("mil returned", "mil off", "the note reports the light both returning and off"),
    ]
    for first, second, message in pairs:
        if first in text and second in text:
            evidence = [s.evidence() for s in sentences if first in s.lower or second in s.lower]
            warnings.append(
                Warning(code="possible_contradiction", message=message, evidence=evidence[:4])
            )
    return warnings


def normalize(order: RepairOrder) -> NormalizedOrder:
    note = order.technician_note
    sentences = _sentences(note)

    warnings: list[Warning] = []
    usable: list[Sentence] = []

    for sentence in sentences:
        if _INJECTION.search(sentence.text):
            # Quarantined, not merely detected. A sentence that tries to dictate
            # the narrative does not get to contribute to it — this note asks for
            # a replacement the customer declined.
            warnings.append(
                Warning(
                    code="instruction_like_content",
                    message=(
                        "The note contains text addressed to the system rather than describing "
                        "the repair. It was excluded from the narrative and is reported here."
                    ),
                    evidence=[sentence.evidence()],
                )
            )
            continue
        usable.append(sentence)

    grouped: dict[Element, list[Sentence]] = {element: [] for element in Element}
    unplaced: list[Sentence] = []
    for sentence in usable:
        element = _classify(sentence)
        if element is not None:
            grouped[element].append(sentence)
        else:
            unplaced.append(sentence)

    warnings.extend(_contradictions(usable))

    proposed = [s for s in usable if _matches(s, NOT_PERFORMED_SIGNALS)]
    if proposed:
        warnings.append(
            Warning(
                code="work_not_performed",
                message=(
                    "The note describes work that was proposed, ordered or declined rather than "
                    "carried out. It is not recorded as a correction."
                ),
                evidence=[s.evidence() for s in proposed[:4]],
            )
        )

    no_fault = [s for s in usable if _matches(s, NO_FAULT_SIGNALS)]
    if no_fault:
        warnings.append(
            Warning(
                code="no_fault_found",
                message=(
                    "The note reports that no fault was found or the concern could not be "
                    "duplicated. There may be nothing to claim against."
                ),
                evidence=[s.evidence() for s in no_fault[:4]],
            )
        )

    verified = any(_matches(s, VERIFICATION_SIGNALS) for s in grouped[Element.CORRECTION])
    if grouped[Element.CORRECTION] and not verified:
        warnings.append(
            Warning(
                code="no_verification",
                message=(
                    "A repair is documented but no verification of the result is. "
                    "Replacing a part is not evidence that the concern was resolved."
                ),
            )
        )

    if unplaced:
        warnings.append(
            Warning(
                code="content_not_placed",
                message=(
                    "Part of the note does not belong to any required element and was left out "
                    "of the narrative rather than forced into one. It is preserved here."
                ),
                evidence=[sentence.evidence() for sentence in unplaced],
            )
        )

    measurements = [m.group(0).strip() for m in _MEASUREMENT.finditer(note)]
    confidence, reasons = _score(grouped, warnings, verified)

    return NormalizedOrder(
        repair_order_id=order.repair_order_id,
        complaint=_assemble(Element.COMPLAINT, grouped[Element.COMPLAINT]),
        cause=_assemble(Element.CAUSE, grouped[Element.CAUSE]),
        correction=_assemble(Element.CORRECTION, grouped[Element.CORRECTION]),
        dtc_codes=list(order.dtc_codes),
        measurements=measurements,
        unplaced=[sentence.evidence() for sentence in unplaced],
        missing_elements=[element for element in Element if not grouped[element]],
        warnings=warnings,
        confidence=confidence,
        confidence_reasons=reasons,
    )
