"""Map framework objects to SuperDocs template/edit payloads. No HTTP."""

from __future__ import annotations

from html import escape

from job_architecture.framework import FrameworkDocument
from job_architecture.models import RoleProfile
from job_architecture.propagation import UpdatePlan

PROFILE_TEMPLATE_ID = "job-architecture-role-profile"


def profile_to_template_payload(profile: RoleProfile) -> dict[str, object]:
    return {
        "template_id": PROFILE_TEMPLATE_ID,
        "filename": f"{profile.id}.md",
        "markdown": render_profile_markdown(profile),
        "metadata": {
            "profile_id": profile.id,
            "role_id": profile.role_id,
            "family_id": profile.family_id,
            "level_id": profile.level_id,
            "classification": profile.classification,
        },
    }


def update_plan_to_edit_instruction(plan: UpdatePlan) -> str:
    changed = ", ".join(plan.changed_rendered_fields) or plan.section_id
    preserved = ", ".join(plan.preserved_rendered_fields)
    preserve_line = (
        f"Preserve these {plan.section_id} fields exactly, including any fallback wording: {preserved}."
        if preserved
        else "Do not rewrite unrelated fields inside the section."
    )
    return (
        f"In the role profile, update ONLY the '{plan.section_id}' section. "
        f"Inside that section, update ONLY these fields: {changed}. "
        f"{preserve_line} "
        "Do not rewrite the rest of the profile. Do not change purpose, "
        "responsibilities, or any other section. The resulting "
        f"'{plan.section_id}' text must be exactly:\n\n{plan.after}"
    )


def render_framework_markdown(framework: FrameworkDocument) -> str:
    lines = [
        f"# Job architecture — {framework.organization}",
        "",
        "## Purpose",
        framework.purpose,
        "",
        "## Principles",
        *[f"- {item}" for item in framework.principles],
        "",
        "## Career tracks",
        *[f"- {item.name} (`{item.id}`): {item.description}" for item in framework.tracks],
        "",
        "## Canonical levels",
    ]
    for level in framework.levels:
        lines.extend(
            [
                f"### {level.label} (`{level.id}`, version {level.version})",
                f"- Scope: {level.scope}",
                f"- Autonomy / decision authority: {level.decision_authority or level.autonomy}",
                f"- Complexity: {level.complexity}",
                f"- Impact: {level.impact}",
                f"- Leadership: {level.leadership}",
                f"- People management: {level.people_management or 'None'}",
                "",
            ]
        )
    lines.extend(["## Job families", ""])
    for family in framework.families:
        lines.append(f"- **{family.name}** (`{family.id}`): {family.description}")
    lines.extend(["", "## Competency matrices", ""])
    for matrix in framework.competency_matrices:
        lines.append(f"### {matrix.family_name}")
        if matrix.evidence_limited:
            lines.append(f"Limitation: {matrix.limitation}")
        for competency in matrix.competencies:
            lines.append(f"- {competency.name} (`{competency.id}`): {competency.description}")
        lines.append("")
    lines.extend(["## Role mappings", ""])
    for mapping in framework.role_mappings:
        lines.append(
            f"- `{mapping.role_id}`: {mapping.fit_status.value}; "
            f"family={mapping.family_id or 'none'}; level={mapping.level_id or 'none'}; "
            f"profile={mapping.profile_id or 'none'}"
        )
    lines.extend(["", "## Provisional roles", ""])
    for item in framework.provisional_roles:
        lines.append(f"- `{item.role_id}` ({item.title}): {item.summary}")
    lines.extend(["", "## Misfits", ""])
    for item in framework.misfits:
        lines.append(f"- `{item.role_id}` ({item.title}): {item.summary}")
    return "\n".join(lines).rstrip() + "\n"


def render_profile_markdown(profile: RoleProfile) -> str:
    responsibilities = "\n".join(f"- {item}" for item in profile.responsibilities)
    return "\n".join(
        [
            f"# {profile.display_title}",
            "",
            f"- Job family: {profile.family_name or profile.family_id}",
            f"- Career track: {profile.track_name or profile.track_id}",
            f"- Level: {profile.level_label or profile.level_id}",
            f"- Classification: {profile.classification}",
            "",
            "## Role purpose",
            profile.summary,
            "",
            "## Responsibilities",
            responsibilities,
            "",
            "## Scope / decision making",
            profile.scope_decision_making,
            "",
            "## Core competencies",
            profile.core_competencies,
            "",
            "## Level expectations",
            profile.level_expectations,
            "",
            "## Progression",
            profile.progression,
            "",
            "## Source / evidence note",
            profile.evidence_note,
            "",
        ]
    )


def _esc(value: str | None) -> str:
    return escape(value or "", quote=True)


def _items(values: list[str] | tuple[str, ...]) -> str:
    if not values:
        return "<p>None.</p>"
    return "<ul>" + "".join(f"<li>{_esc(item)}</li>" for item in values) + "</ul>"


def render_framework_html(framework: FrameworkDocument) -> str:
    """Deterministic semantic HTML for SuperDocs export. Domain data is the source of truth."""
    tracks = "".join(
        f"<li>{_esc(item.name)} ({_esc(item.id)}): {_esc(item.description)}</li>"
        for item in framework.tracks
    )
    level_rows = "".join(
        "<tr>"
        f"<td>{_esc(level.label)}</td>"
        f"<td>{_esc(level.id)}</td>"
        f"<td>{_esc(str(level.version))}</td>"
        f"<td>{_esc(level.scope)}</td>"
        f"<td>{_esc(level.decision_authority or level.autonomy)}</td>"
        f"<td>{_esc(level.complexity)}</td>"
        f"<td>{_esc(level.impact)}</td>"
        f"<td>{_esc(level.leadership)}</td>"
        f"<td>{_esc(level.people_management or 'None')}</td>"
        "</tr>"
        for level in framework.levels
    )
    families = "".join(
        f"<li>{_esc(family.name)} ({_esc(family.id)}): {_esc(family.description)}</li>"
        for family in framework.families
    )
    matrices: list[str] = []
    for matrix in framework.competency_matrices:
        matrices.append(f"<h3>{_esc(matrix.family_name)}</h3>")
        if matrix.evidence_limited:
            matrices.append(f"<p>Limitation: {_esc(matrix.limitation)}</p>")
        matrices.append(
            "<ul>"
            + "".join(
                f"<li>{_esc(item.name)} ({_esc(item.id)}): {_esc(item.description)}</li>"
                for item in matrix.competencies
            )
            + "</ul>"
        )
    mappings = "".join(
        "<li>"
        f"{_esc(item.role_id)}: {_esc(item.fit_status.value)}; "
        f"family={_esc(item.family_id or 'none')}; "
        f"level={_esc(item.level_id or 'none')}; "
        f"profile={_esc(item.profile_id or 'none')}"
        "</li>"
        for item in framework.role_mappings
    )
    if framework.provisional_roles:
        provisional = (
            "<ul>"
            + "".join(
                f"<li>{_esc(item.role_id)} ({_esc(item.title)}): {_esc(item.summary)}</li>"
                for item in framework.provisional_roles
            )
            + "</ul>"
        )
    else:
        provisional = "<p>None.</p>"
    if framework.misfits:
        misfits = (
            "<ul>"
            + "".join(
                f"<li>{_esc(item.role_id)} ({_esc(item.title)}): {_esc(item.summary)}</li>"
                for item in framework.misfits
            )
            + "</ul>"
        )
    else:
        misfits = "<p>None.</p>"
    return (
        f"<h1>Job architecture — {_esc(framework.organization)}</h1>"
        "<h2>Purpose</h2>"
        f"<p>{_esc(framework.purpose)}</p>"
        "<h2>Principles</h2>"
        f"{_items(framework.principles)}"
        "<h2>Career tracks</h2>"
        f"<ul>{tracks}</ul>"
        "<h2>Canonical levels</h2>"
        "<table>"
        "<thead><tr>"
        "<th>Level</th><th>Id</th><th>Version</th><th>Scope</th>"
        "<th>Autonomy / decision authority</th><th>Complexity</th>"
        "<th>Impact</th><th>Leadership</th><th>People management</th>"
        "</tr></thead>"
        f"<tbody>{level_rows}</tbody>"
        "</table>"
        "<h2>Job families</h2>"
        f"<ul>{families}</ul>"
        "<h2>Competency matrices</h2>"
        f"{''.join(matrices)}"
        "<h2>Role mappings</h2>"
        f"<ul>{mappings}</ul>"
        "<h2>Provisional roles</h2>"
        f"{provisional}"
        "<h2>Misfits</h2>"
        f"{misfits}"
    )


def render_profile_html(profile: RoleProfile) -> str:
    """Deterministic semantic HTML for SuperDocs export of one role profile."""
    return (
        f"<h1>{_esc(profile.display_title)}</h1>"
        "<ul>"
        f"<li>Job family: {_esc(profile.family_name or profile.family_id)}</li>"
        f"<li>Career track: {_esc(profile.track_name or profile.track_id)}</li>"
        f"<li>Level: {_esc(profile.level_label or profile.level_id)}</li>"
        f"<li>Classification: {_esc(profile.classification)}</li>"
        "</ul>"
        "<h2>Role purpose</h2>"
        f"<p>{_esc(profile.summary)}</p>"
        "<h2>Responsibilities</h2>"
        f"{_items(tuple(profile.responsibilities))}"
        "<h2>Scope / decision making</h2>"
        f"<p>{_esc(profile.scope_decision_making)}</p>"
        "<h2>Core competencies</h2>"
        f"<p>{_esc(profile.core_competencies)}</p>"
        "<h2>Level expectations</h2>"
        f"<p>{_esc(profile.level_expectations)}</p>"
        "<h2>Progression</h2>"
        f"<p>{_esc(profile.progression)}</p>"
        "<h2>Source / evidence note</h2>"
        f"<p>{_esc(profile.evidence_note)}</p>"
    )
