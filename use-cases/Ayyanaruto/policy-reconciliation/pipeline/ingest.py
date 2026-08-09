"""Stage 1: upload both estates into one SuperDocs compare session."""

from __future__ import annotations

from .common import client, list_docx, slug


def ingest(estate_a, estate_b, run_id, limit=None):
    """Upload both estates into one compare session. First file replaces; rest are extra tabs."""
    session_id = f"pr_{slug(run_id, 24)}_compare"
    docs = []
    first = True
    print(f"  compare session {session_id}")
    for estate, folder in (("a", estate_a), ("b", estate_b)):
        for path in list_docx(folder, limit=limit):
            mode = "replace" if first else "new_focused"
            first = False
            print(f"  upload [{estate}] {path.name}")
            uploaded = client.upload(path, session_id, open_mode=mode)
            docs.append(
                {
                    "estate": estate,
                    "filename": path.name,
                    "stem": path.stem,
                    "path": str(path.resolve()),
                    "session_id": session_id,
                    "document_id": uploaded.get("document_id"),
                    "chunks_count": uploaded.get("chunks_count"),
                }
            )
            if not uploaded.get("document_id"):
                print(f"  warning: no document_id returned for {path.name}")
    return docs, session_id
