"""Folder watcher for detecting new documents and triggering incremental updates.

Monitors a configured directory for new files. When a new document appears,
it triggers a focused incremental update to the existing deliverable rather
than a full pipeline re-run.

The watcher integrates with:
- The extractor registry (for type-specific claim extraction)
- The incremental update engine (for targeted section updates)
- The approval queue (for conflict resolution)

Design:
- Uses polling-based detection (compatible with all filesystems).
- Maintains a set of already-processed file hashes to avoid re-processing.
- Each new file triggers: classify → extract → incremental update.
- Never triggers a full pipeline re-run.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from src.pipeline.deliverable import Deliverable, SectionClaim
from src.pipeline.incremental import (
    ClaimTypeRetrievalLayer,
    IncrementalUpdateEngine,
    IncrementalUpdateResult,
    RetrievalLayer,
)
from src.pipeline.approval import ApprovalService, InMemoryApprovalStore


# ---------------------------------------------------------------------------
# Extractor protocol for the watcher
# ---------------------------------------------------------------------------


class DocumentExtractor(Protocol):
    """Protocol for extracting claims from a new document file.

    Implementations handle: read file → classify → extract → return claims.
    """

    def extract_claims(
        self,
        file_path: str,
        document_id: str,
    ) -> list[SectionClaim]:
        """Extract all claims from a document file.

        Args:
            file_path: Absolute path to the document file.
            document_id: UUID string assigned to this document.

        Returns:
            List of SectionClaim instances extracted from the document.

        Raises:
            Exception: On extraction failure.
        """
        ...


# ---------------------------------------------------------------------------
# Watcher event types
# ---------------------------------------------------------------------------


@dataclass
class WatcherEvent:
    """Record of a file detection and processing by the watcher.

    Attributes:
        file_path: Path to the detected file.
        document_id: Assigned UUID for provenance tracking.
        file_hash: SHA-256 of the file contents (deduplication).
        update_result: The result of the incremental update, or None on error.
        error: Error message if processing failed.
    """

    file_path: str
    document_id: str
    file_hash: str
    update_result: Optional[IncrementalUpdateResult] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Watcher
# ---------------------------------------------------------------------------


class FolderWatcher:
    """Watches a folder for new documents and triggers incremental updates.

    The watcher maintains state about which files have been processed
    (by content hash) to avoid re-processing identical files.

    Args:
        watch_dir: Directory path to monitor for new files.
        deliverable: The current deliverable to update incrementally.
        extractor: Document extractor implementation.
        retrieval_layer: Strategy for identifying affected sections.
            Defaults to ClaimTypeRetrievalLayer.
        approval_service: Approval service for conflict routing.
            If None, creates one with InMemoryApprovalStore.
        run_id: Pipeline run ID for scoping. Auto-generated if not provided.
    """

    def __init__(
        self,
        watch_dir: str,
        deliverable: Deliverable,
        extractor: DocumentExtractor,
        retrieval_layer: Optional[RetrievalLayer] = None,
        approval_service: Optional[ApprovalService] = None,
        run_id: Optional[str] = None,
    ) -> None:
        self._watch_dir = watch_dir
        self._deliverable = deliverable
        self._extractor = extractor
        self._retrieval = retrieval_layer or ClaimTypeRetrievalLayer()
        self._run_id = run_id or str(uuid.uuid4())

        if approval_service is None:
            store = InMemoryApprovalStore()
            self._approval = ApprovalService(store)
        else:
            self._approval = approval_service

        self._engine = IncrementalUpdateEngine(
            retrieval_layer=self._retrieval,
            approval_service=self._approval,
            run_id=self._run_id,
        )

        # Track processed files by content hash
        self._processed_hashes: set[str] = set()
        self._events: list[WatcherEvent] = []

    @property
    def deliverable(self) -> Deliverable:
        """The current deliverable being incrementally updated."""
        return self._deliverable

    @property
    def approval_service(self) -> ApprovalService:
        """The approval service handling conflicts."""
        return self._approval

    @property
    def events(self) -> list[WatcherEvent]:
        """All watcher events (processed files) in order."""
        return self._events

    @property
    def run_id(self) -> str:
        """The run ID used for approval queue scoping."""
        return self._run_id

    def scan(self) -> list[WatcherEvent]:
        """Scan the watch directory for new files and process them.

        Detects files not yet processed (by content hash), extracts claims,
        and triggers incremental updates. Returns events for all newly
        processed files.

        Returns:
            List of WatcherEvent for each newly processed file.
        """
        new_events: list[WatcherEvent] = []

        if not os.path.isdir(self._watch_dir):
            return new_events

        for filename in sorted(os.listdir(self._watch_dir)):
            file_path = os.path.join(self._watch_dir, filename)
            if not os.path.isfile(file_path):
                continue

            # Compute content hash for deduplication
            file_hash = self._hash_file(file_path)
            if file_hash in self._processed_hashes:
                continue

            # Process this new file
            event = self._process_file(file_path, file_hash)
            new_events.append(event)
            self._events.append(event)
            self._processed_hashes.add(file_hash)

        return new_events

    def process_single_file(self, file_path: str) -> WatcherEvent:
        """Process a single file directly (for programmatic triggering).

        Useful when integrating with filesystem event APIs (inotify, FSEvents)
        rather than polling.

        Args:
            file_path: Absolute path to the file to process.

        Returns:
            WatcherEvent describing the outcome.
        """
        file_hash = self._hash_file(file_path)

        if file_hash in self._processed_hashes:
            return WatcherEvent(
                file_path=file_path,
                document_id="",
                file_hash=file_hash,
                error="Already processed (duplicate content hash)",
            )

        event = self._process_file(file_path, file_hash)
        self._events.append(event)
        self._processed_hashes.add(file_hash)
        return event

    def _process_file(self, file_path: str, file_hash: str) -> WatcherEvent:
        """Extract claims from a file and trigger incremental update.

        Args:
            file_path: Path to the file.
            file_hash: Pre-computed content hash.

        Returns:
            WatcherEvent with the result or error.
        """
        document_id = str(uuid.uuid4())

        try:
            # Extract claims from the new document
            claims = self._extractor.extract_claims(file_path, document_id)

            # Run incremental update
            result = self._engine.update(
                deliverable=self._deliverable,
                new_document_claims=claims,
                new_document_id=document_id,
            )

            return WatcherEvent(
                file_path=file_path,
                document_id=document_id,
                file_hash=file_hash,
                update_result=result,
            )

        except Exception as exc:
            return WatcherEvent(
                file_path=file_path,
                document_id=document_id,
                file_hash=file_hash,
                error=f"Processing failed: {exc}",
            )

    @staticmethod
    def _hash_file(file_path: str) -> str:
        """Compute SHA-256 hash of file contents.

        Args:
            file_path: Path to the file to hash.

        Returns:
            Hex digest of the file's SHA-256 hash.
        """
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
