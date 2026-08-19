"""Wires the S3 gateway and the SuperDocs client together. This is the
only module that knows the *sequence*: list new objects, presign,
upload-by-stream, request an edit (approved automatically — see
README), export-by-stream to a presigned destination, then mark the
source object processed so the poller never re-ingests it.

A single bad file must never block or lose the others in the same pass
— see tests/test_pipeline.py::test_a_failure_on_one_file_does_not_block_or_lose_the_others.
"""

from __future__ import annotations

import logging

from app.config import Settings
from app.s3_client import S3Gateway
from app.superdocs_client import SuperDocsClient
from app.util import (
    content_type_for_export_format,
    guess_content_type,
    is_supported_upload_extension,
    sanitize_session_id,
)

logger = logging.getLogger("pipeline")


class Pipeline:
    def __init__(self, settings: Settings, s3: S3Gateway, superdocs: SuperDocsClient):
        self._settings = settings
        self._s3 = s3
        self._superdocs = superdocs

    def process_new_objects(self) -> list[str]:
        """Runs one pass over the incoming/ prefix. Returns the filenames
        it processed. Safe to call repeatedly (a watcher loop) or once
        (a cron/Lambda-style invocation) — objects are moved out of
        incoming/ as they're handled, so nothing is ever double-processed
        within a single S3 bucket."""
        objects = self._s3.list_incoming()

        # "Budget your operations" — an optional stopping rule so a
        # misconfigured watch loop or a huge accidental drop can't burn
        # through a free-tier operations allowance unattended.
        limit = self._settings.max_files_per_run
        if limit is not None and len(objects) > limit:
            logger.info(
                "%d file(s) waiting, processing only the first %d this pass "
                "(max_files_per_run=%d)",
                len(objects), limit, limit,
            )
            objects = objects[:limit]

        processed = []
        for obj in objects:
            if not is_supported_upload_extension(obj.filename):
                logger.warning(
                    "Skipping %s — extension not in SuperDocs' supported set "
                    "(.docx .doc .odt .pdf .txt .html .htm .md .rtf); leaving in incoming/",
                    obj.filename,
                )
                continue
            try:
                self._process_one(obj.key, obj.filename, obj.size_bytes)
                processed.append(obj.filename)
            except Exception:
                logger.exception(
                    "Failed to process %s — leaving it in incoming/ for retry", obj.filename
                )
        return processed

    def _process_one(self, key: str, filename: str, size_bytes: int) -> None:
        logger.info("Processing %s (%d bytes)", filename, size_bytes)
        session_id = sanitize_session_id(f"s3-pipeline-{self._settings.s3_bucket}-{key}")

        # 1. Stream S3 -> SuperDocs. The presigned GET is opened as a
        #    streaming HTTP response and its byte iterator is handed
        #    straight to the client — no full-file buffering here.
        source_url = self._s3.presigned_get(key)
        chunk_iter = self._stream_from_presigned_url(source_url)
        upload = self._superdocs.upload_document(
            chunk_iter,
            filename=filename,
            session_id=session_id,
            size_bytes=size_bytes,
            content_type=guess_content_type(filename),
        )
        logger.info("  uploaded -> session_id=%s (%s upload)", upload.session_id, upload.method)

        # 2. Edit + approve. See superdocs_client.edit_document — either
        #    one synchronous call (approve_all) or the full
        #    async -> poll -> approve -> poll sequence (ask_every_time),
        #    per SUPERDOCS_APPROVAL_MODE.
        result = self._superdocs.edit_document(
            session_id, self._settings.superdocs_edit_instruction
        )
        logger.info("  edited: %s", result.changes_summary or result.response_text[:120])
        if result.monthly_remaining is not None:
            logger.info(
                "  operations remaining this month: %d (used %s)",
                result.monthly_remaining, result.monthly_used,
            )

        # 3. Stream SuperDocs -> S3. Using session_id (not inline HTML)
        #    for the export request means there's no size limit on our
        #    side either — SuperDocs already holds the document.
        result_key = self._s3.result_key_for(filename, self._settings.superdocs_export_format)
        dest_url = self._s3.presigned_put(
            result_key,
            content_type=content_type_for_export_format(self._settings.superdocs_export_format),
        )
        warnings = self._superdocs.export_to_dest_url(
            session_id,
            self._settings.superdocs_export_format,
            dest_url,
            options={"filename": filename.rsplit(".", 1)[0]},
            dest_content_type=content_type_for_export_format(self._settings.superdocs_export_format),
        )
        logger.info("  exported result -> s3://%s/%s", self._settings.s3_bucket, result_key)
        if warnings:
            logger.warning("  export warnings for %s: %s", filename, warnings)

        self._s3.mark_processed(key, filename)
        logger.info("  moved source to processed/")

    def _stream_from_presigned_url(self, url: str):
        """Opens the S3 pre-signed GET as a streaming response and yields
        chunks bounded by the configured chunk size — this is the S3
        side of the "never downloads the payload to the orchestrator"
        property; superdocs_client wraps whatever iterator it's given in
        its own ChunkSizeTracker for the SuperDocs-facing leg."""
        chunk_size = self._settings.stream_chunk_size_bytes
        with self._superdocs.open_presigned_stream(url) as response:
            response.raise_for_status()
            yield from response.iter_bytes(chunk_size=chunk_size)

    @staticmethod
    def _content_type_for(export_format: str) -> str:
        return content_type_for_export_format(export_format)
