from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

from .config import Settings
from .db import Database
from .service import BenchmarkService
from .superdocs import FakeSuperDocsClient
from .targeting import PUBLIC_FAILURE_DEFINITIONS, assess_targeting, verdict_summary


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "final_run"


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def rounded(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def export() -> dict:
    settings=Settings.from_env(); db = Database(settings.db_path)
    benchmark_run = db.one("SELECT * FROM benchmark_runs WHERE selected=1")
    if not benchmark_run:
        raise RuntimeError("No benchmark run is selected")

    rows = db.all(
        """
        WITH latest AS (
          SELECT r.case_id, MAX(r.id) attempt_id
          FROM runs r
          JOIN benchmark_run_cases brc ON brc.benchmark_run_id=r.benchmark_run_id AND brc.case_id=r.case_id
          JOIN cases c ON c.id = r.case_id
          WHERE r.benchmark_run_id = ? AND c.external_case_id IS NOT NULL
          GROUP BY r.case_id
        )
        SELECT
          c.external_case_id case_id,
          d.external_document_id document_id,
          d.filename document,
          c.case_type,
          c.expected_behavior,
          c.expected_section_path expected_target,
          c.acceptable_section_paths_json,
          c.must_not_target_json,
          r.verdict strict_verdict,
          f.name failure_category,
          f.name failure_reason,
          r.adjudication_note reviewer_note,
          r.latency_ms,
          r.operations_charged reported_operations,
          r.id attempt_id,
          r.benchmark_run_id,
          r.status execution_status
        FROM latest l
        JOIN runs r ON r.id = l.attempt_id
        JOIN cases c ON c.id = r.case_id
        JOIN documents d ON d.id = c.document_id
        LEFT JOIN failure_categories f ON f.id = r.failure_category_id
        ORDER BY c.external_case_id
        """,
        (benchmark_run["id"],),
    )

    for row in rows:
        row.update(assess_targeting(row))

    pass_count = sum(row["strict_verdict"] == "pass" for row in rows)
    fail_count = sum(row["strict_verdict"] == "fail" for row in rows)
    expected_total=int(benchmark_run.get("corpus_case_total") or 0)
    if len(rows) != expected_total or pass_count + fail_count != expected_total:
        raise RuntimeError(
            f"Selected final run is incomplete: expected {expected_total} adjudicated cases; found "
            f"{len(rows)} cases / {pass_count} pass / {fail_count} fail"
        )
    if any(row["strict_verdict"] not in {"pass", "fail"} for row in rows):
        raise RuntimeError("Every final official case must be adjudicated pass or fail")

    def breakdown(case_type: str, field: str) -> dict:
        selected = [row for row in rows if row["case_type"] == case_type]
        return verdict_summary(selected,field)

    latencies = [float(row["latency_ms"]) for row in rows if row["latency_ms"] is not None]
    behavior_counts = {
        behavior: {
            "total": sum(row["expected_behavior"] == behavior for row in rows),
            "pass": sum(
                row["expected_behavior"] == behavior and row["strict_verdict"] == "pass"
                for row in rows
            ),
            "fail": sum(
                row["expected_behavior"] == behavior and row["strict_verdict"] == "fail"
                for row in rows
            ),
        }
        for behavior in ("should_clarify", "no_target")
    }
    service_metrics=BenchmarkService(db,FakeSuperDocsClient()).metrics(benchmark_run["id"])
    summary = {
        "benchmark_run_id": benchmark_run["id"],
        "benchmark_run_name": benchmark_run["name"],
        "corpus_version": benchmark_run.get("corpus_version"),
        "selection_rule": "Latest execution attempt per official case in the selected complete official benchmark run",
        "total_cases": len(rows),
        "targeting": verdict_summary(rows,"targeting_verdict"),
        "strict": verdict_summary(rows,"strict_verdict"),
        "targeting_by_case_type": {"search":breakdown("search","targeting_verdict"),"edit":breakdown("edit","targeting_verdict")},
        "strict_by_case_type": {"search":breakdown("search","strict_verdict"),"edit":breakdown("edit","strict_verdict")},
        "latency_ms": {
            "count": len(latencies),
            "average": rounded(statistics.mean(latencies)) if latencies else None,
            "median": rounded(statistics.median(latencies)) if latencies else None,
            "p95": rounded(percentile(latencies, 0.95)),
            "sample_standard_deviation": rounded(statistics.stdev(latencies))
            if len(latencies) > 1
            else None,
            "sample_variance": rounded(statistics.variance(latencies))
            if len(latencies) > 1
            else None,
        },
        "total_api_reported_operations_charged": sum(
            int(row["reported_operations"] or 0) for row in rows
        ),
        "simplified_failure_taxonomy_counts": {category:sum(row.get("simplified_failure_category")==category for row in rows) for category in PUBLIC_FAILURE_DEFINITIONS},
        "budget": {"cap_operations":settings.max_batch_operations,"actual_api_reported_operations":sum(int(row["reported_operations"] or 0) for row in rows),"within_budget":sum(int(row["reported_operations"] or 0) for row in rows)<=settings.max_batch_operations,"dollar_spend_usd":None,"dollar_spend_note":"Dollar spend was not exposed by the stored API responses."},
        "expected_behavior_counts": behavior_counts,
        "secondary_experiments": {
            "applied_edit_verification": service_metrics["applied_verification"],
            "guided_recovery": service_metrics["guided_recovery"],
            "note": "Secondary experiments do not change the official first-attempt verdicts.",
        },
        "dollar_spend_usd": None,
        "dollar_spend_note": "Dollar spend was not exposed by the stored API responses.",
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "case_id",
        "document_id",
        "document",
        "case_type",
        "expected_behavior",
        "expected_target",
        "targeting_verdict",
        "strict_verdict",
        "simplified_failure_category",
        "targeting_reason",
        "failure_reason",
        "reviewer_note",
        "latency_ms",
        "reported_operations",
        "attempt_id",
        "benchmark_run_id",
        "execution_status",
    ]
    with (OUTPUT_DIR / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows({key: row.get(key) for key in fieldnames} for row in rows)
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary


if __name__ == "__main__":
    print(json.dumps(export(), indent=2))
