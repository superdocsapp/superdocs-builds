from __future__ import annotations
import json
import uuid
from typing import Callable

from src.models import Section, Citation
from src.retrieval import RetrievalIndex
from src.mcp_client import MCPClient


# llm_fn signature: (system_prompt: str, user_prompt: str) -> str (raw JSON text)
LLMFn = Callable[[str, str], str]


DRAFTING_SYSTEM_PROMPT = """You are drafting one section of an academic paper.
You will be given a set of source passages, each with a chunk_id.
Write the section using ONLY information from these passages.
Return ONLY valid JSON, no other text, in this exact shape:
{"claims": [{"sentence": "...", "supporting_chunk_id": "..."}]}
Every sentence must have a supporting_chunk_id from the passages given.
Do not include any claim you cannot support from the passages."""


def build_user_prompt(section_title: str, topic: str, passages: list[dict]) -> str:
    passage_block = "\n".join(
        f"[{p['chunk_id']}] {p['text']}" for p in passages
    )
    return (
        f"Paper topic: {topic}\n"
        f"Section to write: {section_title}\n\n"
        f"Source passages:\n{passage_block}\n\n"
        f"Write the '{section_title}' section as a list of cited claims."
    )


def draft_section(
    section: Section,
    topic: str,
    retrieval_index: RetrievalIndex,
    embed_fn: Callable[[list[str]], list[list[float]]],
    llm_fn: LLMFn,
    mcp_client: MCPClient,
    session_id: str,
    chunk_id_to_source_id: dict[str, str],
) -> None:
    """Drafts one section end to end: retrieve -> generate grounded
    claims -> assemble content -> push into SuperDocs via edit_section.
    Mutates `section` in place using Section.set_content (the only
    sanctioned mutation path). Citations stay in OUR OWN Citation
    model — SuperDocs has no insert_citation tool; the drafted text
    is what actually goes into the document."""

    query = f"{section.title}: {topic}"
    query_embedding = embed_fn([query])[0]
    passages = retrieval_index.search(query_embedding, top_k=5)

    if not passages:
        raise ValueError(f"No passages retrieved for section '{section.title}' — cannot draft without sources.")

    system_prompt = DRAFTING_SYSTEM_PROMPT
    user_prompt = build_user_prompt(section.title, topic, passages)
    raw_response = llm_fn(system_prompt, user_prompt)

    parsed = json.loads(raw_response)
    claims = parsed["claims"]

    valid_chunk_ids = {p["chunk_id"] for p in passages}
    content_lines = []
    citations: list[Citation] = []

    for claim in claims:
        sentence = claim["sentence"]
        chunk_id = claim["supporting_chunk_id"]

        if chunk_id not in valid_chunk_ids:
            # LLM hallucinated a chunk_id that wasn't in the passages we gave it.
            # Fail loudly rather than silently accepting an ungrounded claim.
            raise ValueError(
                f"LLM cited chunk_id '{chunk_id}' which was not in the retrieved passages "
                f"for section '{section.title}'."
            )

        content_lines.append(sentence)
        citations.append(Citation(
            id=str(uuid.uuid4()),
            section_id=section.id,
            source_id=chunk_id_to_source_id[chunk_id],
            claim_text=sentence,
            passage_ref=chunk_id,
            verified=False,  # verifier's job, not this function's
        ))

    full_content = " ".join(content_lines)
    section.set_content(full_content)
    section.citations = citations

    mcp_client.edit_section(
        session_id=session_id,
        section_title=section.title,
        new_content=full_content,
    )