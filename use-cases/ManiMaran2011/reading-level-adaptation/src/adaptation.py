"""
Core engine. Given a source document already uploaded to a SuperDocs session, produces one adapted version
per requested adaptation type, each in its own session, and VERIFIES (not just requests) that every
protected chunk survived byte-identical.

Design point worth stating: the client (real or fake) is the only thing that knows how to talk to
SuperDocs. This module never inspects HTTP status codes or session internals -- it only calls the four
methods on the client interface (upload_document, chat, export) plus the pure functions in
chunk_classifier.py. That's what let the fake-client test suite exercise the real verification logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from src.chunk_classifier import classify_document, Chunk

AdaptationType = Literal["lower_reading_level", "language_learner", "reduced_load", "curriculum_aligned"]

_INSTRUCTIONS: dict[AdaptationType, str] = {
    "lower_reading_level": (
        "Rewrite the prose in every non-protected section to a lower reading level (roughly a 5th-grade "
        "reading level): shorter sentences, simpler vocabulary, same factual content. Do not add or remove "
        "information. Do not touch headings' factual content, only simplify wording where natural."
    ),
    "language_learner": (
        "Rewrite the prose in every non-protected section for an English-language-learner audience: "
        "shorter sentences, common vocabulary, avoid idioms, define technical terms inline on first use."
    ),
    "reduced_load": (
        "Rewrite the prose in every non-protected section to reduce cognitive load: break long paragraphs "
        "into shorter ones or bullet points where natural, remove redundant phrasing, keep every fact."
    ),
    "curriculum_aligned": (
        "Rewrite the prose in every non-protected section to align terminology with {terminology_map}, "
        "replacing this chapter's terms with the target curriculum's equivalent terms wherever they appear, "
        "without changing the underlying facts or examples."
    ),
}


@dataclass
class VerificationResult:
    ok: bool
    protected_chunk_ids: list[str]
    corrupted_chunk_ids: list[str]

    def report(self) -> str:
        if self.ok:
            return f"OK — all {len(self.protected_chunk_ids)} protected chunks byte-identical."
        return (
            f"FAILED — {len(self.corrupted_chunk_ids)} of {len(self.protected_chunk_ids)} protected "
            f"chunks were modified: {self.corrupted_chunk_ids}. Adaptation NOT trusted; do not export."
        )


@dataclass
class AdaptationResult:
    adaptation_type: AdaptationType
    session_id: str
    html: str
    verification: VerificationResult
    source_chunk_hashes: dict[str, str] = field(default_factory=dict)  # chunk_id -> hash, for revision diffing


def _protected_hash_map(source_chunks: list[Chunk]) -> dict[str, str]:
    return {c.chunk_id: c.content_hash for c in source_chunks if c.kind == "protected"}


def verify_protected_chunks(source_html: str, adapted_html: str) -> VerificationResult:
    """The trust boundary. Never assumes the AI honored the 'don't touch this' instruction.

    IMPORTANT: this does NOT match chunks by chunk_id across the source -> adapted transition. Real-world
    testing against the live SuperDocs API (2026-08-22) showed chunk ids are NOT stable across a chat turn
    -- SuperDocs re-syncs/reassigns ids as part of processing a document, even for content it didn't
    touch. An id-based comparison therefore reported false failures on every single protected chunk, even
    ones whose actual content was untouched.

    Instead: for every protected chunk in the SOURCE, check whether that exact chunk's HTML (whitespace-
    normalized) appears VERBATIM somewhere in the adapted document, under any id. This is actually the more
    correct definition of 'byte-identical preservation' the task asks for -- it doesn't care what id a
    figure ends up under, only that its content is untouched.
    """
    source_chunks = classify_document(source_html)
    adapted_chunks = classify_document(adapted_html)
    adapted_hashes = {c.content_hash for c in adapted_chunks}

    protected_ids = [c.chunk_id for c in source_chunks if c.kind == "protected"]
    corrupted = []
    for c in source_chunks:
        if c.kind != "protected":
            continue
        if c.content_hash not in adapted_hashes:
            corrupted.append(c.chunk_id)

    return VerificationResult(ok=not corrupted, protected_chunk_ids=protected_ids, corrupted_chunk_ids=corrupted)


def repair_protected_chunks(source_html: str, adapted_html: str) -> tuple[str, list[str]]:
    """Real-world testing (2026-08-22) showed that even an explicit 'do not touch these exact chunk ids'
    instruction is NOT reliably honored by the model -- it rewrote a figure caption's wording on every
    single run regardless. Asking nicely, however precisely, is not a guarantee.

    So: don't ask. ENFORCE. After adaptation, splice each protected chunk's ORIGINAL html back into the
    adapted document at its aligned position (position-based, per the id-instability finding above),
    unconditionally overwriting whatever the model put there. This makes byte-identical preservation a
    property of this code, not a property of the model's compliance -- which is what 'preserved exactly'
    in the task card actually requires, not merely requests.

    Returns (repaired_html, unrepairable_chunk_ids) -- the second list is non-empty only if a protected
    chunk's position doesn't exist at all in the adapted output (e.g. the model deleted whole sections),
    which is a real, surfaced failure this function cannot silently paper over.
    """
    source_chunks = classify_document(source_html)
    adapted_chunks = classify_document(adapted_html)

    unrepairable = []
    repaired_html = adapted_html
    # Walk source chunks in reverse position order so string replacement offsets for earlier chunks aren't
    # invalidated by edits made while processing later ones.
    for i in range(len(source_chunks) - 1, -1, -1):
        source_chunk = source_chunks[i]
        if source_chunk.kind != "protected":
            continue
        if i >= len(adapted_chunks):
            unrepairable.append(source_chunk.chunk_id)
            continue
        adapted_chunk_at_position = adapted_chunks[i]
        if adapted_chunk_at_position.content_hash == source_chunk.content_hash:
            continue  # already untouched, nothing to repair
        repaired_html = repaired_html.replace(adapted_chunk_at_position.html, source_chunk.html, 1)

    return repaired_html, unrepairable


def run_adaptation(
    client, source_session_id: str, source_html: str, adaptation_type: AdaptationType,
    terminology_map: str = "", session_suffix: str = "",
) -> AdaptationResult:
    session_id = f"{source_session_id}__{adaptation_type}{session_suffix}"

    # Real-world testing (2026-08-22) showed a natural-language instruction like "leave figures and
    # equations untouched" is not reliably honored -- the model rewrote a figure caption's wording despite
    # being told not to (verified caught it correctly; this is the fix to reduce how often that happens in
    # the first place). Rather than describe protected content in prose and hope the model infers which
    # chunks that means, tell it the EXACT chunk ids to leave untouched -- we already know them from
    # classification before sending the request, so there's no reason to make the model guess.
    protected = [c.chunk_id for c in classify_document(source_html) if c.kind == "protected"]
    protected_list = ", ".join(protected) if protected else "(none)"

    base_instruction = _INSTRUCTIONS[adaptation_type].format(terminology_map=terminology_map or "the target curriculum")
    instruction = (
        f"{base_instruction} "
        f"CRITICAL CONSTRAINT: the following chunk ids must remain 100% character-for-character identical "
        f"to their current content -- do not rephrase, correct, or touch them in any way, even to fix a typo "
        f"or improve wording: {protected_list}. Only edit chunks NOT in this list."
    )

    response = client.chat(session_id=session_id, message=instruction, document_html=source_html)
    adapted_html = response["document_changes"]["updated_html"]

    # Enforce preservation rather than merely request it -- see repair_protected_chunks' docstring for why
    # this step exists. Verification then runs on the REPAIRED html, so it's checking "did the repair
    # actually work" (e.g. did the model delete a whole section so there's no position to repair into),
    # not "did the model behave" -- a much easier bar to clear honestly.
    repaired_html, unrepairable = repair_protected_chunks(source_html, adapted_html)

    verification = verify_protected_chunks(source_html, repaired_html)
    if unrepairable:
        # A chunk with no corresponding position in the adapted output can't be force-restored -- surface
        # this explicitly rather than silently dropping it from the verification report.
        verification.corrupted_chunk_ids = list(set(verification.corrupted_chunk_ids) | set(unrepairable))
        verification.ok = False

    source_chunks = classify_document(source_html)

    return AdaptationResult(
        adaptation_type=adaptation_type, session_id=session_id, html=repaired_html,
        verification=verification, source_chunk_hashes={c.chunk_id: c.content_hash for c in source_chunks},
    )


def run_all_adaptations(client, source_session_id: str, source_html: str, terminology_map: str = "") -> dict[AdaptationType, AdaptationResult]:
    results = {}
    for adaptation_type in _INSTRUCTIONS:
        results[adaptation_type] = run_adaptation(client, source_session_id, source_html, adaptation_type, terminology_map)
    return results
