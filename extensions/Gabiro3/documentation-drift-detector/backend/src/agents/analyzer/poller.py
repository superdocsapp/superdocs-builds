import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from core.db import exec, exec_one, insert, poll_pending_job, to_uuid, update
from core.llm_provider import LLMProvider
from core.models import ChangeFact
from core.trace import TraceLogger

# A run in one of these states should stop at the next checkpoint boundary.
CANCEL_STATUSES = {"cancelling", "cancelled"}


class RunCancelled(Exception):
    """Raised when a stop was requested; not an error condition."""


class Poller:
    def __init__(self, llm: LLMProvider, agent_name: str = "agent_2"):
        self.llm = llm
        self.agent_name = agent_name

    # ---------------- Job loop ----------------

    async def poll_and_run(self, poll_interval: float = 2.0, max_iters: int = 0):
        iterations = 0
        while max_iters == 0 or iterations < max_iters:
            job = None
            try:
                job = await poll_pending_job("ingestion", self.agent_name)
            except Exception:
                await asyncio.sleep(poll_interval)
                continue

            if not job:
                await asyncio.sleep(poll_interval)
                continue

            payload = (
                json.loads(job["payload"])
                if isinstance(job["payload"], str)
                else job["payload"]
            )
            run_id = to_uuid(payload["run_id"])
            doc_ids = payload["document_ids"]
            trace = TraceLogger(run_id)

            await self._set_run_status(run_id, "in_progress")
            try:
                await self._run_pipeline(run_id, doc_ids, trace)
            except RunCancelled:
                await self._set_run_status(run_id, "cancelled")
                await trace.log("RUN", "-", decision="cancelled")
                await update(
                    "jobs",
                    {"id": job["id"]},
                    {"status": "completed", "result": json.dumps({"cancelled": True})},
                )
            except Exception as exc:
                await self._set_run_status(run_id, "failed")
                await trace.log("RUN", "-", decision=f"failed: {str(exc)[:200]}")
                await update(
                    "jobs",
                    {"id": job["id"]},
                    {"status": "failed", "result": json.dumps({"error": str(exc)[:500]})},
                )
            else:
                await self._set_run_status(run_id, "completed")
                await update(
                    "jobs",
                    {"id": job["id"]},
                    {
                        "status": "completed",
                        "completed_at": datetime.now(timezone.utc),
                        "result": json.dumps({"run_id": str(run_id)}),
                    },
                )
            iterations += 1

    async def run_manual(self, run_id: UUID, document_ids: list[UUID]):
        trace = TraceLogger(run_id)
        await self._set_run_status(run_id, "in_progress")
        try:
            await self._run_pipeline(run_id, document_ids, trace)
        except RunCancelled:
            await self._set_run_status(run_id, "cancelled")
            return
        except Exception:
            await self._set_run_status(run_id, "failed")
            raise
        await self._set_run_status(run_id, "completed")

    # ---------------- Run state ----------------

    @staticmethod
    async def _set_run_status(run_id: UUID, status: str) -> None:
        try:
            await update("runs", {"id": str(run_id)}, {"status": status})
        except Exception:
            pass

    @staticmethod
    def _embedder_of(llm):
        """The provider that actually served embeddings (may be wrapped)."""
        return getattr(llm, "_embedder", llm)

    @staticmethod
    async def _check_cancelled(run_id: UUID) -> None:
        """Cancellation is cooperative: checked between checkpointed units so
        a stop never leaves a half-written step behind."""
        row = await exec_one(
            "SELECT status FROM runs WHERE id = :rid", {"rid": str(run_id)}
        )
        if row and row["status"] in CANCEL_STATUSES:
            raise RunCancelled()

    # ---------------- Checkpointing (run_steps) ----------------

    @staticmethod
    async def _step_completed(run_id: UUID, node: str, input_hash: str) -> bool:
        row = await exec_one(
            "SELECT status FROM run_steps "
            "WHERE run_id = :rid AND node = :node AND input_hash = :h",
            {"rid": str(run_id), "node": node, "h": input_hash},
        )
        return bool(row and row["status"] == "completed")

    @staticmethod
    async def _step_start(run_id: UUID, node: str, input_hash: str) -> None:
        await exec(
            """
            INSERT INTO run_steps (run_id, node, input_hash, status, started_at)
            VALUES (:rid, :node, :h, 'in_progress', now())
            ON CONFLICT (run_id, node, input_hash)
            DO UPDATE SET status = 'in_progress', started_at = now(), ended_at = NULL
            """,
            {"rid": str(run_id), "node": node, "h": input_hash},
        )

    @staticmethod
    async def _step_complete(
        run_id: UUID, node: str, input_hash: str, output_ref: Optional[dict] = None
    ) -> None:
        await exec(
            """
            UPDATE run_steps
               SET status = 'completed', ended_at = now(), output_ref = :out
             WHERE run_id = :rid AND node = :node AND input_hash = :h
            """,
            {
                "rid": str(run_id),
                "node": node,
                "h": input_hash,
                "out": json.dumps(output_ref or {}),
            },
        )

    # ---------------- Pipeline ----------------

    async def _run_pipeline(self, run_id: UUID, doc_ids: list, trace: TraceLogger):
        doc_list = [str(d) for d in doc_ids]
        doc_hash = hashlib.sha256(
            json.dumps(doc_list, sort_keys=True).encode()
        ).hexdigest()[:16]
        doc_uuids = [to_uuid(d) for d in doc_ids]

        # --- EMBED (idempotent: embedder skips chunks that already have one) ---
        if await self._step_completed(run_id, "EMBED", doc_hash):
            await trace.log("EMBED", doc_hash, decision="skipped (checkpoint)")
        else:
            await self._step_start(run_id, "EMBED", doc_hash)
            t0 = time.time()
            await trace.log("EMBED", doc_hash, decision="start")
            from agents.analyzer.embedder import Embedder

            await Embedder(self.llm).embed_documents(doc_uuids)

            # If the embeddings endpoint was unusable we fell back to lexical
            # hashing. Say so plainly — degraded recall must not look clean.
            degraded = getattr(self._embedder_of(self.llm), "degraded", False)
            if degraded:
                reason = getattr(self._embedder_of(self.llm), "reason", "")
                await trace.log(
                    "EMBED",
                    doc_hash,
                    decision="degraded: embeddings endpoint unavailable, "
                    "using lexical fallback (recall reduced)",
                    evidence={"reason": reason},
                )

            await self._step_complete(
                run_id, "EMBED", doc_hash,
                {"documents": len(doc_list), "degraded": bool(degraded)},
            )
            await trace.log(
                "EMBED", doc_hash, decision="embedded", ms=int((time.time() - t0) * 1000)
            )

        await self._check_cancelled(run_id)

        # --- PARSE_CHANGES (persisted so a resume reuses the same fact ids) ---
        change_facts = await self._load_change_facts(run_id)
        if change_facts:
            await trace.log(
                "PARSE_CHANGES",
                doc_hash,
                decision="skipped (checkpoint)",
                evidence={"facts": len(change_facts)},
            )
        else:
            await self._step_start(run_id, "PARSE_CHANGES", doc_hash)
            t0 = time.time()
            await trace.log("PARSE_CHANGES", doc_hash, decision="start")
            from agents.analyzer.change_parser import ChangeParser

            change_facts = await ChangeParser(self.llm).parse(
                run_id, feed_jsonl=self._default_feed()
            )
            await self._persist_change_facts(change_facts)
            await self._step_complete(
                run_id, "PARSE_CHANGES", doc_hash, {"facts": len(change_facts)}
            )
            await trace.log(
                "PARSE_CHANGES",
                doc_hash,
                decision="parsed",
                evidence={"facts": len(change_facts)},
                ms=int((time.time() - t0) * 1000),
            )

        await self._check_cancelled(run_id)

        # --- RETRIEVE (recomputed: cheap, and embeddings are already cached) ---
        t0 = time.time()
        await trace.log("RETRIEVE", doc_hash, decision="start")
        from agents.analyzer.retriever import Retriever

        candidates = await Retriever(self.llm).retrieve(run_id, change_facts)
        await trace.log(
            "RETRIEVE",
            doc_hash,
            decision="retrieved",
            evidence={"candidates": sum(len(c) for c in candidates)},
            ms=int((time.time() - t0) * 1000),
        )

        # --- FINDER -> VERIFIER -> PROPOSE -> JUDGE, one change_fact at a time ---
        # Per-fact granularity is what makes resume worthwhile: the LLM calls
        # are the expensive part, so already-processed facts are never redone.
        already_done = await self._change_facts_with_findings(run_id)

        for cf, cands in zip(change_facts, candidates):
            if cf.id in already_done:
                await trace.log(
                    "FINDER", str(cf.id), decision="skipped (checkpoint)"
                )
                continue

            await self._check_cancelled(run_id)

            step_hash = str(cf.id)
            await self._step_start(run_id, "FINDER", step_hash)
            t1 = time.time()

            findings = await self._process_change_fact(cf, cands, trace)
            for finding in findings:
                await self._persist_finding(run_id, finding)

            states = [f.state for f in findings]
            await self._step_complete(
                run_id, "FINDER", step_hash,
                {"findings": len(findings), "states": states},
            )
            await trace.log(
                "VERIFY+PROPOSE+JUDGE",
                step_hash,
                decision=", ".join(states),
                evidence={"chunks_flagged": sum(s == "CONFIRMED_DRIFT" for s in states)},
                ms=int((time.time() - t1) * 1000),
            )

        await self._check_cancelled(run_id)

        # --- REVIEW_DISPATCH ---
        review_ids = await self._finding_ids(run_id)
        await self._dispatch_review(run_id, review_ids)
        await trace.log(
            "REVIEW_DISPATCH",
            doc_hash,
            decision="dispatched",
            evidence={"findings": len(review_ids)},
        )

    async def _process_change_fact(self, cf, cands, trace: TraceLogger) -> list:
        """Judge one change fact, returning one finding per chunk.

        Verification is per chunk too: a quote is checked against the chunk it
        was cited from, not against the candidate set as a whole.
        """
        from agents.analyzer.finder import Finder
        from agents.analyzer.judge_semantic import JudgeSemantic
        from agents.analyzer.proposer import Proposer
        from agents.analyzer.verifier import Verifier

        raw_findings = await Finder(self.llm).find_for_fact(cf, cands)
        by_chunk = {c["chunk_id"]: c for c in cands}
        verifier = Verifier(self.llm)
        proposer = Proposer(self.llm)
        judge = JudgeSemantic(self.llm)

        processed = []
        for raw in raw_findings:
            if raw.state != "CONFIRMED_DRIFT":
                processed.append(raw)
                continue

            cited = by_chunk.get(raw.evidence_chunk_id or raw.chunk_id)
            raw = await verifier.verify(raw, [cited] if cited else [])
            if raw.state == "UNKNOWN":
                processed.append(raw)
                continue

            raw = proposer.propose_fix(raw)
            judged = judge.judge(raw)
            raw.judge_verdict = judged.judge_verdict
            if judged.state == "UNKNOWN":
                raw.state = "UNKNOWN"
            processed.append(raw)

        return processed

    # ---------------- Persistence helpers ----------------

    @staticmethod
    async def _load_change_facts(run_id: UUID) -> list[ChangeFact]:
        rows = await exec(
            "SELECT id, run_id, type, old_value, new_value, evidence_span, source_ref, "
            "created_at FROM change_facts WHERE run_id = :rid ORDER BY created_at",
            {"rid": str(run_id)},
        )
        return [ChangeFact(**row) for row in rows]

    @staticmethod
    async def _persist_change_facts(change_facts: list[ChangeFact]) -> None:
        for cf in change_facts:
            await insert("change_facts", cf.model_dump())

    @staticmethod
    async def _change_facts_with_findings(run_id: UUID) -> set:
        rows = await exec(
            "SELECT DISTINCT change_fact_id FROM findings "
            "WHERE run_id = :rid AND change_fact_id IS NOT NULL",
            {"rid": str(run_id)},
        )
        return {to_uuid(r["change_fact_id"]) for r in rows}

    @staticmethod
    async def _finding_ids(run_id: UUID) -> list[UUID]:
        rows = await exec(
            "SELECT id FROM findings WHERE run_id = :rid ORDER BY created_at",
            {"rid": str(run_id)},
        )
        return [to_uuid(r["id"]) for r in rows]

    # Columns typed uuid in Postgres: the Finder's schema defaults them to
    # "", which is not a valid uuid, so blanks must become NULL.
    _UUID_COLUMNS = ("change_fact_id", "document_id")

    @staticmethod
    async def _persist_finding(run_id: UUID, finding) -> UUID:
        fid = uuid4()
        data = finding.model_dump()
        data["id"] = fid
        data["run_id"] = run_id

        for col in Poller._UUID_COLUMNS:
            if not data.get(col):
                data[col] = None

        # The model only knows the chunk id; resolve the owning document so
        # the review UI can show a filename instead of a bare id.
        if data.get("document_id") is None:
            chunk_ref = data.get("evidence_chunk_id") or data.get("chunk_id")
            if chunk_ref:
                row = await exec_one(
                    "SELECT c.document_id FROM chunks c "
                    "JOIN documents d ON d.id = c.document_id "
                    "WHERE c.chunk_id = :cid AND d.run_id = :rid LIMIT 1",
                    {"cid": chunk_ref, "rid": str(run_id)},
                )
                if row:
                    data["document_id"] = row["document_id"]

        await insert("findings", data)
        return fid

    @staticmethod
    async def _dispatch_review(run_id: UUID, review_ids: list[UUID]) -> None:
        from core.models import ReviewBatch

        batch = ReviewBatch(run_id=run_id, finding_ids=review_ids)
        await insert(
            "jobs",
            {
                "kind": "review_batch",
                "agent": "agent_3",
                "payload": json.dumps(batch.model_dump(mode="json"), default=str),
                "status": "pending",
                "created_at": datetime.now(timezone.utc),
            },
        )

    def _default_feed(self) -> str:
        return json.dumps(
            [
                {
                    "type": "renamed",
                    "old_value": "npm",
                    "new_value": "pnpm",
                    "source_ref": "CHANGELOG.md#v2.0",
                },
                {
                    "type": "default_changed",
                    "old_value": "3000",
                    "new_value": "8080",
                    "source_ref": "CHANGELOG.md#v2.1",
                },
                {
                    "type": "removed",
                    "old_value": "/healthz",
                    "new_value": "/api/v2/health",
                    "source_ref": "CHANGELOG.md#v2.2",
                },
                {
                    "type": "default_changed",
                    "old_value": "24 hours",
                    "new_value": "1 hour",
                    "source_ref": "CHANGELOG.md#v2.0",
                },
            ]
        )
