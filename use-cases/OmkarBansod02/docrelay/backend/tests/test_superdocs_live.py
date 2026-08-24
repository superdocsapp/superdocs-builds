import asyncio
import os
import time
import zipfile
from io import BytesIO
from pathlib import Path
from uuid import UUID
from xml.etree import ElementTree

import pytest
from sqlalchemy import func, select

from docrelay.core.config import Settings
from docrelay.domain.enums import SyncRunState
from docrelay.integrations.google.runtime import GoogleRuntime
from docrelay.integrations.google.services import GoogleConnectionService
from docrelay.integrations.superdocs.runtime import SuperDocsRuntime
from docrelay.persistence.database import Database
from docrelay.persistence.models import GoogleBaselineCapture, SuperDocsJob
from docrelay.services.artifacts import FilesystemArtifactStore
from docrelay.services.superdocs_workflow import DecisionInput, SuperDocsBaseline, SuperDocsWorkflow

pytestmark = pytest.mark.live_superdocs


@pytest.mark.skipif(
    os.environ.get("DOCRELAY_RUN_LIVE_SUPERDOCS") != "1",
    reason="set DOCRELAY_RUN_LIVE_SUPERDOCS=1 for the bounded production Phase 3 proof",
)
async def test_one_bounded_production_superdocs_restart_review_export(tmp_path: Path) -> None:
    source_raw = os.environ.get("DOCRELAY_LIVE_GOOGLE_SOURCE_ID")
    capture_raw = os.environ.get("DOCRELAY_LIVE_GOOGLE_BASELINE_CAPTURE_ID")
    if not source_raw or not capture_raw:
        pytest.skip("set the live registered source and immutable baseline capture IDs")
    source_id = UUID(source_raw)
    capture_id = UUID(capture_raw)
    settings = Settings()
    google_runtime = GoogleRuntime.from_settings(settings)
    superdocs_runtime = SuperDocsRuntime.from_settings(settings)
    if google_runtime is None or superdocs_runtime is None:
        pytest.skip("configured Google OAuth and SuperDocs credentials are required")
    database = Database(settings.database_url)
    artifacts = FilesystemArtifactStore(tmp_path)
    try:
        async with database.sessions() as session:
            selected = await session.get(GoogleBaselineCapture, capture_id)
            if selected is None or selected.cloud_document_id != source_id:
                pytest.skip("the selected Phase 2 baseline was not found for this source")
            google = GoogleConnectionService(
                session=session,
                runtime=google_runtime,
                owner_subject=settings.docrelay_owner_subject,
                state_ttl_seconds=settings.google_oauth_state_ttl_seconds,
                refresh_skew_seconds=settings.google_access_token_refresh_skew_seconds,
                baseline_max_attempts=settings.google_baseline_max_attempts,
            )
            recaptured = await google.recapture_registered_source(source_id)
        result = recaptured.result
        assert result.revision_id == selected.provider_revision_id
        assert result.native_canonical_sha256 == selected.native_canonical_sha256
        assert "45 days" in _docx_text(result.docx_bytes)
        superdocs_baseline = SuperDocsBaseline(
            cloud_document_id=source_id,
            provider_revision_id=result.revision_id,
            source_format=recaptured.document.mime_type,
            captured_at=result.captured_at,
            native_raw_sha256=result.native_raw_sha256,
            native_canonical_sha256=result.native_canonical_sha256,
            exported_docx_sha256=result.exported_docx_sha256,
            canonical_schema_version=result.canonicalizer_version,
            capability_evidence=recaptured.capture.capability_evidence,
            provider_evidence=recaptured.capture.provider_evidence,
            docx_bytes=result.docx_bytes,
            filename="synthetic-phase3-baseline.docx",
        )
        first_process = SuperDocsWorkflow(
            sessions=database.sessions,
            superdocs=superdocs_runtime.client,
            artifacts=artifacts,
            owner_subject=settings.docrelay_owner_subject,
        )
        started = await first_process.start_run(
            baseline=superdocs_baseline,
            instruction='Change "45 days" to "30 days" and nothing else.',
            model_tier="core",
        )
        assert started.attention_code is None
        deadline = time.monotonic() + 600
        view = started
        while view.state is SyncRunState.EDITING and time.monotonic() < deadline:
            await asyncio.sleep(2)
            view = await first_process.resume(view.run_id)
        assert view.state is SyncRunState.AWAITING_REVIEW
        assert view.awaiting_kind == "CHANGE_BATCH"
        assert len(view.pending_proposals) == 1
        proposal = view.pending_proposals[0]
        assert proposal.old_html is not None and "45 days" in proposal.old_html
        assert proposal.new_html is not None and "30 days" in proposal.new_html

        # Reconstruct the production service with only durable DB/artifact/provider state.
        restarted_process = SuperDocsWorkflow(
            sessions=database.sessions,
            superdocs=superdocs_runtime.client,
            artifacts=FilesystemArtifactStore(tmp_path),
            owner_subject=settings.docrelay_owner_subject,
        )
        recovered = await restarted_process.get_run(view.run_id)
        assert recovered.provider_job_id == started.provider_job_id
        await restarted_process.submit_decisions(
            view.run_id,
            decisions=(DecisionInput(proposal_id=proposal.proposal_id, approve=True),),
            reviewer_subject=settings.docrelay_owner_subject,
        )
        while time.monotonic() < deadline:
            await asyncio.sleep(2)
            recovered = await restarted_process.resume(view.run_id)
            if recovered.state is SyncRunState.REVIEWED_EXPORT_READY:
                break
        assert recovered.state is SyncRunState.REVIEWED_EXPORT_READY
        assert recovered.export is not None
        exported = await artifacts.read(recovered.export.artifact_reference)
        text = _docx_text(exported)
        assert "30 days" in text
        assert "45 days" not in text
        async with database.sessions() as session:
            job_count = await session.scalar(
                select(func.count())
                .select_from(SuperDocsJob)
                .where(SuperDocsJob.sync_run_id == view.run_id)
            )
            stored_job = await session.scalar(
                select(SuperDocsJob).where(SuperDocsJob.sync_run_id == view.run_id)
            )
        assert job_count == 1
        assert stored_job is not None
        assert stored_job.provider_job_id == started.provider_job_id
    finally:
        await superdocs_runtime.close()
        await google_runtime.close()
        await database.dispose()


def _docx_text(content: bytes) -> str:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    return "".join(node.text or "" for node in root.iter(f"{namespace}t"))
