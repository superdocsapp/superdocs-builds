"""The experiment driver: memory-off vs memory-on, over N corpus documents.

Protocol per document, identical between arms except for the memory flags:

1. init_session() — fresh session, every document, every arm. Session reuse
   across documents would let ordinary chat-history context substitute for
   cross-session memory and confound the whole comparison.
2. upload_document_base64() — the corpus document as committed (already at the
   fixed 24-violation profile). document_html is then OMITTED from the chat
   calls below; the session already holds the document.
3. chat_with_retry(GENERIC_INSTRUCTION, approval_mode="approve_all") — the
   agent's own edit. This is the one call the agent's real skill (and,
   for the memory-on arm, its memory) is expressed through.
4. export_document() -> score_document() — THE metric for this document. Scored
   BEFORE any correction is sent.
5. corrections_from_score() — deterministic, pure, no second checker call.
6. If corrections exist: chat_with_retry(corrections.payload,
   approval_mode="approve_all") — the one correction round. This is the
   interaction the memory-on arm's cross_session_memory is meant to learn
   from; the memory-off arm goes through the identical protocol and simply
   discards the opportunity to remember it.
7. export + score again, for the record. Not the metric; a sanity check that
   the correction round actually reduced violations.

Isolation: `cross_session_memory_key` is the ONLY isolation primitive used.
`cross_session_search` is never enabled — per the live tool schema it searches
and can OPEN past documents account-wide, and `cross_session_scope` "only
narrows within the API-key owner" rather than by customer key, so enabling
search would be a leak vector, not a leak defence. See PROGRESS.md for the
live verification and the schema citations behind this.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import config
from checker.h3 import GeminiH3Provider
from checker.score import DocumentScore, load_rubric, score_document
from corrections.generator import (H3Cache, _CachedH3Provider,
                                   corrections_from_score, load_templates)
from runner.preflight import PreflightError, pin_versions, run_preflight
from superdocs.client import ApprovalError, SuperDocsClient, SuperDocsError
from superdocs.mcp_transport import MCPHttpTransport

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus" / "documents"

# Validated live 2026-08-13: the plain "match our house style" instruction
# produced a clarifying-question, zero-edit response — independent of memory
# state — which leaves the metric undefined for that document. This wording
# reliably produced a billed edit across every live trial. It does not name
# any rubric rule; the agent's own judgement is what is being measured.
GENERIC_INSTRUCTION = (
    "Edit this document for professional business writing style: clear, "
    "consistent, polished prose suitable for a client-facing memo. Make the "
    "edits directly in the document yourself — do not ask clarifying "
    "questions, do not request examples, use your own professional judgment."
)

MEMORY_ON_KEY = "measurement_meridian_memory_on"
ARMS = ("memory_off", "memory_on", "memory_off_repeat")
# Whether cross_session_memory is on for a given arm label. The noise-floor
# repeat behaves exactly like memory_off (no key, memory disabled) — it exists
# to measure run-to-run variance with memory out of the picture entirely, per
# the brief: "run the memory-off arm twice to establish a noise floor."
ARM_MEMORY_ON = {"memory_off": False, "memory_on": True,
                 "memory_off_repeat": False}


@dataclass
class DocumentRun:
    document: str
    arm: str
    session_id: str
    edit_billed: bool
    edit_ops_charged: int
    score_before: dict
    corrections_sent: int
    rules_violated: int
    correction_billed: bool
    correction_ops_charged: int
    score_after: dict
    total_ops: int


@dataclass
class ArmResult:
    arm: str
    documents: list[DocumentRun] = field(default_factory=list)
    memory_wipe_removed: int | None = None

    @property
    def total_ops(self) -> int:
        return sum(d.total_ops for d in self.documents)

    @property
    def curve(self) -> list[int]:
        return [d["totals"]["total_raw"] for d in
                (dr.score_before for dr in self.documents)]


def _score_dict(score: DocumentScore) -> dict:
    return score.as_dict()


def run_one_document(client: SuperDocsClient, rubric: dict, templates: dict,
                     h3_provider, doc_path: Path, arm: str) -> DocumentRun:
    memory_on = ARM_MEMORY_ON[arm]
    session = client.init_session()
    client.upload_document(session, doc_path.name, doc_path.read_bytes())

    edit = client.chat_with_retry(
        session, GENERIC_INSTRUCTION, attempts=3, backoff=2,
        approval_mode="approve_all",
        cross_session_memory=memory_on,
        cross_session_memory_key=MEMORY_ON_KEY if memory_on else None,
        cross_session_search=False)

    before_text = client.export_document(session, "markdown")
    score_before = score_document(before_text, rubric, h3_provider)
    corr = corrections_from_score(score_before, templates)

    correction_billed, correction_charged = False, 0
    after_text = before_text
    score_after = score_before
    if corr.corrections:
        correction = client.chat_with_retry(
            session, corr.payload, attempts=3, backoff=2,
            approval_mode="approve_all",
            cross_session_memory=memory_on,
            cross_session_memory_key=MEMORY_ON_KEY if memory_on else None,
            cross_session_search=False)
        correction_billed = correction.was_billable
        correction_charged = correction.ops_charged
        after_text = client.export_document(session, "markdown")
        score_after = score_document(after_text, rubric, h3_provider)

    return DocumentRun(
        document=doc_path.name, arm=arm, session_id=session,
        edit_billed=edit.was_billable, edit_ops_charged=edit.ops_charged,
        score_before=_score_dict(score_before),
        corrections_sent=len(corr.corrections),
        rules_violated=corr.rules_violated,
        correction_billed=correction_billed,
        correction_ops_charged=correction_charged,
        score_after=_score_dict(score_after),
        total_ops=edit.ops_charged + correction_charged)


def run_arm(client: SuperDocsClient, rubric: dict, templates: dict,
           h3_provider, documents: list[Path], arm: str,
           log=print) -> ArmResult:
    result = ArmResult(arm=arm)
    if arm == "memory_on":
        removed = client.clear_cross_session_memory(MEMORY_ON_KEY)
        result.memory_wipe_removed = removed
        log(f"  wiped {MEMORY_ON_KEY!r} before starting: removed={removed} "
            f"(expected 0 on a key never used before)")
    for doc_path in documents:
        log(f"  {doc_path.name} [{arm}] ...")
        run = run_one_document(client, rubric, templates, h3_provider,
                               doc_path, arm)
        result.documents.append(run)
        log(f"    edit billed={run.edit_billed} charged={run.edit_ops_charged}"
            f"  before={run.score_before['totals']['total_raw']}"
            f"  corrections_sent={run.corrections_sent}"
            f"  correction billed={run.correction_billed}"
            f"  after={run.score_after['totals']['total_raw']}"
            f"  ops={run.total_ops}")
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3,
                    help="documents per arm (default 3, the dev sample)")
    ap.add_argument("--run-dir", type=str, default="runs/n3_pilot")
    ap.add_argument("--arms", nargs="+", default=list(ARMS), choices=ARMS)
    ap.add_argument("--start-index", type=int, default=0,
                    help="preflight arm_index to start counting from — set "
                         "this when invoking a single arm as its own process "
                         "call against a run_dir that already has earlier "
                         "arms in it, so the non-empty-cache-from-arm-1 check "
                         "and run_manifest.json see the true chronological "
                         "position rather than restarting at 0")
    ap.add_argument("--merge-results", action="store_true",
                    help="merge into an existing results.json instead of "
                         "overwriting it (for multi-process staged runs)")
    args = ap.parse_args(argv)

    if args.n > 3:
        print(f"NOTE: running n={args.n} (dev sample is 3). Log this in "
              "PROGRESS.md before proceeding.", file=sys.stderr)

    documents = sorted(CORPUS_DIR.glob("doc_*.md"))[:args.n]
    if len(documents) < args.n:
        print(f"only {len(documents)} corpus documents available",
             file=sys.stderr)
        return 2

    rubric = load_rubric("meridian")
    templates = load_templates()
    run_dir = ROOT / args.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)

    cache_path = run_dir / "h3_cache.json"
    if not cache_path.exists():
        cache_path.write_text("{}\n", encoding="utf-8")

    versions = {"rubric": rubric["version"], "templates": templates["version"],
               "h3_prompt": "h3_passive_v1"}

    gemini_key = config.get("GEMINI_API_KEY")
    if not gemini_key:
        print("GEMINI_API_KEY is not set; H3 cannot be scored live.",
             file=sys.stderr)
        return 1
    cache = H3Cache(cache_path)
    h3_provider = _CachedH3Provider(GeminiH3Provider(gemini_key), cache)

    client = SuperDocsClient(MCPHttpTransport())

    results: dict[str, ArmResult] = {}
    for offset, arm in enumerate(args.arms):
        arm_index = args.start_index + offset
        try:
            # expected_documents checks the FULL committed corpus is intact
            # (always 20) — a corpus-integrity check, independent of how many
            # of them this particular run samples via --n.
            run_preflight(run_dir, arm_index, versions, expected_documents=20)
        except PreflightError as exc:
            print(f"PREFLIGHT ABORTED before arm {arm!r}: {exc}",
                 file=sys.stderr)
            return 3
        print(f"\n=== arm: {arm} (index {arm_index}) ===")
        results[arm] = run_arm(client, rubric, templates, h3_provider,
                               documents, arm)
        pin_versions(run_dir, versions, arm_index)

    new_results = {arm: {"memory_wipe_removed": r.memory_wipe_removed,
                         "total_ops": r.total_ops,
                         "documents": [asdict(d) for d in r.documents]}
                  for arm, r in results.items()}
    out_path = run_dir / "results.json"
    if args.merge_results and out_path.exists():
        existing = json.loads(out_path.read_text("utf-8"))
        existing["results"].update(new_results)
        existing["arms"] = sorted(set(existing.get("arms", [])) | set(args.arms))
        existing["ledger"] = client.ledger.as_dict()
        out = existing
    else:
        out = {"n": args.n, "arms": args.arms, "versions": versions,
              "documents": [d.name for d in documents],
              "results": new_results, "ledger": client.ledger.as_dict()}
    out_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"\nwritten: {out_path}")
    print(f"total SuperDocs operations spent this process: "
         f"{client.ledger.total_operations}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
