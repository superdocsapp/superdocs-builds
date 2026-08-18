"""Deterministic In-Memory Wiki Adapter for fast, reproducible testing without external credentials."""

from __future__ import annotations

from typing import Dict
from live_doc_agent.models import (
    ConflictError,
    Patch,
    SectionNotFoundError,
    WikiDocument,
)
from live_doc_agent.patcher import DocumentPatcher
from live_doc_agent.wiki.base import WikiAdapter


class MemoryWikiAdapter(WikiAdapter):
    """In-memory wiki adapter with strict optimistic concurrency control."""

    def __init__(self, initial_documents: Dict[str, WikiDocument] | None = None) -> None:
        self._documents: Dict[str, WikiDocument] = {}
        if initial_documents:
            for doc_id, doc in initial_documents.items():
                self.seed_document(doc)

    def seed_document(self, doc: WikiDocument) -> None:
        """Seed or overwrite a document snapshot in memory."""
        sections = DocumentPatcher.parse_sections(doc.content)
        self._documents[doc.doc_id] = WikiDocument(
            doc_id=doc.doc_id,
            title=doc.title,
            content=doc.content,
            content_version=str(doc.content_version),
            sections=sections,
            metadata=dict(doc.metadata),
        )

    def fetch_page(self, doc_id: str) -> WikiDocument:
        """Fetch current document snapshot."""
        if doc_id not in self._documents:
            raise SectionNotFoundError(f"Document with ID '{doc_id}' not found in memory wiki.")

        stored = self._documents[doc_id]
        sections = DocumentPatcher.parse_sections(stored.content)
        return WikiDocument(
            doc_id=stored.doc_id,
            title=stored.title,
            content=stored.content,
            content_version=stored.content_version,
            sections=sections,
            metadata=dict(stored.metadata),
        )

    def apply_patch(self, doc_id: str, patch: Patch) -> WikiDocument:
        """Surgically apply patch with optimistic locking verification."""
        if doc_id not in self._documents:
            raise SectionNotFoundError(f"Document with ID '{doc_id}' not found in memory wiki.")

        stored = self._documents[doc_id]

        # 1. Optimistic concurrency check
        if str(stored.content_version) != str(patch.expected_version):
            raise ConflictError(
                f"Concurrency conflict on doc '{doc_id}': expected version {patch.expected_version}, "
                f"but current version is {stored.content_version}."
            )

        # 2. Apply surgical edit using DocumentPatcher
        new_content = DocumentPatcher.apply_patch_to_content(stored.content, patch)

        # 3. Increment content version (e.g. "1" -> "2")
        try:
            next_version = str(int(stored.content_version) + 1)
        except ValueError:
            next_version = f"{stored.content_version}_v2"

        updated_sections = DocumentPatcher.parse_sections(new_content)
        updated_doc = WikiDocument(
            doc_id=stored.doc_id,
            title=stored.title,
            content=new_content,
            content_version=next_version,
            sections=updated_sections,
            metadata=dict(stored.metadata),
        )

        self._documents[doc_id] = updated_doc
        return updated_doc

    def get_version(self, doc_id: str) -> str:
        """Return the current document version token."""
        if doc_id not in self._documents:
            raise SectionNotFoundError(f"Document with ID '{doc_id}' not found in memory wiki.")
        return self._documents[doc_id].content_version
