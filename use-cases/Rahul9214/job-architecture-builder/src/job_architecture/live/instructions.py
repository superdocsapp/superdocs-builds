"""Targeted SuperDocs edit instructions. Architecture decisions stay in-domain."""

from __future__ import annotations

from dataclasses import replace

from job_architecture.documents import update_plan_to_edit_instruction
from job_architecture.framework import FrameworkDocument
from job_architecture.live.subset import DemoSubset, subset_profiles, surgical_target_profile
from job_architecture.models import LevelDefinition, RoleProfile
from job_architecture.propagation import UpdatePlan, analyze_level_change, plan_level_updates


def compact_framework_instruction(framework: FrameworkDocument, subset: DemoSubset) -> str:
    wanted = set(subset.role_ids)
    mappings = [item for item in framework.role_mappings if item.role_id in wanted]
    family_ids = {item.family_id for item in mappings if item.family_id}
    families = [item for item in framework.families if item.id in family_ids]
    provisionals = [item for item in framework.provisional_roles if item.role_id in wanted]
    lines = [
        "Fill this framework document from the approved architecture below.",
        "Do not invent families, tracks, or levels. Do not re-classify roles.",
        "Use the template headings already in the document.",
        "",
        f"Organization: {framework.organization}",
        "",
        "Purpose:",
        framework.purpose,
        "",
        "Principles:",
        *[f"- {item}" for item in framework.principles],
        "",
        "Career tracks:",
        *[f"- {item.name} ({item.id}): {item.description}" for item in framework.tracks],
        "",
        "Canonical levels (stable id + version; copy these dimensions):",
    ]
    for level in framework.levels:
        lines.append(
            f"- {level.label} id={level.id} v{level.version}: "
            f"scope={level.scope} | autonomy={level.decision_authority or level.autonomy} | "
            f"complexity={level.complexity} | impact={level.impact} | "
            f"leadership={level.leadership} | people={level.people_management or 'none'}"
        )
    lines.extend(["", "Job families (subset only):"])
    for family in families:
        lines.append(f"- {family.name} ({family.id}): {family.description}")
    lines.extend(["", "Role mappings (subset only):"])
    for mapping in mappings:
        lines.append(
            f"- {mapping.role_id}: {mapping.fit_status.value}; "
            f"family={mapping.family_id or 'none'}; level={mapping.level_id or 'none'}"
        )
    if provisionals:
        lines.extend(["", "Provisional (not finalized):"])
        for item in provisionals:
            lines.append(f"- {item.role_id}: {item.summary}")
    return "\n".join(lines)


def compact_profile_instruction(profile: RoleProfile) -> str:
    """Approved section values for a *blank* template.

    Do not send this against an already-filled profile. Replacing a narrow
    header span with this full Level expectations block duplicates dimensions.
    """
    responsibilities = "\n".join(f"- {item}" for item in profile.responsibilities)
    return "\n".join(
        [
            "Fill this role profile using the template headings already in the document.",
            "Use the following approved section values exactly. Do not change family, track, or level.",
            "",
            f"Role title: {profile.display_title}",
            f"Job family: {profile.family_name or profile.family_id}",
            f"Career track: {profile.track_name or profile.track_id}",
            f"Level: {profile.level_label or profile.level_id}",
            f"Classification: {profile.classification}",
            "",
            "Role purpose:",
            profile.summary,
            "",
            "Responsibilities:",
            responsibilities,
            "",
            "Scope / decision making:",
            profile.scope_decision_making,
            "",
            "Core competencies:",
            profile.core_competencies,
            "",
            "Level expectations:",
            profile.level_expectations,
            "",
            "Progression:",
            profile.progression,
            "",
            "Source / evidence note:",
            profile.evidence_note,
        ]
    )


def surgical_level_change(old: LevelDefinition) -> LevelDefinition:
    return replace(
        old,
        scope=old.scope + " Explicit domain sequencing veto for live verification.",
        version=old.version + 1,
    )


def surgical_update_plan(
    framework: FrameworkDocument,
    subset: DemoSubset,
) -> tuple[RoleProfile, LevelDefinition, LevelDefinition, UpdatePlan]:
    profile = surgical_target_profile(framework, subset)
    old = framework.level(profile.level_id)
    new = surgical_level_change(old)
    analysis = analyze_level_change(
        old,
        new,
        framework.dependency_graph,
        framework.profiles,
        levels=framework.levels,
    )
    if profile.id not in analysis.affected_profile_ids:
        raise ValueError(f"Dependency graph did not select {profile.id} for {old.label}")
    plans = plan_level_updates(
        analysis,
        old_level=old,
        new_level=new,
        dependency_graph=framework.dependency_graph,
        profiles=framework.profiles,
    )
    targeted = next(item for item in plans if item.profile_id == profile.id)
    if targeted.section_id != "level_expectations":
        raise ValueError("Surgical plan must target level_expectations only")
    return profile, old, new, targeted


def profile_duplicate_repair_instruction(canonical_block: str) -> str:
    """In-place reviewed repair: keep one approved Level expectations block."""
    return (
        "This is a structural repair of duplicated Level expectations, not a level change "
        "and not a new profile. The current section contains the canonical dimensions twice. "
        "Replace the entire Level expectations section body with EXACTLY the following text "
        "once. Delete the duplicate copy. Do not keep two Scope, Autonomy / decision authority, "
        "Complexity, Impact, Leadership, or People-management expectations lines. "
        "Do not bump the definition version. Do not add new scope wording. "
        "Do not rewrite Role purpose, Responsibilities, Scope / decision making, "
        "Core competencies, Progression, or evidence notes.\n\n"
        f"{canonical_block}"
    )


def surgical_edit_instruction(plan: UpdatePlan) -> str:
    text = update_plan_to_edit_instruction(plan)
    return (
        text
        + "\n\nDo not rewrite the profile. Leave Role purpose, Responsibilities, "
        "Scope / decision making, Core competencies, Progression, and evidence notes untouched."
    )


def subset_profile_for_demo(framework: FrameworkDocument, subset: DemoSubset) -> RoleProfile:
    try:
        return surgical_target_profile(framework, subset)
    except ValueError:
        pass
    profiles = subset_profiles(framework, subset)
    classified = [item for item in profiles if item.classification == "strong_fit"]
    if classified:
        return classified[0]
    if profiles:
        return profiles[0]
    raise ValueError("Demo subset produced no role profiles")
