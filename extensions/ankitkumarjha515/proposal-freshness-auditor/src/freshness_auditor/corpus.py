"""The document corpus registry.

A `Corpus` is a flat list of documents the auditor knows about, each tagged
with a `role`: "library" (reusable boilerplate) or "draft" (an in-progress
proposal). This module only loads and validates the registry and reads raw
file contents; it does not parse HTML or detect stale claims — that is the
detection engine's job (T2).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

ALLOWED_ROLES = {"library", "draft"}


class CorpusError(Exception):
    """Base class for all corpus validation errors."""


class DuplicateDocumentIdError(CorpusError):
    """Raised when two documents in the corpus share the same id."""


class InvalidDocumentRoleError(CorpusError):
    """Raised when a document's `role` is not one of the allowed values."""


class MissingDocumentFileError(CorpusError):
    """Raised when a document's `path` does not exist on disk."""


class DocumentNotFoundError(CorpusError):
    """Raised when looking up a document id that is not in the corpus."""


@dataclass(frozen=True)
class Document:
    id: str
    role: str  # "library" | "draft"
    path: Path
    title: str


class Corpus:
    """A validated registry of `Document`s, loaded from YAML."""

    def __init__(self, documents: list[Document]):
        self._documents = documents
        self._by_id: dict[str, Document] = {d.id: d for d in documents}

    @classmethod
    def load(cls, path: str | Path) -> "Corpus":
        path = Path(path)
        base_dir = path.parent
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        raw_docs = data.get("documents") or []
        documents: list[Document] = []
        seen_ids: set[str] = set()
        for raw in raw_docs:
            doc_id = raw.get("id")
            if doc_id in seen_ids:
                raise DuplicateDocumentIdError(
                    f"document '{doc_id}': duplicate document id — each id "
                    f"in corpus.yaml must be unique; rename or remove the "
                    f"duplicate entry"
                )
            seen_ids.add(doc_id)

            role = raw.get("role")
            if role not in ALLOWED_ROLES:
                raise InvalidDocumentRoleError(
                    f"document '{doc_id}': role '{role}' is not one of "
                    f"{sorted(ALLOWED_ROLES)} — fix the 'role' field in "
                    f"corpus.yaml"
                )

            rel_path = raw.get("path")
            full_path = (base_dir / rel_path).resolve()
            if not full_path.is_file():
                raise MissingDocumentFileError(
                    f"document '{doc_id}': file '{full_path}' does not "
                    f"exist on disk — check the 'path' field in "
                    f"corpus.yaml or restore the missing fixture file"
                )

            documents.append(
                Document(
                    id=doc_id,
                    role=role,
                    path=full_path,
                    title=raw.get("title", ""),
                )
            )

        return cls(documents)

    def documents(self) -> list[Document]:
        return list(self._documents)

    def by_role(self, role: str) -> list[Document]:
        return [d for d in self._documents if d.role == role]

    def get(self, doc_id: str) -> Document:
        try:
            return self._by_id[doc_id]
        except KeyError:
            raise DocumentNotFoundError(
                f"document '{doc_id}' not found in corpus — check the id "
                f"against corpus.yaml"
            ) from None

    def read_text(self, doc_id: str) -> str:
        doc = self.get(doc_id)
        return doc.path.read_text(encoding="utf-8")

    def __iter__(self):
        return iter(self._documents)

    def __len__(self) -> int:
        return len(self._documents)
