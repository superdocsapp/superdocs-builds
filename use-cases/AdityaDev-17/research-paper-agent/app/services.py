"""Wraps the src/ pipeline for the Streamlit UI. Owns client lifecycle
(cached so the MCP background thread and OpenAI client are created once
per app process, not on every rerun) and exposes a generator-based
run_pipeline() so the UI can show live progress."""
from __future__ import annotations
import io
import json
import sys
import uuid
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
from pypdf import PdfReader
from docx import Document as DocxDocument

from src.config import OPENAI_API_KEY, SUPERDOCS_API_KEY, SUPERDOCS_MCP_URL
from src.openai_client import OpenAIClient, EMBEDDING_DIM
from src.mcp_client import SuperDocsMCPClient
from src.retrieval import RetrievalIndex
from src.models import Source, Paper, RunLog, RunAction
from src.outline_agent import create_paper_with_outline, FIXED_SECTION_TITLES
from src.drafting_agent import draft_section
from src.verifier import verify_section
from src.revision_agent import revise_and_reverify_section
from src.export_agent import export_paper
from src.models import Source, Paper, RunLog, RunAction, SectionStatus

MAX_REVISION_ROUNDS = 3

TOPIC_INFERENCE_SYSTEM_PROMPT = """You are given excerpts from a set of
research source documents. Propose ONE concise, specific academic paper
topic/title that could reasonably be written primarily from this material.
Return ONLY valid JSON in this exact shape: {"topic": "..."}"""


@st.cache_resource
def get_openai_client() -> OpenAIClient:
    return OpenAIClient(api_key=OPENAI_API_KEY)


@st.cache_resource
def get_mcp_client() -> SuperDocsMCPClient:
    return SuperDocsMCPClient(url=SUPERDOCS_MCP_URL, api_key=SUPERDOCS_API_KEY)


def _extract_text(uploaded_file) -> str:
    name = uploaded_file.name.lower()
    data = uploaded_file.read()

    if name.endswith(".txt"):
        return data.decode("utf-8")

    if name.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if name.endswith(".docx"):
        doc = DocxDocument(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs)

    raise ValueError(f"Unsupported file type: {uploaded_file.name} (use .txt, .pdf, or .docx)")


def sources_from_uploads(uploaded_files) -> list[Source]:
    sources = []
    for i, f in enumerate(uploaded_files, start=1):
        text = _extract_text(f)
        sources.append(Source(id=f"src-{i}", title=f.name, raw_text=text))
    return sources


def infer_topic_from_sources(sources: list[Source]) -> str:
    """One LLM call: propose a paper topic from the actual uploaded
    content, rather than asking the user to type one before they've
    even chosen their sources."""
    llm_fn = get_openai_client().llm_fn
    excerpt_block = "\n\n".join(f"[{s.title}]\n{s.raw_text[:1500]}" for s in sources)
    raw = llm_fn(TOPIC_INFERENCE_SYSTEM_PROMPT, excerpt_block)
    return json.loads(raw)["topic"]


def build_retrieval_index(sources: list[Source]) -> tuple[RetrievalIndex, dict[str, str]]:
    openai_client = get_openai_client()
    index = RetrievalIndex(embedding_dim=EMBEDDING_DIM)
    chunk_id_to_source_id = {}
    for source in sources:
        index.add_source(source, openai_client.embed_fn)
        for chunk in source.chunks:
            chunk_id_to_source_id[chunk.chunk_id] = source.id
    return index, chunk_id_to_source_id


def run_pipeline(topic: str, sources: list[Source]) -> Iterator[dict]:
    """Generator: yields a progress event dict after each step. Events
    are deliberately coarse (section-title-level) — verifying/revising
    sub-steps happen silently underneath so the UI checklist only shows
    section titles ticking off, per the requested transparency model."""
    openai_client = get_openai_client()
    mcp_client = get_mcp_client()
    embed_fn = openai_client.embed_fn
    llm_fn = openai_client.llm_fn

    run_logs: list[RunLog] = []

    yield {"event": "indexing"}
    retrieval_index, chunk_id_to_source_id = build_retrieval_index(sources)

    yield {"event": "outlining"}
    paper = create_paper_with_outline(topic, mcp_client)

    for section in paper.sections:
        yield {"event": "drafting", "section": section.title}
        try:
            draft_section(
                section=section, topic=topic, retrieval_index=retrieval_index,
                embed_fn=embed_fn, llm_fn=llm_fn, mcp_client=mcp_client,
                session_id=paper.session_id, chunk_id_to_source_id=chunk_id_to_source_id,
            )
        except ValueError as e:
            yield {"event": "draft_failed", "section": section.title, "error": str(e)}
            continue

        run_logs.append(RunLog(
            run_id=str(uuid.uuid4()), action=RunAction.DRAFT,
            sections_touched=[section.id],
            tokens_used=openai_client.total_tokens, cost_usd=openai_client.total_cost_usd,
        ))

        findings = verify_section(section, retrieval_index, llm_fn)
        round_num = 0
        while findings and round_num < MAX_REVISION_ROUNDS:
            round_num += 1
            before = paper.snapshot_all_hashes()
            try:
                findings = revise_and_reverify_section(
                    section, findings, topic, retrieval_index, embed_fn,
                    llm_fn, llm_fn, mcp_client, session_id=paper.session_id,
                    chunk_id_to_source_id=chunk_id_to_source_id,
                )
            except ValueError as e:
                yield {"event": "revision_failed", "section": section.title, "error": str(e)}
                break  # leave this section FLAGGED rather than crashing the whole run
            changed = paper.diff_against(before)
            run_logs.append(RunLog(
                run_id=str(uuid.uuid4()), action=RunAction.REVISE,
                sections_touched=changed,
                tokens_used=openai_client.total_tokens, cost_usd=openai_client.total_cost_usd,
            ))

        yield {"event": "section_done", "section": section.title, "status": section.status.value}

    yield {
        "event": "done", "paper": paper, "run_logs": run_logs,
        "retrieval_index": retrieval_index, "chunk_id_to_source_id": chunk_id_to_source_id,
    }


def combine_sections_for_editing(paper: Paper) -> str:
    """One big editable blob: '# Title\\ncontent' per section, in order."""
    return "\n\n".join(f"# {s.title}\n{s.content}" for s in paper.sections)


def parse_combined_draft(text: str) -> dict[str, str]:
    """Inverse of combine_sections_for_editing — splits the user's
    edited blob back into {title: content} by '# ' heading markers."""
    sections: dict[str, str] = {}
    current_title = None
    current_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("# "):
            if current_title is not None:
                sections[current_title] = "\n".join(current_lines).strip()
            current_title = line[2:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_title is not None:
        sections[current_title] = "\n".join(current_lines).strip()
    return sections


def save_combined_draft(paper: Paper, edited_text: str) -> list[str]:
    """Parses the combined editor text, pushes ONLY the sections whose
    content actually changed. Returns the list of changed section titles."""
    parsed = parse_combined_draft(edited_text)
    changed_titles = []
    for section in paper.sections:
        new_text = parsed.get(section.title)
        if new_text is not None and new_text.strip() != section.content.strip():
            apply_manual_edit(paper, section.id, new_text.strip())
            changed_titles.append(section.title)
    return changed_titles


def apply_manual_edit(paper: Paper, section_id: str, new_text: str) -> None:
    """User edited a section directly in the UI. Push it to SuperDocs
    verbatim (no re-drafting), update our local model + hash, and mark
    it VERIFIED — a human directly approving the content is the export
    gate's strongest possible signal, stronger than the automated check."""
    mcp_client = get_mcp_client()
    section = paper.get_section(section_id)
    section.set_content(new_text)
    section.status = SectionStatus.VERIFIED
    mcp_client.edit_section(session_id=paper.session_id, section_title=section.title, new_content=new_text)


def export_current(paper: Paper, fmt: str) -> str:
    mcp_client = get_mcp_client()
    return export_paper(paper, mcp_client, format=fmt)