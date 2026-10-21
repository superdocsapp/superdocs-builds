"""Live profile baseline integrity. SuperDocs fill is not the profile source of truth."""

from __future__ import annotations

from typing import Any, Mapping

from job_architecture.live.state import LiveState

INTEGRITY_NEEDS_REPAIR = "needs_repair"
INTEGRITY_AUTHORITATIVE_UPLOAD = "authoritative_upload"
INTEGRITY_REPAIR_PENDING_VERIFY = "repair_pending_export_verify"
INTEGRITY_VERIFIED = "verified"

PROFILE_FILL_SOURCE = "superdocs_fill"
PROFILE_UPLOAD_SOURCE = "authoritative_filled_upload"


def prepare_profile_integrity(state: LiveState) -> bool:
    current = dict(state.profile_integrity or {})
    status = str(current.get("status") or "")
    if status == INTEGRITY_VERIFIED:
        return False
    repair = state.jobs.get("profile_repair") or {}
    if _repair_applied(repair):
        updated = {
            **current,
            "status": INTEGRITY_REPAIR_PENDING_VERIFY,
            "reason": (
                "Reviewed duplicate-section repair was approved. Export the live profile "
                "and run verify-profile-structure before surgical-update."
            ),
            "repair_required": False,
        }
        if current != updated:
            state.profile_integrity = updated
            return True
        return False
    profile = state.jobs.get("profile") or {}
    if _looks_like_superdocs_fill(profile) and status != INTEGRITY_AUTHORITATIVE_UPLOAD:
        updated = {
            **current,
            "status": INTEGRITY_NEEDS_REPAIR,
            "reason": (
                "Live profile was created by a SuperDocs fill against an already-filled "
                "document. That class of edit can duplicate Level expectations. "
                "Run repair-profile; do not start surgical-update."
            ),
            "repair_required": True,
        }
        if current != updated:
            state.profile_integrity = updated
            return True
        return False
    return False


def mark_authoritative_upload(state: LiveState, *, profile_id: str, document_id: str) -> None:
    if (state.profile_integrity or {}).get("status") == INTEGRITY_VERIFIED:
        return
    if _looks_like_superdocs_fill(state.jobs.get("profile") or {}):
        prepare_profile_integrity(state)
        return
    state.profile_integrity = {
        "status": INTEGRITY_AUTHORITATIVE_UPLOAD,
        "reason": "Deterministic filled profile uploaded; SuperDocs did not regenerate sections.",
        "repair_required": False,
        "profile_id": profile_id,
        "document_id": document_id,
    }


def mark_structure_verified(state: LiveState, *, path: str) -> None:
    state.profile_integrity = {
        **dict(state.profile_integrity or {}),
        "status": INTEGRITY_VERIFIED,
        "reason": f"Exported profile structure verified from {path}",
        "repair_required": False,
        "verified_path": path,
    }


def surgical_blocked_reason(state: LiveState) -> str | None:
    prepare_profile_integrity(state)
    status = str((state.profile_integrity or {}).get("status") or "")
    if status == INTEGRITY_NEEDS_REPAIR:
        return (
            "Refusing surgical-update: the live profile baseline is structurally untrusted. "
            "A SuperDocs fill against an already-filled profile can duplicate Level expectations. "
            "Run: python scripts/superdocs_live.py repair-profile --confirm"
        )
    if status == INTEGRITY_REPAIR_PENDING_VERIFY:
        return (
            "Refusing surgical-update until the repaired live profile is exported and "
            "verify-profile-structure confirms exactly one Level expectations block. "
            "Run: python scripts/superdocs_live.py export --kind profile --confirm"
        )
    return None


def looks_like_superdocs_fill(job: Mapping[str, Any]) -> bool:
    if not job.get("job_id"):
        return False
    if job.get("source") == PROFILE_UPLOAD_SOURCE:
        return False
    return True


def _looks_like_superdocs_fill(job: Mapping[str, Any]) -> bool:
    return looks_like_superdocs_fill(job)


def _repair_applied(job: Mapping[str, Any]) -> bool:
    if not job.get("job_id"):
        return False
    outcome = str(job.get("review_outcome") or job.get("human_decision") or "")
    return outcome == "approved" and job.get("mutation_applied") is True
