from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.local_retrieval import chunk_documents, hybrid_search  # noqa: E402
from common.verification import quote_grounded  # noqa: E402
from common.superdocs_client import SuperDocsClient  # noqa: E402
from common.config import get_budget_floor, get_required_api_key, load_environment  # noqa: E402
from common.superdocs_client import OperationBudget  # noqa: E402
from schemas import Hop, MultiHopAnswer  # noqa: E402


def answer_question(question: str, documents: dict[str, str]) -> MultiHopAnswer:
    """Minimal, deterministic multi-hop answer builder.

    The real integration path would call the SuperDocs API to answer using only
    top retrieved chunks. This local logic keeps the grounding and deduplication
    rules testable without network access.
    """
    chunks = []
    for doc_id, text in documents.items():
        chunks.extend(chunk_documents([{"doc_id": doc_id, "text": text}]))

    retrieved = hybrid_search(question, chunks, top_k=4)
    if not retrieved:
        return MultiHopAnswer(answer=None, could_not_answer=True, hops=[])

    hops: list[Hop] = []
    for chunk in retrieved:
        evidence = chunk.text.strip()
        if evidence:
            hops.append(
                Hop(
                    claim=question.strip(),
                    source_doc_id=chunk.doc_id,
                    evidence_quote=evidence,
                    verified=quote_grounded(evidence, documents.get(chunk.doc_id, "")),
                )
            )

    deduped = MultiHopAnswer.dedupe_hops(hops)
    answer = "\n".join(f"- {hop.claim} ({hop.source_doc_id})" for hop in deduped)
    return MultiHopAnswer(
        answer=answer or None,
        could_not_answer=False,
        hops=deduped,
    ).validate_against_documents(documents)


def run_session_workflow(
    question: str,
    documents: dict[str, str],
    client: SuperDocsClient,
    out_path: str,
    session_id: str | None = None,
) -> dict:
    """Upload a document set, answer locally, and export an auditable report."""
    if not documents:
        raise ValueError("At least one document is required.")
    session_id = session_id or f"multihop-qa-{uuid.uuid4()}"
    for doc_id, text in documents.items():
        if not text.strip():
            raise ValueError(f"Document '{doc_id}' is empty.")
        client.upload(f"{doc_id}.txt", text, session_id)

    result = answer_question(question, documents)
    report = {
        "session_id": session_id,
        "question": question,
        **result.as_dict(),
        "source_documents": sorted(documents),
    }
    Path(out_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    client.export(session_id, "markdown", str(Path(out_path).with_suffix(".md")))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-hop QA over a document set.")
    parser.add_argument("question", help="Question to answer from the uploaded set.")
    parser.add_argument("--docs-dir", required=True)
    parser.add_argument("--out", default="output/multihop_answer.json")
    parser.add_argument("--session-id")
    args = parser.parse_args()

    load_environment(Path(__file__).resolve().parent)
    api_key = get_required_api_key()
    docs_dir = Path(args.docs_dir)
    documents = {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted(docs_dir.glob("*.txt"))
    }
    client = SuperDocsClient(api_key, budget=OperationBudget(floor=get_budget_floor()))
    report = run_session_workflow(args.question, documents, client, args.out, args.session_id)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
