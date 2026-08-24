"""Explicit opt-in checks against a browser-authorized, persisted Google connection.

This module never accepts a copied access token. Complete the backend OAuth web flow
first, then provide only database identity and synthetic/public-safe Drive file IDs.
"""

import os
from uuid import UUID

import pytest
from sqlalchemy import select

from docrelay.core.config import Settings
from docrelay.domain.enums import ConnectionStatus
from docrelay.integrations.google.errors import GoogleErrorCode, GoogleIntegrationError
from docrelay.integrations.google.runtime import GoogleRuntime
from docrelay.integrations.google.services import GoogleConnectionService
from docrelay.persistence.database import Database
from docrelay.persistence.models import CloudConnection

pytestmark = pytest.mark.live_google


async def test_real_oauth_connection_native_baseline_and_unsupported_type() -> None:
    if os.environ.get("DOCRELAY_RUN_LIVE_GOOGLE") != "1":
        pytest.skip("set DOCRELAY_RUN_LIVE_GOOGLE=1 to run live Google checks")
    connection_value = os.environ.get("DOCRELAY_LIVE_GOOGLE_CONNECTION_ID")
    native_file_id = os.environ.get("DOCRELAY_LIVE_GOOGLE_FILE_ID")
    unsupported_file_id = os.environ.get("DOCRELAY_LIVE_GOOGLE_UNSUPPORTED_FILE_ID")
    if not all((connection_value, native_file_id, unsupported_file_id)):
        pytest.skip(
            "live test requires connection, native Google Doc, and unsupported Drive file IDs"
        )

    settings = Settings()
    runtime = GoogleRuntime.from_settings(settings)
    assert runtime is not None, "configure the documented Google OAuth environment"
    database = Database(settings.database_url)
    try:
        async with database.sessions() as session:
            connection_id = UUID(connection_value)
            connection = await session.scalar(
                select(CloudConnection).where(
                    CloudConnection.id == connection_id,
                    CloudConnection.owner_subject == settings.docrelay_owner_subject,
                )
            )
            assert connection is not None
            assert connection.status is ConnectionStatus.CONNECTED
            service = GoogleConnectionService(
                session=session,
                runtime=runtime,
                owner_subject=settings.docrelay_owner_subject,
                state_ttl_seconds=settings.google_oauth_state_ttl_seconds,
                refresh_skew_seconds=settings.google_access_token_refresh_skew_seconds,
                baseline_max_attempts=settings.google_baseline_max_attempts,
            )
            if os.environ.get("DOCRELAY_LIVE_FORCE_REFRESH") == "1":
                await service._valid_access_token(connection, force_refresh=True)

            captured = await service.register_and_capture(
                connection_id=connection_id,
                file_id=native_file_id,
            )
            assert captured.document.provider_file_id == native_file_id
            assert captured.result.metadata.parent_ids is not None
            assert captured.result.revision_id
            assert len(captured.result.native_canonical_sha256) == 64
            assert len(captured.result.exported_docx_sha256) == 64
            assert captured.result.exported_docx_size_bytes > 0
            assert captured.result.attempt_count <= settings.google_baseline_max_attempts

            with pytest.raises(GoogleIntegrationError) as unsupported:
                await service.register_and_capture(
                    connection_id=connection_id,
                    file_id=unsupported_file_id,
                )
            assert unsupported.value.code is GoogleErrorCode.UNSUPPORTED_SOURCE_TYPE
    finally:
        await runtime.close()
        await database.dispose()
