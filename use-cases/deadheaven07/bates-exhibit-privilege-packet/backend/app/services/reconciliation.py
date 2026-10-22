from dataclasses import dataclass
from typing import Any


@dataclass
class ReconciliationResult:
    """Result of page-count reconciliation verification."""

    is_valid: bool
    total_packet_pages: int
    sum_bates_pages: int
    discrepancies: list[str]
    proof: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "reconciliation_passed": self.is_valid,
            "total_packet_pages": self.total_packet_pages,
            "sum_bates_pages": self.sum_bates_pages,
            "discrepancies": self.discrepancies,
            "proof": self.proof,
        }


def compute_bates_range_pages(bates_start: str, bates_end: str, prefix: str) -> int:
    """Compute number of pages in a Bates range."""
    import re

    def extract_number(bates: str) -> int:
        match = re.search(r"(\d+)$", bates)
        if not match:
            raise ValueError(f"Cannot extract number from Bates: {bates}")
        return int(match.group(1))

    start_num = extract_number(bates_start)
    end_num = extract_number(bates_end)

    if end_num < start_num:
        raise ValueError(f"Bates end ({bates_end}) < start ({bates_start})")

    return end_num - start_num + 1


def verify_reconciliation(
    manifest_entries: list[dict[str, Any]], total_packet_pages: int, packet_prefix: str
) -> ReconciliationResult:
    """
    Perform strict mathematical proof: Total Packet Page Count == Sum of All Exhibit Bates Ranges.

    Args:
        manifest_entries: List of exhibit entries with bates_start, bates_end, page_count
        total_packet_pages: Total pages in final packet (including cover sheets)
        packet_prefix: The Bates prefix used for this packet

    Returns:
        ReconciliationResult with boolean validity and detailed proof
    """
    discrepancies = []
    proof_steps = []

    # Step 1: Calculate sum of Bates range pages per exhibit
    exhibit_calculations = []
    sum_bates_pages = 0

    for entry in manifest_entries:
        bates_start = entry.get("bates_start", "")
        bates_end = entry.get("bates_end", "")
        exhibit_id = entry.get("exhibit_identifier", "UNKNOWN")
        page_count = entry.get("page_count", 0)

        if bates_start and bates_end and bates_start != "N/A" and bates_end != "N/A":
            try:
                bates_pages = compute_bates_range_pages(bates_start, bates_end, packet_prefix)
                sum_bates_pages += bates_pages
                exhibit_calculations.append(
                    {
                        "exhibit": exhibit_id,
                        "bates_start": bates_start,
                        "bates_end": bates_end,
                        "bates_pages": bates_pages,
                        "manifest_page_count": page_count,
                    }
                )
                proof_steps.append(
                    f"{exhibit_id}: Bates {bates_start} to {bates_end} = {bates_pages} pages"
                )
            except ValueError as e:
                discrepancies.append(f"{exhibit_id}: {e}")
        else:
            discrepancies.append(
                f"{exhibit_id}: Missing or invalid Bates range ({bates_start} - {bates_end})"
            )

    proof_steps.append(f"Sum of Bates range pages = {sum_bates_pages}")

    # Step 2: Total packet pages (includes cover sheets)
    proof_steps.append(f"Total packet pages (manifest) = {total_packet_pages}")

    # Step 3: Calculate expected total (Bates pages + cover sheets)
    num_exhibits = len([e for e in manifest_entries if e.get("bates_start") != "N/A"])
    expected_total = sum_bates_pages + num_exhibits
    proof_steps.append(
        f"Expected total (Bates pages + {num_exhibits} cover sheets) = {expected_total}"
    )

    # Step 4: Verify
    is_valid = True

    if total_packet_pages != expected_total:
        discrepancies.append(
            f"Page count mismatch: manifest total_pages={total_packet_pages} "
            f"!= expected={expected_total} (sum_bates={sum_bates_pages} + covers={num_exhibits})"
        )
        is_valid = False

    # Also verify each exhibit's page_count matches its Bates range + 1 (cover)
    for calc in exhibit_calculations:
        expected_exhibit_pages = calc["bates_pages"] + 1  # +1 for cover sheet
        if calc["manifest_page_count"] != expected_exhibit_pages:
            discrepancies.append(
                f"{calc['exhibit']}: page_count={calc['manifest_page_count']} "
                f"!= expected={expected_exhibit_pages} (bates={calc['bates_pages']} + cover=1)"
            )
            is_valid = False

    proof = {
        "steps": proof_steps,
        "invariant": (
            "Total Packet Pages == Sum(Exhibit Bates Pages) + Number of Exhibits (cover sheets)"
        ),
        "exhibit_calculations": exhibit_calculations,
        "sum_bates_pages": sum_bates_pages,
        "num_exhibits": num_exhibits,
        "expected_total": expected_total,
        "actual_total": total_packet_pages,
    }

    return ReconciliationResult(
        is_valid=is_valid,
        total_packet_pages=total_packet_pages,
        sum_bates_pages=sum_bates_pages,
        discrepancies=discrepancies,
        proof=proof,
    )


def generate_reconciliation_readme(result: ReconciliationResult) -> str:
    """Generate a README.md summary section for the reconciliation proof."""
    status = "✅ PASSED" if result.is_valid else "❌ FAILED"

    lines = [
        "## Page-Count Reconciliation Proof",
        "",
        f"**Status:** {status}",
        "",
        "### Invariant Verified",
        "> Total Packet Page Count == Sum of All Exhibit Bates Ranges "
        "((End Bates - Start Bates) + 1) + Cover Sheets",
        "",
        "### Proof Steps",
        "",
    ]

    for step in result.proof.get("steps", []):
        lines.append(f"- {step}")

    lines.extend(["", "### Exhibit Breakdown", ""])

    for calc in result.proof.get("exhibit_calculations", []):
        lines.append(
            f"- **{calc['exhibit']}**: Bates {calc['bates_start']}–{calc['bates_end']} "
            f"= {calc['bates_pages']} content pages + 1 cover = {calc['bates_pages'] + 1} total"
        )

    lines.extend(
        [
            "",
            "### Summary",
            f"- **Sum of Bates content pages**: {result.sum_bates_pages}",
            f"- **Number of exhibits (cover sheets)**: {result.proof.get('num_exhibits', 0)}",
            f"- **Expected total**: {result.proof.get('expected_total', 0)}",
            f"- **Actual total (manifest)**: {result.total_packet_pages}",
            "",
        ]
    )

    if result.discrepancies:
        lines.append("### ⚠️ Discrepancies Found")
        for d in result.discrepancies:
            lines.append(f"- {d}")
        lines.append("")

    return "\n".join(lines)
