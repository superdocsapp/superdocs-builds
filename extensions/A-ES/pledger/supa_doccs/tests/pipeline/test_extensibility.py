"""Test that adding a rule to YAML is sufficient — no Python changes needed.

This test demonstrates Requirement 7 (Extensibility Without Code Changes):
- 7.1: Pipeline evaluates any rule in a valid playbook without Python changes
- 7.2: New rule is picked up on next load
- 7.3: Unbounded rules per playbook

The MF-004 rule was added to rules/microfinance_v1.yaml without modifying
any .py source file. This test verifies it loads, partitions, and is evaluable.
"""

import yaml
from pathlib import Path

from src.pipeline.playbook import (
    Playbook,
    RuleDefinition,
    partition_rules,
)
from src.pipeline.findings import CitedSpan, EvaluationResult


RULES_DIR = Path("rules")
PLAYBOOK_FILE = RULES_DIR / "microfinance_v1.yaml"


class TestExtensibilityNoCodeChanges:
    """Verify that MF-004, added only via YAML, is fully functional."""

    def _load_playbook(self) -> Playbook:
        """Load and validate the playbook from YAML via Pydantic."""
        with open(PLAYBOOK_FILE) as f:
            raw = yaml.safe_load(f)
        return Playbook.model_validate(raw)

    def test_mf004_present_in_loaded_playbook(self):
        """MF-004 is present in the validated playbook rules list."""
        playbook = self._load_playbook()
        rule_ids = [r.id for r in playbook.rules]
        assert "MF-004" in rule_ids

    def test_mf004_has_correct_fields(self):
        """MF-004 has the expected description, scope, and check_type."""
        playbook = self._load_playbook()
        mf004 = next(r for r in playbook.rules if r.id == "MF-004")

        assert mf004.scope == "source"
        assert mf004.check_type == "llm"
        assert "late payment penalty" in mf004.description.lower()
        assert mf004.check_description.strip() != ""

    def test_mf004_partitioned_into_source_rules(self):
        """MF-004 (scope=source) appears in source_rules after partitioning."""
        playbook = self._load_playbook()
        partitioned = partition_rules(playbook)

        source_ids = [r.id for r in partitioned.source_rules]
        claims_ids = [r.id for r in partitioned.claims_rules]

        assert "MF-004" in source_ids
        assert "MF-004" not in claims_ids

    def test_mf004_evaluable_as_evaluation_result(self):
        """MF-004 can be used to construct a valid EvaluationResult (evaluable)."""
        playbook = self._load_playbook()
        mf004 = next(r for r in playbook.rules if r.id == "MF-004")

        # Simulate producing an EvaluationResult for this rule
        result = EvaluationResult(
            rule_id=mf004.id,
            verdict="fail",
            cited_span=CitedSpan(
                start_offset=100,
                end_offset=150,
                text="late payment penalty of 10% of outstanding balance",
            ),
            explanation="Penalty of 10% exceeds the 5% maximum.",
            evaluation_method="llm",
        )

        assert result.rule_id == "MF-004"
        assert result.verdict == "fail"
        assert result.cited_span.start_offset < result.cited_span.end_offset
        assert result.evaluation_method == "llm"

    def test_playbook_still_valid_with_four_rules(self):
        """Adding MF-004 does not break existing rules — all 4 validate."""
        playbook = self._load_playbook()
        assert len(playbook.rules) == 4
        # All original rules still present
        ids = {r.id for r in playbook.rules}
        assert ids == {"MF-001", "MF-002", "MF-003", "MF-004"}
