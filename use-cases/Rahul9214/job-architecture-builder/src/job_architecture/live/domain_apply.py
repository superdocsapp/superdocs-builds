"""Verification-gated domain apply. Remote completed is not a domain apply."""

from __future__ import annotations

from typing import Any, Mapping

from job_architecture.framework import FrameworkDocument
from job_architecture.live.instructions import surgical_level_change, surgical_target_profile
from job_architecture.live.job_state import normalize_remote_status, normalize_review_outcome
from job_architecture.live.preservation import ExportPreservationCheck
from job_architecture.live.state import LiveState
from job_architecture.live.subset import DemoSubset
from job_architecture.profile_structure import StructureReport
from job_architecture.propagation import (
    analyze_level_change,
    apply_approved_plans,
    approve_plans,
    plan_level_updates,
)
from job_architecture.superdocs.errors import SuperDocsError

JOB_SURGICAL = "surgical"


def record_structure_verification(
    state: LiveState,
    *,
    path: str,
    report: StructureReport,
) -> None:
    verification = dict(state.verification or {})
    verification["structure"] = {
        "ok": bool(report.ok),
        "path": path,
        "violations": list(report.violations),
        "field_counts": dict(report.field_counts),
        "section_counts": dict(report.section_counts),
    }
    state.verification = verification


def record_preservation_verification(
    state: LiveState,
    *,
    path: str,
    check: ExportPreservationCheck,
) -> None:
    verification = dict(state.verification or {})
    verification["preservation"] = {
        "ok": bool(check.ok),
        "path": path,
        "found_new_fragment": check.found_new_fragment,
        "preserved_markers": list(check.preserved_markers),
        "missing_markers": list(check.missing_markers),
    }
    state.verification = verification
    preservation = dict(state.preservation or {})
    preservation["verification"] = dict(verification["preservation"])
    state.preservation = preservation


def domain_apply_blocked_reason(state: LiveState, job_name: str = JOB_SURGICAL) -> str | None:
    """Return a refusal reason, or None if finalize may run (including idempotent re-run)."""
    job = state.jobs.get(job_name) or {}
    if job.get("domain_applied") and (state.domain_apply or {}).get("applied"):
        return None
    outcome = normalize_review_outcome(job.get("review_outcome") or job.get("human_decision"))
    mutation_applied = job.get("mutation_applied")
    if outcome == "rejected" or mutation_applied is False:
        return (
            "Refusing domain apply: rejected attempts can never be domain-applied. "
            f"review_outcome={outcome} mutation_applied={mutation_applied}."
        )
    if outcome != "approved":
        return (
            "Refusing domain apply: reviewed mutation was not approved. "
            f"review_outcome={outcome}."
        )
    if mutation_applied is not True:
        return "Refusing domain apply: mutation_applied must be true after an approved review."
    remote = normalize_remote_status(job.get("remote_job_status") or job.get("status"))
    if remote != "completed":
        return (
            "Refusing domain apply: remote job is not completed. "
            "completed alone is not enough; verification is still required."
        )
    structure = (state.verification or {}).get("structure") or {}
    if not structure.get("ok"):
        return "Refusing domain apply: structure verification has not passed."
    preservation = _preservation_record(state)
    if not preservation.get("ok"):
        return "Refusing domain apply: required preservation verification has not passed."
    if not (structure.get("path") or (state.profile_integrity or {}).get("verified_path")):
        return "Refusing domain apply: exported document was not verified."
    if not preservation.get("path"):
        return "Refusing domain apply: exported document was not preservation-verified."
    return None


def apply_verified_domain(
    framework: FrameworkDocument,
    subset: DemoSubset,
    state: LiveState,
    *,
    job_name: str = JOB_SURGICAL,
) -> tuple[FrameworkDocument, dict[str, Any]]:
    """Advance local dependency/source version only after verification gates pass."""
    blocked = domain_apply_blocked_reason(state, job_name)
    if blocked:
        raise SuperDocsError(blocked)
    job = state.jobs.get(job_name) or {}
    existing = dict(state.domain_apply or {})
    if job.get("domain_applied") and existing.get("applied"):
        framework = hydrate_applied_domain(framework, subset, state)
        return framework, {
            "ok": True,
            "idempotent": True,
            "domain_applied": True,
            "level_id": existing.get("level_id"),
            "old_version": existing.get("old_version"),
            "new_version": existing.get("new_version"),
        }
    framework, record = _advance_domain(framework, subset)
    job["domain_applied"] = True
    state.jobs[job_name] = job
    state.domain_apply = record
    state.mark("domain-apply")
    return framework, {
        "ok": True,
        "idempotent": False,
        "domain_applied": True,
        "level_id": record["level_id"],
        "old_version": record["old_version"],
        "new_version": record["new_version"],
    }


def hydrate_applied_domain(
    framework: FrameworkDocument,
    subset: DemoSubset,
    state: LiveState,
) -> FrameworkDocument:
    record = state.domain_apply or {}
    if not record.get("applied"):
        return framework
    level_id = str(record.get("level_id") or "")
    new_version = int(record.get("new_version") or 0)
    if not level_id or new_version < 1:
        return framework
    current = framework.level(level_id)
    if current.version >= new_version:
        return framework
    updated, _record = _advance_domain(framework, subset)
    return updated


def _advance_domain(
    framework: FrameworkDocument,
    subset: DemoSubset,
) -> tuple[FrameworkDocument, dict[str, Any]]:
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
    plans = approve_plans(
        plan_level_updates(
            analysis,
            old_level=old,
            new_level=new,
            dependency_graph=framework.dependency_graph,
            profiles=framework.profiles,
        )
    )
    profiles, graph, _report, _finished = apply_approved_plans(
        plans,
        framework.profiles,
        framework.dependency_graph,
        new_level=new,
    )
    updated = framework.with_level(new).with_profiles(profiles).with_graph(graph)
    return updated, {
        "applied": True,
        "job_name": JOB_SURGICAL,
        "level_id": old.id,
        "level_label": old.label,
        "old_version": old.version,
        "new_version": new.version,
        "profile_id": profile.id,
        "section_id": "level_expectations",
    }


def _preservation_record(state: LiveState) -> Mapping[str, Any]:
    verification = (state.verification or {}).get("preservation") or {}
    if verification:
        return verification
    return (state.preservation or {}).get("verification") or {}
