import hashlib
from typing import Optional
from uuid import UUID


class JudgeByte:
    @staticmethod
    def phase_a(pending_changes: list[dict], target_chunk_ids: set[str]) -> dict:
        for change in pending_changes:
            cid = change.get("chunk_id", "")
            if cid and cid not in target_chunk_ids:
                return {
                    "ok": False,
                    "reason": f"change.chunk_id {cid} not in intended targets {target_chunk_ids}",
                }
        return {"ok": True}

    @staticmethod
    def phase_b(post: dict[str, str], pre: dict[str, str], target_id: str) -> dict:
        for cid, post_hash in post.items():
            if cid == target_id:
                continue
            if cid not in pre:
                continue
            if post_hash != pre[cid]:
                return {
                    "ok": False,
                    "reason": f"Chunk {cid} byte-identity violated: "
                              f"pre={pre[cid][:12]} post={post_hash[:12]}",
                }
        return {"ok": True}

    @staticmethod
    def hash_document_snapshot(chunks: list[dict]) -> dict[str, str]:
        return {c["chunk_id"]: c["content_hash"] for c in chunks}