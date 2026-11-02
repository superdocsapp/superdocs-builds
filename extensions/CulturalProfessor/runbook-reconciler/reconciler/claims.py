"""What a document asserts, where it says it, and what we concluded about it.

Three types, and the relationships between them are the whole data model:

- `Anchor` — how to find a passage again in a document that has moved on.
- `Claim` — one checkable assertion, anchored.
- `Finding` — the verdict on a claim, or on the estate as a whole.

## Why `claim_id` is built the way it is

`claim_id = sha256(page_id | kind | subject | anchor_hash)`, and `anchor_hash`
is built from the heading path, a hash of the passage text, and an occurrence
index — *not* from the node's position in the document.

Position was the obvious choice and it is wrong. Insert an unrelated paragraph
near the top of a page and every claim below it shifts index, gets a new
`claim_id`, and is re-proposed as if it were new — a page nobody touched
generates a queue of duplicates because somebody fixed a typo three headings up.

Text is in the hash on purpose, and it has the consequence you would want: once
an approved fix lands, the passage says something different, so the old claim
ceases to exist and a new one appears that agrees with ground truth. An applied
finding cannot be re-proposed because the claim it belonged to is gone. That is
rule 6 falling out of the identity scheme rather than being enforced by a flag
somebody has to remember to set.

The occurrence index exists because two identical sentences under one heading
are two passages that each need fixing. Without it they collide onto one
`claim_id` and the second one is silently never repaired.

`value_occurrence` is the same argument one level down, and the level it was
missing at. A paragraph reading "latency stays above 800ms … the secondary page
also uses 800ms" makes the claim twice, in one block, under one heading — same
subject, same text hash, same occurrence, therefore one `claim_id`. The
extractor deduplicated them, the reviewer saw one finding, the splice took
`str.find` and corrected the first, and the second stayed wrong on a page the
tool had just reported as fixed. Counting how many times the value already
appeared in the block separates them, and the apply path seeks that same
ordinal rather than the first match.

## Verdicts

`agrees | contradicts | unverifiable`, and the third is not a polite way of
saying the first. A claim nothing could settle is reported as unchecked, every
time, in every summary. See `docs/` for what that bucket looks like on the
corpus — it is not small, and pretending otherwise is the failure mode this
whole project is about.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

Verdict = Literal["agrees", "contradicts", "unverifiable"]
Decision = Literal["approved", "rejected"]

VERDICTS: tuple[Verdict, ...] = ("agrees", "contradicts", "unverifiable")

#: Claim kinds. `directive` is the odd one: it is not a claim about
#: infrastructure but a passage that addresses the tooling reading it. It is
#: modelled as a claim so it lands in the same register and the same review
#: queue as everything else, because the right response to it is a human
#: looking at it — not a special-cased branch that quietly drops the page.
KINDS = (
    "threshold",
    "command",
    "resource",
    "link",
    "escalation",
    "version",
    "coverage",
    "directive",
)


def _digest(*parts: str) -> str:
    """Short, stable, and not a security boundary — collision-resistant enough.

    16 hex characters of SHA-256. Truncated because these ids are read aloud in
    review and pasted into tickets, and 64 characters of hex is hostile to the
    human this tool exists to serve.
    """
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Anchor:
    """How to find a passage again after the document has changed underneath us.

    `char_start` and `char_end` are offsets into one specific version of the
    body and are worthless against any other version — Confluence hands back a
    whole document and a version number, and a human edit anywhere above the
    passage moves every offset below it. They are carried because the splice
    needs them *within the version it just read*, and re-resolved from
    `heading_path` and `content_hash` at apply time. Trusting a stored offset
    across versions is how an automated editor writes into the middle of a
    sentence somebody else was writing.

    `editable` is the node allowlist's verdict, decided at extraction. False
    means the passage contains something this tool cannot faithfully
    reconstruct, and the honest path is an inline comment for a human rather
    than a best-effort edit.
    """

    heading_path: tuple[str, ...]
    node_index: int
    content_hash: str
    char_start: int
    char_end: int
    editable: bool = True
    refusal: str | None = None
    occurrence: int = 0
    #: How many times the asserted value already appeared in this block before
    #: this one. `occurrence` distinguishes two identical *passages*; this
    #: distinguishes two identical *values inside one passage*, which is a
    #: different collision and was silently losing the second one.
    value_occurrence: int = 0

    @property
    def anchor_hash(self) -> str:
        # node_index is deliberately absent. See the module docstring.
        parts = [" > ".join(self.heading_path), self.content_hash, str(self.occurrence)]
        # Appended only when non-zero, so every claim that existed before this
        # field did keeps its id. That is not cosmetic: `finding_id` derives
        # from `claim_id`, and churning them would throw away every decision a
        # human has already recorded. The first value in a passage is what every
        # stored claim is, and it hashes as it always did.
        if self.value_occurrence:
            parts.append(f"v{self.value_occurrence}")
        return _digest(*parts)


@dataclass(frozen=True)
class Claim:
    """One checkable assertion a document makes."""

    page_id: str
    kind: str
    subject: str
    asserted: str
    excerpt: str
    anchor: Anchor
    page_version: int = 1

    @property
    def claim_id(self) -> str:
        return _digest(self.page_id, self.kind, self.subject, self.anchor.anchor_hash)


@dataclass(frozen=True)
class Finding:
    """A verdict, and the evidence that justifies it.

    `evidence_file` and `evidence_line` are not decoration. Rule 8 — a finding
    whose evidence does not resolve to a real file and line is a bug — is
    enforced by a test, and it is enforced because a finding an engineer cannot
    check in ten seconds is a finding they will learn to ignore.

    `claim_id` is `None` for estate-level findings: an alert with no runbook is
    not something a document said, so there is no passage to anchor it to. They
    still live in this table because the review queue, the coverage report and
    the readiness pack all need them, and a second parallel store would drift.
    """

    rule_id: str
    kind: str
    subject: str
    verdict: Verdict
    evidence_file: str
    claim_id: str | None = None
    page_id: str | None = None
    observed: str | None = None
    evidence_line: int | None = None
    confidence: float = 1.0
    detail: str = ""
    proposed: str | None = None
    decision: Decision | None = None
    decided_at: str | None = None
    applied_at: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def finding_id(self) -> str:
        return _digest(self.rule_id, self.subject, self.claim_id or f"estate:{self.page_id or ''}")

    @property
    def actionable(self) -> bool:
        """Worth a human's attention in the review queue.

        `agrees` is not, and `unverifiable` is not either — it is reported in
        every summary and counted, but a queue that asks somebody to adjudicate
        every RPO nobody can check is a queue that stops being read.
        """
        return self.verdict == "contradicts"


__all__ = [
    "KINDS",
    "VERDICTS",
    "Anchor",
    "Claim",
    "Decision",
    "Finding",
    "Verdict",
]
