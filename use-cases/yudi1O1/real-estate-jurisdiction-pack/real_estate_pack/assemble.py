"""Assemble the three-document pack and prove the three documents agree.

The card names `Multi-document` as a surface, and the interesting part of
multi-document work is not producing three files — it is producing three files
that stay consistent. A lease whose attachment schedule lists a disclosure the
packet does not contain is worse than a lease with no schedule at all, because
it reads as complete.

`check_consistency` therefore runs over the **rendered** documents, not over the
data they were rendered from. Checking the inputs would only prove the inputs
agreed with themselves. Checking the output catches a renderer that drops an
entry, mangles a reference, or formats the same amount two different ways — and
a renderer bug is exactly the kind of thing that survives a review of the data
model.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .entries import PackEntry, disclosures, lease_clauses, number_entries
from .models import LeasePackRequest
from .render import (
    build_instruction,
    render_compliance_index,
    render_disclosure_packet,
    render_lease,
)
from .rules import Jurisdiction
from .validate import ValidationResult

LEASE = "lease"
PACKET = "disclosure_packet"
INDEX = "compliance_index"

#: Document order is fixed: the lease references the packet, and the index
#: describes both. Producing them in this order keeps a partial run useful.
DOCUMENT_ORDER = (LEASE, PACKET, INDEX)

_TITLES = {
    LEASE: "Residential Lease Agreement",
    PACKET: "Required Disclosure Packet",
    INDEX: "Disclosure Compliance Index",
}


@dataclass
class AssembledDocument:
    kind: str
    title: str
    content_html: str

    def instruction(self, req: LeasePackRequest, jurisdiction: Jurisdiction) -> str:
        return build_instruction(self.title, self.content_html, req, jurisdiction)


@dataclass
class DocumentSet:
    pack_id: str
    jurisdiction: Jurisdiction
    request: LeasePackRequest
    entries: list[PackEntry] = field(default_factory=list)
    documents: list[AssembledDocument] = field(default_factory=list)
    generated_on: Optional[date] = None

    def get(self, kind: str) -> AssembledDocument:
        for doc in self.documents:
            if doc.kind == kind:
                return doc
        raise KeyError(f"No '{kind}' document in this set. Have: {[d.kind for d in self.documents]}")

    def disclosure_ids(self) -> list[str]:
        return [e.entry_id for e in disclosures(self.entries)]

    def clause_ids(self) -> list[str]:
        return [e.entry_id for e in lease_clauses(self.entries)]


def assemble(
    req: LeasePackRequest,
    jurisdiction: Jurisdiction,
    validation: ValidationResult,
    today: Optional[date] = None,
) -> DocumentSet:
    """Turn a validated request into three cross-referenced documents.

    Assembly assumes validation has already passed or been consciously
    overridden; it does not re-litigate applicability. The one thing it reads
    from the validation result is which rules fired, so there is a single source
    of truth for that decision.
    """
    today = today or date.today()
    stale_ids = {d.rule.id for d in validation.decisions if d.applies and d.stale}
    entries = number_entries(validation.applicable(), stale_ids=stale_ids)

    documents = [
        AssembledDocument(LEASE, _TITLES[LEASE], render_lease(req, jurisdiction, entries)),
        AssembledDocument(PACKET, _TITLES[PACKET], render_disclosure_packet(req, jurisdiction, entries)),
        AssembledDocument(
            INDEX,
            _TITLES[INDEX],
            render_compliance_index(req, jurisdiction, entries, validation.decisions, today),
        ),
    ]

    return DocumentSet(
        pack_id=req.pack_id,
        jurisdiction=jurisdiction,
        request=req,
        entries=entries,
        documents=documents,
        generated_on=today,
    )


_REF_PATTERN = re.compile(r"\b([DL]-\d+)\b")


def _refs_in(text: str) -> set[str]:
    return set(_REF_PATTERN.findall(text))


def _strip_tags(html_text: str) -> str:
    """Rendered HTML back to comparable plain text.

    The `html.unescape` is not cosmetic. Rendering escapes apostrophes to
    `&#x27;`, so without it any statutory passage containing "Tenant's" compared
    unequal to itself and the consistency checker reported a false mismatch on
    correct output. A checker that cries wolf gets switched off, so this is the
    same class of defect as one that misses a real fault."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", html_text))).strip()


def check_consistency(doc_set: DocumentSet) -> list[str]:
    """Return a list of inconsistencies. Empty means the three documents agree.

    Every check here is phrased so that its failure message says what is wrong
    and where, because this runs in CI and in the CLI and nobody debugging it
    will have the rendered HTML in front of them.
    """
    problems: list[str] = []
    lease = doc_set.get(LEASE)
    packet = doc_set.get(PACKET)
    index = doc_set.get(INDEX)

    expected_disclosures = set(doc_set.disclosure_ids())
    expected_clauses = set(doc_set.clause_ids())

    # 1. The packet contains exactly the disclosures it should.
    packet_refs = _refs_in(packet.content_html)
    missing_from_packet = expected_disclosures - packet_refs
    if missing_from_packet:
        problems.append(
            f"Disclosure packet is missing {sorted(missing_from_packet)} — these disclosures fired but "
            f"were not rendered into the packet."
        )
    stray_in_packet = {r for r in packet_refs if r.startswith("D-")} - expected_disclosures
    if stray_in_packet:
        problems.append(f"Disclosure packet references {sorted(stray_in_packet)}, which are not in this pack.")

    # 2. The lease's attachment schedule names every disclosure in the packet.
    lease_refs = _refs_in(lease.content_html)
    lease_disclosure_refs = {r for r in lease_refs if r.startswith("D-")}
    if lease_disclosure_refs != expected_disclosures:
        missing = sorted(expected_disclosures - lease_disclosure_refs)
        extra = sorted(lease_disclosure_refs - expected_disclosures)
        detail = []
        if missing:
            detail.append(f"not listed in the lease: {missing}")
        if extra:
            detail.append(f"listed in the lease but not in the packet: {extra}")
        problems.append(f"Lease attachment schedule disagrees with the disclosure packet — {'; '.join(detail)}.")

    # 3. Every clause and disclosure appears in the index.
    index_refs = _refs_in(index.content_html)
    missing_from_index = (expected_disclosures | expected_clauses) - index_refs
    if missing_from_index:
        problems.append(
            f"Compliance index does not account for {sorted(missing_from_index)} — the index must "
            f"enumerate every item in the pack."
        )

    # 4. The identity facts are identical in all three, compared on rendered text
    #    rather than on the record they came from.
    req = doc_set.request
    texts = {LEASE: _strip_tags(lease.content_html), PACKET: _strip_tags(packet.content_html), INDEX: _strip_tags(index.content_html)}
    shared_facts = {
        "pack reference": req.pack_id,
        "property address": req.property.full_address(),
        "lease start date": req.tenancy.start_date,
        "lease end date": req.tenancy.end_date,
        "landlord name": req.landlord.name,
    }
    for label, value in shared_facts.items():
        if not str(value).strip():
            continue
        normalized = re.sub(r"\s+", " ", str(value)).strip()
        absent = [kind for kind, text in texts.items() if normalized not in text]
        if absent:
            problems.append(
                f"The {label} ({value!r}) does not appear in: {', '.join(sorted(absent))}. All three "
                f"documents in a pack must carry the same identity block."
            )

    # 5. Verbatim statutory text survived rendering intact.
    for entry in disclosures(doc_set.entries):
        if not entry.rule.verbatim_statutory:
            continue
        # Compare on a distinctive slice, normalised the same way both sides are,
        # so template-driven reflow does not read as a mismatch.
        anchor = re.sub(r"\s+", " ", entry.rule.body.strip())[:80]
        if anchor and anchor not in texts[PACKET]:
            problems.append(
                f"{entry.entry_id} ({entry.title}) is statutorily prescribed text, but its opening does "
                f"not appear verbatim in the rendered packet."
            )

    return problems
