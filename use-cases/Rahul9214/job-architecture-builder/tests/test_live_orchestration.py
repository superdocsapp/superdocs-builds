"""Phase 7A: live SuperDocs orchestration against FakeProtocolClient. No live HTTP."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from job_architecture.live.docxgen import write_demo_artifacts
from job_architecture.live.instructions import (
    compact_framework_instruction,
    compact_profile_instruction,
    surgical_edit_instruction,
    surgical_update_plan,
)
from job_architecture.level_text import changed_dimensions, parse_level_expectations
from job_architecture.live.orchestrator import LiveOrchestrator
from job_architecture.live.preservation import extract_docx_text, verify_exported_profile
from job_architecture.live.review import format_pending
from job_architecture.live.roster import reconcile_documents_from_roster
from job_architecture.live.state import LiveState, LiveStateError, RuntimeStore
from job_architecture.live.subset import load_demo_subset
from job_architecture.superdocs.errors import SuperDocsError
from job_architecture.superdocs.models import DocumentRef, ReviewDecision, SessionRoster, TemplateRef

from tests.live_fake import OFFLINE_API_KEY, FakeProtocolClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVE_SRC = PROJECT_ROOT / "src" / "job_architecture" / "live"


def _orchestrator(tmp_path: Path, fake: FakeProtocolClient | None = None) -> tuple[LiveOrchestrator, FakeProtocolClient]:
    client = fake or FakeProtocolClient()
    store = RuntimeStore(tmp_path / "live-state.json")
    orch = LiveOrchestrator(client, store, artifacts_dir=tmp_path / "artifacts")
    return orch, client


def test_demo_subset_has_four_required_kinds() -> None:
    subset = load_demo_subset()
    kinds = {item.kind for item in subset.roles}
    assert kinds == {
        "engineering_ic",
        "higher_scope_engineering_ic",
        "people_manager",
        "provisional",
    }
    assert subset.roles[0].kind == "engineering_ic"
    assert "misfit" not in kinds


def test_docx_artifacts_are_valid_word_packages(tmp_path: Path) -> None:
    subset = load_demo_subset()
    written = write_demo_artifacts(tmp_path, subset=subset)
    for role in subset.roles:
        path = written[role.role_id]
        with zipfile.ZipFile(path) as archive:
            assert "word/document.xml" in archive.namelist()
        text = extract_docx_text(path)
        assert text
    for name in ("framework-template", "role-profile-template"):
        path = written[name]
        with zipfile.ZipFile(path) as archive:
            assert "word/document.xml" in archive.namelist()
        text = extract_docx_text(path)
        assert "Insert" in text or "title" in text.lower() or "Level expectations" in text


def test_multi_document_upload_keeps_distinct_ids(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    roster = orch.upload_sources()
    assert len(roster.documents) == 4
    ids = [item.document_id for item in roster.documents]
    assert len(set(ids)) == 4
    assert len(fake.uploads) == 4
    state = orch.state()
    assert "upload" in state.completed_steps
    assert {item["role_id"] for item in state.documents} >= set(orch.subset.role_ids)
    assert all(item.get("durable_document_id") for item in state.documents)


def test_roster_reconcile_fills_durable_ids_missing_from_upload(tmp_path: Path) -> None:
    fake = FakeProtocolClient()
    fake.omit_durable_on_upload = True
    orch, _ = _orchestrator(tmp_path, fake)
    roster = orch.upload_sources()
    assert len(fake.uploads) == 4
    assert all(item.durable_document_id for item in roster.documents)
    payload = json.loads(orch.store.path.read_text(encoding="utf-8"))
    persisted = [item for item in payload["documents"] if item.get("role_id") in orch.subset.role_ids]
    assert len(persisted) == 4
    assert all(item["document_id"] for item in persisted)
    assert all(item["durable_document_id"] for item in persisted)
    assert [item["durable_document_id"] for item in persisted] == [
        item.durable_document_id for item in roster.documents
    ]
    orch.upload_sources()
    assert len(fake.uploads) == 4


def test_repaired_durable_ids_survive_restart_without_duplicate_upload(tmp_path: Path) -> None:
    subset = load_demo_subset()
    fake = FakeProtocolClient()
    store = RuntimeStore(tmp_path / "live-state.json")
    records = []
    for index, role in enumerate(subset.roles, start=1):
        document_id = f"doc_offline_{index}"
        durable = f"durable_offline_{index}"
        fake.documents.append(
            DocumentRef(
                document_id=document_id,
                durable_document_id=durable,
                title=f"{role.role_id}.docx",
                session_id=subset.session_id,
            )
        )
        records.append(
            {
                "role_id": role.role_id,
                "kind": role.kind,
                "filename": f"{role.role_id}.docx",
                "document_id": document_id,
                "durable_document_id": None,
                "operation_key": f"live-upload:{role.role_id}",
            }
        )
    store.save(
        LiveState(
            session_id=subset.session_id,
            workflow="upload",
            completed_steps=["prepare", "upload"],
            documents=records,
            operation_keys=[item["operation_key"] for item in records],
        )
    )
    orch = LiveOrchestrator(fake, store, artifacts_dir=tmp_path / "artifacts")
    orch.upload_sources()
    assert fake.uploads == []
    repaired = orch.state()
    by_role = {item["role_id"]: item for item in repaired.documents}
    for index, role in enumerate(subset.roles, start=1):
        assert by_role[role.role_id]["document_id"] == f"doc_offline_{index}"
        assert by_role[role.role_id]["durable_document_id"] == f"durable_offline_{index}"

    restarted = LiveOrchestrator(fake, store, artifacts_dir=tmp_path / "artifacts")
    restarted.upload_sources()
    assert fake.uploads == []
    assert all(item["durable_document_id"] for item in restarted.state().documents if item["role_id"] in subset.role_ids)


def test_known_durable_id_is_not_replaced_with_null() -> None:
    state = LiveState(
        session_id="job-arch-live",
        documents=[
            {
                "role_id": "role-offline",
                "document_id": "doc_offline_keep",
                "durable_document_id": "durable_offline_keep",
            }
        ],
    )
    roster = SessionRoster(
        session_id="job-arch-live",
        documents=(DocumentRef(document_id="doc_offline_keep", durable_document_id=None),),
        focused_document_id="doc_offline_keep",
    )
    reconcile_documents_from_roster(state, roster)
    assert state.documents[0]["durable_document_id"] == "durable_offline_keep"


def test_conflicting_roster_durable_ids_fail() -> None:
    state = LiveState(
        session_id="job-arch-live",
        documents=[{"role_id": "role-offline", "document_id": "doc_offline_conflict", "durable_document_id": None}],
    )
    roster = SessionRoster(
        session_id="job-arch-live",
        documents=(
            DocumentRef(document_id="doc_offline_conflict", durable_document_id="durable_offline_a"),
            DocumentRef(document_id="doc_offline_conflict", durable_document_id="durable_offline_b"),
        ),
        focused_document_id="doc_offline_conflict",
    )
    with pytest.raises(SuperDocsError, match="conflicting durable_document_id"):
        reconcile_documents_from_roster(state, roster)


def test_state_roster_durable_id_conflict_fails() -> None:
    state = LiveState(
        session_id="job-arch-live",
        documents=[
            {
                "role_id": "role-offline",
                "document_id": "doc_offline_conflict",
                "durable_document_id": "durable_offline_a",
            }
        ],
    )
    roster = SessionRoster(
        session_id="job-arch-live",
        documents=(DocumentRef(document_id="doc_offline_conflict", durable_document_id="durable_offline_b"),),
        focused_document_id="doc_offline_conflict",
    )
    with pytest.raises(SuperDocsError, match="disagree"):
        reconcile_documents_from_roster(state, roster)


def test_template_setup_uploads_then_reuses(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    first = orch.upload_templates()
    assert set(first) == {"framework", "role-profile"}
    assert fake.template_uploads == ["framework-template.docx", "role-profile-template.docx"]
    orch.upload_templates()
    assert fake.template_uploads == ["framework-template.docx", "role-profile-template.docx"]

    other_store = RuntimeStore(tmp_path / "other-state.json")
    reuse_fake = FakeProtocolClient()
    reuse_fake.template_refs = [
        TemplateRef(template_id="tpl_existing_fw", filename="framework-template.docx", name="fw"),
        TemplateRef(template_id="tpl_existing_rp", filename="role-profile-template.docx", name="rp"),
    ]
    reuse = LiveOrchestrator(reuse_fake, other_store, artifacts_dir=tmp_path / "artifacts-reuse")
    reused = reuse.upload_templates()
    assert reused["framework"] == "tpl_existing_fw"
    assert reuse_fake.template_uploads == []


def test_reviewed_edit_stops_for_approval(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    snapshot = orch.start_framework()
    assert snapshot.status == "awaiting_approval"
    assert snapshot.pending_changes
    assert snapshot.pending_changes[0].change_id == "ch_1"
    assert fake.edits and "Do not invent families" in fake.edits[0]["message"]
    rendered = format_pending(snapshot)
    assert "change id:" in rendered
    assert "before:" in rendered
    assert "after:" in rendered
    assert "reason:" in rendered


def test_approve_and_reject_require_explicit_decisions(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    orch.start_framework()
    with pytest.raises(SuperDocsError, match="Explicit"):
        orch.submit_decisions("framework", [])
    approved = orch.submit_decisions(
        "framework",
        [ReviewDecision(change_id="ch_1", approved=True)],
    )
    assert approved.status == "completed"
    assert fake.reviews[-1][1][0].approved is True

    reject_orch, reject_fake = _orchestrator(tmp_path / "reject")
    reject_orch.start_framework()
    rejected = reject_orch.submit_decisions(
        "framework",
        [ReviewDecision(change_id="ch_1", approved=False)],
    )
    assert rejected.status == "completed"
    assert reject_fake.reviews[-1][1][0].approved is False


def test_resume_from_saved_non_secret_state(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    first = orch.start_framework()
    resumed = LiveOrchestrator(fake, orch.store, artifacts_dir=tmp_path / "artifacts")
    second = resumed.start_framework()
    assert first.job_id == second.job_id
    assert len(fake.edits) == 1


def test_duplicate_completed_operation_is_not_resent(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    orch.upload_sources()
    orch.upload_templates()
    orch.upload_sources()
    orch.upload_templates()
    assert len(fake.uploads) == 4
    assert len(fake.template_uploads) == 2


def test_surgical_instruction_targets_only_level_expectations(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    snapshot = orch.start_surgical_update()
    assert snapshot.status == "awaiting_approval"
    message = fake.edits[0]["message"]
    assert "level_expectations" in message
    assert "ONLY" in message
    assert "Do not rewrite the profile" in message
    plan_profile, old, new, plan = surgical_update_plan(orch.framework, orch.subset)
    assert plan.section_id == "level_expectations"
    assert plan_profile.level_id == old.id
    assert new.version == old.version + 1
    instruction = surgical_edit_instruction(plan)
    assert instruction.count("level_expectations") >= 1
    assert "complexity" in plan.preserved_rendered_fields
    before_complexity = parse_level_expectations(plan.before).raw_for("complexity")
    after_complexity = parse_level_expectations(plan.after).raw_for("complexity")
    assert after_complexity == before_complexity
    assert changed_dimensions(old, new) == frozenset({"scope", "version"})
    assert "Preserve these" in instruction
    state = orch.state()
    assert state.preservation["section_id"] == "level_expectations"
    assert state.preservation["before_hashes"]
    assert "purpose" in state.preservation["before_hashes"]


def test_rejected_completed_review_does_not_mark_domain_applied(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    first = orch.start_surgical_update()
    assert first.status == "awaiting_approval"
    snapshot = orch.submit_decisions(
        "surgical",
        [ReviewDecision(change_id="ch_1", approved=False)],
    )
    assert snapshot.status == "completed"
    job = orch.state().jobs["surgical"]
    assert job["status"] == "completed"
    assert job["remote_job_status"] == "completed"
    assert job["human_decision"] == "rejected"
    assert job["review_outcome"] == "rejected"
    assert job["mutation_applied"] is False
    assert job["domain_applied"] is False
    assert job["review_decisions"] == [{"change_id": "ch_1", "approved": False}]
    assert orch.domain_update_applied("surgical") is False
    assert orch.surgical_intent().estimated_count == 1
    second = orch.start_surgical_update()
    assert second.job_id != first.job_id
    assert len(fake.edits) == 2
    retry = orch.state().jobs["surgical"]
    assert retry["prior_job_id"] == first.job_id
    assert retry["domain_applied"] is False
    assert retry["review_outcome"] == "pending"
    assert retry["human_decision"] == "pending"
    assert retry["operation_key"] == "live-edit:surgical:2"
    history = retry["history"]
    assert history[0]["job_id"] == first.job_id
    assert history[0]["review_outcome"] == "rejected"
    assert history[0]["mutation_applied"] is False
    assert history[0]["review_decisions"] == [{"change_id": "ch_1", "approved": False}]


def test_explicit_continue_is_not_automatic(tmp_path: Path) -> None:
    fake = FakeProtocolClient()
    fake.after_review_status = "awaiting_approval"
    fake.after_review_awaiting = "continue_prompt"
    orch, _ = _orchestrator(tmp_path, fake)
    orch.start_framework()
    snapshot = orch.submit_decisions("framework", [ReviewDecision(change_id="ch_1", approved=True)])
    assert snapshot.awaiting_kind == "continue_prompt"
    assert fake.continues == []
    continued = orch.continue_after_review("framework")
    assert continued.status == "completed"
    assert fake.continues == ["job_1"]


def test_search_demo_uses_cross_session_query(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    accepted = orch.start_search()
    assert fake.searches[0]["cross_session"] is True
    assert "IC4" in accepted.query
    orch.start_search()
    assert len(fake.searches) == 1


def test_export_writes_destination(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    orch.start_framework()
    destination = tmp_path / "out" / "framework.docx"
    path = orch.export("framework", destination)
    assert path == destination
    assert destination.read_bytes() == fake.export_bytes
    assert "export:framework" in orch.state().completed_steps
    request = fake.export_requests[-1]
    assert "html" in request
    assert "document_id" not in request
    assert "durable_document_id" not in request
    assert "IC1" in request["html"]
    assert "People Manager" in request["html"]
    assert "Software Engineer, Backend" not in request["html"]


def test_failed_live_step_preserves_resumable_state(tmp_path: Path) -> None:
    fake = FakeProtocolClient()
    fake.fail_after_uploads = 2
    orch, _ = _orchestrator(tmp_path, fake)
    with pytest.raises(SuperDocsError, match="forced upload failure"):
        orch.upload_sources()
    state = orch.state()
    assert len([item for item in state.documents if item.get("kind") not in {"framework", "profile"}]) == 2
    assert state.last_error
    assert "upload" not in state.completed_steps
    assert orch.store.path.is_file()

    fake.fail_after_uploads = None
    roster = orch.upload_sources()
    assert len(roster.documents) == 4
    assert len(fake.uploads) == 4


def test_failed_wait_keeps_job_id(tmp_path: Path) -> None:
    fake = FakeProtocolClient()
    fake.fail_wait = True
    orch, _ = _orchestrator(tmp_path, fake)
    with pytest.raises(SuperDocsError, match="forced wait failure"):
        orch.start_framework()
    state = orch.state()
    assert state.jobs["framework"]["job_id"]
    assert state.last_error
    fake.fail_wait = False
    snapshot = orch.start_framework()
    assert snapshot.job_id == state.jobs["framework"]["job_id"]
    assert len(fake.edits) == 1


def test_secrets_never_enter_saved_state(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    orch.upload_sources()
    orch.start_framework()
    payload = json.loads(orch.store.path.read_text(encoding="utf-8"))
    dumped = json.dumps(payload)
    assert "api_key" not in dumped
    assert OFFLINE_API_KEY not in dumped
    assert "sk_" not in dumped.lower()
    assert fake.settings.api_key not in dumped
    with pytest.raises(LiveStateError):
        LiveState(session_id="job-arch-live", jobs={"api_key": "secret"}).to_dict()
    with pytest.raises(LiveStateError):
        LiveState(session_id="x", last_error="bearer abc").to_dict()


def test_framework_and_profile_instructions_do_not_reinvent_architecture() -> None:
    subset = load_demo_subset()
    from job_architecture.live.subset import build_demo_framework
    from job_architecture.live.instructions import subset_profile_for_demo

    _, framework = build_demo_framework(subset)
    framework_text = compact_framework_instruction(framework, subset)
    assert "Do not invent families" in framework_text
    assert "Do not re-classify roles" in framework_text
    for role_id in subset.role_ids:
        assert role_id in framework_text
    profile = subset_profile_for_demo(framework, subset)
    profile_text = compact_profile_instruction(profile)
    assert "Do not change family, track, or level" in profile_text
    assert profile.display_title in profile_text


def test_export_preservation_checks_text_not_bytes(tmp_path: Path) -> None:
    orch, _ = _orchestrator(tmp_path)
    orch.prepare()
    profile, _old, _new, _plan = surgical_update_plan(orch.framework, orch.subset)
    filled = tmp_path / "artifacts" / f"{profile.id}.docx"
    text = extract_docx_text(filled)
    mutated = tmp_path / "exported.docx"
    from job_architecture.live.docxgen import markdown_to_docx

    markdown_to_docx(
        text + "\n\nExplicit domain sequencing veto for live verification.\n",
        mutated,
        title="exported",
    )
    result = verify_exported_profile(
        mutated,
        expected_new_fragment="Explicit domain sequencing veto for live verification",
        preserved_markers={"purpose": profile.summary[:80]},
    )
    assert result.ok
    assert filled.read_bytes() != mutated.read_bytes()


def test_live_package_does_not_import_http_client() -> None:
    forbidden = ("import httpx", "from httpx", "from job_architecture.superdocs.client")
    for path in LIVE_SRC.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in text, f"{path.name} contains {needle}"
    docxgen = (LIVE_SRC / "docxgen.py").read_text(encoding="utf-8")
    assert "from docx import Document" in docxgen
    for path in LIVE_SRC.glob("*.py"):
        if path.name == "docxgen.py":
            continue
        body = path.read_text(encoding="utf-8")
        assert "from docx" not in body
        assert "import docx" not in body
