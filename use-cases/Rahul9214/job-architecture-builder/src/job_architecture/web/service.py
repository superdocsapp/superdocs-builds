"""Workspace operations. Delegates reasoning to existing domain functions."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from job_architecture.architecture import build_architecture, extract_corpus_evidence
from job_architecture.documents import render_framework_markdown, render_profile_markdown
from job_architecture.fixtures import PROJECT_ROOT, list_corpus_ids, load_corpus
from job_architecture.framework import generate_framework
from job_architecture.graph import DependencyGraphError
from job_architecture.level_text import CANONICAL_DIMENSIONS
from job_architecture.live.docxgen import markdown_to_docx
from job_architecture.live.state import RuntimeStore
from job_architecture.models import LevelDefinition
from job_architecture.propagation import (
    ChangeStatus,
    analyze_level_change,
    apply_approved_plans,
    plan_level_updates,
)
from job_architecture.superdocs.config import load_settings
from job_architecture.superdocs.errors import ConfigurationError
from job_architecture.web.errors import ApiError
from job_architecture.web.serializers import (
    architecture_summary,
    corpus_summary,
    exceptions_payload,
    framework_payload,
    impact_payload,
    plan_dict,
    preservation_payload,
    profile_detail,
    profile_summary,
    review_artifact_dict,
    review_payload,
    role_detail,
)
from job_architecture.web.store import ReviewSession, WorkspaceStore

EDITABLE_DIMENSIONS = tuple(item for item in CANONICAL_DIMENSIONS if item not in {"version", "label"})
SECRET_SUBSTRINGS = ("api_key", "authorization", "bearer ", "sk_")


class WorkspaceService:
    def __init__(self, store: WorkspaceStore | None = None) -> None:
        self.store = store or WorkspaceStore()

    def list_corpora(self) -> list[dict[str, Any]]:
        rows = []
        for corpus_id in list_corpus_ids():
            corpus = load_corpus(corpus_id)
            workspace = self.store.workspace(corpus_id)
            rows.append(corpus_summary(corpus, analyzed=workspace.analyzed))
        return rows

    def get_corpus(self, corpus_id: str) -> dict[str, Any]:
        corpus = self._load_corpus(corpus_id)
        workspace = self.store.workspace(corpus_id)
        return corpus_summary(corpus, analyzed=workspace.analyzed)

    def analyze(self, corpus_id: str) -> dict[str, Any]:
        corpus = self._load_corpus(corpus_id)
        architecture = build_architecture(corpus)
        evidences = extract_corpus_evidence(corpus)
        framework = generate_framework(architecture, evidences)
        workspace = self.store.workspace(corpus_id)
        workspace.analyzed = True
        workspace.architecture = architecture
        workspace.framework = framework
        workspace.evidences = evidences
        workspace.review = None
        return architecture_summary(architecture, corpus)

    def architecture(self, corpus_id: str) -> dict[str, Any]:
        corpus, architecture, _framework = self._require_analyzed(corpus_id)
        return architecture_summary(architecture, corpus)

    def roles(self, corpus_id: str) -> list[dict[str, Any]]:
        corpus, architecture, framework = self._require_analyzed(corpus_id)
        evidence_by_id = {item.role_id: item for item in self.store.workspace(corpus_id).evidences}
        rows = []
        for assessment in architecture.assessments:
            evidence = evidence_by_id[assessment.role_id]
            rows.append(
                role_detail(
                    corpus=corpus,
                    evidence=evidence,
                    assessment=assessment,
                    arch=architecture,
                    framework=framework,
                )
            )
        return rows

    def role(self, corpus_id: str, role_id: str) -> dict[str, Any]:
        corpus, architecture, framework = self._require_analyzed(corpus_id)
        try:
            assessment = architecture.assessment_for(role_id)
        except KeyError as exc:
            raise ApiError(404, "role_not_found", f"Unknown role {role_id}") from exc
        evidence = next((item for item in self.store.workspace(corpus_id).evidences if item.role_id == role_id), None)
        if evidence is None:
            raise ApiError(404, "role_not_found", f"Unknown role {role_id}")
        return role_detail(
            corpus=corpus,
            evidence=evidence,
            assessment=assessment,
            arch=architecture,
            framework=framework,
        )

    def exceptions(self, corpus_id: str) -> dict[str, Any]:
        corpus, architecture, framework = self._require_analyzed(corpus_id)
        return exceptions_payload(architecture, corpus, framework)

    def framework(self, corpus_id: str) -> dict[str, Any]:
        _corpus, _architecture, framework = self._require_analyzed(corpus_id)
        payload = framework_payload(framework)
        payload["editable_dimensions"] = list(EDITABLE_DIMENSIONS)
        return payload

    def profiles(self, corpus_id: str) -> dict[str, Any]:
        _corpus, _architecture, framework = self._require_analyzed(corpus_id)
        return {
            "profiles": [profile_summary(item) for item in framework.profiles],
            "review_artifacts": [review_artifact_dict(item) for item in (*framework.provisional_roles, *framework.misfits)],
        }

    def profile(self, corpus_id: str, profile_id: str) -> dict[str, Any]:
        _corpus, _architecture, framework = self._require_analyzed(corpus_id)
        try:
            return profile_detail(framework.profile(profile_id))
        except KeyError as exc:
            artifact = next(
                (item for item in (*framework.provisional_roles, *framework.misfits) if item.role_id == profile_id or f"profile-{item.role_id}" == profile_id),
                None,
            )
            if artifact is not None:
                return {
                    **review_artifact_dict(artifact),
                    "normalized_profile": False,
                    "message": "This role is a review artifact, not a normalized employee-readable profile.",
                }
            raise ApiError(404, "profile_not_found", f"Unknown profile {profile_id}") from exc

    def impact(self, corpus_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        old, new, analysis, _plans = self._plan_change(corpus_id, body)
        return {
            **impact_payload(analysis, old, new),
            "plans_preview_count": len(_plans),
        }

    def plan(self, corpus_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        old, new, analysis, plans = self._plan_change(corpus_id, body)
        workspace = self.store.workspace(corpus_id)
        workspace.review = ReviewSession(
            corpus_id=corpus_id,
            level_id=old.id,
            old_level=old,
            new_level=new,
            analysis=analysis,
            plans=plans,
        )
        return {
            "impact": impact_payload(analysis, old, new),
            "plans": [plan_dict(item) for item in plans],
            "review": review_payload(workspace.review),
        }

    def review(self, corpus_id: str) -> dict[str, Any]:
        workspace = self.store.workspace(corpus_id)
        if workspace.review is None:
            return {
                "corpus_id": corpus_id,
                "empty": True,
                "plans": [],
                "review_outcome": "none",
                "mutation_applied": False,
                "domain_applied": False,
                "remote_operation": "none",
                "message": "No pending review. Propose a level change first.",
            }
        return {"empty": False, **review_payload(workspace.review)}

    def submit_decisions(self, corpus_id: str, items: list[Mapping[str, Any]]) -> dict[str, Any]:
        session = self._require_review(corpus_id)
        if session.domain_applied:
            raise ApiError(409, "already_applied", "This review session was already applied.")
        if not items:
            raise ApiError(400, "decisions_required", "Explicit approve/reject decisions are required.")
        known = {_plan_key(plan) for plan in session.plans}
        for item in items:
            plan_id = str(item.get("plan_id") or "")
            if "approved" not in item:
                raise ApiError(400, "malformed_decision", "Each decision needs plan_id and approved.")
            if plan_id not in known:
                raise ApiError(400, "unknown_plan", f"Unknown plan {plan_id}")
            session.decisions[plan_id] = bool(item.get("approved"))
        session.review_outcome = _outcome_from_decisions(session)
        return review_payload(session)

    def apply_review(self, corpus_id: str) -> dict[str, Any]:
        workspace = self.store.workspace(corpus_id)
        session = self._require_review(corpus_id)
        if session.domain_applied:
            return {
                **review_payload(session),
                "idempotent": True,
            }
        if len(session.decisions) != len(session.plans):
            raise ApiError(
                409,
                "incomplete_review",
                "Every proposed update needs an explicit approve or reject before apply.",
            )
        if session.review_outcome == "pending":
            session.review_outcome = _outcome_from_decisions(session)
        if not session.decisions:
            raise ApiError(400, "decisions_required", "Explicit approve/reject decisions are required.")
        decided = []
        for plan in session.plans:
            approved = session.decisions.get(_plan_key(plan))
            if approved is True:
                decided.append(plan.with_status(ChangeStatus.APPROVED))
            else:
                decided.append(plan.with_status(ChangeStatus.REJECTED))
        framework = workspace.framework
        assert framework is not None
        try:
            profiles, graph, report, finished = apply_approved_plans(
                decided,
                framework.profiles,
                framework.dependency_graph,
                new_level=session.new_level,
            )
        except DependencyGraphError as exc:
            raise ApiError(409, "apply_failed", str(exc)) from exc
        applied_any = any(item.status is ChangeStatus.APPLIED for item in finished)
        if applied_any:
            workspace.framework = (
                framework.with_level(session.new_level).with_profiles(profiles).with_graph(graph)
            )
        session.plans = finished
        session.preservation = report
        session.mutation_applied = applied_any
        session.domain_applied = applied_any
        session.remote_operation = "local_completed"
        session.review_outcome = _outcome_from_decisions(session)
        return {
            **review_payload(session),
            "idempotent": False,
            "preservation": preservation_payload(report),
        }

    def export_local(self, corpus_id: str, kind: str, profile_id: str | None = None) -> dict[str, Any]:
        _corpus, _architecture, framework = self._require_analyzed(corpus_id)
        export_dir = PROJECT_ROOT / "exports" / "web" / corpus_id
        if kind == "framework":
            markdown = render_framework_markdown(framework)
            destination = export_dir / "framework.docx"
            markdown_to_docx(markdown, destination, title=f"Framework — {framework.organization}")
            record = {
                "ok": True,
                "kind": "framework",
                "path": str(destination),
                "filename": destination.name,
                "via": "local_docx",
                "superdocs": False,
            }
        elif kind == "profile":
            if not profile_id:
                raise ApiError(400, "profile_required", "Selected role-profile export needs profile_id.")
            try:
                profile = framework.profile(profile_id)
            except KeyError as exc:
                raise ApiError(404, "profile_not_found", f"Unknown profile {profile_id}") from exc
            markdown = render_profile_markdown(profile)
            destination = export_dir / f"{profile.id}.docx"
            markdown_to_docx(markdown, destination, title=profile.display_title)
            record = {
                "ok": True,
                "kind": "profile",
                "profile_id": profile.id,
                "path": str(destination),
                "filename": destination.name,
                "via": "local_docx",
                "superdocs": False,
            }
        else:
            raise ApiError(400, "invalid_export", "kind must be framework or profile")
        self.store.workspace(corpus_id).last_export = record
        return record

    def export_file(self, corpus_id: str, filename: str) -> Path:
        self._load_corpus(corpus_id)
        safe = Path(filename).name
        if safe != filename or not safe.endswith(".docx") or "/" in filename or "\\" in filename:
            raise ApiError(400, "invalid_filename", "Export downloads are limited to generated .docx files.")
        path = PROJECT_ROOT / "exports" / "web" / corpus_id / safe
        if not path.is_file():
            raise ApiError(404, "export_not_found", "No local export file with that name exists yet.")
        return path

    def superdocs_status(self) -> dict[str, Any]:
        configured = False
        base_url = None
        try:
            settings = load_settings(require_api_key=True)
            configured = True
            base_url = settings.base_url
        except ConfigurationError:
            configured = False
        live = _safe_live_status()
        return {
            "configured": configured,
            "base_url": base_url if configured else None,
            "offline_demo": not configured,
            "live_export_available": False,
            "live_export_reason": (
                "Live SuperDocs export is available from the CLI after a live session. "
                "This web app writes local DOCX artifacts without calling SuperDocs."
                if configured
                else "SUPERDOCS_API_KEY is not configured. Browse the architecture offline; live upload/search/export stay in the CLI."
            ),
            "live": live,
        }

    def _plan_change(self, corpus_id: str, body: Mapping[str, Any]) -> tuple:
        _corpus, _architecture, framework = self._require_analyzed(corpus_id)
        level_id = str(body.get("level_id") or "").strip()
        if not level_id:
            occupied = framework_payload(framework)["default_occupied_level_id"]
            level_id = str(occupied or "")
        if not level_id:
            raise ApiError(400, "level_required", "No occupied level is available to edit.")
        try:
            old = framework.level(level_id)
        except KeyError as exc:
            raise ApiError(404, "level_not_found", f"Unknown level {level_id}") from exc
        try:
            new = _proposed_level(old, body)
        except ValueError as exc:
            raise ApiError(400, "malformed_level_edit", str(exc)) from exc
        if new == old:
            raise ApiError(400, "malformed_level_edit", "The proposed level definition is unchanged.")
        try:
            analysis = analyze_level_change(
                old,
                new,
                framework.dependency_graph,
                framework.profiles,
                levels=framework.levels,
            )
            plans = plan_level_updates(
                analysis,
                old_level=old,
                new_level=new,
                dependency_graph=framework.dependency_graph,
                profiles=framework.profiles,
            )
        except DependencyGraphError as exc:
            raise ApiError(409, "impact_failed", str(exc)) from exc
        return old, new, analysis, plans

    def _load_corpus(self, corpus_id: str):
        try:
            return load_corpus(corpus_id)
        except FileNotFoundError as exc:
            raise ApiError(404, "corpus_not_found", f"Unknown corpus {corpus_id}") from exc
        except ValueError as exc:
            raise ApiError(404, "corpus_not_found", str(exc)) from exc

    def _require_analyzed(self, corpus_id: str):
        self._load_corpus(corpus_id)
        workspace = self.store.workspace(corpus_id)
        if not workspace.analyzed or workspace.architecture is None or workspace.framework is None:
            raise ApiError(
                409,
                "not_analyzed",
                f"Corpus {corpus_id} has not been analyzed. POST /api/corpora/{corpus_id}/analyze first.",
            )
        return self._load_corpus(corpus_id), workspace.architecture, workspace.framework

    def _require_review(self, corpus_id: str) -> ReviewSession:
        workspace = self.store.workspace(corpus_id)
        if workspace.review is None:
            raise ApiError(404, "no_pending_review", "No pending review for this corpus.")
        return workspace.review


def _proposed_level(old: LevelDefinition, body: Mapping[str, Any]) -> LevelDefinition:
    changes = body.get("changes")
    dimension = body.get("dimension")
    value = body.get("value")
    updates: dict[str, Any] = {}
    if isinstance(changes, Mapping):
        updates.update(changes)
    if dimension:
        updates[str(dimension)] = value
    if not updates:
        raise ValueError("Provide dimension and value, or a changes object.")
    allowed = set(EDITABLE_DIMENSIONS)
    unknown = [key for key in updates if key not in allowed]
    if unknown:
        raise ValueError(f"Unsupported dimension(s): {', '.join(unknown)}")
    if any(updates[key] is None or str(updates[key]).strip() == "" for key in updates):
        raise ValueError("Dimension values must be non-empty strings.")
    kwargs = {key: str(updates[key]) for key in updates}
    return replace(old, version=old.version + 1, **kwargs)


def _plan_key(plan) -> str:
    return f"{plan.profile_id}:{plan.section_id}"


def _outcome_from_decisions(session: ReviewSession) -> str:
    if len(session.decisions) != len(session.plans):
        return "pending"
    flags = [session.decisions.get(_plan_key(plan)) for plan in session.plans]
    if all(flags):
        return "approved"
    if not any(flags):
        return "rejected"
    return "mixed"


def _safe_live_status() -> dict[str, Any]:
    store = RuntimeStore()
    state = store.load()
    if state is None:
        return {"present": False}
    integrity = dict(state.profile_integrity or {})
    domain = dict(state.domain_apply or {})
    search = dict((state.jobs or {}).get("search") or {})
    payload = {
        "present": True,
        "session_label": "job-arch-live" if state.session_id == "job-arch-live" else "recorded",
        "workflow": state.workflow,
        "completed_steps": list(state.completed_steps),
        "profile_integrity_status": integrity.get("status"),
        "domain_applied": bool(domain.get("applied")),
        "search_verified": bool(search.get("verified")),
        "search_status": search.get("remote_job_status") or search.get("status"),
        "notes": (
            "Live document and job identifiers are omitted. "
            "See docs/live-verification.md for the human-run record."
        ),
    }
    return _strip_secrets(payload)


def _strip_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ("api_key", "authorization", "secret", "token", "password", "bearer")):
                continue
            cleaned[key] = _strip_secrets(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_secrets(item) for item in value]
    if isinstance(value, str) and any(token in value.lower() for token in SECRET_SUBSTRINGS):
        return "[redacted]"
    return value
