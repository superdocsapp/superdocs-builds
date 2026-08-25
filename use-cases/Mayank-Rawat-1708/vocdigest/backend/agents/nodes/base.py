"""
@file: backend/agents/nodes/base.py
@description: The contract every node obeys. Wrapping node bodies in one place means
    checkpoint-on-entry, skip-if-done, retry-with-backoff, cost accounting, and decision
    logging cannot be forgotten in an individual node — the behaviours are structural
    rather than a convention each node re-implements.
@flow: node(state) -> BaseNode.__call__ opens a session, checks the checkpoint (returns
    cached result and skips if COMPLETE), marks RUNNING, calls run() with retries, then
    writes the checkpoint plus a cost row before returning the mutated state.
@dependencies:
    - backend.db.checkpoint: the persistence primitives this class orchestrates
    - backend.services.groq_client.LLMUsage: token accumulation per stage
"""

from __future__ import annotations

import abc
import asyncio
import logging
import random
import uuid
from typing import Any

from backend.agents.state import DigestState
from backend.config import MissingCredentialError, settings
from backend.db.checkpoint import (
    STAGE_FAILED,
    STAGE_SKIPPED,
    append_decision,
    claim_stage,
    record_stage_cost,
    save_checkpoint,
    set_run_status,
)
from backend.db.database import session_scope
from backend.db.sqlite_checkpoint import mirror_checkpoint
from backend.models import Run, RunStatus, utcnow
from backend.services.groq_client import GroqUnavailable, LLMUsage

logger = logging.getLogger(__name__)


class NodeSkip(Exception):
    """Raised by a node to skip itself for a stated reason.

    Skipping is a first-class outcome, not a silent no-op: the reason is checkpointed
    and shown in the run timeline as a SKIPPED step.
    """

    def __init__(self, reason: str, result: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.result = result or {}


class NodeInputMissing(RuntimeError):
    """A stage's required input is empty or was never produced.

    Distinct from NodeSkip, and the distinction is the whole point. A skip says "there
    was nothing for me to do and the run is still sound" — no prior digest to compare
    against, for example. This says "what I need does not exist", which means every
    result downstream of here would be assembled from nothing. Raised rather than
    returned empty, and not retried: an absent input does not appear on a second attempt.
    """

    def __init__(self, reason: str, *, upstream_stage: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.upstream_stage = upstream_stage


class NodeCancelled(Exception):
    """The operator cancelled this run.

    Separate from NodePause because a paused run is expected to resume and a cancelled
    one is not — conflating them would leave cancelled runs looking resumable in the UI.
    """

    def __init__(self, reason: str = "Cancelled by operator") -> None:
        super().__init__(reason)
        self.reason = reason


class NodePause(Exception):
    """Raised to pause the run without failing it.

    Used for the human gate and for graceful degradation (e.g. Groq down). A paused run
    keeps every completed checkpoint and can be resumed in place.
    """

    def __init__(self, reason: str, status: RunStatus = RunStatus.PAUSED) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


class BaseNode(abc.ABC):
    """Base for every graph node.

    Subclasses implement run(); everything else is handled here.
    """

    #: checkpoint key and timeline label
    stage: str = ""
    #: run status while this node executes
    running_status: RunStatus = RunStatus.PENDING
    #: whether a failure here should fail the whole run (False => degrade and continue)
    fatal_on_error: bool = True
    #: stages whose output this one is built from. Each must have COMPLETED — a stage
    #: that failed, or that an operator skipped, has no output to build on, and running
    #: anyway is how a failure turns into a plausible-looking empty result further down.
    #: A stage that legitimately SKIPPED itself is not listed as a requirement by anyone,
    #: because a legitimate skip means its absence was survivable.
    requires: tuple[str, ...] = ()

    def __init__(self) -> None:
        if not self.stage:
            raise ValueError(f"{type(self).__name__} must define a stage name")
        self.usage = LLMUsage()
        self.superdocs_operations = 0

    @abc.abstractmethod
    async def run(self, state: DigestState, run_id: uuid.UUID) -> DigestState:
        """Do the stage's work. Raise NodeSkip or NodePause for non-failure exits."""

    async def __call__(self, state: DigestState) -> DigestState:
        run_id = uuid.UUID(state["run_id"])
        self.usage = LLMUsage()
        self.superdocs_operations = 0

        # --- cancellation check ---
        # Checked on entry to every node, so cancellation takes effect at the next stage
        # boundary. It cannot interrupt an in-flight HTTP call, which is why the token
        # budget below exists as well — a bound on spend does not depend on anyone
        # watching.
        async with session_scope() as session:
            run = await session.get(Run, run_id)
            if run is not None and run.status == RunStatus.CANCELLED:
                logger.info("Run %s is cancelled; stopping before %s", run_id, self.stage)
                raise NodeCancelled(
                    f"Run cancelled before the {self.stage} stage could start"
                )

            # --- token budget ---
            if settings.max_tokens_per_run > 0:
                spent = int(
                    ((run.cost_report or {}).get("totals") or {}).get(
                        "groq_tokens_used", 0
                    )
                )
                if spent >= settings.max_tokens_per_run:
                    from backend.services.llm_gate import trip_breaker

                    trip_breaker(
                        f"Run token budget reached ({spent:,} of "
                        f"{settings.max_tokens_per_run:,}). Remaining stages will use "
                        f"heuristics."
                    )
                    await append_decision(
                        session,
                        run_id,
                        self.stage,
                        "BUDGET_REACHED",
                        f"This run has used {spent:,} Groq tokens, at or over its "
                        f"MAX_TOKENS_PER_RUN limit of "
                        f"{settings.max_tokens_per_run:,}. Further stages run without a "
                        f"language model rather than continuing to spend.",
                        metadata={"tokens_used": spent},
                    )

        # --- upstream dependency check ---
        # A FAILED stage must stop the pipeline, and it must keep stopping it across
        # resumes. Raising from the failing node halts the current invocation, but the
        # next resume walks the same linear chain again, and an operator "skip stage"
        # rewrites a failure as a SKIPPED checkpoint. Either way a later stage can find
        # itself running on output that was never produced. The check belongs here, where
        # every stage passes through, rather than in each node.
        blocker = await self._blocking_upstream(run_id)
        if blocker is not None:
            upstream, status = blocker
            message = (
                f"Cannot run {self.stage}: the {upstream} stage it depends on is "
                f"{status}, so its output does not exist. Fix or retry {upstream} "
                f"first — running {self.stage} now would build on nothing."
            )
            logger.error("%s (run %s)", message, run_id)
            async with session_scope() as session:
                await append_decision(
                    session, run_id, self.stage, "BLOCKED_UPSTREAM", message,
                    metadata={"upstream_stage": upstream, "upstream_status": status},
                )
                await set_run_status(
                    session, run_id, RunStatus.FAILED, error_message=message
                )
            state["error"] = message
            state["failed_stage"] = upstream
            raise RuntimeError(message)

        # --- resume check and claim, atomically ---
        # One locked transaction does both: "has this finished?" and "I am running it
        # now". Splitting them let two workers on the same run both pass the check and
        # duplicate the stage, paying twice for the same LLM and SuperDocs calls.
        async with session_scope() as session:
            done, cached, attempt_no = await claim_stage(
                session, run_id, self.stage, self.running_status
            )
        if done:
            # Idempotency: return the cached result and make no LLM or API calls at all.
            logger.info("Stage %s already complete for run %s — skipping", self.stage, run_id)
            state.update(cached.get("state_delta", {}))
            return state

        started_at = utcnow()
        attempts = settings.node_max_retries
        last_error: Exception | None = None

        for attempt in range(attempt_no, attempt_no + attempts):
            try:
                # Snapshot BEFORE running. Nodes mutate state in place and return the
                # same object, so diffing the returned value against `state` would
                # compare the dict to itself and always yield an empty delta — silently
                # checkpointing nothing and breaking resume.
                before = dict(state)
                new_state = await self.run(state, run_id)
                completed_at = utcnow()

                # A prior non-fatal stage may have left an error on the state. Once a
                # later stage succeeds that error is stale, and leaving it there makes a
                # recovered run report as failed to the API and the UI.
                if new_state.get("error") and new_state.get("failed_stage") != self.stage:
                    new_state["error"] = None
                    new_state["failed_stage"] = None

                async with session_scope() as session:
                    await save_checkpoint(
                        session,
                        run_id,
                        self.stage,
                        {"state_delta": self._delta(before, new_state)},
                    )
                    await record_stage_cost(
                        session,
                        run_id,
                        self.stage,
                        started_at=started_at,
                        completed_at=completed_at,
                        groq_usage=self.usage.to_dict(),
                        superdocs_operations=self.superdocs_operations,
                    )
                # Write-behind mirror. Runs after the authoritative commit and never
                # raises, so a mirror problem cannot undo real progress.
                await mirror_checkpoint(
                    run_id, self.stage, "COMPLETE",
                    {"state_delta": self._delta(before, new_state)},
                    attempts=attempt,
                )
                return new_state

            except NodeCancelled:
                # Not an error and not retryable. Leave the status as CANCELLED and stop.
                async with session_scope() as session:
                    await append_decision(
                        session, run_id, self.stage, "CANCELLED",
                        "Run cancelled by operator before this stage ran",
                    )
                raise

            except NodeSkip as skip:
                completed_at = utcnow()
                async with session_scope() as session:
                    await save_checkpoint(
                        session,
                        run_id,
                        self.stage,
                        {"state_delta": skip.result, "skip_reason": skip.reason},
                        status=STAGE_SKIPPED,
                    )
                    await append_decision(
                        session, run_id, self.stage, "SKIPPED", skip.reason
                    )
                    await record_stage_cost(
                        session,
                        run_id,
                        self.stage,
                        started_at=started_at,
                        completed_at=completed_at,
                        groq_usage=self.usage.to_dict(),
                        superdocs_operations=self.superdocs_operations,
                        notes=f"skipped: {skip.reason}",
                    )
                state.update(skip.result)
                return state

            except NodePause as pause:
                # Not an error. Persist progress and hand control back to a human or
                # operator; the run resumes from exactly here.
                async with session_scope() as session:
                    await append_decision(
                        session, run_id, self.stage, "PAUSED", pause.reason
                    )
                    await set_run_status(session, run_id, pause.status)
                    await record_stage_cost(
                        session,
                        run_id,
                        self.stage,
                        started_at=started_at,
                        completed_at=utcnow(),
                        groq_usage=self.usage.to_dict(),
                        superdocs_operations=self.superdocs_operations,
                        notes=f"paused: {pause.reason}",
                    )
                state["paused_reason"] = pause.reason
                raise

            except NodeInputMissing as exc:
                # Not retryable: an input that does not exist will not exist on a second
                # attempt. Fail immediately, with the reason the input was missing rather
                # than a generic "failed after 3 attempts".
                last_error = exc
                logger.error("Stage %s has no usable input: %s", self.stage, exc.reason)
                break

            except MissingCredentialError as exc:
                # Retrying a missing key is pointless — it will not appear between
                # attempts — and failing the run would discard completed stages. Pause
                # immediately with a message naming the variable to set.
                async with session_scope() as session:
                    await append_decision(
                        session, run_id, self.stage, "PAUSED_MISSING_CREDENTIAL", str(exc)
                    )
                    await set_run_status(
                        session, run_id, RunStatus.PAUSED, error_message=str(exc)
                    )
                raise NodePause(str(exc)) from exc

            except GroqUnavailable as exc:
                # Graceful degradation: an LLM outage pauses the run with a clear reason
                # rather than crashing it, so no completed work is thrown away.
                last_error = exc
                logger.warning("Groq unavailable in %s: %s", self.stage, exc)
                if attempt >= attempt_no + attempts - 1:
                    async with session_scope() as session:
                        await append_decision(
                            session,
                            run_id,
                            self.stage,
                            "PAUSED",
                            f"Groq unavailable after {attempts} attempts: {exc}",
                        )
                        await set_run_status(
                            session, run_id, RunStatus.PAUSED, error_message=str(exc)
                        )
                    raise NodePause(f"Groq unavailable: {exc}") from exc
                await self._backoff(attempt - attempt_no + 1)

            except Exception as exc:  # noqa: BLE001 - deliberate boundary
                last_error = exc
                logger.exception("Stage %s attempt %d failed", self.stage, attempt)
                if attempt >= attempt_no + attempts - 1:
                    break
                await self._backoff(attempt - attempt_no + 1)

        # Retries exhausted, or an unretryable failure broke out of the loop.
        if isinstance(last_error, NodeInputMissing):
            message = f"{self.stage} cannot run: {last_error.reason}"
        else:
            message = f"{self.stage} failed after {attempts} attempts: {last_error}"
        async with session_scope() as session:
            await save_checkpoint(
                session,
                run_id,
                self.stage,
                {},
                status=STAGE_FAILED,
                error=str(last_error),
            )
            await append_decision(
                session, run_id, self.stage, "FAILED", str(last_error)
            )
            if self.fatal_on_error:
                await set_run_status(
                    session, run_id, RunStatus.FAILED, error_message=message
                )

        state["error"] = message
        state["failed_stage"] = self.stage
        if self.fatal_on_error:
            raise RuntimeError(message) from last_error
        return state

    async def _blocking_upstream(
        self, run_id: uuid.UUID
    ) -> tuple[str, str] | None:
        """The first required upstream stage that has no usable output, if any.

        Returns (stage, status). A required stage that has not run at all is not a
        blocker: on a fresh run every stage is unrun when its successor is checked, and
        the graph's own ordering guarantees it runs first.
        """
        if not self.requires:
            return None
        async with session_scope() as session:
            run = await session.get(Run, run_id)
            stages = ((run.checkpoint_data or {}) if run else {}).get("stages") or {}
        for upstream in self.requires:
            record = stages.get(upstream)
            if not record:
                continue
            status = str(record.get("status") or "")
            if status in {STAGE_FAILED, STAGE_SKIPPED}:
                return upstream, status
        return None

    @staticmethod
    def _delta(before: DigestState, after: DigestState) -> dict[str, Any]:
        """Only the keys this node changed, so the checkpoint stays small."""
        return {k: v for k, v in after.items() if before.get(k) != v}

    @staticmethod
    async def _backoff(attempt: int) -> None:
        delay = min(settings.node_retry_base_delay_s * (2 ** (attempt - 1)), 30.0)
        await asyncio.sleep(delay + random.uniform(0, delay * 0.25))

    async def log_decision(
        self,
        run_id: uuid.UUID,
        decision: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a branching choice for the run timeline."""
        async with session_scope() as session:
            await append_decision(
                session, run_id, self.stage, decision, reason, metadata=metadata
            )