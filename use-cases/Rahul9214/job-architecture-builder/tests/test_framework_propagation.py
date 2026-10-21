"""Phase 6: framework generation, profiles, dependencies, surgical propagation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from job_architecture.architecture import build_architecture, extract_corpus_evidence
from job_architecture.documents import (
    profile_to_template_payload,
    update_plan_to_edit_instruction,
)
from job_architecture.fixtures import load_corpus
from job_architecture.framework import generate_framework
from job_architecture.graph import DependencyGraph, DependencyGraphError, validate_dependency_graph
from job_architecture.hashes import hash_section
from job_architecture.level_text import (
    FIELD_COMPLEXITY,
    changed_dimensions,
    parse_level_expectations,
    patch_level_expectations,
)
from job_architecture.models import (
    PROFILE_SECTION_IDS,
    DependencyEdge,
    FitStatus,
    LevelDefinition,
    RoleProfile,
)
from job_architecture.propagation import (
    ChangeStatus,
    analyze_level_change,
    apply_approved_plans,
    approve_plans,
    plan_level_updates,
    reject_plans,
    snapshot_hashes,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATION_FILES = (
    "framework.py",
    "profiles.py",
    "matrices.py",
    "graph.py",
    "propagation.py",
    "documents.py",
    "hashes.py",
    "level_text.py",
)


def _framework(corpus_id: str):
    corpus = load_corpus(corpus_id)
    architecture = build_architecture(corpus)
    evidences = extract_corpus_evidence(corpus)
    return architecture, generate_framework(architecture, evidences)


def test_framework_contains_canonical_ic_and_m_levels():
    _, framework = _framework("corpus-a")
    labels = {item.label for item in framework.levels}
    assert labels >= {"IC1", "IC2", "IC3", "IC4", "IC5", "M1", "M2", "M3"}
    for level in framework.levels:
        assert level.version >= 1
        assert level.scope
        assert level.autonomy
        assert level.decision_authority
        assert level.complexity
        assert level.impact
        assert level.leadership


def test_strong_fit_roles_map_to_profiles():
    architecture, framework = _framework("corpus-a")
    strong = {item.role_id for item in architecture.assessments if item.fit_status is FitStatus.STRONG_FIT}
    profile_roles = {item.role_id for item in framework.profiles}
    assert strong <= profile_roles
    mapped = {item.role_id for item in framework.role_mappings if item.profile_id}
    assert strong <= mapped


def test_provisional_roles_remain_visible():
    architecture, framework = _framework("corpus-a")
    provisional = {item.role_id for item in architecture.assessments if item.fit_status is FitStatus.PROVISIONAL}
    artifact_ids = {item.role_id for item in framework.provisional_roles}
    profile_ids = {
        item.role_id for item in framework.profiles if item.classification == FitStatus.PROVISIONAL.value
    }
    assert provisional == artifact_ids | profile_ids
    for profile in framework.profiles:
        if profile.classification == FitStatus.PROVISIONAL.value:
            assert "provisional" in profile.evidence_note.lower()
            assert "not finalized" in profile.evidence_note.lower()


def test_misfits_are_not_normalized():
    architecture, framework = _framework("corpus-a")
    misfits = {item.role_id for item in architecture.assessments if item.fit_status is FitStatus.MISFIT}
    assert misfits
    assert {item.role_id for item in framework.misfits} == misfits
    assert not {item.role_id for item in framework.profiles} & misfits
    for artifact in framework.misfits:
        assert "misfit" in artifact.summary.lower()
        assert artifact.reasons


def test_family_matrices_are_consistent():
    _, framework = _framework("corpus-a")
    family_ids = {item.id for item in framework.families}
    assert {item.family_id for item in framework.competency_matrices} == family_ids
    for matrix in framework.competency_matrices:
        assert matrix.competencies
        names = [item.name for item in matrix.competencies]
        assert len(names) == len(set(names))
        for competency in matrix.competencies:
            assert competency.family_id == matrix.family_id
            assert competency.indicators_by_level


def test_dependency_graph_has_level_to_profile_edges():
    _, framework = _framework("corpus-a")
    level_edges = [
        edge
        for edge in framework.dependency_graph.edges
        if edge.source_type == "level_definition" and edge.target_section == "level_expectations"
    ]
    assert level_edges
    assert {edge.target_id for edge in level_edges} == {item.id for item in framework.profiles}
    competency_edges = [
        edge for edge in framework.dependency_graph.edges if edge.source_type == "competency"
    ]
    assert competency_edges


def test_ic4_change_selects_ic4_and_excludes_other_levels():
    _, framework = _framework("corpus-a")
    old = framework.level("IC4")
    ic4_ids = {item.id for item in framework.profiles_for_level("IC4")}
    assert ic4_ids
    new = replace(old, scope=old.scope + " Explicit domain veto added.", version=old.version + 1)
    analysis = analyze_level_change(
        old,
        new,
        framework.dependency_graph,
        framework.profiles,
        levels=framework.levels,
    )
    assert set(analysis.affected_profile_ids) == ic4_ids
    excluded = {item.id for item in framework.profiles if item.level_id != old.id}
    assert set(analysis.unaffected_profile_ids) == excluded
    for profile in framework.profiles:
        if profile.level_label in {"IC1", "IC2", "IC3", "IC5", "M1", "M2", "M3"}:
            assert profile.id not in analysis.affected_profile_ids


def test_only_intended_sections_change_and_hashes_hold():
    _, framework = _framework("corpus-a")
    old = framework.level("IC4")
    new = replace(old, impact=old.impact + " Added reliability bar.", version=old.version + 1)
    analysis = analyze_level_change(
        old, new, framework.dependency_graph, framework.profiles, levels=framework.levels
    )
    plans = approve_plans(
        plan_level_updates(
            analysis,
            old_level=old,
            new_level=new,
            dependency_graph=framework.dependency_graph,
            profiles=framework.profiles,
        )
    )
    before = snapshot_hashes(framework.profiles)
    updated, graph, report, applied = apply_approved_plans(
        plans,
        framework.profiles,
        framework.dependency_graph,
        new_level=new,
        expected_before=before,
    )
    assert report.ok
    assert report.violations == ()
    changed_ids = {item.profile_id for item in report.changed_sections}
    assert changed_ids == set(analysis.affected_profile_ids)
    for item in report.changed_sections:
        assert item.section_id == "level_expectations"
    by_id = {item.id: item for item in updated}
    for profile in framework.profiles:
        for section_id in PROFILE_SECTION_IDS:
            if profile.id in changed_ids and section_id == "level_expectations":
                assert hash_section(by_id[profile.id], section_id) != before[profile.id][section_id]
            else:
                assert hash_section(by_id[profile.id], section_id) == before[profile.id][section_id]
    for edge in graph.for_source("level_definition", old.id):
        if edge.target_id in changed_ids:
            assert edge.source_version == new.version


def test_second_application_is_idempotent():
    _, framework = _framework("corpus-a")
    old = framework.level("IC4")
    new = replace(old, leadership=old.leadership + " Coaches via written RFCs.", version=old.version + 1)
    analysis = analyze_level_change(
        old, new, framework.dependency_graph, framework.profiles, levels=framework.levels
    )
    planned = plan_level_updates(
        analysis,
        old_level=old,
        new_level=new,
        dependency_graph=framework.dependency_graph,
        profiles=framework.profiles,
    )
    approved = approve_plans(planned)
    updated, graph, report, _ = apply_approved_plans(
        approved, framework.profiles, framework.dependency_graph, new_level=new
    )
    assert report.ok
    second_plans = plan_level_updates(
        analysis,
        old_level=old,
        new_level=new,
        dependency_graph=graph,
        profiles=updated,
    )
    assert second_plans == ()
    before = snapshot_hashes(updated)
    again, graph2, report2, _ = apply_approved_plans(
        approved, updated, graph, new_level=new, expected_before=before
    )
    assert report2.ok
    assert report2.changed_sections == ()
    assert snapshot_hashes(again) == before
    for left, right in zip(graph.edges, graph2.edges, strict=True):
        assert left.source_version == right.source_version


def test_rejected_update_remains_unapplied():
    _, framework = _framework("corpus-a")
    old = framework.level("IC4")
    new = replace(old, scope=old.scope + " Rejected draft.", version=old.version + 1)
    analysis = analyze_level_change(
        old, new, framework.dependency_graph, framework.profiles, levels=framework.levels
    )
    rejected = reject_plans(
        plan_level_updates(
            analysis,
            old_level=old,
            new_level=new,
            dependency_graph=framework.dependency_graph,
            profiles=framework.profiles,
        )
    )
    assert rejected and all(item.status is ChangeStatus.REJECTED for item in rejected)
    before = snapshot_hashes(framework.profiles)
    updated, graph, report, finished = apply_approved_plans(
        rejected, framework.profiles, framework.dependency_graph, new_level=new, expected_before=before
    )
    assert report.changed_sections == ()
    assert snapshot_hashes(updated) == before
    for edge in graph.edges:
        original = next(item for item in framework.dependency_graph.edges if item.id == edge.id)
        assert edge.source_version == original.source_version
    assert all(item.status is ChangeStatus.REJECTED for item in finished)


def test_dependency_version_updates_only_after_apply():
    _, framework = _framework("corpus-a")
    old = framework.level("IC4")
    new = replace(old, autonomy=old.autonomy + " Domain sequencing authority.", version=old.version + 1)
    analysis = analyze_level_change(
        old, new, framework.dependency_graph, framework.profiles, levels=framework.levels
    )
    planned = plan_level_updates(
        analysis,
        old_level=old,
        new_level=new,
        dependency_graph=framework.dependency_graph,
        profiles=framework.profiles,
    )
    for edge in framework.dependency_graph.for_source("level_definition", old.id):
        assert edge.source_version == old.version
    _, graph, _, _ = apply_approved_plans(
        approve_plans(planned), framework.profiles, framework.dependency_graph, new_level=new
    )
    for edge in graph.for_source("level_definition", old.id):
        assert edge.source_version == new.version


def test_malformed_dependency_graph_fails_safely():
    _, framework = _framework("corpus-a")
    dangling = DependencyEdge(
        id="bad-edge",
        source_type="level_definition",
        source_id=framework.level("IC4").id,
        target_type="role_profile",
        target_id="profile-does-not-exist",
        target_section="level_expectations",
    )
    with pytest.raises(DependencyGraphError, match="Dangling"):
        validate_dependency_graph(DependencyGraph(edges=(dangling,)), framework.profiles, framework.levels)
    unknown_section = replace(
        framework.dependency_graph.edges[0],
        id="bad-section",
        target_section="not_a_section",
    )
    with pytest.raises(DependencyGraphError, match="Unknown target_section"):
        validate_dependency_graph(
            DependencyGraph(edges=(unknown_section,)), framework.profiles, framework.levels
        )


def test_corpus_b_uses_same_generation_path():
    architecture, framework = _framework("corpus-b")
    assert framework.organization == architecture.organization
    labels = {item.label for item in framework.levels}
    assert labels >= {"IC1", "IC2", "IC3", "IC4", "IC5", "M1", "M2", "M3"}
    strong = {item.role_id for item in architecture.assessments if item.fit_status is FitStatus.STRONG_FIT}
    assert strong <= {item.role_id for item in framework.profiles}
    misfits = {item.role_id for item in architecture.assessments if item.fit_status is FitStatus.MISFIT}
    assert misfits <= {item.role_id for item in framework.misfits}
    assert {item.family_id for item in framework.competency_matrices} == {item.id for item in framework.families}


_FALLBACK_BLOCK = (
    "IC4 (definition version 1)\n"
    "Scope: scope A\n"
    "Autonomy / decision authority: auto A\n"
    "Complexity: fallback F\n"
    "Impact: impact A\n"
    "Leadership: lead A\n"
    "People-management expectations: people A"
)


def _level(**overrides) -> LevelDefinition:
    payload = {
        "id": "ic4",
        "family_id": "canonical",
        "track_id": "individual_contributor",
        "label": "IC4",
        "rank": 4,
        "scope": "scope A",
        "autonomy": "auto A",
        "impact": "impact A",
        "leadership": "lead A",
        "people_management": "people A",
        "complexity": "canonical C",
        "decision_authority": "auto A",
        "version": 1,
    }
    payload.update(overrides)
    return LevelDefinition(**payload)


def _demo_profile(text: str = _FALLBACK_BLOCK) -> RoleProfile:
    return RoleProfile(
        id="profile-demo",
        role_id="role-demo",
        family_id="engineering",
        track_id="individual_contributor",
        level_id="ic4",
        display_title="Demo",
        summary="purpose text",
        responsibilities=["do work"],
        level_expectations=text,
        scope_decision_making="unrelated scope section",
        core_competencies="unrelated competencies",
        progression="unrelated progression",
        evidence_note="unrelated note",
    )


def _demo_graph() -> DependencyGraph:
    return DependencyGraph(
        edges=(
            DependencyEdge(
                id="level_definition:ic4->profile-demo:level_expectations",
                source_type="level_definition",
                source_id="ic4",
                target_type="role_profile",
                target_id="profile-demo",
                target_section="level_expectations",
                source_version=1,
            ),
        )
    )


def _plan_change(old: LevelDefinition, new: LevelDefinition, profile: RoleProfile | None = None):
    profile = profile or _demo_profile()
    graph = _demo_graph()
    analysis = analyze_level_change(old, new, graph, (profile,), levels=(old, new))
    plans = plan_level_updates(
        analysis,
        old_level=old,
        new_level=new,
        dependency_graph=graph,
        profiles=(profile,),
    )
    return profile, analysis, plans


def test_changed_dimensions_detects_scope_and_version_only():
    old = _level()
    new = replace(old, scope="scope B", version=2)
    assert changed_dimensions(old, new) == frozenset({"scope", "version"})


def test_scope_change_preserves_fallback_complexity_text():
    old = _level(scope="scope A", complexity="canonical C")
    new = replace(old, scope="scope B", version=2)
    stored = _FALLBACK_BLOCK
    after = patch_level_expectations(stored, new, changed_dimensions(old, new))
    parsed_before = parse_level_expectations(stored)
    parsed_after = parse_level_expectations(after)
    assert parsed_after.value_for("scope") == "scope B"
    assert parsed_after.raw_for(FIELD_COMPLEXITY) == parsed_before.raw_for(FIELD_COMPLEXITY)
    assert parsed_after.raw_for(FIELD_COMPLEXITY) == "Complexity: fallback F"
    assert "definition version 2" in after
    profile, _, plans = _plan_change(old, new, _demo_profile(stored))
    assert len(plans) == 1
    assert plans[0].after == after
    assert "complexity" in plans[0].preserved_rendered_fields
    assert "scope" in plans[0].changed_rendered_fields
    assert "canonical C" not in plans[0].after
    instruction = update_plan_to_edit_instruction(plans[0])
    assert "scope" in instruction
    assert "Preserve these" in instruction
    assert "complexity" in instruction
    approved = approve_plans(plans)
    updated, graph, report, finished = apply_approved_plans(
        approved, (profile,), _demo_graph(), new_level=new
    )
    assert report.ok
    assert updated[0].core_competencies == profile.core_competencies
    assert updated[0].summary == profile.summary
    assert parse_level_expectations(updated[0].level_expectations).raw_for(FIELD_COMPLEXITY) == (
        "Complexity: fallback F"
    )
    assert finished[0].status is ChangeStatus.APPLIED
    assert graph.for_source("level_definition", "ic4")[0].source_version == 2


def test_single_dimension_impact_change_is_surgical():
    old = _level()
    new = replace(old, impact="impact B", version=2)
    _, _, plans = _plan_change(old, new)
    assert changed_dimensions(old, new) == frozenset({"impact", "version"})
    parsed = parse_level_expectations(plans[0].after)
    assert parsed.value_for("impact") == "impact B"
    assert parsed.raw_for(FIELD_COMPLEXITY) == "Complexity: fallback F"
    assert parsed.value_for("scope") == "scope A"
    assert parsed.value_for("leadership") == "lead A"


def test_single_dimension_leadership_change_is_surgical():
    old = _level()
    new = replace(old, leadership="lead B", version=2)
    _, _, plans = _plan_change(old, new)
    assert changed_dimensions(old, new) == frozenset({"leadership", "version"})
    parsed = parse_level_expectations(plans[0].after)
    assert parsed.value_for("leadership") == "lead B"
    assert parsed.raw_for(FIELD_COMPLEXITY) == "Complexity: fallback F"
    assert parsed.value_for("scope") == "scope A"
    assert parsed.value_for("impact") == "impact A"


def test_generation_logic_has_no_corpus_specific_identifiers():
    src = PROJECT_ROOT / "src" / "job_architecture"
    forbidden = (
        "corpus-a",
        "corpus-b",
        "northstar",
        "meridian",
        "ns-swe",
        "ns-em",
        "mh-",
        "workplace tools",
        "developer advocate",
        "medical science",
        "program coordinator",
        "solutions architect",
        "patient portal widgets",
    )
    for name in GENERATION_FILES:
        text = (src / name).read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in text, f"{name} contains {token!r}"


def test_hero_acceptance_corpus_a_measurable_preservation():
    architecture, framework = _framework("corpus-a")
    occupied = [
        (level, framework.profiles_for_level(level.id))
        for level in framework.levels
        if framework.profiles_for_level(level.id)
    ]
    occupied.sort(key=lambda item: len(item[1]), reverse=True)
    old, occupants = occupied[0]
    assert len(occupants) >= 2
    new = replace(
        old,
        scope=old.scope + " Surgical change for preservation proof.",
        version=old.version + 1,
    )
    analysis = analyze_level_change(
        old, new, framework.dependency_graph, framework.profiles, levels=framework.levels
    )
    assert set(analysis.affected_profile_ids) == {item.id for item in occupants}
    plans = plan_level_updates(
        analysis,
        old_level=old,
        new_level=new,
        dependency_graph=framework.dependency_graph,
        profiles=framework.profiles,
    )
    assert {item.profile_id for item in plans} == set(analysis.affected_profile_ids)
    instruction = update_plan_to_edit_instruction(plans[0])
    assert "ONLY" in instruction
    assert "rewrite the rest of the profile" in instruction.lower() or "Do not rewrite" in instruction
    payload = profile_to_template_payload(framework.profiles[0])
    assert payload["template_id"] == "job-architecture-role-profile"
    before = snapshot_hashes(framework.profiles)
    updated, _, report, applied = apply_approved_plans(
        approve_plans(plans),
        framework.profiles,
        framework.dependency_graph,
        new_level=new,
        expected_before=before,
    )
    assert applied and all(item.status is ChangeStatus.APPLIED for item in applied)
    assert report.ok
    assert len(report.violations) == 0
    affected = len(analysis.affected_profile_ids)
    changed_sections = len(report.changed_sections)
    untouched = len(report.unchanged_sections)
    assert affected >= 2
    assert changed_sections == affected
    expected_untouched = len(framework.profiles) * len(PROFILE_SECTION_IDS) - changed_sections
    assert untouched == expected_untouched
    by_id = {item.id: item for item in updated}
    changed_canonical = changed_dimensions(old, new)
    changed_fields: set[str] = set()
    preserved_fields: set[str] = set()
    for profile in occupants:
        before_parsed = parse_level_expectations(profile.level_expectations)
        after_parsed = parse_level_expectations(by_id[profile.id].level_expectations)
        assert "Surgical change for preservation proof" in by_id[profile.id].level_expectations
        assert after_parsed.raw_for(FIELD_COMPLEXITY) == before_parsed.raw_for(FIELD_COMPLEXITY)
        assert after_parsed.raw_for("autonomy") == before_parsed.raw_for("autonomy")
        assert after_parsed.raw_for("impact") == before_parsed.raw_for("impact")
        assert after_parsed.raw_for("leadership") == before_parsed.raw_for("leadership")
        assert after_parsed.raw_for("people_management") == before_parsed.raw_for("people_management")
        assert by_id[profile.id].summary == profile.summary
        assert by_id[profile.id].responsibilities == profile.responsibilities
        assert by_id[profile.id].core_competencies == profile.core_competencies
        for field_id in ("header", "scope", "autonomy", "complexity", "impact", "leadership", "people_management"):
            if before_parsed.raw_for(field_id) == after_parsed.raw_for(field_id):
                preserved_fields.add(field_id)
            else:
                changed_fields.add(field_id)
    print(
        f"affected profiles: {affected}; changed sections: {changed_sections}; "
        f"untouched sections verified: {untouched}; violations: 0; "
        f"canonical dimensions changed: {sorted(changed_canonical)}; "
        f"profile fields changed: {sorted(changed_fields)}; "
        f"profile fields preserved: {sorted(preserved_fields)}"
    )
    assert architecture.assessments
