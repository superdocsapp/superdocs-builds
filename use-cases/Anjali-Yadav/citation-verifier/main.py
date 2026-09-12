from __future__ import annotations

import re
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.verification import check_entailment  # noqa: E402
from common.config import get_budget_floor, get_required_api_key, load_environment  # noqa: E402
from common.superdocs_client import OperationBudget, SuperDocsClient  # noqa: E402
from schemas import CitationPair  # noqa: E402


class SessionEntailmentClient:
    """Adapt the session-scoped SuperDocs client to the verifier contract."""

    def __init__(self, client, session_id: str):
        self.client = client
        self.session_id = session_id

    def chat(self, **kwargs):
        result = self.client.chat(self.session_id, kwargs["message"])
        if isinstance(result, dict) and "verdict" not in result:
            return result.get("response", result)
        return result


def extract_citation_pairs(document_text: str, reference_map: dict[str, str] | dict[str, dict[str, str]]) -> list[CitationPair]:
    """Extract claim/citation pairs from text using inline citation markers.

    The function accepts either a flat map of citation IDs to text or a nested
    map keyed by document ID then citation ID.
    """
    pairs: list[CitationPair] = []
    pattern = re.compile(r"(.+?)(\[(\d+|[A-Za-z]+)\])")
    for match in pattern.finditer(document_text):
        claim = match.group(1).strip()
        citation_target = match.group(3)
        if not claim:
            continue
        pairs.append(
            CitationPair(
                claim=claim,
                citation_target=citation_target,
                source_doc_id="document",
            )
        )
    return pairs


def verify_pairs(pairs: list[CitationPair], reference_map: dict, client) -> list[dict]:
    """Evaluate each citation claim independently and report a per-citation verdict."""
    findings: list[dict] = []
    for pair in pairs:
        target_map = reference_map.get(pair.source_doc_id, reference_map)
        if isinstance(target_map, dict) and pair.citation_target in target_map:
            cited_text = target_map[pair.citation_target]
            verdict = check_entailment(pair.claim, cited_text, client)
            findings.append({
                "claim": pair.claim,
                "citation_target": pair.citation_target,
                "source_doc_id": pair.source_doc_id,
                **verdict,
            })
        else:
            findings.append({
                "claim": pair.claim,
                "citation_target": pair.citation_target,
                "source_doc_id": pair.source_doc_id,
                "verdict": "unverifiable",
                "reason": "The cited source is not in the uploaded set.",
            })
    return findings


def build_report(document_text: str, reference_map: dict, client) -> dict:
    """Extract citations and independently verify every extracted pair."""
    pairs = extract_citation_pairs(document_text, reference_map)
    return {
        "pairs": [pair.model_dump() for pair in pairs],
        "findings": verify_pairs(pairs, reference_map, client),
    }


def run_session_workflow(
    document_text: str,
    reference_map: dict,
    client,
    out_path: str,
    session_id: str | None = None,
) -> dict:
    """Upload the source set, verify citations, and export the source session."""
    if not document_text.strip():
        raise ValueError("The cited document is empty.")
    session_id = session_id or f"citation-verifier-{uuid.uuid4()}"
    client.upload("citation-source.txt", document_text, session_id)
    report = build_report(
        document_text,
        reference_map,
        SessionEntailmentClient(client, session_id),
    )
    report["session_id"] = session_id
    Path(out_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    client.export(session_id, "markdown", str(Path(out_path).with_suffix(".md")))
    return report


def main() -> None:
    parser = __import__("argparse").ArgumentParser(description="Citation verification assistant")
    parser.add_argument("document_path", help="Path to the source document")
    parser.add_argument("--refs", default="sample_documents/references.json")
    parser.add_argument("--out", help="Optional JSON report path")
    args = parser.parse_args()

    load_environment(Path(__file__).resolve().parent)
    try:
        api_key = get_required_api_key()
    except RuntimeError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    document_text = Path(args.document_path).read_text(encoding="utf-8")
    refs = __import__("json").loads(Path(args.refs).read_text(encoding="utf-8"))
    client = SuperDocsClient(
        api_key,
        budget=OperationBudget(floor=get_budget_floor()),
    )
    report_path = args.out or "output/citation_report.json"
    report = run_session_workflow(document_text, refs, client, report_path)
    rendered = __import__("json").dumps(report, indent=2, ensure_ascii=True)
    print(rendered)


if __name__ == "__main__":
    main()
