"""Export sends documented HTML, not SuperDocs document ids."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_architecture.documents import render_framework_html, render_profile_html
from job_architecture.live.docxgen import write_demo_artifacts
from job_architecture.live.orchestrator import LiveOrchestrator
from job_architecture.live.preservation import (
    verify_exported_framework,
    verify_exported_profile,
    verify_framework_content,
)
from job_architecture.live.selection import build_export_request, require_export_kind
from job_architecture.live.state import LiveState, RuntimeStore
from job_architecture.live.subset import build_demo_framework, load_demo_subset
from job_architecture.superdocs.errors import ExportError, SuperDocsError
from job_architecture.superdocs.models import DOCUMENTED_EXPORT_BODY_KEYS, ExportRequest
from tests.live_fake import FakeProtocolClient
from tests.superdocs_fake import FakeSuperDocsAPI, make_client

SESSION_ID = "job-arch-live"
SOURCE_JD_TITLE = "Software Engineer, Backend"
SOURCE_JD_EXCERPT = "Build and maintain the service APIs"


def _multi_doc_records() -> list[dict[str, str]]:
    return [
        {
            "role_id": "ns-swe-backend",
            "kind": "engineering_ic",
            "filename": "ns-swe-backend.docx",
            "document_id": "doc_jd_backend",
            "durable_document_id": "dur_jd_backend",
        },
        {
            "role_id": "ns-swe-ii-payments",
            "kind": "higher_scope_engineering_ic",
            "filename": "ns-swe-ii-payments.docx",
            "document_id": "doc_jd_payments",
            "durable_document_id": "dur_jd_payments",
        },
        {
            "role_id": "framework",
            "kind": "framework",
            "filename": "framework-starter.docx",
            "document_id": "doc_framework_saved",
            "durable_document_id": "dur_framework_saved",
        },
        {
            "role_id": "profile",
            "kind": "profile",
            "filename": "role-profile.docx",
            "document_id": "doc_profile_saved",
            "durable_document_id": "dur_profile_saved",
        },
    ]


def _seeded_orchestrator(
    tmp_path: Path,
    documents: list[dict[str, str]] | None = None,
) -> tuple[LiveOrchestrator, FakeProtocolClient, RuntimeStore]:
    store = RuntimeStore(tmp_path / "live-state.json")
    store.save(LiveState(session_id=SESSION_ID, documents=list(documents or _multi_doc_records())))
    fake = FakeProtocolClient()
    orch = LiveOrchestrator(fake, store, artifacts_dir=tmp_path / "artifacts")
    return orch, fake, store


def _assert_documented_body(body: dict) -> None:
    assert set(body) <= DOCUMENTED_EXPORT_BODY_KEYS
    assert "document_id" not in body
    assert "durable_document_id" not in body
    assert body["format"] == "docx"
    assert body["session_id"]
    assert str(body["html"]).strip()


def test_framework_export_body_contains_framework_html(tmp_path: Path) -> None:
    orch, fake, _store = _seeded_orchestrator(tmp_path)
    orch.export("framework", tmp_path / "framework.docx")
    body = fake.export_requests[-1]
    _assert_documented_body(body)
    html = body["html"]
    assert "<h2>Purpose</h2>" in html
    assert "<h2>Principles</h2>" in html
    assert "Individual Contributor" in html
    assert "People Manager" in html
    assert SOURCE_JD_TITLE not in html
    assert SOURCE_JD_EXCERPT not in html


def test_framework_html_contains_ic_and_manager_levels(tmp_path: Path) -> None:
    orch, fake, _store = _seeded_orchestrator(tmp_path)
    orch.export("framework", tmp_path / "framework.docx")
    html = fake.export_requests[-1]["html"]
    for label in ("IC1", "IC2", "IC3", "IC4", "IC5", "M1", "M2", "M3"):
        assert label in html


def test_framework_export_body_does_not_contain_source_jd(tmp_path: Path) -> None:
    orch, fake, _store = _seeded_orchestrator(tmp_path)
    orch.export("framework", tmp_path / "framework.docx")
    html = fake.export_requests[-1]["html"]
    assert SOURCE_JD_TITLE not in html
    assert SOURCE_JD_EXCERPT not in html
    assert "Platform Services" not in html or "Role purpose" not in html


def test_profile_export_contains_selected_profile_html(tmp_path: Path) -> None:
    orch, fake, _store = _seeded_orchestrator(tmp_path)
    orch.export("profile", tmp_path / "profile.docx")
    body = fake.export_requests[-1]
    _assert_documented_body(body)
    html = body["html"]
    selected_id = load_demo_subset().surgical_role_id
    selected = next(item for item in orch.framework.profiles if item.role_id == selected_id)
    assert selected.display_title in html
    assert "payments platform" in html.lower()
    assert "<h2>Role purpose</h2>" in html
    assert SOURCE_JD_TITLE not in html
    assert SOURCE_JD_EXCERPT not in html


def test_profile_export_does_not_contain_framework_or_jd_content(tmp_path: Path) -> None:
    orch, fake, _store = _seeded_orchestrator(tmp_path)
    orch.export("profile", tmp_path / "profile.docx")
    html = fake.export_requests[-1]["html"]
    assert "Canonical levels" not in html
    assert "Job architecture" not in html
    for label in ("IC1", "IC2", "M1", "M2", "M3"):
        assert label not in html
    assert SOURCE_JD_TITLE not in html
    assert SOURCE_JD_EXCERPT not in html


def test_empty_html_fails_before_http(tmp_path: Path) -> None:
    fake = FakeSuperDocsAPI()
    client = make_client(fake)
    with pytest.raises(ExportError, match="Export HTML is empty"):
        ExportRequest(session_id=SESSION_ID, html="   ", format="docx", filename="x.docx")
    assert fake.json_bodies == []
    assert ("POST", "/v1/documents/export") not in fake.calls
    orch, protocol, _store = _seeded_orchestrator(tmp_path)
    with pytest.raises(ExportError, match="Export HTML is empty"):
        protocol.export_document(
            tmp_path / "out.docx",
            ExportRequest(session_id=SESSION_ID, html="", format="docx"),
        )
    assert protocol.export_requests == []
    assert "export_document" not in protocol.calls


def test_export_request_matches_documented_api_shape(tmp_path: Path) -> None:
    fake = FakeSuperDocsAPI()
    client = make_client(fake)
    dest = tmp_path / "framework.docx"
    html = "<h1>Job architecture</h1><h2>Purpose</h2><p>Approved.</p>"
    result = client.export_document(
        dest,
        ExportRequest(
            session_id=SESSION_ID,
            html=html,
            format="docx",
            filename="framework.docx",
        ),
    )
    assert result.byte_count == len(fake.export_bytes)
    body = fake.json_bodies[-1]
    _assert_documented_body(body)
    assert body["html"] == html
    assert body["session_id"] == SESSION_ID
    assert body["format"] == "docx"
    assert body["filename"] == "framework.docx"
    assert body["options"]["filename"] == "framework.docx"


def test_list_order_and_session_focus_cannot_change_exported_artifact(tmp_path: Path) -> None:
    reversed_docs = list(reversed(_multi_doc_records()))
    assert reversed_docs[0]["kind"] != "framework"
    orch, fake, _store = _seeded_orchestrator(tmp_path, reversed_docs)
    orch.export("framework", tmp_path / "framework.docx")
    html = fake.export_requests[-1]["html"]
    expected = render_framework_html(orch.framework)
    assert html == expected
    assert SOURCE_JD_TITLE not in html
    other, other_fake, _ = _seeded_orchestrator(tmp_path / "b", _multi_doc_records())
    other.export("framework", tmp_path / "b" / "framework.docx")
    assert other_fake.export_requests[-1]["html"] == html


def test_framework_semantic_verifier_rejects_source_jd(tmp_path: Path) -> None:
    subset = load_demo_subset()
    _architecture, framework = build_demo_framework(subset)
    written = write_demo_artifacts(tmp_path, subset=subset, framework=framework)
    jd = verify_exported_framework(written["ns-swe-backend"])
    assert not jd.ok
    assert jd.looks_like_source_jd
    assert "IC1" in jd.missing_markers


def test_framework_semantic_verifier_passes_rendered_framework_html() -> None:
    _architecture, framework = build_demo_framework()
    html = render_framework_html(framework)
    check = verify_framework_content(html)
    assert check.ok
    assert not check.missing_markers
    assert not check.looks_like_source_jd


def test_profile_semantic_verifier_still_passes(tmp_path: Path) -> None:
    orch, _fake, _store = _seeded_orchestrator(tmp_path)
    orch.prepare()
    subset = load_demo_subset()
    selected = next(item for item in orch.framework.profiles if item.role_id == subset.surgical_role_id)
    filled = tmp_path / "artifacts" / f"{selected.id}.docx"
    result = verify_exported_profile(
        filled,
        expected_new_fragment=selected.summary[:40],
        preserved_markers={"purpose": selected.summary[:80]},
    )
    assert result.ok
    html = render_profile_html(selected)
    assert selected.display_title in html
    assert "<h2>Role purpose</h2>" in html
    assert "payments platform" in html.lower()


def test_no_undocumented_export_selector_is_required(tmp_path: Path) -> None:
    orch, fake, _store = _seeded_orchestrator(tmp_path, [])
    orch.export("framework", tmp_path / "framework.docx")
    body = fake.export_requests[-1]
    _assert_documented_body(body)
    assert "document_id" not in body
    assert "durable_document_id" not in body


def test_unknown_kind_fails_before_http(tmp_path: Path) -> None:
    orch, fake, _store = _seeded_orchestrator(tmp_path)
    with pytest.raises(SuperDocsError, match="Export kind must be"):
        require_export_kind("engineering_ic")
    with pytest.raises(SuperDocsError, match="Export kind must be"):
        orch.export("engineering_ic", tmp_path / "out.docx")
    assert fake.export_requests == []
    assert "export_document" not in fake.calls


def test_build_export_request_is_stable_for_kind() -> None:
    subset = load_demo_subset()
    _architecture, framework = build_demo_framework(subset)
    first = build_export_request(
        "framework",
        session_id=subset.session_id,
        filename="framework.docx",
        framework=framework,
        subset=subset,
    )
    second = build_export_request(
        "framework",
        session_id=subset.session_id,
        filename="framework.docx",
        framework=framework,
        subset=subset,
    )
    assert first.html == second.html
    assert first.json_body()["html"] == render_framework_html(framework)
