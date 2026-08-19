from __future__ import annotations

import csv
import json
import statistics
from collections import Counter
from pathlib import Path

from .config import Settings
from .db import Database


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
    db = Database(Settings.from_env().db_path)
    benchmark_run = db.one(
        "SELECT * FROM benchmark_runs WHERE selected=1 ORDER BY id DESC LIMIT 1"
    )
    if not benchmark_run:
        raise RuntimeError("No benchmark run is selected")

    rows = db.all(
        """
        WITH latest AS (
          SELECT r.case_id, MAX(r.id) attempt_id
          FROM runs r
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
          r.verdict,
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

    pass_count = sum(row["verdict"] == "pass" for row in rows)
    fail_count = sum(row["verdict"] == "fail" for row in rows)
    if len(rows) != 40 or pass_count != 25 or fail_count != 15:
        raise RuntimeError(
            f"Expected 40 cases / 25 pass / 15 fail; found "
            f"{len(rows)} / {pass_count} / {fail_count}"
        )
    if any(row["verdict"] not in {"pass", "fail"} for row in rows):
        raise RuntimeError("Every final official case must be adjudicated pass or fail")

    def breakdown(case_type: str) -> dict:
        selected = [row for row in rows if row["case_type"] == case_type]
        passed = sum(row["verdict"] == "pass" for row in selected)
        return {
            "total": len(selected),
            "pass": passed,
            "fail": len(selected) - passed,
            "pass_rate": passed / len(selected) if selected else 0,
        }

    latencies = [float(row["latency_ms"]) for row in rows if row["latency_ms"] is not None]
    behavior_counts = {
        behavior: {
            "total": sum(row["expected_behavior"] == behavior for row in rows),
            "pass": sum(
                row["expected_behavior"] == behavior and row["verdict"] == "pass"
                for row in rows
            ),
            "fail": sum(
                row["expected_behavior"] == behavior and row["verdict"] == "fail"
                for row in rows
            ),
        }
        for behavior in ("should_clarify", "no_target")
    }
    summary = {
        "benchmark_run_id": benchmark_run["id"],
        "benchmark_run_name": benchmark_run["name"],
        "selection_rule": "Latest execution attempt per official case in the selected benchmark run",
        "total_cases": len(rows),
        "pass": pass_count,
        "fail": fail_count,
        "pass_rate": pass_count / len(rows),
        "search_question": breakdown("search"),
        "edit": breakdown("edit"),
        "latency_ms": {
            "count": len(latencies),
            "average": rounded(statistics.mean(latencies)) if latencies else None,
            "median": rounded(statistics.median(latencies)) if latencies else None,
            "p95": rounded(percentile(latencies, 0.95)),
            "sample_standard_deviation": rounded(statistics.stdev(latencies))
            if len(latencies) > 1
            else None,
        },
        "total_api_reported_operations_charged": sum(
            int(row["reported_operations"] or 0) for row in rows
        ),
        "failure_taxonomy_counts": dict(
            sorted(
                Counter(
                    row["failure_reason"]
                    for row in rows
                    if row["verdict"] == "fail" and row["failure_reason"]
                ).items()
            )
        ),
        "expected_behavior_counts": behavior_counts,
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
        "verdict",
        "failure_reason",
        "reviewer_note",
        "latency_ms",
        "reported_operations",
        "attempt_id",
        "benchmark_run_id",
        "execution_status",
    ]
    with (OUTPUT_DIR / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({key: row.get(key) for key in fieldnames} for row in rows)
    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary


if __name__ == "__main__":
    print(json.dumps(export(), indent=2))
