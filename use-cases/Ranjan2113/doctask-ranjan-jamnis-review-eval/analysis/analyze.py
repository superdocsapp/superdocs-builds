"""Turn raw decision events into results: kappa, timings, accuracy.

Usage:
    python analysis/analyze.py                # writes REPORT.md + raw_timings.csv
    python analysis/analyze.py --events X.jsonl --batches Y.json

Scoring joins events to ground truth by change_id here, at analysis time --
the only place both halves are legitimately in scope
(GROUND_TRUTH_SAFETY.md GT-6).

Two things this deliberately does NOT do:

  * No p-values. With 3-5 reviewers a significance test would dress a
    descriptive difference in inferential clothing it cannot support.
    PLAN.md.pdf section 7 asks for effect sizes and raw numbers instead.
  * No reporting on a corpus whose answer key drifted since pre-registration.
    verify_ground_truth raises rather than reporting against a key we cannot
    vouch for (GT-4).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from analysis.stats import (  # noqa: E402
    build_rating_matrix,
    describe,
    fleiss_kappa,
    interpret_kappa,
    proportion,
    wilson_interval,
)
from ground_truth import score_decisions, verify_ground_truth  # noqa: E402

STUDY_DATA = REPO / "study_data"
DEFAULT_EVENTS = STUDY_DATA / "raw_events.jsonl"
DEFAULT_BATCHES = STUDY_DATA / "batches.json"
REPORT_PATH = REPO / "REPORT.md"
TIMINGS_PATH = REPO / "analysis" / "raw_timings.csv"

# Hand-written prose, injected into the generated report. Kept in its own file
# so regenerating REPORT.md cannot destroy it -- the recommendation is the point
# of the study and must not be a casualty of re-running the analysis.
RECOMMENDATION_PATH = REPO / "RECOMMENDATION.md"


def load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_batches(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    batches = {}
    for batch in payload.get("batches", []):
        verify_ground_truth(batch)  # GT-4
        batches[batch["batch_id"]] = batch
    return batches


def latest_decisions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one decision per (reviewer, batch, change): the last one recorded.

    The event log is append-only, so a reviewer who changed their mind appears
    twice. Their final answer is the decision; the earlier one stays in the raw
    log for anyone who wants to study revisions, but counting both would let
    one reviewer vote twice on the same change.
    """
    keyed: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in events:
        key = (
            event.get("reviewer_id", ""),
            event.get("batch_id", ""),
            event.get("reviewer_change_id", ""),
        )
        keyed[key] = event  # later events overwrite earlier ones
    return list(keyed.values())


def score_all(
    events: list[dict[str, Any]], batches: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for batch_id, batch in batches.items():
        relevant = [e for e in events if e.get("batch_id") == batch_id]
        scored.extend(score_decisions(relevant, batch))
    return scored


def by_condition(scored: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scored:
        grouped[row["condition"]].append(row)
    return dict(grouped)


def kappa_for(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Fleiss' kappa across reviewers within one condition."""
    decisions: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if row["decision"] in ("approve", "reject"):
            decisions[row["source_change_id"]].append(row["decision"])

    n_reviewers = len({row["reviewer_id"] for row in rows})
    if n_reviewers < 2:
        return {
            "kappa": None,
            "note": f"only {n_reviewers} reviewer(s); kappa needs at least 2",
            "n_changes": len(decisions),
            "n_reviewers": n_reviewers,
        }

    matrix, excluded = build_rating_matrix(decisions)
    if not matrix:
        return {
            "kappa": None,
            "note": "no change was rated by every reviewer",
            "n_changes": 0,
            "n_reviewers": n_reviewers,
            "excluded_changes": excluded,
        }

    value = fleiss_kappa(matrix)
    return {
        "kappa": value,
        "interpretation": interpret_kappa(value),
        "n_changes": len(matrix),
        "n_reviewers": n_reviewers,
        "excluded_changes": excluded,
    }


def accuracy_for(rows: list[dict[str, Any]]) -> dict[str, Any]:
    judged = [r for r in rows if r["correct"] is not None]
    correct = sum(1 for r in judged if r["correct"])
    low, high = wilson_interval(correct, len(judged))

    # Which error types slip through: a reviewer wrongly approving a seeded-bad
    # change is the failure mode that matters most in deployment.
    missed: dict[str, int] = defaultdict(int)
    for row in judged:
        if not row["correct"] and row["decision"] == "approve":
            missed[row.get("expected_error_kind") or "unknown"] += 1

    return {
        "n": len(judged),
        "correct": correct,
        "accuracy": proportion(correct, len(judged)),
        "ci95": (low, high),
        "missed_by_error_kind": dict(missed),
    }


def timings_for(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [r["decision_ms"] for r in rows if isinstance(r.get("decision_ms"), int)]
    summary = dict(describe(values))
    render = [
        r["render_to_decision_ms"]
        for r in rows
        if isinstance(r.get("render_to_decision_ms"), int)
    ]
    if render:
        summary["render_median"] = describe(render).get("median")
    return summary


# Below this, a "decision" is too fast to be a reading of a contract clause.
# Not a hard error -- an obvious change can be judged quickly -- but a run made
# mostly of these is a click-through, which pilot run 1 was in its later
# conditions. Surfaced rather than silently averaged in.
CLICK_THROUGH_MS = 2000


def quality_for(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Signals that the decisions may not reflect real review."""
    timed = [r for r in rows if isinstance(r.get("decision_ms"), int)]
    fast = [r for r in timed if r["decision_ms"] < CLICK_THROUGH_MS]
    unengaged = [r for r in rows if r.get("was_engaged") is False]
    verdicts = {r["decision"] for r in rows}

    return {
        "n": len(rows),
        "n_under_2s": len(fast),
        "pct_under_2s": proportion(len(fast), len(timed)) if timed else 0.0,
        "n_no_engagement_signal": len(unengaged),
        "single_verdict_only": len(verdicts) == 1 and len(rows) > 2,
        "verdicts_used": sorted(verdicts),
    }


def analyse(
    events: list[dict[str, Any]], batches: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    deduped = latest_decisions(events)
    scored = score_all(deduped, batches)
    grouped = by_condition(scored)

    return {
        "n_events_raw": len(events),
        "n_decisions_scored": len(scored),
        "n_reviewers": len({r["reviewer_id"] for r in scored}),
        "conditions": {
            condition: {
                "timing_ms": timings_for(rows),
                "accuracy": accuracy_for(rows),
                "agreement": kappa_for(rows),
                "quality": quality_for(rows),
            }
            for condition, rows in sorted(grouped.items())
        },
        "overall": {
            "timing_ms": timings_for(scored),
            "accuracy": accuracy_for(scored),
            "quality": quality_for(scored),
        },
        "scored_rows": scored,
    }


def write_timings_csv(scored: list[dict[str, Any]], path: Path) -> None:
    """Published raw timings. Reviewer ids are already pseudonyms (R1, R2...).

    Includes `correct`, which is safe here: this file is produced after data
    collection, never served to a reviewer.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "reviewer_id",
                "condition",
                "batch_id",
                "change_id",
                "decision",
                "decision_ms",
                "render_to_decision_ms",
                "was_engaged",
                "correct",
                "expected_error_kind",
            ]
        )
        for row in sorted(scored, key=lambda r: (r["reviewer_id"], r["condition"])):
            writer.writerow(
                [
                    row["reviewer_id"],
                    row["condition"],
                    row["batch_id"],
                    row["source_change_id"],
                    row["decision"],
                    row.get("decision_ms", ""),
                    row.get("render_to_decision_ms", ""),
                    row.get("was_engaged", ""),
                    row["correct"],
                    row.get("expected_error_kind") or "",
                ]
            )


def _fmt_ms(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{value / 1000:.1f}s"


def load_recommendation(path: Path = RECOMMENDATION_PATH) -> str:
    """The hand-written recommendation, or a visible placeholder.

    A missing recommendation is stated as missing rather than passed over: a
    report that quietly omits its conclusion reads like a report that has one.
    """
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return (
        "## Recommendation\n\n"
        "> **Not yet written.** `RECOMMENDATION.md` is absent, so this report "
        "contains measurements and no conclusion."
    )


def render_report(results: dict[str, Any], recommendation: str | None = None) -> str:
    n_rev = results["n_reviewers"]
    lines: list[str] = [
        "# REPORT — how humans review AI-proposed edits",
        "",
        "Generated by `analysis/analyze.py`. Every number below is descriptive.",
        "",
        f"**N = {n_rev} reviewer(s), {results['n_decisions_scored']} scored decisions.**",
        "",
    ]

    if n_rev < 2:
        lines += [
            "> **This is not yet a result.** With fewer than two reviewers there is",
            "> no inter-reviewer agreement to measure and no basis for comparing",
            "> conditions. The numbers below describe what was collected, nothing more.",
            "",
        ]
    elif n_rev < 5:
        lines += [
            f"> **Small sample.** With {n_rev} reviewers, differences between",
            "> conditions are indicative at best. No significance testing is reported:",
            "> at this N a p-value would imply a precision the design cannot deliver.",
            "",
        ]

    lines += [
        "## Per condition",
        "",
        "| Condition | n | Median time | IQR | Accuracy | 95% CI | Fleiss' κ |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    for condition, block in results["conditions"].items():
        timing = block["timing_ms"]
        acc = block["accuracy"]
        agree = block["agreement"]
        kappa = agree.get("kappa")
        kappa_text = (
            f"{kappa:.2f} ({agree['interpretation']})" if kappa is not None else "—"
        )

        # A reviewer who used one verdict for everything has not discriminated,
        # so their "accuracy" is the corpus base rate wearing an accuracy label.
        # Suppressed exactly like an undefined kappa: printing 86% invites
        # someone to quote 86%.
        if block["quality"]["single_verdict_only"]:
            acc_text, ci_text = "— (single verdict)", "—"
        else:
            acc_text = f"{acc['correct']}/{acc['n']} ({acc['accuracy']:.0%})"
            ci_text = f"{acc['ci95'][0]:.0%}–{acc['ci95'][1]:.0%}"

        lines.append(
            f"| `{condition}` | {timing.get('n', 0)} | "
            f"{_fmt_ms(timing.get('median'))} | "
            f"{_fmt_ms(timing.get('q1'))}–{_fmt_ms(timing.get('q3'))} | "
            f"{acc_text} | {ci_text} | {kappa_text} |"
        )

    # Data quality comes BEFORE the findings: if the decisions were not real
    # review, nothing below the table means anything, and a reader should meet
    # that warning before they meet the numbers.
    overall_quality = results["overall"]["quality"]
    concerns: list[str] = []
    if overall_quality["single_verdict_only"]:
        concerns.append(
            f"**Every decision was `{overall_quality['verdicts_used'][0]}`.** The reviewer "
            "never used the other verdict, so nothing here measures discrimination. "
            "Per-condition accuracy is suppressed in the table above rather than printed: "
            "the figure would be the corpus base rate wearing an accuracy label. The "
            "error breakdown below is still informative — it says which seeded errors a "
            "blanket approval lets through — but it is a property of the corpus, not of "
            "the reviewer."
        )
    if overall_quality["pct_under_2s"] > 0.30:
        concerns.append(
            f"**{overall_quality['pct_under_2s']:.0%} of decisions took under 2 seconds** "
            f"({overall_quality['n_under_2s']} of {overall_quality['n']}), which is faster "
            "than reading a contract clause allows. Likely click-through."
        )
    if overall_quality["n_no_engagement_signal"]:
        concerns.append(
            f"{overall_quality['n_no_engagement_signal']} decision(s) arrived with no "
            "engagement signal, so their timing falls back to render time and is an "
            "upper bound rather than a measurement."
        )

    if concerns:
        lines += ["", "## Data quality warnings", ""]
        lines += [f"- {c}" for c in concerns]
        lines += [
            "",
            "Treat the per-condition figures above as provisional until a run without "
            "these warnings exists.",
        ]

    lines += ["", "### Per-condition quality", ""]
    lines += ["| Condition | <2s | No engagement signal | Verdicts used |", "| --- | --- | --- | --- |"]
    for condition, block in results["conditions"].items():
        q = block["quality"]
        lines.append(
            f"| `{condition}` | {q['n_under_2s']}/{q['n']} | "
            f"{q['n_no_engagement_signal']} | {', '.join(q['verdicts_used'])} |"
        )

    lines += ["", "## Errors that slipped through", ""]
    any_missed = False
    for condition, block in results["conditions"].items():
        missed = block["accuracy"]["missed_by_error_kind"]
        if missed:
            any_missed = True
            detail = ", ".join(f"{k}: {v}" for k, v in sorted(missed.items()))
            lines.append(f"- `{condition}` — wrongly approved: {detail}")
    if not any_missed:
        lines.append("- No seeded-bad change was wrongly approved.")

    lines += [
        "",
        "## Limitations",
        "",
        "- Ground truth is the study designer's pre-registered judgment, not an",
        "  independent legal expert's. A real deployment would want the latter.",
        "- Reviewers judged a static, pre-captured change batch rather than a live",
        "  SuperDocs session, which keeps the stimulus identical across reviewers",
        "  but removes the pressure of a real editing session.",
        "- The AI explanations attached to these changes are generic (all eight",
        "  edits were requested in one call to stay inside the operations budget),",
        "  so this study says nothing about how explanation quality affects review.",
        "- Condition order is counterbalanced by Latin square, but with N < 4 the",
        "  square is incomplete and order effects are not fully cancelled.",
        "- Decision time is measured from when the reviewer first reached a change,",
        "  not from when it rendered. In the batch conditions every change renders",
        "  at once, so render-to-click would include time spent on earlier changes.",
        "  `render_to_decision_ms` is retained in the raw data for batch-level",
        "  questions.",
        "",
        "## Raw data",
        "",
        "- `analysis/raw_timings.csv` — every scored decision, reviewer ids pseudonymised.",
        "- `study_data/raw_events.jsonl` — the append-only event log, including revisions.",
        "",
        "---",
        "",
    ]
    lines.append(
        recommendation if recommendation is not None else load_recommendation()
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--batches", type=Path, default=DEFAULT_BATCHES)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--timings", type=Path, default=TIMINGS_PATH)
    args = parser.parse_args(argv)

    events = load_events(args.events)
    batches = load_batches(args.batches)

    if not batches:
        print(f"No batches at {args.batches}. Run corpus_builder.py first.")
        return 1
    if not events:
        print(
            f"No decision events at {args.events} yet.\n"
            "Nothing to analyse until at least one reviewer has completed a session."
        )
        return 1

    results = analyse(events, batches)
    write_timings_csv(results["scored_rows"], args.timings)
    args.report.write_text(render_report(results), encoding="utf-8")

    print(f"reviewers        : {results['n_reviewers']}")
    print(f"decisions scored : {results['n_decisions_scored']}")
    print(f"wrote            : {args.report}")
    print(f"wrote            : {args.timings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
