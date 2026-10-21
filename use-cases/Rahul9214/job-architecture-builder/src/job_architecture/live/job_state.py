"""Reviewed SuperDocs job lifecycle. Remote status is not a domain apply."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from job_architecture.live.integrity import prepare_profile_integrity
from job_architecture.live.state import LiveState, RuntimeStore
from job_architecture.superdocs.models import ReviewDecision

REVIEWED_JOB_ORDER = ("framework", "profile", "surgical")
REMOTE_STATUSES = frozenset({"queued", "processing", "awaiting_approval", "completed", "failed"})
REVIEW_OUTCOMES = frozenset({"pending", "approved", "rejected", "mixed", "none"})


def normalize_remote_status(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip().lower()
    aliases = {"pending": "queued", "in_progress": "processing", "success": "completed"}
    text = aliases.get(text, text)
    return text if text in REMOTE_STATUSES else text


def normalize_review_outcome(value: Any) -> str:
    if value is None or value == "":
        return "none"
    text = str(value).strip().lower()
    aliases = {"approve": "approved", "reject": "rejected"}
    text = aliases.get(text, text)
    if text not in REVIEW_OUTCOMES:
        return "none"
    return text


def review_outcome_from_decisions(decisions: Sequence[Mapping[str, Any] | ReviewDecision]) -> dict[str, Any]:
    if not decisions:
        return {
            "review_outcome": "none",
            "human_decision": "none",
            "mutation_applied": False,
            "domain_applied": False,
            "partial_mutation": False,
            "review_decisions": [],
        }
    rows = [_decision_row(item) for item in decisions]
    flags = [bool(item["approved"]) for item in rows]
    if all(flags):
        outcome = "approved"
        mutation_applied = True
        partial = False
    elif not any(flags):
        outcome = "rejected"
        mutation_applied = False
        partial = False
    else:
        outcome = "mixed"
        mutation_applied = True
        partial = True
    return {
        "review_outcome": outcome,
        "human_decision": outcome,
        "mutation_applied": mutation_applied,
        "domain_applied": False,
        "partial_mutation": partial,
        "review_decisions": rows,
    }


def reviewed_job_action(job: Mapping[str, Any] | None) -> str:
    """What the live CLI/orchestrator should do with a reviewed mutation job."""
    if not job or not job.get("job_id"):
        return "new_edit"
    remote = normalize_remote_status(job.get("remote_job_status") or job.get("status"))
    outcome = normalize_review_outcome(job.get("review_outcome") or job.get("human_decision"))
    derived = None
    if job.get("review_decisions"):
        derived = review_outcome_from_decisions(job.get("review_decisions") or [])
        outcome = derived["review_outcome"]
    mutation_applied = job.get("mutation_applied")
    if mutation_applied is None:
        if derived is not None:
            mutation_applied = derived["mutation_applied"]
        else:
            mutation_applied = outcome in {"approved", "mixed"}
    if remote in {"queued", "processing"}:
        return "poll"
    if remote == "awaiting_approval":
        return "resume"
    if remote == "failed":
        if mutation_applied:
            return "ambiguous"
        return "new_edit"
    if remote == "completed":
        if outcome == "rejected":
            return "new_edit"
        if outcome == "approved":
            return "done" if mutation_applied else "ambiguous"
        if outcome == "mixed":
            return "partial"
        if outcome == "pending":
            return "resume"
        return "ambiguous"
    return "ambiguous"


def should_start_new_reviewed_edit(job: Mapping[str, Any] | None) -> bool:
    return reviewed_job_action(job) == "new_edit"


def annotate_review(state: LiveState, job_name: str, outcome: str) -> dict[str, Any]:
    job = state.jobs.get(job_name)
    if not job or not job.get("job_id"):
        raise ValueError(f"No saved job named {job_name}")
    normalized = normalize_review_outcome(outcome)
    if normalized not in {"approved", "rejected", "mixed", "none"}:
        raise ValueError("review outcome must be approved, rejected, mixed, or none")
    job["review_outcome"] = normalized
    job["human_decision"] = normalized
    job["remote_job_status"] = normalize_remote_status(job.get("remote_job_status") or job.get("status")) or job.get(
        "status"
    )
    if normalized in {"rejected", "none"}:
        job["mutation_applied"] = False
        job["partial_mutation"] = False
    elif normalized == "approved":
        job["mutation_applied"] = True
        job["partial_mutation"] = False
    else:
        job["mutation_applied"] = True
        job["partial_mutation"] = True
    job["domain_applied"] = False
    job["review_annotated"] = True
    job.pop("needs_review_annotation", None)
    return job


def prepare_jobs(state: LiveState) -> bool:
    """Fill remote/review fields and infer missing outcomes. Returns True if state changed."""
    changed = False
    later_present = _later_reviewed_jobs(state)
    for name in REVIEWED_JOB_ORDER:
        job = state.jobs.get(name)
        if not isinstance(job, dict) or not job.get("job_id"):
            continue
        before = json_safe_snapshot(job)
        _normalize_job_record(job, name=name, operation_keys=state.operation_keys)
        if not _has_explicit_outcome(job):
            if later_present.get(name):
                job["review_outcome"] = "approved"
                job["human_decision"] = "approved"
                job["mutation_applied"] = True
                job["partial_mutation"] = False
                job["domain_applied"] = False
                job["review_inferred"] = True
            elif (job.get("remote_job_status") or job.get("status")) == "completed":
                job["review_outcome"] = "none"
                job["human_decision"] = "none"
                job["mutation_applied"] = False
                job["domain_applied"] = False
                job["partial_mutation"] = False
                job["review_inferred"] = True
                if f"review:{name}" in state.completed_steps:
                    job["needs_review_annotation"] = True
        if json_safe_snapshot(job) != before:
            changed = True
    if prepare_profile_integrity(state):
        changed = True
    return changed


def load_and_prepare(store: RuntimeStore) -> LiveState | None:
    state = store.load()
    if state is None:
        return None
    if prepare_jobs(state):
        store.save(state)
    return state


def archive_job_attempt(prior: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not prior or not prior.get("job_id"):
        return [dict(item) for item in list((prior or {}).get("history") or [])]
    history = [dict(item) for item in list(prior.get("history") or [])]
    archived = {key: value for key, value in prior.items() if key != "history"}
    history.append(archived)
    return history


def next_attempt_number(prior: Mapping[str, Any] | None) -> int:
    if not prior or not prior.get("job_id"):
        return 1
    return int(prior.get("attempt") or 1) + 1


def next_edit_operation_key(name: str, prior: Mapping[str, Any] | None) -> str:
    return f"live-edit:{name}:{next_attempt_number(prior)}"


def json_safe_snapshot(job: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items()}


def _normalize_job_record(job: dict[str, Any], *, name: str, operation_keys: Sequence[str]) -> None:
    remote = normalize_remote_status(job.get("remote_job_status") or job.get("status"))
    if remote:
        job["remote_job_status"] = remote
        job["status"] = remote
    if not job.get("attempt"):
        job["attempt"] = 1
    if not job.get("operation_key"):
        legacy = f"live-edit:{name}"
        job["operation_key"] = legacy if legacy in operation_keys else f"live-edit:{name}:1"
    if job.get("review_decisions") and not _has_explicit_outcome(job):
        job.update(review_outcome_from_decisions(job["review_decisions"]))
        return
    outcome = normalize_review_outcome(job.get("review_outcome") or job.get("human_decision"))
    if outcome != "none" or job.get("review_outcome") is not None or job.get("human_decision") is not None:
        job["review_outcome"] = outcome
        job["human_decision"] = outcome
    if "domain_applied" not in job:
        job["domain_applied"] = False
    if "mutation_applied" not in job and outcome in {"rejected", "none", "pending"}:
        job["mutation_applied"] = False
    if "mutation_applied" not in job and outcome == "approved":
        job["mutation_applied"] = True
    if "mutation_applied" not in job and outcome == "mixed":
        job["mutation_applied"] = True
        job["partial_mutation"] = True


def _has_explicit_outcome(job: Mapping[str, Any]) -> bool:
    if job.get("review_annotated"):
        return True
    outcome = normalize_review_outcome(job.get("review_outcome") or job.get("human_decision"))
    if outcome in {"approved", "rejected", "mixed"}:
        return True
    if job.get("review_decisions"):
        return True
    return False


def _later_reviewed_jobs(state: LiveState) -> dict[str, bool]:
    present = {name: bool((state.jobs.get(name) or {}).get("job_id")) for name in REVIEWED_JOB_ORDER}
    later: dict[str, bool] = {}
    for index, name in enumerate(REVIEWED_JOB_ORDER):
        later[name] = any(present[other] for other in REVIEWED_JOB_ORDER[index + 1 :])
    return later


def _decision_row(item: Mapping[str, Any] | ReviewDecision) -> dict[str, Any]:
    if isinstance(item, ReviewDecision):
        return {"change_id": item.change_id, "approved": bool(item.approved)}
    return {"change_id": str(item.get("change_id")), "approved": bool(item.get("approved"))}
