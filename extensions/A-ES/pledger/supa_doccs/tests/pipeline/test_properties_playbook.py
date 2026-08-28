"""Property-based tests for Playbook schema, loader, and rule partitioner.

**Validates: Requirements 1.2, 1.3, 1.5, 1.6, 2.1, 7.3**

Property 1: Playbook Schema Round-Trip
    For any valid Playbook model instance, serializing to a dict and parsing
    back via Playbook.model_validate() SHALL produce an equivalent model.

Property 2: Invalid Playbook ID Produces Permanent Error
    For any string that is not a key in PLAYBOOK_WHITELIST, calling
    load_playbook() SHALL raise a PlaybookLoadError.

Property 3: Rule Scope Partitioning Correctness
    For any valid playbook with N rules, partitioning by scope SHALL produce
    two lists where: (a) every rule with scope "claims" or "both" appears in
    claims_rules, (b) every rule with scope "source" or "both" appears in
    source_rules, and (c) no rule is lost.

Property 8: Default Check Type Is LLM
    For any rule definition dict that omits the check_type field, parsing via
    RuleDefinition.model_validate() SHALL produce a model with
    check_type == "llm".

Property 9: Unbounded Rules Per Playbook
    For any positive integer N, a playbook containing N rules (each with
    unique IDs and valid fields) SHALL pass Pydantic validation without error.
"""

from __future__ import annotations

import asyncio

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.playbook import (
    PLAYBOOK_WHITELIST,
    Playbook,
    PlaybookLoadError,
    PartitionedRules,
    RuleDefinition,
    load_playbook,
    partition_rules,
)


# --- Strategies ---

VALID_SCOPES = st.sampled_from(["claims", "source", "both"])
VALID_CHECK_TYPES = st.sampled_from(["llm", "structured"])


@st.composite
def valid_rule_ids(draw: st.DrawFn) -> str:
    """Generate valid non-empty rule IDs."""
    prefix = draw(st.sampled_from(["MF", "CL", "RG", "CHK", "RL"]))
    suffix = draw(st.integers(min_value=1, max_value=9999))
    return f"{prefix}-{suffix:04d}"


@st.composite
def valid_rule_definitions(draw: st.DrawFn) -> RuleDefinition:
    """Generate valid RuleDefinition instances."""
    rule_id = draw(valid_rule_ids())
    description = draw(st.text(min_size=1, max_size=200, alphabet=st.characters(
        categories=("L", "N", "P", "Z", "S"),
    )))
    check_description = draw(st.text(min_size=1, max_size=300, alphabet=st.characters(
        categories=("L", "N", "P", "Z", "S"),
    )))
    scope = draw(VALID_SCOPES)
    check_type = draw(VALID_CHECK_TYPES)

    return RuleDefinition(
        id=rule_id,
        description=description,
        check_description=check_description,
        scope=scope,
        check_type=check_type,
    )


@st.composite
def unique_rule_lists(draw: st.DrawFn, min_size: int = 1, max_size: int = 20) -> list[RuleDefinition]:
    """Generate lists of RuleDefinition with unique IDs."""
    count = draw(st.integers(min_value=min_size, max_value=max_size))
    rules = []
    used_ids: set[str] = set()

    for i in range(count):
        # Ensure uniqueness by embedding the index
        rule_id = f"RULE-{i:04d}"
        description = draw(st.text(min_size=1, max_size=100, alphabet=st.characters(
            categories=("L", "N", "P", "Z", "S"),
        )))
        check_description = draw(st.text(min_size=1, max_size=150, alphabet=st.characters(
            categories=("L", "N", "P", "Z", "S"),
        )))
        scope = draw(VALID_SCOPES)
        check_type = draw(VALID_CHECK_TYPES)

        rules.append(RuleDefinition(
            id=rule_id,
            description=description,
            check_description=check_description,
            scope=scope,
            check_type=check_type,
        ))
        used_ids.add(rule_id)

    return rules


@st.composite
def valid_playbooks(draw: st.DrawFn) -> Playbook:
    """Generate valid Playbook instances."""
    playbook_id = draw(st.text(min_size=1, max_size=50, alphabet=st.characters(
        categories=("L", "N"),
    )))
    name = draw(st.text(min_size=1, max_size=100, alphabet=st.characters(
        categories=("L", "N", "P", "Z", "S"),
    )))
    version = draw(st.from_regex(r"[0-9]{1,3}\.[0-9]{1,3}", fullmatch=True))
    rules = draw(unique_rule_lists(min_size=1, max_size=15))

    return Playbook(
        playbook_id=playbook_id,
        name=name,
        version=version,
        rules=rules,
    )


# --- Property Tests ---


@given(playbook=valid_playbooks())
@settings(max_examples=200)
def test_playbook_schema_round_trip(playbook: Playbook) -> None:
    """Property 1: Playbook Schema Round-Trip.

    **Validates: Requirements 1.2, 1.5, 1.6**

    Serialize any valid Playbook to dict and re-validate — the result
    SHALL be equivalent to the original.
    """
    serialized = playbook.model_dump()
    restored = Playbook.model_validate(serialized)

    assert restored.playbook_id == playbook.playbook_id
    assert restored.name == playbook.name
    assert restored.version == playbook.version
    assert len(restored.rules) == len(playbook.rules)

    for original_rule, restored_rule in zip(playbook.rules, restored.rules):
        assert restored_rule.id == original_rule.id
        assert restored_rule.description == original_rule.description
        assert restored_rule.check_description == original_rule.check_description
        assert restored_rule.scope == original_rule.scope
        assert restored_rule.check_type == original_rule.check_type


@given(
    playbook_id=st.text(min_size=1, max_size=200, alphabet=st.characters(
        categories=("L", "N", "P", "S"),
    )).filter(lambda s: s not in PLAYBOOK_WHITELIST)
)
@settings(max_examples=200)
def test_invalid_playbook_id_produces_permanent_error(playbook_id: str) -> None:
    """Property 2: Invalid Playbook ID Produces Permanent Error.

    **Validates: Requirements 1.3**

    Any string that is NOT a key in PLAYBOOK_WHITELIST SHALL cause
    load_playbook() to raise PlaybookLoadError.
    """
    with pytest.raises(PlaybookLoadError):
        asyncio.run(load_playbook(playbook_id))


@given(playbook=valid_playbooks())
@settings(max_examples=200)
def test_rule_scope_partitioning_correctness(playbook: Playbook) -> None:
    """Property 3: Rule Scope Partitioning Correctness.

    **Validates: Requirements 2.1**

    All rules appear in the correct lists based on their scope, and no
    rule is lost.
    """
    partitioned = partition_rules(playbook)

    # (a) Every rule with scope "claims" or "both" appears in claims_rules
    for rule in playbook.rules:
        if rule.scope in ("claims", "both"):
            assert rule in partitioned.claims_rules, (
                f"Rule '{rule.id}' with scope '{rule.scope}' should be in claims_rules"
            )

    # (b) Every rule with scope "source" or "both" appears in source_rules
    for rule in playbook.rules:
        if rule.scope in ("source", "both"):
            assert rule in partitioned.source_rules, (
                f"Rule '{rule.id}' with scope '{rule.scope}' should be in source_rules"
            )

    # (c) No rule is lost — the unique IDs across both lists cover all rules
    claims_ids = {r.id for r in partitioned.claims_rules}
    source_ids = {r.id for r in partitioned.source_rules}
    all_partitioned_ids = claims_ids | source_ids
    all_original_ids = {r.id for r in playbook.rules}

    assert all_partitioned_ids == all_original_ids, (
        f"Rules lost during partitioning. "
        f"Original: {all_original_ids}, Partitioned: {all_partitioned_ids}"
    )

    # Additional: claims_rules should not contain scope "source" only rules
    for rule in partitioned.claims_rules:
        assert rule.scope in ("claims", "both"), (
            f"Rule '{rule.id}' with scope '{rule.scope}' should not be in claims_rules"
        )

    # Additional: source_rules should not contain scope "claims" only rules
    for rule in partitioned.source_rules:
        assert rule.scope in ("source", "both"), (
            f"Rule '{rule.id}' with scope '{rule.scope}' should not be in source_rules"
        )


@given(
    description=st.text(min_size=1, max_size=200, alphabet=st.characters(
        categories=("L", "N", "P", "Z", "S"),
    )),
    check_description=st.text(min_size=1, max_size=200, alphabet=st.characters(
        categories=("L", "N", "P", "Z", "S"),
    )),
    scope=VALID_SCOPES,
    rule_id=valid_rule_ids(),
)
@settings(max_examples=200)
def test_default_check_type_is_llm(
    description: str, check_description: str, scope: str, rule_id: str
) -> None:
    """Property 8: Default Check Type Is LLM.

    **Validates: Requirements 1.6**

    Omitting check_type from a rule definition dict SHALL default to "llm".
    """
    rule_dict = {
        "id": rule_id,
        "description": description,
        "check_description": check_description,
        "scope": scope,
        # check_type intentionally omitted
    }

    rule = RuleDefinition.model_validate(rule_dict)

    assert rule.check_type == "llm", (
        f"Default check_type should be 'llm', got '{rule.check_type}'"
    )


@given(n=st.integers(min_value=1, max_value=100))
@settings(max_examples=200)
def test_unbounded_rules_per_playbook(n: int) -> None:
    """Property 9: Unbounded Rules Per Playbook.

    **Validates: Requirements 7.3**

    N rules with unique IDs SHALL validate successfully for any positive N.
    """
    rules = [
        RuleDefinition(
            id=f"GEN-{i:05d}",
            description=f"Generated rule {i}",
            check_description=f"Check condition {i}",
            scope="source",
            check_type="llm",
        )
        for i in range(n)
    ]

    playbook = Playbook(
        playbook_id="test_playbook",
        name="Generated Test Playbook",
        version="1.0",
        rules=rules,
    )

    # Validation succeeded if we get here — verify contents
    assert len(playbook.rules) == n
    assert all(r.id == f"GEN-{i:05d}" for i, r in enumerate(playbook.rules))
