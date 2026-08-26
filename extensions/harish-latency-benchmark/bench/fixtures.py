"""
Synthetic plain-text documents at three declared size tiers. Uses only
generated/fictional content -- no real third-party data, per the task
document's "invent clients and data" instruction.
"""
from __future__ import annotations

SIZE_TIERS = {
    "small": 300,
    "medium": 3000,
    "large": 15000,
}

_PARAGRAPH = (
    "This Section governs the obligations of each party with respect to "
    "confidential information, deliverables, timelines, and remedies "
    "available upon breach. Each party shall act in good faith and in "
    "accordance with the standards customary in the industry. "
)


def make_synthetic_doc(tier: str) -> str:
    if tier not in SIZE_TIERS:
        raise ValueError(f"unknown tier {tier!r}, expected one of {list(SIZE_TIERS)}")
    target_words = SIZE_TIERS[tier]
    words_per_para = len(_PARAGRAPH.split())
    n_paragraphs = max(1, target_words // words_per_para)

    lines = [f"# Synthetic Agreement -- {tier.upper()} tier\n"]
    section_every = 8
    for i in range(n_paragraphs):
        if i % section_every == 0:
            lines.append(f"\n## Section {i // section_every + 1}\n")
        lines.append(_PARAGRAPH)
    return "".join(lines)


def doc_bytes(tier: str) -> bytes:
    return make_synthetic_doc(tier).encode("utf-8")
