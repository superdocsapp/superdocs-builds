import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from docrelay.domain.enums import ConnectionStatus, Provider
from docrelay.persistence.models import (
    CloudConnection,
    CloudDocument,
    GoogleBaselineCapture,
)

pytestmark = pytest.mark.postgresql


async def test_real_postgresql_jsonb_constraints_indexes_and_immutability() -> None:
    database_url = os.environ.get("DOCRELAY_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("set DOCRELAY_TEST_POSTGRES_URL to run PostgreSQL integration tests")

    engine = create_async_engine(database_url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            now = datetime.now(UTC)
            cloud_connection = CloudConnection(
                owner_subject="postgres-test-owner",
                provider=Provider.GOOGLE,
                provider_account_subject="postgres-test-principal",
                status=ConnectionStatus.CONNECTED,
                granted_scopes={"scopes": ["openid", "drive.file"]},
            )
            session.add(cloud_connection)
            await session.flush()
            document = CloudDocument(
                connection_id=cloud_connection.id,
                provider_file_id="postgres-test-file",
                mime_type="application/vnd.google-apps.document",
                parent_ids=["parent-1"],
                provider_metadata={"nested": {"jsonb": True}},
            )
            session.add(document)
            await session.flush()
            baseline = GoogleBaselineCapture(
                cloud_document_id=document.id,
                provider_revision_id="opaque-revision-A",
                native_raw_sha256="0" * 64,
                native_canonical_sha256="1" * 64,
                exported_docx_sha256="2" * 64,
                exported_docx_size_bytes=42,
                canonicalizer_version="docrelay.google-native-canonical.v1",
                canonical_payload={"tabs": [{"id": "t.0"}]},
                capability_evidence={"can_download": True},
                parent_ids=["parent-1"],
                attempt_count=1,
                capture_started_at=now,
                captured_at=now,
                provider_evidence={"revision_before": "opaque-revision-A"},
            )
            session.add(baseline)
            await session.flush()

            jsonb_evidence = (
                await session.execute(
                    text(
                        "SELECT pg_typeof(canonical_payload)::text, "
                        "canonical_payload @> CAST(:expected AS jsonb) "
                        "FROM google_baseline_captures WHERE id = :capture_id"
                    ),
                    {"expected": '{"tabs":[{"id":"t.0"}]}', "capture_id": baseline.id},
                )
            ).one()
            assert jsonb_evidence == ("jsonb", True)

            index_names = set(
                await session.scalars(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname='public' AND tablename='google_baseline_captures'"
                    )
                )
            )
            assert {
                "ix_google_baseline_captures_cloud_document_id",
                "ix_google_baseline_document_revision",
            }.issubset(index_names)

            constraint_names = set(
                await session.scalars(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid IN "
                        "('cloud_connections'::regclass, "
                        "'google_baseline_captures'::regclass, "
                        "'sync_runs'::regclass, 'external_effects'::regclass, "
                        "'proposed_changes'::regclass, 'superdocs_exports'::regclass)"
                    )
                )
            )
            assert {
                "ck_cloud_connections_connection_status",
                "ck_google_baseline_captures_google_baseline_attempt_positive",
                "uq_cloud_connection_owner_provider_account",
                "ck_sync_runs_sync_run_state",
                "ck_external_effects_effect_type",
                "ck_proposed_changes_ordinal_positive",
                "uq_proposed_change_round_ordinal",
                "uq_superdocs_export_job",
            }.issubset(constraint_names)

            trigger_names = set(
                await session.scalars(
                    text(
                        "SELECT tgname FROM pg_trigger "
                        "WHERE NOT tgisinternal AND tgrelid IN "
                        "('mapping_proofs'::regclass, 'proposed_changes'::regclass, "
                        "'review_decisions'::regclass, 'write_plans'::regclass, "
                        "'write_plan_lineage'::regclass, "
                        "'google_baseline_captures'::regclass, "
                        "'superdocs_exports'::regclass)"
                    )
                )
            )
            assert {
                "trg_mapping_proofs_immutable",
                "trg_proposed_changes_immutable",
                "trg_review_decisions_immutable",
                "trg_write_plans_immutable",
                "trg_write_plan_lineage_immutable",
                "trg_google_baseline_captures_immutable",
                "trg_superdocs_exports_immutable",
            } == trigger_names

            with pytest.raises(DBAPIError, match="immutable DocRelay evidence"):
                await session.execute(
                    text(
                        "UPDATE google_baseline_captures "
                        "SET provider_revision_id='forbidden' WHERE id=:capture_id"
                    ),
                    {"capture_id": baseline.id},
                )
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()
    await engine.dispose()
