"""SuperDocs live workflow. Depends on SuperDocsClientProtocol, not HTTP."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from job_architecture.hashes import hash_all_sections
from job_architecture.live.domain_apply import (
    apply_verified_domain,
    hydrate_applied_domain,
    record_preservation_verification,
    record_structure_verification,
)
from job_architecture.live.docxgen import write_demo_artifacts
from job_architecture.live.instructions import (
    compact_framework_instruction,
    profile_duplicate_repair_instruction,
    subset_profile_for_demo,
    surgical_edit_instruction,
    surgical_update_plan,
)
from job_architecture.live.integrity import (
    looks_like_superdocs_fill,
    mark_authoritative_upload,
    mark_structure_verified,
    prepare_profile_integrity,
    surgical_blocked_reason,
)
from job_architecture.live.job_state import (
    annotate_review,
    archive_job_attempt,
    next_attempt_number,
    next_edit_operation_key,
    prepare_jobs,
    review_outcome_from_decisions,
    reviewed_job_action,
    should_start_new_reviewed_edit,
)
from job_architecture.live.preservation import inspect_docx_layout, verify_exported_profile
from job_architecture.live.roster import reconcile_documents_from_roster
from job_architecture.live.selection import build_export_request, documents_with_kind
from job_architecture.live.state import LiveState, RuntimeStore
from job_architecture.live.subset import DemoSubset, build_demo_framework, load_demo_subset
from job_architecture.profile_structure import validate_level_expectations_block, validate_profile_document_text
from job_architecture.superdocs.errors import JobFailedError, JobTimeoutError, SuperDocsError
from job_architecture.superdocs.models import (
    AsyncJobHandle,
    JobSnapshot,
    ReviewDecision,
    SearchAccepted,
    SessionRoster,
    TemplateRef,
    UploadResult,
)
from job_architecture.superdocs.protocol import SuperDocsClientProtocol

TEMPLATE_FILES = {
    "framework": "framework-template.docx",
    "role-profile": "role-profile-template.docx",
}


@dataclass(frozen=True)
class LiveIntent:
    action: str
    summary: str
    mutating_calls: tuple[str, ...]
    estimated_count: int


@dataclass(frozen=True)
class ProfilePublishResult:
    profile_id: str
    document_id: str
    integrity_status: str
    structure_ok: bool


def prepare_demo_artifacts(
    artifacts_dir: Path,
    store: RuntimeStore,
    *,
    subset: DemoSubset | None = None,
) -> dict[str, Path]:
    spec = subset or load_demo_subset()
    _, framework = build_demo_framework(spec)
    profile = subset_profile_for_demo(framework, spec)
    written = write_demo_artifacts(
        artifacts_dir,
        subset=spec,
        framework=framework,
        profile=profile,
    )
    state = store.load_or_create(spec.session_id)
    prepare_jobs(state)
    if "prepare" not in state.completed_steps:
        state.completed_steps.append("prepare")
    if state.workflow in {"new", "prepare"}:
        state.workflow = "prepare"
    store.save(state)
    return written


class LiveOrchestrator:
    def __init__(
        self,
        client: SuperDocsClientProtocol,
        store: RuntimeStore,
        *,
        artifacts_dir: Path,
        subset: DemoSubset | None = None,
    ) -> None:
        self.client = client
        self.store = store
        self.artifacts_dir = artifacts_dir
        self.subset = subset or load_demo_subset()
        self.architecture, self.framework = build_demo_framework(self.subset)
        existing = self.store.load()
        if existing is not None:
            self.framework = hydrate_applied_domain(self.framework, self.subset, existing)

    def state(self) -> LiveState:
        state = self.store.load_or_create(self.subset.session_id)
        if prepare_jobs(state):
            self.store.save(state)
        return state

    def _save(self, state: LiveState) -> None:
        self.store.save(state)

    def prepare(self) -> dict[str, Path]:
        profile = subset_profile_for_demo(self.framework, self.subset)
        written = write_demo_artifacts(
            self.artifacts_dir,
            subset=self.subset,
            framework=self.framework,
            profile=profile,
        )
        state = self.state()
        if "prepare" not in state.completed_steps:
            state.completed_steps.append("prepare")
        if state.workflow in {"new", "prepare"}:
            state.workflow = "prepare"
        self._save(state)
        return written

    def upload_intent(self) -> LiveIntent:
        state = self.state()
        pending_docs = [item.role_id for item in self.subset.roles if not state.document_for(item.role_id)]
        pending_templates = [name for name in TEMPLATE_FILES if name not in state.templates]
        calls = tuple(f"POST /v1/documents/upload ({role_id})" for role_id in pending_docs) + tuple(
            f"POST /v1/templates/upload-base64 ({name})" for name in pending_templates
        )
        return LiveIntent(
            action="upload",
            summary=(
                f"Upload {len(pending_docs)} job-description DOCX files into session "
                f"{self.subset.session_id} with open_mode=new_focused, then "
                f"upload or reuse {len(pending_templates)} templates. "
                "Existing ids in .runtime/ are skipped."
            ),
            mutating_calls=calls,
            estimated_count=len(calls),
        )

    def upload_sources(self) -> SessionRoster:
        self.prepare()
        state = self.state()
        try:
            for role in self.subset.roles:
                if state.document_for(role.role_id):
                    continue
                path = self.artifacts_dir / f"{role.role_id}.docx"
                key = f"live-upload:{role.role_id}"
                uploaded = self.client.upload_document(
                    path.name,
                    path.read_bytes(),
                    session_id=self.subset.session_id,
                    open_mode="new_focused",
                    operation_key=key,
                )
                self._record_uploaded_document(
                    state,
                    role_id=role.role_id,
                    kind=role.kind,
                    filename=path.name,
                    uploaded=uploaded,
                    operation_key=key,
                )
            roster = self.client.list_session_documents(self.subset.session_id)
            _assert_multi_document(roster, expected=len(self.subset.roles))
            reconcile_documents_from_roster(state, roster)
            state.mark("upload")
            self._save(state)
            return roster
        except Exception as exc:
            state.last_error = f"{type(exc).__name__}: {_safe_error(exc)}"
            self._save(state)
            raise

    def upload_templates(self) -> dict[str, str]:
        self.prepare()
        state = self.state()
        try:
            needed = {name: filename for name, filename in TEMPLATE_FILES.items() if name not in state.templates}
            existing: dict[str, TemplateRef] = {}
            if needed:
                existing = {item.filename: item for item in self.client.list_templates() if item.filename}
            for name, filename in needed.items():
                path = self.artifacts_dir / filename
                key = f"live-template:{name}"
                reused = existing.get(filename)
                if reused is not None:
                    template_id = reused.template_id
                else:
                    uploaded = self.client.upload_template(
                        path.name,
                        path.read_bytes(),
                        operation_key=key,
                    )
                    template_id = uploaded.template_id
                    existing[filename] = uploaded
                state.templates[name] = {
                    "template_id": template_id,
                    "filename": filename,
                    "operation_key": key,
                }
                state.remember_operation(key)
                self._save(state)
            state.mark("templates")
            self._save(state)
            return {name: str(item["template_id"]) for name, item in state.templates.items()}
        except Exception as exc:
            state.last_error = f"{type(exc).__name__}: {_safe_error(exc)}"
            self._save(state)
            raise

    def setup(self) -> SessionRoster:
        roster = self.upload_sources()
        self.upload_templates()
        return roster

    def framework_intent(self) -> LiveIntent:
        state = self.state()
        calls, summary = _reviewed_intent_payload(
            state,
            "framework",
            upload_kind="framework",
            upload_label="framework-starter",
            edit_label="framework",
            default_summary=(
                "Create or edit the framework document from the approved structured "
                "architecture. SuperDocs must not invent families, tracks, or levels."
            ),
        )
        return LiveIntent(
            action="framework",
            summary=summary,
            mutating_calls=tuple(calls),
            estimated_count=len(calls),
        )

    def start_framework(self) -> JobSnapshot:
        self.prepare()
        state = self.state()
        try:
            snapshot = self._resume_job(state, "framework")
            if snapshot is not None:
                return snapshot
            doc = self._ensure_named_document(
                state,
                kind="framework",
                filename="framework-starter.docx",
                operation_key="live-upload:framework-starter",
            )
            handle = self.client.start_reviewed_edit(
                self.subset.session_id,
                compact_framework_instruction(self.framework, self.subset),
                document_id=doc["document_id"],
                operation_key=next_edit_operation_key("framework", state.jobs.get("framework")),
            )
            return self._record_and_wait(state, "framework", handle, extra={"document_id": doc["document_id"]})
        except Exception as exc:
            state.last_error = f"{type(exc).__name__}: {_safe_error(exc)}"
            self._save(state)
            raise

    def profile_intent(self) -> LiveIntent:
        state = self.state()
        calls: list[str] = []
        if state.document_for("profile") is None:
            calls.append("POST /v1/documents/upload (filled role profile)")
        blocked = surgical_blocked_reason(state)
        summary = (
            "Upload the deterministic filled role profile as the authoritative baseline. "
            "SuperDocs is not asked to regenerate already-decided section values."
        )
        if blocked:
            summary += " The existing live profile still needs a reviewed duplicate-section repair."
        return LiveIntent(
            action="profile",
            summary=summary,
            mutating_calls=tuple(calls),
            estimated_count=len(calls),
        )

    def start_profile(self) -> ProfilePublishResult:
        self.prepare()
        state = self.state()
        try:
            profile = subset_profile_for_demo(self.framework, self.subset)
            self._assert_local_profile_structure(profile)
            filename = f"{profile.id}.docx"
            path = self.artifacts_dir / filename
            if not path.is_file():
                raise SuperDocsError(f"Deterministic filled profile is missing: {path}")
            doc = self._ensure_named_document(
                state,
                kind="profile",
                filename=filename,
                operation_key="live-upload:profile-filled",
            )
            if not looks_like_superdocs_fill(state.jobs.get("profile") or {}):
                state.jobs["profile"] = {
                    **dict(state.jobs.get("profile") or {}),
                    "source": "authoritative_filled_upload",
                    "document_id": doc["document_id"],
                    "profile_id": profile.id,
                    "mutation_applied": False,
                    "domain_applied": False,
                    "review_outcome": "none",
                    "remote_job_status": "none",
                }
            mark_authoritative_upload(state, profile_id=profile.id, document_id=doc["document_id"])
            state.mark("profile")
            self._save(state)
            integrity = state.profile_integrity or {}
            return ProfilePublishResult(
                profile_id=profile.id,
                document_id=str(doc["document_id"]),
                integrity_status=str(integrity.get("status") or ""),
                structure_ok=True,
            )
        except Exception as exc:
            state.last_error = f"{type(exc).__name__}: {_safe_error(exc)}"
            self._save(state)
            raise

    def surgical_intent(self) -> LiveIntent:
        state = self.state()
        blocked = surgical_blocked_reason(state)
        if blocked:
            return LiveIntent(
                action="surgical-update",
                summary=blocked,
                mutating_calls=(),
                estimated_count=0,
            )
        calls, summary = _reviewed_intent_payload(
            state,
            "surgical",
            upload_kind="profile",
            upload_label="filled role profile",
            edit_label="surgical-update, level_expectations only",
            default_summary=(
                "Targeted reviewed edit of ONLY the level-expectations section on the "
                "graph-selected occupied profile. Unrelated sections must be left untouched."
            ),
        )
        return LiveIntent(
            action="surgical-update",
            summary=summary,
            mutating_calls=tuple(calls),
            estimated_count=len(calls),
        )

    def start_surgical_update(self) -> JobSnapshot:
        self.prepare()
        state = self.state()
        try:
            self._assert_surgical_baseline_ready(state)
            snapshot = self._resume_job(state, "surgical")
            if snapshot is not None:
                return snapshot
            profile, old, new, plan = surgical_update_plan(self.framework, self.subset)
            self._assert_local_profile_structure(profile)
            filename = f"{profile.id}.docx"
            if not (self.artifacts_dir / filename).is_file():
                raise SuperDocsError(f"Deterministic filled profile is missing: {filename}")
            doc = self._ensure_named_document(
                state,
                kind="profile",
                filename=filename,
                operation_key="live-upload:profile-filled",
            )
            instruction = surgical_edit_instruction(plan)
            if "level_expectations" not in instruction:
                raise SuperDocsError("Surgical instruction did not name the target section")
            state.preservation = {
                "profile_id": profile.id,
                "role_id": profile.role_id,
                "level_id": old.id,
                "level_label": old.label,
                "old_version": old.version,
                "new_version": new.version,
                "section_id": plan.section_id,
                "before_hashes": hash_all_sections(profile),
                "expected_after_fragment": "Explicit domain sequencing veto for live verification",
                "preserved_purpose": profile.summary[:180],
                "preserved_responsibilities": (profile.responsibilities[0] if profile.responsibilities else "")[:180],
            }
            handle = self.client.start_reviewed_edit(
                self.subset.session_id,
                instruction,
                document_id=doc["document_id"],
                operation_key=next_edit_operation_key("surgical", state.jobs.get("surgical")),
            )
            return self._record_and_wait(
                state,
                "surgical",
                handle,
                extra={
                    "document_id": doc["document_id"],
                    "profile_id": profile.id,
                    "section_id": plan.section_id,
                },
            )
        except Exception as exc:
            state.last_error = f"{type(exc).__name__}: {_safe_error(exc)}"
            self._save(state)
            raise

    def repair_profile_intent(self) -> LiveIntent:
        state = self.state()
        blocked = surgical_blocked_reason(state)
        if blocked is None or "repair-profile" not in blocked:
            if (state.profile_integrity or {}).get("status") == "repair_pending_export_verify":
                return LiveIntent(
                    action="repair-profile",
                    summary=(
                        "Reviewed repair already approved. Export the live profile and run "
                        "verify-profile-structure before surgical-update."
                    ),
                    mutating_calls=(),
                    estimated_count=0,
                )
            return LiveIntent(
                action="repair-profile",
                summary="No duplicated live profile baseline is recorded; not starting a repair edit.",
                mutating_calls=(),
                estimated_count=0,
            )
        calls: list[str] = []
        if should_start_new_reviewed_edit(state.jobs.get("profile_repair") or {}):
            calls.append("POST /v1/chat/async (profile duplicate-section repair)")
        summary = (
            "Reviewed in-place repair: remove the duplicate Level expectations block only. "
            "Preserve the intended approved profile content. Stops at human approval."
        )
        if not should_start_new_reviewed_edit(state.jobs.get("profile_repair") or {}):
            summary = "Resuming the in-place profile repair job. No duplicate SuperDocs edit."
        return LiveIntent(
            action="repair-profile",
            summary=summary,
            mutating_calls=tuple(calls),
            estimated_count=len(calls),
        )

    def start_profile_repair(self) -> JobSnapshot:
        self.prepare()
        state = self.state()
        try:
            blocked = surgical_blocked_reason(state)
            if blocked is None or "repair-profile" not in blocked:
                raise SuperDocsError(
                    "No safe in-place profile repair is required. Not rewriting the live document."
                )
            snapshot = self._resume_job(state, "profile_repair")
            if snapshot is not None:
                return snapshot
            profile = subset_profile_for_demo(self.framework, self.subset)
            self._assert_local_profile_structure(profile)
            doc = state.document_for("profile")
            if doc is None:
                raise SuperDocsError("No existing live profile document to repair in place")
            handle = self.client.start_reviewed_edit(
                self.subset.session_id,
                profile_duplicate_repair_instruction(profile.level_expectations),
                document_id=doc["document_id"],
                operation_key=next_edit_operation_key("profile_repair", state.jobs.get("profile_repair")),
            )
            return self._record_and_wait(
                state,
                "profile_repair",
                handle,
                extra={
                    "document_id": doc["document_id"],
                    "profile_id": profile.id,
                    "section_id": "level_expectations",
                    "repair": "duplicate_level_expectations",
                },
            )
        except Exception as exc:
            state.last_error = f"{type(exc).__name__}: {_safe_error(exc)}"
            self._save(state)
            raise

    def verify_profile_structure(self, path: Path) -> dict[str, object]:
        layout = inspect_docx_layout(path)
        report = validate_profile_document_text(layout.text, layout=layout.as_dict())
        state = self.state()
        record_structure_verification(state, path=str(path), report=report)
        if report.ok:
            mark_structure_verified(state, path=str(path))
            self._save(state)
        else:
            self._save(state)
        return {
            "ok": report.ok,
            "violations": report.violations,
            "field_counts": report.field_counts,
            "section_counts": report.section_counts,
            "field_values": report.field_values,
            "layout": report.layout,
            "path": str(path),
        }

    def verify_export(self, path: Path) -> dict[str, object]:
        state = self.state()
        markers = {
            "purpose": str((state.preservation or {}).get("preserved_purpose") or ""),
            "responsibilities": str((state.preservation or {}).get("preserved_responsibilities") or ""),
        }
        markers = {key: value for key, value in markers.items() if value}
        check = verify_exported_profile(
            path,
            expected_new_fragment=str((state.preservation or {}).get("expected_after_fragment") or ""),
            preserved_markers=markers,
        )
        record_preservation_verification(state, path=str(path), check=check)
        self._save(state)
        return {
            "ok": check.ok,
            "found_new_fragment": check.found_new_fragment,
            "preserved_markers": check.preserved_markers,
            "missing_markers": check.missing_markers,
            "path": str(path),
        }

    def finalize_domain_apply(self, job_name: str = "surgical") -> dict[str, object]:
        state = self.state()
        try:
            self.framework, result = apply_verified_domain(
                self.framework,
                self.subset,
                state,
                job_name=job_name,
            )
            self._save(state)
            return result
        except Exception as exc:
            state.last_error = f"{type(exc).__name__}: {_safe_error(exc)}"
            self._save(state)
            raise

    def search_intent(self) -> LiveIntent:
        job = self.state().jobs.get("search") or {}
        if job.get("job_id"):
            status = job.get("remote_job_status") or job.get("status") or "queued"
            return LiveIntent(
                action="search",
                summary=(
                    f"Resume existing search job (status={status}). Poll the same job id; "
                    "do not POST another search. The dependency graph remains the authority "
                    "for surgical propagation."
                ),
                mutating_calls=(),
                estimated_count=0,
            )
        return LiveIntent(
            action="search",
            summary=(
                f"Cross-session search demonstration: {self.subset.search_query} "
                "The dependency graph remains the authority for surgical propagation."
            ),
            mutating_calls=("POST /v1/chat/async (search, cross_session_search=true)",),
            estimated_count=1,
        )

    def start_search(self) -> SearchAccepted:
        return self.poll_search()["accepted"]

    def poll_search(self) -> dict[str, object]:
        state = self.state()
        job = dict(state.jobs.get("search") or {})
        posted = False
        try:
            if not job.get("job_id"):
                accepted = self.client.search_documents(
                    self.subset.search_query,
                    session_id=self.subset.session_id,
                    cross_session=True,
                    operation_key="live-search:ic4",
                )
                posted = True
                state.remember_operation("live-search:ic4")
                job = {
                    "job_id": accepted.handle.job_id,
                    "status": accepted.handle.normalized_status,
                    "remote_job_status": accepted.handle.normalized_status,
                    "query": self.subset.search_query,
                    "operation_key": "live-search:ic4",
                    "verified": False,
                }
                state.jobs["search"] = job
                self._save(state)
            snapshot = self._poll_existing_search(state, job)
            accepted = SearchAccepted(
                handle=AsyncJobHandle(
                    job_id=str(job["job_id"]),
                    session_id=self.subset.session_id,
                    status=snapshot.status,
                    normalized_status=snapshot.status,
                    operation_key=str(job.get("operation_key") or "live-search:ic4"),
                ),
                query=str(job.get("query") or self.subset.search_query),
            )
            return {
                "accepted": accepted,
                "snapshot": snapshot,
                "posted": posted,
                "verified": bool(job.get("verified")),
                "terminal": snapshot.status in {"completed", "failed", "cancelled"},
            }
        except Exception as exc:
            state.last_error = f"{type(exc).__name__}: {_safe_error(exc)}"
            self._save(state)
            raise

    def _poll_existing_search(self, state: LiveState, job: dict) -> JobSnapshot:
        job_id = str(job["job_id"])
        snapshot = self.client.get_job(job_id)
        if snapshot.status in {"queued", "processing"}:
            try:
                snapshot = self.client.wait_for_job(job_id, stop_on_review=False)
            except JobTimeoutError:
                job.update(_search_job_fields(snapshot, verified=False))
                state.jobs["search"] = job
                self._save(state)
                raise
            except JobFailedError as exc:
                job.update(
                    {
                        "status": "failed",
                        "remote_job_status": "failed",
                        "verified": False,
                        "terminal": True,
                        "error": _safe_error(exc),
                        "has_result": False,
                    }
                )
                state.jobs["search"] = job
                self._save(state)
                raise
        verified = snapshot.status == "completed" and not snapshot.error
        job.update(_search_job_fields(snapshot, verified=verified))
        state.jobs["search"] = job
        if verified:
            state.mark("search")
        self._save(state)
        return snapshot

    def pending_changes(self, job_name: str) -> JobSnapshot:
        state = self.state()
        job = state.jobs.get(job_name)
        if not job or not job.get("job_id"):
            raise SuperDocsError(f"No saved job named {job_name}")
        snapshot = self.client.get_job(job["job_id"])
        job["status"] = snapshot.status
        job["remote_job_status"] = snapshot.status
        job["awaiting_kind"] = snapshot.awaiting_kind
        self._save(state)
        return snapshot

    def submit_decisions(self, job_name: str, decisions: Sequence[ReviewDecision]) -> JobSnapshot:
        state = self.state()
        job = state.jobs.get(job_name)
        if not job or not job.get("job_id"):
            raise SuperDocsError(f"No saved job named {job_name}")
        if not decisions:
            raise SuperDocsError("Explicit approve/reject decisions are required")
        try:
            self.client.submit_review(
                self.subset.session_id,
                job["job_id"],
                decisions,
                operation_key=f"live-review:{job_name}:{job['job_id']}",
            )
            snapshot = self.client.wait_for_job(job["job_id"], stop_on_review=True)
            outcome = review_outcome_from_decisions(decisions)
            job["status"] = snapshot.status
            job["remote_job_status"] = snapshot.status
            job["awaiting_kind"] = snapshot.awaiting_kind
            job.update(outcome)
            job.pop("needs_review_annotation", None)
            prepare_profile_integrity(state)
            state.mark(f"review:{job_name}")
            self._save(state)
            return snapshot
        except Exception as exc:
            state.last_error = f"{type(exc).__name__}: {_safe_error(exc)}"
            self._save(state)
            raise

    def continue_intent(self, job_name: str) -> LiveIntent:
        return LiveIntent(
            action="continue",
            summary=f"Explicitly continue large-edit job {job_name} after continue_prompt. Not an approval.",
            mutating_calls=(f"POST /v1/chat/{{session}}/continue ({job_name})",),
            estimated_count=1,
        )

    def continue_after_review(self, job_name: str, *, resume: bool = True) -> JobSnapshot:
        state = self.state()
        job = state.jobs.get(job_name)
        if not job or not job.get("job_id"):
            raise SuperDocsError(f"No saved job named {job_name}")
        try:
            self.client.continue_large_edit(
                self.subset.session_id,
                job["job_id"],
                resume=resume,
                operation_key=f"live-continue:{job_name}:{job['job_id']}",
            )
            waited = self.client.wait_for_job(job["job_id"], stop_on_review=True)
            job["status"] = waited.status
            job["remote_job_status"] = waited.status
            job["awaiting_kind"] = waited.awaiting_kind
            state.mark(f"continue:{job_name}")
            self._save(state)
            return waited
        except Exception as exc:
            state.last_error = f"{type(exc).__name__}: {_safe_error(exc)}"
            self._save(state)
            raise

    def export_intent(self, kind: str) -> LiveIntent:
        request = build_export_request(
            kind,
            session_id=self.subset.session_id,
            filename=f"{kind}.docx",
            framework=self.framework,
            subset=self.subset,
        )
        return LiveIntent(
            action="export",
            summary=(
                f"Export the {kind} artifact as DOCX by POSTing documented "
                f"html + session_id to /v1/documents/export "
                f"({len(request.html)} chars of HTML). SuperDocs is not asked "
                "to infer architecture or pick a session document by id."
            ),
            mutating_calls=("POST /v1/documents/export",),
            estimated_count=1,
        )

    def export(self, kind: str, destination: Path) -> Path:
        state = self.state()
        request = build_export_request(
            kind,
            session_id=self.subset.session_id,
            filename=destination.name,
            framework=self.framework,
            subset=self.subset,
        )
        try:
            self.client.export_document(
                destination,
                request,
                operation_key=f"live-export:{kind}",
            )
            state.remember_operation(f"live-export:{kind}")
            state.jobs.setdefault(kind, {})["export"] = str(destination)
            state.mark(f"export:{kind}")
            self._save(state)
            return destination
        except Exception as exc:
            state.last_error = f"{type(exc).__name__}: {_safe_error(exc)}"
            self._save(state)
            raise

    def _ensure_named_document(
        self,
        state: LiveState,
        *,
        kind: str,
        filename: str,
        operation_key: str,
    ) -> dict:
        matches = documents_with_kind(state, kind)
        if len(matches) > 1:
            raise SuperDocsError(
                f"Ambiguous {kind} document: {len(matches)} saved records match "
                f"kind={kind!r}; refusing to guess"
            )
        if matches:
            return matches[0]
        path = self.artifacts_dir / filename
        uploaded = self.client.upload_document(
            path.name,
            path.read_bytes(),
            session_id=self.subset.session_id,
            open_mode="new_focused",
            operation_key=operation_key,
        )
        return self._record_uploaded_document(
            state,
            role_id=kind,
            kind=kind,
            filename=path.name,
            uploaded=uploaded,
            operation_key=operation_key,
        )

    def _record_uploaded_document(
        self,
        state: LiveState,
        *,
        role_id: str,
        kind: str,
        filename: str,
        uploaded: UploadResult,
        operation_key: str,
    ) -> dict:
        record = {
            "role_id": role_id,
            "kind": kind,
            "filename": filename,
            "document_id": uploaded.document.document_id,
            "durable_document_id": uploaded.document.durable_document_id,
            "operation_key": operation_key,
        }
        state.documents.append(record)
        reconcile_documents_from_roster(state, uploaded.roster)
        state.remember_operation(operation_key)
        if kind == "profile" and "template" not in filename:
            mark_authoritative_upload(
                state,
                profile_id=str(record.get("role_id") or "profile"),
                document_id=str(uploaded.document.document_id),
            )
        self._save(state)
        return record

    def domain_update_applied(self, job_name: str) -> bool:
        job = self.state().jobs.get(job_name) or {}
        return bool(job.get("domain_applied"))

    def annotate_review(self, job_name: str, outcome: str) -> dict:
        state = self.state()
        job = annotate_review(state, job_name, outcome)
        self._save(state)
        return job

    def _assert_local_profile_structure(self, profile) -> None:
        report = validate_level_expectations_block(profile.level_expectations)
        if not report.ok:
            raise SuperDocsError(
                "Local domain profile level_expectations are malformed: " + "; ".join(report.violations)
            )
        path = self.artifacts_dir / f"{profile.id}.docx"
        if path.is_file():
            from job_architecture.live.preservation import inspect_docx_layout

            layout = inspect_docx_layout(path)
            doc_report = validate_profile_document_text(layout.text, layout=layout.as_dict())
            if not doc_report.ok:
                raise SuperDocsError(
                    "Local filled profile DOCX is malformed: " + "; ".join(doc_report.violations)
                )

    def _assert_surgical_baseline_ready(self, state: LiveState) -> None:
        blocked = surgical_blocked_reason(state)
        if blocked:
            raise SuperDocsError(blocked)
        profile = subset_profile_for_demo(self.framework, self.subset)
        self._assert_local_profile_structure(profile)

    def _record_and_wait(
        self,
        state: LiveState,
        name: str,
        handle: AsyncJobHandle,
        *,
        extra: dict | None = None,
    ) -> JobSnapshot:
        prior = dict(state.jobs.get(name) or {})
        attempt = next_attempt_number(prior)
        operation_key = handle.operation_key or next_edit_operation_key(name, prior)
        record = {
            **(extra or {}),
            "job_id": handle.job_id,
            "status": handle.normalized_status,
            "remote_job_status": handle.normalized_status,
            "attempt": attempt,
            "operation_key": operation_key,
            "review_outcome": "pending",
            "human_decision": "pending",
            "mutation_applied": False,
            "domain_applied": False,
            "partial_mutation": False,
            "prior_job_id": prior.get("job_id"),
            "history": archive_job_attempt(prior),
        }
        state.jobs[name] = record
        state.remember_operation(operation_key)
        self._save(state)
        snapshot = self.client.wait_for_job(handle.job_id, stop_on_review=True)
        record["status"] = snapshot.status
        record["remote_job_status"] = snapshot.status
        record["awaiting_kind"] = snapshot.awaiting_kind
        if snapshot.status == "awaiting_approval":
            record["review_outcome"] = "pending"
            record["human_decision"] = "pending"
        state.mark(name)
        self._save(state)
        return snapshot

    def _resume_job(self, state: LiveState, name: str) -> JobSnapshot | None:
        job = state.jobs.get(name) or {}
        action = reviewed_job_action(job)
        if action == "new_edit":
            return None
        if action == "ambiguous":
            job_id = job.get("job_id") or "(unknown)"
            raise SuperDocsError(
                f"Remote {name} job {job_id} is completed but review_outcome is missing. "
                "Not treating completed as applied, and not starting a blind retry. "
                f"Annotate locally: python scripts/superdocs_live.py annotate-review "
                f"--job {name} --review-outcome rejected|approved"
            )
        if action not in {"resume", "poll", "done", "partial"}:
            return None
        snapshot = self.client.get_job(job["job_id"])
        if snapshot.status in {"queued", "processing"}:
            snapshot = self.client.wait_for_job(snapshot.job_id, stop_on_review=True)
        job["status"] = snapshot.status
        job["remote_job_status"] = snapshot.status
        job["awaiting_kind"] = snapshot.awaiting_kind
        self._save(state)
        return snapshot


def _reviewed_intent_payload(
    state: LiveState,
    name: str,
    *,
    upload_kind: str,
    upload_label: str,
    edit_label: str,
    default_summary: str,
) -> tuple[list[str], str]:
    calls: list[str] = []
    if not documents_with_kind(state, upload_kind):
        calls.append(f"POST /v1/documents/upload ({upload_label})")
    job = state.jobs.get(name) or {}
    action = reviewed_job_action(job)
    if should_start_new_reviewed_edit(job):
        calls.append(f"POST /v1/chat/async ({edit_label})")
    summary = default_summary
    outcome = job.get("review_outcome") or job.get("human_decision")
    if action == "new_edit" and outcome == "rejected":
        summary = (
            f"Previous {name} review was rejected; mutation was not applied. "
            "Starting a new reviewed edit. The rejected attempt remains in history."
        )
    elif action == "ambiguous":
        summary = (
            f"Remote {name} job completed but review_outcome is not stored. "
            "Not treating completed as applied, and not starting a blind retry. "
            "Annotate locally: python scripts/superdocs_live.py annotate-review "
            f"--job {name} --review-outcome rejected|approved"
        )
    elif action == "partial":
        summary = (
            f"Mixed {name} review: only individually approved changes may have been applied. "
            "Not starting a duplicate edit."
        )
    elif action == "done":
        summary = (
            f"Latest {name} review was approved and mutation_applied is true. "
            "Not duplicating the completed edit."
        )
    return calls, summary


def _assert_multi_document(roster: SessionRoster, *, expected: int) -> None:
    ids = [item.document_id for item in roster.documents]
    if len(ids) < expected:
        raise SuperDocsError(
            f"Session roster has {len(ids)} documents; expected at least {expected} coexisting uploads"
        )
    if len(set(ids)) != len(ids):
        raise SuperDocsError("Session roster document ids are not unique")


def _safe_error(exc: BaseException) -> str:
    text = str(exc)
    lowered = text.lower()
    if "sk_" in lowered or "bearer " in lowered:
        return type(exc).__name__
    return text[:300]


def _search_job_fields(snapshot: JobSnapshot, *, verified: bool, error: str | None = None) -> dict:
    return {
        "status": snapshot.status,
        "remote_job_status": snapshot.status,
        "awaiting_kind": snapshot.awaiting_kind,
        "verified": verified,
        "terminal": snapshot.status in {"completed", "failed", "cancelled"},
        "has_result": snapshot.result is not None,
        "error": error or snapshot.error,
    }
