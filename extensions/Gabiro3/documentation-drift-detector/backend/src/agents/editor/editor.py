"""Apply an approved fix through SuperDocs under a two-phase byte Judge.

The protocol (spec §5) is deliberately paranoid about scope:

    snapshot = {chunk_id -> content_hash}          # pre-edit, from SuperDocs
    chat_async("In chunk {id}, replace '{old}' with '{new}'",
               approval_mode="ask_every_time", model_tier="max")
    poll -> awaiting_approval, branching on metadata.awaiting_kind FIRST
    PHASE A (pre-commit, CODE): every pending change must target an intended
        chunk, else reject the batch and apply nothing
    approve
    PHASE B (post-apply, CODE): every non-target chunk must hash identically,
        else ALARM and block the commit

Both phases are hash/set comparisons. No LLM opinion enters either one —
"nothing else changed" is a measurement, not a judgement.
"""

import asyncio
import hashlib
import json
import time
from typing import Optional
from uuid import UUID

from core.superdocs_client import SuperDocsClient, SuperDocsError
from core.trace import TraceLogger

from agents.editor.judge_byte import JudgeByte

POLL_INTERVAL_SECONDS = 1.0
POLL_TIMEOUT_SECONDS = 180


class ApplyOutcome:
    APPLIED = "APPLIED"
    NEEDS_ESCALATION = "NEEDS_ESCALATION"
    ALARM = "ALARM"
    FAILED = "FAILED"


def parse_pending_changes(metadata: dict) -> list[dict]:
    """Read pending_changes, which is an object when polling but a JSON
    string on the SSE path — hence the second parse."""
    raw = (metadata or {}).get("pending_changes")
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if isinstance(raw, dict):
        raw = raw.get("changes", [])
    return raw if isinstance(raw, list) else []


class Editor:
    def __init__(
        self,
        sd_client: SuperDocsClient,
        trace: Optional[TraceLogger] = None,
        poll_interval: float = POLL_INTERVAL_SECONDS,
        poll_timeout: float = POLL_TIMEOUT_SECONDS,
    ):
        self.sd = sd_client
        self.trace = trace
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout

    async def _log(self, node: str, input_hash: str, **kw):
        if self.trace:
            await self.trace.log(node, input_hash, **kw)

    async def apply_fix(
        self,
        superdocs_doc_id: str,
        target_chunk_id: str,
        old_text: str,
        new_text: str,
        session_id: Optional[str] = None,
    ) -> dict:
        """Apply one scoped edit and prove it touched nothing else.

        `session_id` is the document's own SuperDocs session. Every editing
        call — open, focus, chat, approve — is session-scoped, so they must be
        issued against the session the document actually lives in.
        """
        step = hashlib.sha256(
            f"{superdocs_doc_id}:{target_chunk_id}:{old_text}:{new_text}".encode()
        ).hexdigest()[:16]
        t0 = time.time()

        sd = self.sd.for_session(session_id)

        # An edit targets a document that is open in the session; a document
        # ingested in an earlier session must be re-opened first.
        try:
            await sd.open_documents([superdocs_doc_id])
            await sd.focus_document(superdocs_doc_id)
        except SuperDocsError as exc:
            # A 404 here is not a transient failure: the id we stored does not
            # name a document SuperDocs still has. Say so, because "open
            # failed [404]" reads like an outage and sends people looking in
            # the wrong place.
            missing = "404" in str(exc) or "not found" in str(exc).lower()
            if missing and not await sd.document_exists(superdocs_doc_id):
                reason = (
                    f"This document no longer exists in SuperDocs "
                    f"(id {superdocs_doc_id}). It cannot be edited until it is "
                    f"re-ingested from its source file."
                )
                await self._log("APPLY", step, decision=f"failed: {reason}")
                return {
                    "status": ApplyOutcome.FAILED,
                    "reason": reason,
                    "document_missing": True,
                }
            await self._log("APPLY", step, decision=f"failed: could not open document ({exc})")
            return {"status": ApplyOutcome.FAILED, "reason": f"open failed: {exc}"}

        # --- Pre-edit snapshot, from SuperDocs ---
        try:
            pre_chunks = await sd.get_document_chunks(superdocs_doc_id)
        except SuperDocsError as exc:
            await self._log("APPLY", step, decision=f"failed: snapshot unavailable ({exc})")
            return {"status": ApplyOutcome.FAILED, "reason": f"snapshot failed: {exc}"}

        pre_by_id = {c["chunk_id"]: c for c in pre_chunks}
        snapshot = JudgeByte.hash_document_snapshot(pre_chunks)
        if target_chunk_id not in snapshot:
            await self._log(
                "APPLY", step,
                decision=f"failed: target chunk {target_chunk_id} not in document",
            )
            return {
                "status": ApplyOutcome.FAILED,
                "reason": f"target chunk {target_chunk_id} not present in document",
            }

        # --- Scoped instruction: name the chunk, quote both sides ---
        instruction = (
            f"In chunk {target_chunk_id}, replace exactly \"{old_text}\" "
            f"with \"{new_text}\". Change nothing else anywhere in the document."
        )
        try:
            job_id = await sd.chat_async(
                instruction, approval_mode="ask_every_time", model_tier="max",
                document_id=superdocs_doc_id,
            )
        except SuperDocsError as exc:
            await self._log("APPLY", step, decision=f"failed: chat_async ({exc})")
            return {"status": ApplyOutcome.FAILED, "reason": str(exc)}

        job = await self._await_approval(job_id, sd)
        if job is None:
            await self._log("APPLY", step, decision="failed: timed out awaiting approval")
            return {"status": ApplyOutcome.FAILED, "reason": "timed out awaiting approval"}

        metadata = job.get("metadata") or {}

        # Branch on awaiting_kind BEFORE reading pending_changes.
        if metadata.get("awaiting_kind") == "continue_prompt":
            await sd.continue_job(job_id)
            job = await self._await_approval(job_id, sd)
            if job is None:
                return {"status": ApplyOutcome.FAILED, "reason": "timed out after continue"}
            metadata = job.get("metadata") or {}

        pending = parse_pending_changes(metadata)
        if not pending:
            await self._log("APPLY", step, decision="failed: no pending changes proposed")
            return {"status": ApplyOutcome.FAILED, "reason": "no changes proposed"}

        # --- JUDGE byte, Phase A: stop a stray edit BEFORE it lands ---
        phase_a = JudgeByte.phase_a(pending, {target_chunk_id})
        if not phase_a["ok"]:
            for change in pending:
                cid = change.get("change_id")
                if cid:
                    await sd.approve_change(
                        job_id, cid, approved=False,
                        feedback="Rejected: change targets a chunk outside the approved scope.",
                    )
            await self._log(
                "JUDGE_BYTE_A", step, decision=f"rejected: {phase_a['reason']}",
                ms=int((time.time() - t0) * 1000),
            )
            return {
                "status": ApplyOutcome.NEEDS_ESCALATION,
                "phase": "A",
                "reason": phase_a["reason"],
            }

        await self._log("JUDGE_BYTE_A", step, decision="passed: batch within scope")

        # --- Approve (top-level `approved` is required on every call) ---
        approved_change_ids = []
        for change in pending:
            cid = change.get("change_id")
            if not cid:
                continue
            await sd.approve_change(job_id, cid, approved=True)
            approved_change_ids.append(cid)

        await self._await_settled(job_id, sd)

        # --- JUDGE byte, Phase B: prove the untouched property AFTER ---
        try:
            post_chunks = await sd.get_document_chunks(superdocs_doc_id)
        except SuperDocsError as exc:
            await self._log("JUDGE_BYTE_B", step, decision=f"failed: re-fetch ({exc})")
            return {"status": ApplyOutcome.FAILED, "reason": f"post-edit re-fetch failed: {exc}"}

        post = JudgeByte.hash_document_snapshot(post_chunks)
        phase_b = JudgeByte.phase_b(post, snapshot, target_chunk_id)
        if not phase_b["ok"]:
            await self._log(
                "JUDGE_BYTE_B", step, decision=f"ALARM: {phase_b['reason']}",
                ms=int((time.time() - t0) * 1000),
            )
            return {
                "status": ApplyOutcome.ALARM,
                "phase": "B",
                "reason": phase_b["reason"],
                "job_id": job_id,
            }

        target_changed = post.get(target_chunk_id) != snapshot.get(target_chunk_id)
        await self._log(
            "JUDGE_BYTE_B", step,
            decision="passed: all non-target chunks byte-identical",
            evidence={
                "target_chunk_changed": target_changed,
                "chunks_checked": len(post),
            },
            superdocs_ops=2,
            ms=int((time.time() - t0) * 1000),
        )

        # The post-edit chunks are already in hand from Phase B. Returning them
        # is what lets the caller bring our stored copy in line with the
        # document and record what the edit actually changed — without them the
        # edit lands in SuperDocs and is invisible everywhere else.
        post_by_id = {c["chunk_id"]: c for c in post_chunks}
        before = pre_by_id.get(target_chunk_id, {})
        after = post_by_id.get(target_chunk_id, {})

        return {
            "status": ApplyOutcome.APPLIED,
            "job_id": job_id,
            "change_ids": approved_change_ids,
            "target_chunk_changed": target_changed,
            "chunks_verified": len(post),
            "before_html": before.get("html"),
            "after_html": after.get("html"),
            "before_hash": before.get("content_hash"),
            "after_hash": after.get("content_hash"),
            "post_chunks": post_chunks,
        }

    async def _await_approval(
        self, job_id: str, sd: Optional[SuperDocsClient] = None
    ) -> Optional[dict]:
        sd = sd or self.sd
        deadline = time.time() + self.poll_timeout
        while time.time() < deadline:
            job = await sd.get_job(job_id)
            status = (job.get("status") or "").lower()
            if status in ("awaiting_approval", "awaiting_input"):
                return job
            if status in ("failed", "error", "cancelled"):
                return None
            if status in ("completed", "succeeded"):
                # Nothing to approve (approve_all, or a no-op edit).
                return job
            await asyncio.sleep(self.poll_interval)
        return None

    async def _await_settled(
        self, job_id: str, sd: Optional[SuperDocsClient] = None
    ) -> Optional[dict]:
        sd = sd or self.sd
        deadline = time.time() + self.poll_timeout
        while time.time() < deadline:
            job = await sd.get_job(job_id)
            status = (job.get("status") or "").lower()
            if status in ("completed", "succeeded", "failed", "error", "cancelled"):
                return job
            await asyncio.sleep(self.poll_interval)
        return None
