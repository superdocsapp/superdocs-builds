"""The wipe test.

Not "the wipe call returned success" — a subsequent edit, under the same key,
on a fresh document, showing no trace of what was taught before the wipe.

Protocol, all under one fresh memory_key never used elsewhere this session:

1. Document A: agent edit, then (if needed) a scripted correction teaching
   H13 (acronym expansion) and H7 (Author, Year citation form) — chosen
   because they are house-specific conventions, not generic "good writing"
   defaults a base model would apply unprompted (H1/H8/H9/H11 were observed
   to be baseline-satisfied in the n=3 pilot; H13/H7 were not).
2. Document B: FRESH session, same key, same violation shapes, generic
   instruction only. If memory is doing anything, B should need less
   correction than A did — this is the positive control, run BEFORE any
   wipe, so there is a real signal to wipe in the first place.
3. clear_cross_session_memory(key) — the wipe. Removed-count logged.
4. Document C: FRESH session, same key, same violation shapes, generic
   instruction only. If the wipe genuinely wiped, C should look like A
   (uncorrected), not like B (corrected) — the wipe undoes the positive
   control, not just returns {"removed": N}.

If step 2 shows no learning signal at all, that is reported as such rather
than forced into a claim the data does not support — the wipe cannot be
meaningfully demonstrated against a signal that was never established.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from checker.h3 import MockH3Provider
from checker.score import load_rubric, score_document
from corrections.generator import corrections_from_score, load_templates
from runner.experiment import GENERIC_INSTRUCTION
from superdocs.client import SuperDocsClient
from superdocs.mcp_transport import MCPHttpTransport

ROOT = Path(__file__).resolve().parent.parent
WIPE_KEY = "wipe_test_probe"

DOC_A = ("<h1>Retention review</h1><p>ARR grew across the period. "
        "The finding appears in the register (see Harlow 2024).</p>")
DOC_B = ("<h1>Delivery review</h1><p>NRR held across the period. "
        "The finding appears in the register (see Okafor 2023).</p>")
DOC_C = ("<h1>Pipeline review</h1><p>CAC moved little across the period. "
        "The finding appears in the register (see Delgado 2025).</p>")

TARGET_RULES = ("H13", "H7")


@dataclass
class ProbeResult:
    label: str
    session_id: str
    edit_ops_charged: int
    score_before: dict
    corrections_sent: int
    correction_ops_charged: int
    target_violations_before: int


def _target_count(score) -> int:
    return sum(score.rules[r].count_raw for r in TARGET_RULES
              if r in score.rules)


def probe(client: SuperDocsClient, rubric, templates, doc_html: str,
         label: str, teach: bool) -> ProbeResult:
    session = client.init_session()
    edit = client.chat_with_retry(
        session, GENERIC_INSTRUCTION, attempts=3, backoff=2,
        approval_mode="approve_all", document_html=doc_html,
        cross_session_memory=True, cross_session_memory_key=WIPE_KEY,
        cross_session_search=False)
    text = client.export_document(session, "markdown")
    score = score_document(text, rubric, MockH3Provider())
    before = _target_count(score)

    correction_charged = 0
    sent = 0
    if teach and before > 0:
        corr = corrections_from_score(score, templates)
        target_corr = [c for c in corr.corrections if c.rule_id in TARGET_RULES]
        if target_corr:
            payload = "\n".join(f"{i}. {c.message}"
                                for i, c in enumerate(target_corr, 1))
            correction = client.chat_with_retry(
                session, payload, attempts=3, backoff=2,
                approval_mode="approve_all", cross_session_memory=True,
                cross_session_memory_key=WIPE_KEY, cross_session_search=False)
            correction_charged = correction.ops_charged
            sent = len(target_corr)

    return ProbeResult(label=label, session_id=session,
                       edit_ops_charged=edit.ops_charged,
                       score_before=score.as_dict(), corrections_sent=sent,
                       correction_ops_charged=correction_charged,
                       target_violations_before=before)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=str, default="runs/wipe_test")
    args = ap.parse_args(argv)

    rubric = load_rubric("meridian")
    templates = load_templates()
    run_dir = ROOT / args.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)

    client = SuperDocsClient(MCPHttpTransport())

    print("1. Document A: teach H13/H7 under a fresh key")
    a = probe(client, rubric, templates, DOC_A, "A_teach", teach=True)
    print(f"   target violations before correction: {a.target_violations_before}"
         f"  corrections_sent={a.corrections_sent}")

    print("\n2. Document B: fresh session, SAME key, generic instruction only "
         "(positive control, pre-wipe)")
    b = probe(client, rubric, templates, DOC_B, "B_pre_wipe", teach=False)
    print(f"   target violations (should be LOWER than A's if memory "
         f"helped): {b.target_violations_before}")

    print("\n3. Wipe")
    removed = client.clear_cross_session_memory(WIPE_KEY)
    print(f"   clear_cross_session_memory({WIPE_KEY!r}) -> removed={removed}")

    print("\n4. Document C: fresh session, SAME key, generic instruction only "
         "(post-wipe)")
    c = probe(client, rubric, templates, DOC_C, "C_post_wipe", teach=False)
    print(f"   target violations (should be back to A-like if wipe worked): "
         f"{c.target_violations_before}")

    signal_established = a.target_violations_before > 0
    learning_observed = signal_established and b.target_violations_before < a.target_violations_before
    wipe_confirmed = learning_observed and c.target_violations_before >= b.target_violations_before + 1 \
        if learning_observed else None

    verdict = {
        "signal_established": signal_established,
        "learning_observed_pre_wipe": learning_observed,
        "wipe_confirmed_by_behavioural_reversion": wipe_confirmed,
        "note": ("wipe_confirmed is None when no learning signal was ever "
                "established (nothing to wipe), True/False only when a "
                "genuine before/after behavioural comparison was possible."),
    }
    print("\n=== verdict ===")
    print(json.dumps(verdict, indent=2))

    out = {"a_teach": asdict(a), "b_pre_wipe": asdict(b),
          "wipe_removed": removed, "c_post_wipe": asdict(c),
          "verdict": verdict, "ledger": client.ledger.as_dict()}
    out_path = run_dir / "results.json"
    out_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"\nwritten: {out_path}")
    print(f"total SuperDocs operations spent: {client.ledger.total_operations}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
