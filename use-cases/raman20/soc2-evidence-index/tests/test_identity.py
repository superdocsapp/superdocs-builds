from soc2_index.diff import compute
from soc2_index.models import IndexDoc, IndexRow, Coverage


def _idx(rows):
    cov = Coverage(
        catalog_id="tsc-cc6-cc7",
        controls_total=1,
        present_rows=len(rows),
        present_controls=1,
        present_control_ids=["CC6.5"],
        gap_rows=0,
        unmapped_files=0,
        flagged_files=0,
        ambiguous_files=0,
    )
    return IndexDoc(
        catalog_id="tsc-cc6-cc7",
        catalog_sha256="00" * 32,
        org="x",
        period="y",
        generated_at="1970-01-01T00:00:00Z",
        rows=rows,
        coverage=cov,
    )


def test_rename_same_hash():
    sha = "ab" * 32
    old = _idx(
        [
            IndexRow(
                row_id="CC6.5::present::access/PHYS-2025-01.md",
                control_id="CC6.5",
                criterion="Physical access",
                status="Present",
                evidence_title="phys",
                date="2025-01-31",
                owner="Jordan Hale",
                source_path="access/PHYS-2025-01.md",
                sha256=sha,
            )
        ]
    )
    new = _idx(
        [
            IndexRow(
                row_id="CC6.5::present::access/PHYS-moved.md",
                control_id="CC6.5",
                criterion="Physical access",
                status="Present",
                evidence_title="phys",
                date="2025-01-31",
                owner="Jordan Hale",
                source_path="access/PHYS-moved.md",
                sha256=sha,
            )
        ]
    )
    d = compute(old, new, "a", "b")
    assert d.summary["renamed"] == 1
    assert d.renamed[0].from_row_id.endswith("PHYS-2025-01.md")
    assert d.renamed[0].to_row_id.endswith("PHYS-moved.md")
    assert d.added == []
    assert d.removed == []
