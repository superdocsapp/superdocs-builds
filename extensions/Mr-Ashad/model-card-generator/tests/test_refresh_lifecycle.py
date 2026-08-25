"""Tests for In-Place Evaluation Table Refresh and Human Narrative Preservation."""

import pytest
from pathlib import Path
from src.updater import (
    SectionBoundaryUpdater,
    AnchorNotFoundError,
    CorruptedAnchorError,
    EVAL_SECTION_START,
    EVAL_SECTION_END,
    EVAL_TIMESTAMP_START,
    EVAL_TIMESTAMP_END,
)


DOCUMENT_WITH_HUMAN_NARRATIVE = """# Model Card: Frontier-Nexus-99B

<div align="center">
| **Version** | **Release Date** |
| :---: | :---: |
| 1.0.0 | 2026-08-01 |
</div>

## 1. Executive Summary & Custom Human Commentary
This is a custom-written paragraph by the lead research scientist explaining the fine-tuning nuances.
**Important note on tokenization**: The tokenizer handles whitespace in code indentation with a custom byte-level fallback.

### Custom Safety Architecture
- Hand-crafted policy rule #1: Prohibit weaponized exploit creation.
- Hand-crafted policy rule #2: Do not execute unauthorized external subprocesses.

---

## 2. Intended Purpose
- Production coding assistant
- Analytical scientific report generation

---

## 3. Known Limitations
- The model exhibits degradation on questions requiring reasoning over >90k distractor tokens.
- Specialized legal dialect comprehension in non-English jurisdictions requires domain fine-tuning.

---

## 5. Quantitative Evaluations & Benchmarks

> **Evaluation Run Metadata**
> <!-- EVALUATION_TIMESTAMP_START -->
> - **Last Updated**: 2026-08-01 00:00:00 UTC
> - **Evaluation Run ID**: `run-original-001`
> - **Baseline Reference**: Legacy-Baseline-70B
> <!-- EVALUATION_TIMESTAMP_END -->

<!-- EVALUATION_SECTION_START -->
| Benchmark | Score |
| :--- | :---: |
| MMLU | 75.0% |
| GSM8K | 80.0% |
<!-- EVALUATION_SECTION_END -->

---

## 6. Safety, Alignment & Ethical Considerations
Human-written notes on bias assessment and red-teaming findings:
1. Conducted 400 person-hours of external red-teaming.
2. Verified zero-shot resistance to standard jailbreak suites (e.g. DAN 11.0, Tree-of-Attacks).

---

## 7. Custom Maintenance Notes
Contact the engineering on-call at ops-ai@example.org or page the rotation at #ai-ops-nexus.
"""


def test_eval_refresh_leaves_non_eval_text_100_percent_untouched():
    """Verify that updating evaluation tables leaves all narrative text strictly identical."""
    new_eval_tables = (
        "### Benchmark Performance (Run v2)\n"
        "| Benchmark | Metric | Current Score | Baseline | Delta |\n"
        "| :--- | :--- | :---: | :---: | :---: |\n"
        "| **MMLU** | Accuracy (5-shot) | **89.5%** | 75.0% | ▲ +14.5% |\n"
        "| **GSM8K** | Exact Match | **94.2%** | 80.0% | ▲ +14.2% |\n"
        "| **HumanEval** | Pass@1 | **88.0%** | — | — |"
    )

    new_timestamp = "2026-08-17 11:30:00 UTC"
    new_run_id = "run-refreshed-002"
    new_baseline = "Nexus-70B-Legacy"

    updated = SectionBoundaryUpdater.update_evaluation(
        document_content=DOCUMENT_WITH_HUMAN_NARRATIVE,
        new_eval_markdown=new_eval_tables,
        timestamp=new_timestamp,
        run_id=new_run_id,
        baseline_model=new_baseline,
    )

    # 1. Text BEFORE the timestamp anchor must match EXACTLY
    prefix_original = DOCUMENT_WITH_HUMAN_NARRATIVE.split(EVAL_TIMESTAMP_START)[0]
    prefix_updated = updated.split(EVAL_TIMESTAMP_START)[0]
    assert prefix_original == prefix_updated, "Text before evaluation timestamp was altered!"

    # 2. Text between timestamp end and eval start must match EXACTLY
    mid_orig = DOCUMENT_WITH_HUMAN_NARRATIVE.split(EVAL_TIMESTAMP_END)[1].split(EVAL_SECTION_START)[0]
    mid_updated = updated.split(EVAL_TIMESTAMP_END)[1].split(EVAL_SECTION_START)[0]
    assert mid_orig == mid_updated, "Text between timestamp and eval section was altered!"

    # 3. Text AFTER the eval section end must match EXACTLY
    suffix_original = DOCUMENT_WITH_HUMAN_NARRATIVE.split(EVAL_SECTION_END)[1]
    suffix_updated = updated.split(EVAL_SECTION_END)[1]
    assert suffix_original == suffix_updated, "Text after evaluation section was altered!"

    # 4. Confirm new contents are present inside anchors
    assert "89.5%" in updated
    assert "run-refreshed-002" in updated
    assert "2026-08-17 11:30:00 UTC" in updated
    assert "Nexus-70B-Legacy" in updated


def test_multiple_consecutive_refresh_cycles():
    """Verify that running multiple successive updates does not accumulate drift or duplicate anchors."""
    content = DOCUMENT_WITH_HUMAN_NARRATIVE

    for cycle in range(1, 5):
        eval_text = f"| Run {cycle} | Score {cycle * 10}% |"
        ts = f"2026-08-17 0{cycle}:00:00 UTC"
        run_id = f"run-cycle-{cycle}"

        content = SectionBoundaryUpdater.update_evaluation(
            document_content=content,
            new_eval_markdown=eval_text,
            timestamp=ts,
            run_id=run_id,
        )

        assert content.count(EVAL_SECTION_START) == 1
        assert content.count(EVAL_SECTION_END) == 1
        assert content.count(EVAL_TIMESTAMP_START) == 1
        assert content.count(EVAL_TIMESTAMP_END) == 1
        assert f"Score {cycle * 10}%" in content
        assert run_id in content

    # Check that original human comments survived all 4 cycles
    assert "Executive Summary & Custom Human Commentary" in content
    assert "Conducted 400 person-hours of external red-teaming" in content
    assert "ops-ai@example.org" in content


def test_missing_anchors_raise_clean_error():
    """Verify that missing start or end anchors raises AnchorNotFoundError rather than corrupting file."""
    corrupted_doc = "# Model Card\nNo anchors in this document.\n"

    with pytest.raises(AnchorNotFoundError) as exc_info:
        SectionBoundaryUpdater.update_evaluation(
            document_content=corrupted_doc,
            new_eval_markdown="new content"
        )
    assert "anchor not found" in str(exc_info.value).lower()


def test_file_in_place_update(tmp_path):
    """Test the SectionBoundaryUpdater.update_file_in_place helper on disk."""
    card_file = tmp_path / "test_model_card.md"
    card_file.write_text(DOCUMENT_WITH_HUMAN_NARRATIVE, encoding="utf-8")

    updated_text, modified = SectionBoundaryUpdater.update_file_in_place(
        card_file_path=card_file,
        new_eval_markdown="| Benchmark | Score |\n| MATH | 99% |",
        run_id="run-disk-test"
    )

    assert modified is True
    disk_content = card_file.read_text(encoding="utf-8")
    assert disk_content == updated_text
    assert "MATH" in disk_content
    assert "run-disk-test" in disk_content
    assert "Custom Safety Architecture" in disk_content
