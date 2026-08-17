from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

WEIGHTS = {
    "criterion_1_score": 30,
    "criterion_2_score": 20,
    "criterion_3_score": 20,
    "criterion_4_score": 15,
    "criterion_5_score": 15,
}

CRITERIA = list(WEIGHTS.keys())
DATA_PATH = Path(__file__).resolve().parent / "data" / "scored_accounts.csv"


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


with DATA_PATH.open("r", encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle))

ensure(len(rows) == 80, f"Expected 80 rows, found {len(rows)}")

companies = [row["company"] for row in rows]
ensure(len(set(companies)) == len(companies), "Duplicate companies detected")

for row in rows:
    ensure(row["company"].strip(), "Missing company")
    ensure(row["vertical"].strip(), "Missing vertical")
    ensure(row["specific_use_case"].strip(), "Missing specific_use_case")
    ensure(row["buyer_function"].strip(), "Missing buyer_function")
    ensure(row["evidence"].strip(), "Missing evidence")
    ensure(row["rationale"].strip(), "Missing rationale")
    ensure(row["confidence"].strip(), "Missing confidence")

    ensure("@" not in row["company"], f"Email-like text in company name: {row['company']}")
    ensure("@" not in row["evidence"], f"Email-like text in evidence: {row['evidence']}")
    ensure(not re.search(r"\b\d{3}[-. ]?\d{3}[-. ]?\d{4}\b", row["evidence"]), "Telephone number found in evidence")
    ensure("linkedin.com" not in row["evidence"].lower(), "LinkedIn URL found in evidence")
    ensure("linkedin.com" not in row["company"].lower(), "LinkedIn URL found in company")

    for key in CRITERIA:
        value = float(row[key])
        ensure(0 <= value <= WEIGHTS[key], f"{key} out of range for {row['company']}: {value}")

    total = float(row["total_score"])
    expected_total = round(sum(float(row[k]) for k in CRITERIA), 1)
    ensure(abs(total - expected_total) < 0.01, f"Total mismatch for {row['company']}: {total} != {expected_total}")

    ensure(row["confidence"] in {"High", "Medium", "Low"}, f"Invalid confidence for {row['company']}: {row['confidence']}")

vertical_counts = Counter(row["vertical"] for row in rows)
ensure(sum(vertical_counts.values()) == 80, "Vertical counts do not sum to 80")

for name, count in vertical_counts.items():
    ensure(count > 0, f"Vertical without companies: {name}")

# Additional checks to ensure differentiation and dataset quality.
all_totals = [float(row["total_score"]) for row in rows]
ensure(max(all_totals) - min(all_totals) >= 20, "Score spread too small to differentiate accounts")

print("Validation passed.")
print(f"Rows checked: {len(rows)}")
print(f"Unique companies: {len(set(companies))}")
print(f"Vertical distribution: {dict(vertical_counts)}")
print(f"Score range: {min(all_totals):.1f} - {max(all_totals):.1f}")
print(f"Weight total: {sum(WEIGHTS.values())}")
