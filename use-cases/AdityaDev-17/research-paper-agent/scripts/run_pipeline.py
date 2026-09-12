"""End-to-end pipeline run against REAL OpenAI and REAL SuperDocs MCP.

Usage:
    python scripts\\run_pipeline.py --topic "Your paper topic" --sources-dir path\\to\\txt\\sources

Sources: put a few plain .txt files (excerpts, abstracts, notes) in a folder
and point --sources-dir at it. Each file becomes one Source.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import OPENAI_API_KEY, SUPERDOCS_API_KEY, SUPERDOCS_MCP_URL
from src.openai_client import OpenAIClient, EMBEDDING_DIM
from src.mcp_client import SuperDocsMCPClient
from src.retrieval import RetrievalIndex
from src.models import Source
from src.outline_agent import create_paper_with_outline
from src.drafting_agent import draft_section
from src.verifier import verify_section
from src.revision_agent import revise_and_reverify_section
from src.export_agent import export_paper


MAX_REVISION_ROUNDS = 3


def load_sources(sources_dir: Path) -> list[Source]:
    sources = []
    for i, path in enumerate(sorted(sources_dir.glob("*.txt")), start=1):
        text = path.read_text(encoding="utf-8")
        sources.append(Source(id=f"src-{i}", title=path.stem, raw_text=text))
    if not sources:
        raise ValueError(f"No .txt source files found in {sources_dir}")
    return sources


def main(topic: str, sources_dir: Path) -> None:
    openai_client = OpenAIClient(api_key=OPENAI_API_KEY)
    embed_fn = openai_client.embed_fn
    llm_fn = openai_client.llm_fn

    print(f"Loading sources from {sources_dir}...")
    sources = load_sources(sources_dir)
    print(f"Loaded {len(sources)} source(s): {[s.title for s in sources]}")

    print("Building retrieval index...")
    retrieval_index = RetrievalIndex(embedding_dim=EMBEDDING_DIM)
    chunk_id_to_source_id = {}
    for source in sources:
        retrieval_index.add_source(source, embed_fn)
        for chunk in source.chunks:
            chunk_id_to_source_id[chunk.chunk_id] = source.id
    print(f"Indexed {len(chunk_id_to_source_id)} chunks total.")

    with SuperDocsMCPClient(url=SUPERDOCS_MCP_URL, api_key=SUPERDOCS_API_KEY) as mcp_client:
        print(f"\nCreating paper outline for topic: {topic!r}")
        paper = create_paper_with_outline(topic, mcp_client)
        print(f"Session: {paper.session_id}")
        print(f"Sections: {[s.title for s in paper.sections]}")

        for section in paper.sections:
            print(f"\n--- Drafting: {section.title} ---")
            try:
                draft_section(
                    section=section, topic=topic, retrieval_index=retrieval_index,
                    embed_fn=embed_fn, llm_fn=llm_fn, mcp_client=mcp_client,
                    session_id=paper.session_id, chunk_id_to_source_id=chunk_id_to_source_id,
                )
                print(f"Drafted {len(section.content)} chars, {len(section.citations)} citation(s).")
            except ValueError as e:
                print(f"WARNING: could not draft '{section.title}': {e}")
                continue

            print(f"Verifying: {section.title}")
            findings = verify_section(section, retrieval_index, llm_fn)
            round_num = 0
            while findings and round_num < MAX_REVISION_ROUNDS:
                round_num += 1
                print(f"  {len(findings)} unsupported claim(s) found — revision round {round_num}")
                before = paper.snapshot_all_hashes()
                findings = revise_and_reverify_section(
                    section, findings, topic, retrieval_index, embed_fn,
                    llm_fn, llm_fn, mcp_client, session_id=paper.session_id,
                    chunk_id_to_source_id=chunk_id_to_source_id,
                )
                changed = paper.diff_against(before)
                print(f"  Sections touched by this revision: {changed}")
            print(f"Final status: {section.status.value}")

        print("\n--- Exporting ---")
        try:
            export_path = export_paper(paper, mcp_client, format="docx")
            print(f"Exported to: {export_path}")
        except ValueError as e:
            print(f"EXPORT BLOCKED: {e}")

    print(f"\nTotal OpenAI cost: ${openai_client.total_cost_usd:.4f} ({openai_client.total_tokens} tokens)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--sources-dir", required=True, type=Path)
    args = parser.parse_args()
    main(args.topic, args.sources_dir)