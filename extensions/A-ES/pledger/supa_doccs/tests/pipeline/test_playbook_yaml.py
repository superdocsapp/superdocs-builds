"""Test that the sample microfinance_v1 playbook YAML validates against the Pydantic schema."""

import yaml

from src.pipeline.playbook import Playbook


def test_microfinance_v1_playbook_validates():
    """Load microfinance_v1.yaml and verify it validates against the Playbook schema."""
    with open("rules/microfinance_v1.yaml") as f:
        raw = yaml.safe_load(f)

    playbook = Playbook.model_validate(raw)

    assert playbook.playbook_id == "microfinance_v1"
    assert playbook.name == "Microfinance Compliance Rules v1"
    assert playbook.version == "1.0"
    assert len(playbook.rules) == 4

    # Verify rule IDs
    rule_ids = [r.id for r in playbook.rules]
    assert rule_ids == ["MF-001", "MF-002", "MF-003", "MF-004"]

    # Verify scopes
    assert playbook.rules[0].scope == "source"
    assert playbook.rules[1].scope == "both"
    assert playbook.rules[2].scope == "claims"
    assert playbook.rules[3].scope == "source"

    # Verify check_types (MF-002 omits check_type, should default to "llm")
    assert playbook.rules[0].check_type == "llm"
    assert playbook.rules[1].check_type == "llm"  # default
    assert playbook.rules[2].check_type == "structured"
    assert playbook.rules[3].check_type == "llm"
