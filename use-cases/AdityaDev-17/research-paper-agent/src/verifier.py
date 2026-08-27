from __future__ import annotations
import json
from typing import Callable

from src.models import Section, SectionStatus
from src.retrieval import RetrievalIndex


VerifierLLMFn = Callable[[str, str], str]


VERIFIER_SYSTEM_PROMPT = """You are a supervisor checking whether a claim is
genuinely supported by a source passage. Be strict: a claim is only supported
if the passage actually states or directly implies it. Do not be lenient
because the claim sounds plausible.
Return ONLY valid JSON in this exact shape:
{"supported": true/false, "reason": "one sentence explaining why"}"""


def build_verifier_prompt(claim_text: str, passage_text: str) -> str:
    return (
        f"Claim: {claim_text}\n\n"
        f"Source passage: {passage_text}\n\n"
        f"Is the claim supported by this passage?"
    )


def verify_citation(claim_text: str, passage_text: str, llm_fn: VerifierLLMFn) -> tuple[bool, str]:
    raw_response = llm_fn(VERIFIER_SYSTEM_PROMPT, build_verifier_prompt(claim_text, passage_text))
    parsed = json.loads(raw_response)
    return parsed["supported"], parsed["reason"]


def verify_section(section: Section, retrieval_index: RetrievalIndex, llm_fn: VerifierLLMFn) -> list[dict]:
    """Checks every citation in the section. Mutates citation.verified
    in place and updates section.status. Returns a list of unsupported
    findings: [{citation_id, claim_text, reason}, ...] — empty if all
    claims check out."""
    unsupported_findings = []

    for citation in section.citations:
        chunk = retrieval_index.chunk_by_id.get(citation.passage_ref)
        if chunk is None:
            # The citation points at a chunk_id the index doesn't know about —
            # that's a data integrity problem, not a grounding problem. Fail loudly.
            raise ValueError(
                f"Citation {citation.id} references unknown chunk_id '{citation.passage_ref}'"
            )

        supported, reason = verify_citation(citation.claim_text, chunk.text, llm_fn)
        citation.verified = supported

        if not supported:
            unsupported_findings.append({
                "citation_id": citation.id,
                "claim_text": citation.claim_text,
                "reason": reason,
            })

    section.status = SectionStatus.FLAGGED if unsupported_findings else SectionStatus.VERIFIED
    return unsupported_findings