import hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
from core.superdocs_client import SuperDocsClient
from core.models import ParsedDocument
from core.text import html_to_text


class EmptyParseError(RuntimeError):
    """SuperDocs returned a document with no usable chunks."""


class Ingestor:
    def __init__(self, sd_client: SuperDocsClient, session_id: str):
        self.sd = sd_client
        self.session_id = session_id

    async def upload_only(self, file_path: str) -> ParsedDocument:
        """Upload a file into its own session and return the fresh parse.

        Used by re-ingest, which rebuilds an existing document's SuperDocs
        identity and chunks in place and so must not create a second
        `documents` row.
        """
        path = Path(file_path)
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()

        # A distinct session per attempt: re-ingest exists because the previous
        # document was lost, so it must not reuse a session that may still
        # hold one and overwrite it again.
        session = self.sd.session_for_document(f"{file_hash[:12]}-{uuid4().hex[:8]}")
        parsed = await self.sd.upload_document(str(file_path), session_id=session)
        parsed.file_hash = file_hash

        usable = [
            c for c in parsed.chunks
            if (c.get("html") or c.get("text") or "").strip()
        ]
        if not usable:
            raise EmptyParseError(
                f"SuperDocs returned no usable chunks for {path.name}. "
                f"Nothing was changed."
            )
        parsed.chunks = usable
        return parsed

    async def ingest_file(
        self, file_path: str, run_id: UUID, persist: bool = True
    ) -> ParsedDocument | None:
        """Upload a file through SuperDocs and persist its chunks.

        persist=False skips all database access (used by unit tests, which
        run without a live Postgres). When persist=True, database errors
        propagate rather than being swallowed — a failed insert must not
        look like a successful ingest.
        """
        path = Path(file_path)
        file_bytes = path.read_bytes()
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        if persist:
            from core.db import exec_one, insert_many, to_uuid

            # Idempotent by (run_id, file_hash): re-uploading the same bytes
            # into the same run is a no-op.
            existing = await exec_one(
                "SELECT id, superdocs_doc_id FROM documents "
                "WHERE run_id = :rid AND file_hash = :fh",
                {"rid": str(run_id), "fh": file_hash},
            )
            if existing:
                return ParsedDocument(
                    document_id=to_uuid(existing["id"]),
                    session_id=self.session_id,
                    superdocs_doc_id=existing["superdocs_doc_id"],
                    filename=path.name,
                    file_hash=file_hash,
                    chunks=[],
                    html="",
                )

        # One session per document. A SuperDocs session holds a single active
        # document, so uploading every file into one shared session made each
        # upload overwrite the previous document rather than adding to a
        # corpus. Keying the session on the content hash keeps a re-upload of
        # the same bytes on the same session instead of spawning duplicates.
        doc_session = self.sd.session_for_document(file_hash[:16])
        parsed = await self.sd.upload_document(str(file_path), session_id=doc_session)
        parsed.file_hash = file_hash

        # A document with no chunks is unusable: it renders blank, downloads
        # empty, and gives the pipeline nothing to reason over. SuperDocs can
        # return an empty parse (a cold session is a documented cause), so
        # refuse it before it reaches storage. Checked regardless of `persist`
        # because the parse is invalid either way.
        usable = [
            c for c in parsed.chunks
            if (c.get("html") or c.get("text") or "").strip()
        ]
        if not usable:
            raise EmptyParseError(
                f"SuperDocs returned no usable chunks for {path.name} "
                f"({len(file_bytes)} bytes uploaded). The document was not "
                f"stored. Retry the upload; if it persists, check the file "
                f"parses in SuperDocs."
            )
        parsed.chunks = usable

        if not persist:
            parsed.document_id = uuid4()
            return parsed

        doc_id = uuid4()
        writes: list[tuple[str, dict]] = [
            (
                "documents",
                {
                    "id": str(doc_id),
                    "run_id": str(run_id),
                    "superdocs_doc_id": parsed.superdocs_doc_id,
                    # The document's own session, not the global one: this is
                    # where its edits have to be issued.
                    "session_id": parsed.session_id or doc_session,
                    "filename": path.name,
                    "file_hash": file_hash,
                    "created_at": datetime.now(timezone.utc),
                },
            )
        ]
        for position, chunk in enumerate(usable):
            chunk_content = chunk.get("html") or chunk.get("text") or ""
            content_hash = chunk.get("content_hash") or hashlib.sha256(
                chunk_content.encode()
            ).hexdigest()
            writes.append(
                (
                    "chunks",
                    {
                        "id": str(uuid4()),
                        "document_id": str(doc_id),
                        "chunk_id": chunk["chunk_id"],
                        # Document order, captured at parse time. Chunk ids are
                        # random UUIDs, so ordering by them renders a document
                        # scrambled — and nothing else records position.
                        "ordinal": position,
                        "html": chunk_content,
                        # Written here so search never has to strip markup at
                        # query time, and never matches tag names.
                        "text_content": html_to_text(chunk_content),
                        "content_hash": content_hash,
                    },
                )
            )

        # One transaction: either the document and all its chunks land, or
        # neither does.
        await insert_many(writes)

        parsed.document_id = doc_id
        return parsed
