from __future__ import annotations
import json
from typing import Callable

from src.models import Section, Paper
from src.retrieval import RetrievalIndex
from src.verifier import verify_section
from src.mcp_client import MCPClient


LLMFn = Callable[[str, str], str]

REVISION_SYSTEM_PROMPT = """You are revising ONE flagged claim from an academic
paper section. You will be given the unsupported claim and a fresh source
passage. Rewrite the claim so it is fully supported by the passage — either
soften it or replace it with something the passage actually states.
Return ONLY valid JSON in this shape:
{"sentence": "...", "supporting_chunk_id": "..."}"""


def build_revision_prompt(old_claim: str, passages: list[dict]) -> str:
    passage_block = "\n".join(f"[{p['chunk_id']}] {p['text']}" for p in passages)
    return (
        f"Unsupported claim to fix: {old_claim}\n\n"
        f"Available passages:\n{passage_block}\n\n"
        f"Rewrite this claim so it is grounded in one of these passages."
    )


def revise_flagged_citations(
    section: Section,
    findings: list[dict],
    topic: str,
    retrieval_index: RetrievalIndex,
    embed_fn: Callable[[list[str]], list[list[float]]],
    llm_fn: LLMFn,
    mcp_client: MCPClient,
    session_id: str,
    chunk_id_to_source_id: dict[str, str],
) -> None:
    """Rewrites only the citations named in `findings`. Every other
    citation/sentence in the section is left untouched. Reassembles
    section.content from ALL citations (revised + untouched) and pushes
    it via a SINGLE edit_section call — SuperDocs has no insert_citation
    tool, so citation bookkeeping stays entirely in our own model."""

    flagged_citation_ids = {f["citation_id"] for f in findings}

    for citation in section.citations:
        if citation.id not in flagged_citation_ids:
            continue  # untouched claim — leave exactly as is

        query = f"{section.title}: {topic}: {citation.claim_text}"
        query_embedding = embed_fn([query])[0]
        passages = retrieval_index.search(query_embedding, top_k=5)

        raw_response = llm_fn(REVISION_SYSTEM_PROMPT, build_revision_prompt(citation.claim_text, passages))
        parsed = json.loads(raw_response)

        new_chunk_id = parsed["supporting_chunk_id"]
        valid_chunk_ids = {p["chunk_id"] for p in passages}
        if new_chunk_id not in valid_chunk_ids:
            raise ValueError(f"Revision cited unknown chunk_id '{new_chunk_id}'")

        citation.claim_text = parsed["sentence"]
        citation.passage_ref = new_chunk_id
        citation.source_id = chunk_id_to_source_id[new_chunk_id]
        citation.verified = False  # must be re-verified, not assumed fixed

    # Reassemble content from all citations in their original relative order
    new_content = " ".join(c.claim_text for c in section.citations)
    section.set_content(new_content)  # single mutation path, hash refreshed automatically

    mcp_client.edit_section(
        session_id=session_id,
        section_title=section.title,
        new_content=new_content,
    )


def revise_and_reverify_section(
    section: Section,
    findings: list[dict],
    topic: str,
    retrieval_index: RetrievalIndex,
    embed_fn: Callable[[list[str]], list[list[float]]],
    revision_llm_fn: LLMFn,
    verifier_llm_fn: LLMFn,
    mcp_client: MCPClient,
    session_id: str,
    chunk_id_to_source_id: dict[str, str],
) -> list[dict]:
    """The full revision loop: revise flagged citations, then re-verify
    the whole section. Returns remaining findings (empty if now clean)."""
    revise_flagged_citations(
        section, findings, topic, retrieval_index, embed_fn,
        revision_llm_fn, mcp_client, session_id, chunk_id_to_source_id,
    )
    return verify_section(section, retrieval_index, verifier_llm_fn)


def prove_only_target_section_changed(paper: Paper, snapshot: dict[str, str], target_section_id: str) -> None:
    """Raises if the revision touched anything other than target_section_id.
    Call this after every revision — it's the literal proof the card asks for."""
    changed = paper.diff_against(snapshot)
    if changed != [target_section_id]:
        raise AssertionError(
            f"Revision was supposed to touch only '{target_section_id}', "
            f"but these sections changed: {changed}"
        )