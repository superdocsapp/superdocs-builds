"""Playbook schema, loader, and rule partitioner for the rules-checking stage.

Playbooks are YAML files under rules/ that define compliance rules.
They are validated at load time via Pydantic and routed by scope
to the appropriate pipeline nodes.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


# --- Pydantic Models ---


class RuleDefinition(BaseModel):
    """A single compliance rule within a playbook."""

    id: str = Field(..., description="Unique rule identifier")
    description: str = Field(..., description="Human-readable rule description")
    check_description: str = Field(
        ..., description="Detailed instructions for evaluation"
    )
    scope: Literal["claims", "source", "both"] = Field(
        ..., description="Which pipeline path evaluates this rule"
    )
    check_type: Literal["llm", "structured"] = Field(
        default="llm", description="Evaluation method"
    )

    @field_validator("id")
    @classmethod
    def id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Rule id must not be empty")
        return v


class Playbook(BaseModel):
    """A validated playbook loaded from YAML."""

    playbook_id: str = Field(..., description="Matches the whitelist key")
    name: str = Field(..., description="Human-readable playbook name")
    version: str = Field(default="1.0", description="Playbook version")
    rules: list[RuleDefinition] = Field(
        ..., description="Unbounded list of compliance rules"
    )

    @field_validator("rules")
    @classmethod
    def rules_have_unique_ids(
        cls, v: list[RuleDefinition]
    ) -> list[RuleDefinition]:
        ids = [r.id for r in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Rule ids must be unique within a playbook")
        return v


# --- Playbook Loader ---

PLAYBOOK_WHITELIST: dict[str, str] = {
    "microfinance_v1": "microfinance_v1.yaml",
    "consumer_lending_v1": "consumer_lending_v1.yaml",
}

RULES_DIR = Path("rules")


class PlaybookLoadError(Exception):
    """Raised when playbook loading fails (permanent error)."""

    pass


async def load_playbook(playbook_id: str) -> Playbook:
    """Resolve, load, and validate a playbook by ID.

    Args:
        playbook_id: Must match a key in PLAYBOOK_WHITELIST.

    Returns:
        Validated Playbook model.

    Raises:
        PlaybookLoadError: If playbook_id is unknown or YAML is invalid.
    """
    if playbook_id not in PLAYBOOK_WHITELIST:
        raise PlaybookLoadError(
            f"Unknown playbook_id '{playbook_id}'. "
            f"Valid options: {list(PLAYBOOK_WHITELIST.keys())}"
        )

    yaml_path = RULES_DIR / PLAYBOOK_WHITELIST[playbook_id]
    if not yaml_path.exists():
        raise PlaybookLoadError(f"Playbook file not found: {yaml_path}")

    with open(yaml_path) as f:
        raw = yaml.safe_load(f)

    try:
        return Playbook.model_validate(raw)
    except Exception as e:
        raise PlaybookLoadError(f"Playbook validation failed: {e}") from e


# --- Rule Scope Partitioner ---


@dataclass
class PartitionedRules:
    """Rules partitioned by evaluation target."""

    claims_rules: list[RuleDefinition]
    source_rules: list[RuleDefinition]


def partition_rules(playbook: Playbook) -> PartitionedRules:
    """Partition playbook rules by scope for routing to correct nodes.

    Rules with scope "both" appear in both lists.

    Args:
        playbook: Validated Playbook model.

    Returns:
        PartitionedRules with claims_rules and source_rules.
    """
    claims_rules: list[RuleDefinition] = []
    source_rules: list[RuleDefinition] = []

    for rule in playbook.rules:
        if rule.scope in ("claims", "both"):
            claims_rules.append(rule)
        if rule.scope in ("source", "both"):
            source_rules.append(rule)

    return PartitionedRules(
        claims_rules=claims_rules,
        source_rules=source_rules,
    )
