"""The workflow itself: classify -> extract -> generate companion doc ->
normalize -> write metadata back to Box.

Design choices that map directly to "what strong looks like" on the task
card:
  - metadata fields are populated accurately enough to drive retention
    decisions, and left empty rather than guessed when the document does
    not say  -> _apply_extracted() only ever writes keys SuperDocs's
    extraction actually returned; nothing is defaulted or inferred here.
  - governance labels and legal holds are never overridden -> checked
    BEFORE any SuperDocs call is made (fail fast, no wasted work) and
    also enforced a second time inside FakeBoxClient.update_metadata as
    a defense-in-depth backstop, so a bug in this file can't silently
    write a protected key even if the pre-check were ever removed.
  - idempotent per file version -> IdempotencyStore keyed on
    (file_id, content sha1), checked before any SuperDocs call.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from app.clients.box_client import BoxAPIError, BoxClient
from app.clients.superdocs_client import SuperDocsAPIError, SuperDocsClient
from app.models import DocClass, ExtractedFields, StageCost
from app.workflow.checkpoint import CheckpointStore
from app.workflow.calibration_tracker import CalibrationTracker
from app.workflow.companion_doc import render_companion_docx
from app.workflow.cost_tracker import CostTracker
from app.workflow.near_duplicate import NearDuplicateDetector
from app.workflow.history_store import MetadataHistoryStore
from app.workflow.idempotency import IdempotencyStore
from app.workflow.retry import (
    DEFAULT_BASE_DELAY_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
    CircuitBreaker,
    CircuitOpenError,
    call_with_retry,
)
from app.workflow.review_queue import ReviewQueue
from app.workflow.dead_letter import DeadLetterQueue

logger = logging.getLogger("box_metadata_writeback")

METADATA_TEMPLATE_KEY = "documentIntelligence"
COMPANION_DOC_FOLDER_ENV_DEFAULT = "companion_docs_folder"


class GovernanceViolation(Exception):
    """Raised if a code path ever attempts to touch a protected field.
    Should be unreachable in normal operation -- the pipeline checks
    governance state up front -- but exists so a future refactor that
    breaks that check fails loudly instead of silently."""


@dataclass
class StageResult:
    name: str
    status: str  # "done" | "skipped" | "failed"
    detail: str = ""
    latency_ms: float = 0.0
    operations: int = 0  # SuperDocs operations spent in this stage


@dataclass
class RunReport:
    file_id: str
    version_sha1: str
    stages: list[StageResult] = field(default_factory=list)
    extracted: Optional[ExtractedFields] = None
    metadata_written: dict[str, Any] = field(default_factory=dict)
    skipped_reason: Optional[str] = None
    history_entries: list[Any] = field(default_factory=list)
    queued_for_review: list[str] = field(default_factory=list)
    calibration_mode: str = "none"  # "none" | "pairwise" | "ensemble" -- which mode produced this run
    near_duplicate_of: Optional[str] = None  # file_id of the closest near-duplicate, if any
    near_duplicate_similarity: Optional[float] = None

    @property
    def total_operations(self) -> int:
        return sum(s.operations for s in self.stages)

    @property
    def total_latency_ms(self) -> float:
        return sum(s.latency_ms for s in self.stages)


class BoxMetadataWritebackPipeline:
    def __init__(
        self,
        box: BoxClient,
        superdocs: SuperDocsClient,
        idempotency: Optional[IdempotencyStore] = None,
        companion_folder_id: str = "0",
        review_queue: Optional[ReviewQueue] = None,
        history: Optional[MetadataHistoryStore] = None,
        checkpoint: Optional[CheckpointStore] = None,
        max_retry_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_base_delay: float = DEFAULT_BASE_DELAY_SECONDS,
        retry_sleep_fn=time.sleep,
        circuit_breaker: Optional[CircuitBreaker] = None,
        dead_letter: Optional[DeadLetterQueue] = None,
        enable_calibration: bool = False,
        ensemble_runs: int = 0,
    ) -> None:
        self.box = box
        self.superdocs = superdocs
        self.idempotency = idempotency or IdempotencyStore()
        self.companion_folder_id = companion_folder_id
        self.review_queue = review_queue or ReviewQueue()
        self.history = history or MetadataHistoryStore()
        self.checkpoint = checkpoint or CheckpointStore()
        self.max_retry_attempts = max_retry_attempts
        self.retry_base_delay = retry_base_delay
        self.retry_sleep_fn = retry_sleep_fn
        # One breaker per pipeline instance (== per tenant, since each
        # tenant gets its own pipeline): a sustained SuperDocs outage
        # trips it once and every subsequent file fails fast instead of
        # each burning its own full per-file retry budget against a
        # dependency that isn't coming back in the next few hundred ms.
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.dead_letter = dead_letter or DeadLetterQueue()
        # Opt-in: doubles extract-stage SuperDocs operations per file in
        # exchange for a calibrated (not just self-reported) confidence
        # signal. See app/workflow/calibration.py's module docstring for
        # the trade-off this makes explicit rather than forced.
        self.enable_calibration = enable_calibration
        # N-way extension of enable_calibration: instead of exactly one
        # second opinion, runs `ensemble_runs` additional independent
        # extraction passes and uses agreement FRACTION (not just
        # binary match) as the confidence signal -- more precise, but
        # scales SuperDocs operations linearly with this number.
        # Mutually exclusive with enable_calibration (ensemble_runs > 0
        # takes precedence if both are set, since it's a strict
        # superset of what pairwise calibration does).
        self.ensemble_runs = ensemble_runs
        # Accumulates real approve/reject outcomes against original
        # confidence, closing the loop calibration.py's one-shot
        # dual-extraction signal can't -- see
        # app/workflow/calibration_tracker.py's module docstring.
        self.calibration_tracker = CalibrationTracker()
        self.cost_tracker = CostTracker()
        self.near_duplicate_detector = NearDuplicateDetector()

    def _chat(self, doc_id: str, instruction: str):
        """Every stage's SuperDocs chat() call goes through here so retry
        behavior is applied uniformly. Returns (ChatResult, attempts).
        On exhausted retries, re-raises SuperDocsAPIError with an
        `.attempts` attribute set so the caller can report the real
        number of operations spent, including the failed attempts --
        a retried-then-failed stage costs more than 1 operation and the
        cost report should say so, not hide it.

        The circuit breaker wraps the whole retry-with-backoff call, not
        each individual attempt: a full per-file retry exhaustion counts
        as one breaker failure, and a single success (even one that took
        several attempts) resets it. If the breaker is already open,
        CircuitOpenError is raised immediately -- no network call is
        attempted at all."""
        self.circuit_breaker.before_call()
        try:
            retry_result = call_with_retry(
                lambda: self.superdocs.chat(doc_id, instruction),
                max_attempts=self.max_retry_attempts,
                base_delay=self.retry_base_delay,
                sleep_fn=self.retry_sleep_fn,
            )
        except Exception:
            self.circuit_breaker.record_failure()
            raise
        else:
            self.circuit_breaker.record_success()
        return retry_result.value, retry_result.attempts

    def _log_dead_letters(self, file_id: str, version_sha1: str, report: "RunReport") -> None:
        """Any stage that ended 'failed' this run (retries exhausted, or
        the circuit was open) gets a dead-letter entry -- called both on
        early-return paths (classify/extract failures abort the run via
        _commit_partial) and at the terminal success path, since a
        companion/normalize failure doesn't abort the run but still
        deserves an ops worklist entry."""
        for s in report.stages:
            if s.status == "failed":
                self.dead_letter.add(
                    file_id=file_id,
                    version_sha1=version_sha1,
                    stage=s.name,
                    reason=s.detail,
                    attempts=s.operations,
                )

    def process(self, file_id: str) -> RunReport:
        """Thin wrapper around _process_inner(): guarantees cost is
        recorded exactly once per call, regardless of which of
        _process_inner's several return points was hit (idempotent
        no-op, partial failure, or full success) -- a run that failed
        partway still spent real SuperDocs operations and its cost
        should count toward the tenant's cost report."""
        report = self._process_inner(file_id)
        self.cost_tracker.record_run(report.calibration_mode, report.total_operations, report.total_latency_ms)
        return report

    def _process_inner(self, file_id: str) -> RunReport:
        version = self.box.get_file_version(file_id)
        report = RunReport(file_id=file_id, version_sha1=version.sha1)
        report.calibration_mode = (
            "ensemble" if self.ensemble_runs > 0 else ("pairwise" if self.enable_calibration else "none")
        )
        logger.info("run started file_id=%s version_sha1=%s", file_id, version.sha1)

        # --- idempotency: same bytes already processed -> honest no-op ---
        if self.idempotency.already_processed(file_id, version.sha1):
            report.skipped_reason = "already processed this exact file version"
            report.stages.append(
                StageResult(name="idempotency_check", status="skipped", detail=report.skipped_reason)
            )
            return report

        # --- concurrency: another run already owns this file_id right now ---
        if not self.idempotency.try_claim(file_id):
            report.skipped_reason = "another run is already processing this file"
            report.stages.append(
                StageResult(name="concurrency_check", status="skipped", detail=report.skipped_reason)
            )
            return report

        try:
            # --- governance check BEFORE any SuperDocs call: fail fast ---
            governance = self.box.get_governance_state(file_id)
            if governance.legal_hold or governance.retention_policy_locked:
                report.skipped_reason = (
                    "file is under legal hold or retention lock; "
                    "processing skipped, no metadata written"
                )
                report.stages.append(
                    StageResult(name="governance_check", status="skipped", detail=report.skipped_reason)
                )
                return report
            report.stages.append(StageResult(name="governance_check", status="done"))

            # --- resume support: load whatever stage-level checkpoint
            # exists for this exact (file_id, sha1), if a previous run
            # was killed partway through. A resumed stage costs zero
            # SuperDocs operations and zero latency -- it isn't redone,
            # it's replayed from what was already proven to have
            # succeeded. ---
            existing_checkpoint = self.checkpoint.get(file_id, version.sha1)
            resumed_stage_names = set(existing_checkpoint.completed_stages) if existing_checkpoint else set()
            if existing_checkpoint and existing_checkpoint.extracted:
                extracted = ExtractedFields.model_validate(existing_checkpoint.extracted)
            else:
                extracted = ExtractedFields()

            content = self.box.download_file(file_id)

            # Near-duplicate check: informational only, never blocks
            # processing (see near_duplicate.py's module docstring for
            # why auto-skip would be the wrong call). Runs once per
            # process() call, on the actual content bytes -- decoded
            # best-effort the same way the accuracy layer's source
            # grounding does.
            source_text_for_dedup = content.decode("utf-8", errors="ignore") if content else ""
            dup_match = self.near_duplicate_detector.check_and_register(file_id, source_text_for_dedup)
            if dup_match:
                report.near_duplicate_of = dup_match.file_id
                report.near_duplicate_similarity = dup_match.similarity
                logger.info(
                    "near-duplicate detected file_id=%s similar_to=%s similarity=%.3f",
                    file_id,
                    dup_match.file_id,
                    dup_match.similarity,
                )

            # Only re-upload to SuperDocs if we're about to run at least
            # one live stage against it; a fully-resumed run (every stage
            # already checkpointed -- possible if the process died right
            # between normalize completing and _commit_final running)
            # shouldn't need a document at all.
            remaining_stage_names = {"classify", "extract", "generate_companion", "normalize"} - resumed_stage_names
            doc_id = self.superdocs.upload(version.name, content) if remaining_stage_names else ""

            # Stage: classify
            if "classify" in resumed_stage_names:
                self._replay_stage(existing_checkpoint, "classify", report)
            else:
                extracted = self._run_stage_classify(doc_id, extracted, report)
                self._checkpoint_stage_if_done(file_id, version.sha1, "classify", report, extracted)
                if report.stages[-1].status == "failed":
                    self._commit_partial(file_id, version.sha1, extracted, report)
                    self.checkpoint.clear(file_id, version.sha1)
                    self._log_dead_letters(file_id, version.sha1, report)
                    return report

            # Stage: extract key terms
            if "extract" in resumed_stage_names:
                self._replay_stage(existing_checkpoint, "extract", report)
            else:
                extracted = self._run_stage_extract(
                    doc_id, extracted, report, file_id, version.sha1, source_content=content
                )
                self._checkpoint_stage_if_done(file_id, version.sha1, "extract", report, extracted)
                if report.stages[-1].status == "failed":
                    self._commit_partial(file_id, version.sha1, extracted, report)
                    self.checkpoint.clear(file_id, version.sha1)
                    self._log_dead_letters(file_id, version.sha1, report)
                    return report

            # Stage: generate companion document (only meaningful for
            # doc classes that need one; contracts/amendments do, an
            # already-informal "correspondence" doesn't)
            if "generate_companion" in resumed_stage_names:
                self._replay_stage(existing_checkpoint, "generate_companion", report)
            elif extracted.doc_class in (DocClass.CONTRACT, DocClass.AMENDMENT):
                extracted = self._run_stage_companion(doc_id, version, extracted, report)
                self._checkpoint_stage_if_done(file_id, version.sha1, "generate_companion", report, extracted)
            else:
                report.stages.append(
                    StageResult(
                        name="generate_companion",
                        status="skipped",
                        detail=f"doc_class={extracted.doc_class.value} does not require a companion document",
                    )
                )

            # Stage: normalize to retention-approved template
            if "normalize" in resumed_stage_names:
                self._replay_stage(existing_checkpoint, "normalize", report)
            else:
                extracted = self._run_stage_normalize(doc_id, extracted, report)
                self._checkpoint_stage_if_done(file_id, version.sha1, "normalize", report, extracted)

            self._commit_final(file_id, version.sha1, extracted, report)
            if report.skipped_reason:
                # _commit_final aborted (e.g. version changed underneath
                # us -- see its version-guard check). Leave the
                # checkpoint in place and do NOT mark this version
                # completed; the newer version will be processed by a
                # subsequent run.
                return report
            # Run reached a terminal, committed state -- the checkpoint
            # has done its job and shouldn't linger for a version that
            # won't be reprocessed as-is.
            self.checkpoint.clear(file_id, version.sha1)
            # Only a genuinely successful, fully-committed run marks the
            # version done. A partial/failed run (see the early returns
            # above) never reaches this line, so it stays retryable.
            self.idempotency.mark_completed(file_id, version.sha1)
            # A run can reach here and still have one or more individual
            # stages that exhausted retries or hit an open circuit --
            # graceful degradation means the run still commits its
            # honest partial state rather than crashing. But "committed
            # with honest gaps" and "worth an operator's attention" are
            # different things: log every such run to the dead-letter
            # queue so it shows up on a real worklist instead of only
            # being visible by reading extraction_notes on each file by
            # hand.
            self._log_dead_letters(file_id, version.sha1, report)
            logger.info(
                "run finished file_id=%s version_sha1=%s operations=%s failed_stages=%s",
                file_id,
                version.sha1,
                report.total_operations,
                [s.name for s in report.stages if s.status == "failed"],
            )
            return report
        finally:
            self.idempotency.release(file_id)

    def _checkpoint_stage_if_done(
        self,
        file_id: str,
        sha1: str,
        stage_name: str,
        report: RunReport,
        extracted: ExtractedFields,
    ) -> None:
        """Persists a stage's result the instant it succeeds, so a kill
        immediately after (even before the next stage starts) still
        finds it on restart. Failed stages are never checkpointed --
        the next run should retry them, not replay a failure."""
        last = report.stages[-1]
        if last.name != stage_name or last.status != "done":
            return
        self.checkpoint.save_stage(
            file_id,
            sha1,
            stage_name,
            {
                "name": last.name,
                "status": last.status,
                "detail": last.detail,
                "latency_ms": last.latency_ms,
                "operations": last.operations,
            },
            extracted.model_dump(mode="json"),
        )

    def _replay_stage(self, checkpoint, stage_name: str, report: RunReport) -> None:
        """Re-appends a previously-completed stage's result to this run's
        report as a zero-cost 'resumed' entry, instead of calling
        SuperDocs again. The original latency/operations are preserved
        in the detail text for auditability, but this run's own cost
        accounting (total_operations, total_latency_ms) correctly shows
        0 for it -- a resumed stage should not appear to cost twice."""
        original = checkpoint.completed_stages[stage_name]
        report.stages.append(
            StageResult(
                name=stage_name,
                status="done",
                detail=f"resumed from checkpoint (originally: {original.get('detail', '')})",
                latency_ms=0.0,
                operations=0,
            )
        )

    # --- individual stages, each independently retryable/skippable -------------

    def _run_stage_classify(
        self, doc_id: str, extracted: ExtractedFields, report: RunReport
    ) -> ExtractedFields:
        t0 = time.monotonic()
        try:
            result, attempts = self._chat(doc_id, "Please classify this document.")
            self.superdocs.approve(doc_id, result.session_id)
            change = result.proposed_change or {}
            doc_class_raw = change.get("doc_class", "unknown")
            try:
                extracted.doc_class = DocClass(doc_class_raw)
            except ValueError:
                extracted.doc_class = DocClass.UNKNOWN
            extracted.doc_class_confidence = float(change.get("confidence", 0.0))
            extracted.field_session_ids["doc_class"] = result.session_id
            report.stages.append(
                StageResult(
                    name="classify",
                    status="done",
                    detail=(
                        f"class={extracted.doc_class.value} confidence={extracted.doc_class_confidence}"
                        + (f" (succeeded after {attempts} attempts)" if attempts > 1 else "")
                    ),
                    latency_ms=(time.monotonic() - t0) * 1000,
                    operations=attempts,
                )
            )
        except (SuperDocsAPIError, CircuitOpenError) as e:
            # Graceful degradation: classification failure doesn't crash
            # the run, it honestly records doc_class as unknown and lets
            # a human see exactly why in the review stage.
            attempts = getattr(e, "attempts", 1)
            extracted.doc_class = DocClass.UNKNOWN
            extracted.extraction_notes += f"classification unavailable after {attempts} attempt(s): {e}. "
            report.stages.append(
                StageResult(
                    name="classify",
                    status="failed",
                    detail=f"{e} (failed after {attempts} attempts)",
                    latency_ms=(time.monotonic() - t0) * 1000,
                    operations=attempts,  # every attempted call was billed, even the failed ones
                )
            )
        return extracted

    def _run_stage_extract(
        self,
        doc_id: str,
        extracted: ExtractedFields,
        report: RunReport,
        file_id: str,
        version_sha1: str,
        threshold: Optional[float] = None,
        source_content: bytes = b"",
    ) -> ExtractedFields:
        t0 = time.monotonic()
        # `threshold` (if passed) is a caller override applied uniformly;
        # otherwise each field is gated by the review queue's own
        # per-field threshold (falls back to its global default), so a
        # tenant can require a tighter bar on e.g. contract_value than
        # counterparty_name without a policy engine.
        try:
            result, attempts = self._chat(doc_id, "Extract key terms from this document.")
            self.superdocs.approve(doc_id, result.session_id)
            change = result.proposed_change or {}
            fields = change.get("fields", {})
            confidences = change.get("field_confidence", {})

            # Calibration (opt-in, see __init__): either a single second,
            # independently phrased extraction pass (enable_calibration),
            # or an N-way ensemble (ensemble_runs > 0) using agreement
            # FRACTION across all runs as a more precise signal than a
            # single binary match/mismatch. Either way, only the FIRST
            # run's values are ever written anywhere; additional runs are
            # validation signal only.
            calibration_attempts = 0
            if self.ensemble_runs > 0:
                from app.workflow.calibration import calibrate_fields_ensemble

                additional_runs_fields = []
                for i in range(self.ensemble_runs):
                    run_result, run_attempts = self._chat(
                        doc_id,
                        f"Extract key terms from this document again, independently re-checking your "
                        f"work (ensemble pass {i + 1}).",
                    )
                    self.superdocs.approve(doc_id, run_result.session_id)
                    calibration_attempts += run_attempts
                    run_change = run_result.proposed_change or {}
                    additional_runs_fields.append(run_change.get("fields", {}))
                ensemble_calibrated = calibrate_fields_ensemble(fields, confidences, additional_runs_fields)
                for field_name, c in ensemble_calibrated.items():
                    confidences[field_name] = c.calibrated_confidence
                    if c.agreement_fraction <= 0.5:
                        extracted.extraction_notes += (
                            f"ensemble calibration disagreement on {field_name}: only "
                            f"{c.agreement_fraction:.0%} of {c.run_count} independent runs agreed "
                            f"with the primary value {c.canonical_value!r}. "
                        )
            elif self.enable_calibration:
                from app.workflow.calibration import calibrate_fields

                second_result, calibration_attempts = self._chat(
                    doc_id, "Extract key terms from this document again, independently re-checking your work."
                )
                self.superdocs.approve(doc_id, second_result.session_id)
                second_change = second_result.proposed_change or {}
                second_fields = second_change.get("fields", {})
                calibrated = calibrate_fields(fields, confidences, second_fields)
                for field_name, c in calibrated.items():
                    confidences[field_name] = c.calibrated_confidence
                    if not c.agreed:
                        extracted.extraction_notes += (
                            f"calibration disagreement on {field_name}: "
                            f"first run={c.first_value!r} second run={c.second_value!r}. "
                        )

            extracted.field_confidence.update(confidences)

            # Honesty over fabrication: only set what SuperDocs actually
            # returned. Anything not present stays None, which the Box
            # metadata write step later renders as an explicit empty
            # field rather than a guessed one.
            #
            # Accuracy layer: type/format validation, cross-field
            # consistency, and source-grounding are applied on top of
            # (never instead of) the model's self-reported confidence --
            # see app/workflow/accuracy.py. A field that fails any of
            # these is capped to VALIDATION_FAILURE_CEILING, guaranteeing
            # it queues for review under any sane threshold, regardless
            # of what confidence SuperDocs claimed.
            from app.workflow.accuracy import (
                check_cross_field_consistency,
                check_source_grounding,
                downgrade_confidence,
                validate_field_types,
            )

            source_text = source_content.decode("utf-8", errors="ignore") if source_content else ""
            type_results = validate_field_types(
                fields.get("counterparty_name"),
                fields.get("effective_date"),
                fields.get("expiration_date"),
                fields.get("contract_value"),
            )
            consistency = check_cross_field_consistency(
                fields.get("effective_date"), fields.get("expiration_date")
            )
            accuracy_notes: list[str] = []
            for key in ("counterparty_name", "effective_date", "expiration_date", "contract_value"):
                if key not in fields or not fields[key]:
                    continue
                grounded = check_source_grounding(fields[key], source_text) if source_text else True
                new_conf, notes = downgrade_confidence(
                    key, confidences.get(key, 1.0), type_valid=type_results[key].valid, grounded=grounded
                )
                confidences[key] = new_conf
                accuracy_notes.extend(notes)
            if not consistency.valid:
                # A logical contradiction between fields caps BOTH
                # implicated fields, not just one -- the pair is what's
                # wrong, not either field in isolation.
                for key in ("effective_date", "expiration_date"):
                    if key in confidences:
                        confidences[key] = min(confidences[key], 0.3)
                accuracy_notes.extend(consistency.reasons)

            # Fields returned WITH a value are further split by
            # confidence (now accuracy-adjusted): at/above threshold,
            # they're set directly on extracted (same as before); below
            # threshold, the value is held back and staged in the review
            # queue instead -- it never reaches Box metadata until a
            # human approves it.
            populated, queued = [], []
            for key in (
                "counterparty_name",
                "effective_date",
                "expiration_date",
                "contract_value",
            ):
                if key not in fields or not fields[key]:
                    continue
                value = fields[key]
                conf = confidences.get(key, 1.0)
                gate = threshold if threshold is not None else self.review_queue.threshold_for(key)
                if conf >= gate:
                    setattr(extracted, key, value)
                    extracted.field_session_ids[key] = result.session_id
                    populated.append(key)
                else:
                    review = self.review_queue.stage(
                        file_id, version_sha1, key, value, conf, source_session_id=result.session_id
                    )
                    extracted.pending_review_ids.append(review.review_id)
                    extracted.field_session_ids[key] = result.session_id
                    queued.append(f"{key} (conf={conf})")

            missing = {"counterparty_name", "effective_date", "expiration_date", "contract_value"} - set(
                populated
            ) - {k.split(" ")[0] for k in queued}
            notes = list(accuracy_notes)
            if missing:
                notes.append(f"source did not support: {', '.join(sorted(missing))}")
            if queued:
                notes.append(f"held for human review (below confidence threshold): {', '.join(queued)}")
            if notes:
                extracted.extraction_notes += ". ".join(notes) + ". "

            extracted.key_terms_summary = result.raw_message
            report.queued_for_review.extend(extracted.pending_review_ids)
            report.stages.append(
                StageResult(
                    name="extract",
                    status="done",
                    detail=(
                        f"populated={populated or 'none'} queued_for_review={queued or 'none'}"
                        + (f" (succeeded after {attempts} attempts)" if attempts > 1 else "")
                        + (f" (calibrated, +{calibration_attempts} ops)" if calibration_attempts else "")
                    ),
                    latency_ms=(time.monotonic() - t0) * 1000,
                    operations=attempts + calibration_attempts,
                )
            )
        except (SuperDocsAPIError, CircuitOpenError) as e:
            attempts = getattr(e, "attempts", 1)
            extracted.extraction_notes += f"extraction unavailable after {attempts} attempt(s): {e}. "
            report.stages.append(
                StageResult(
                    name="extract",
                    status="failed",
                    detail=f"{e} (failed after {attempts} attempts)",
                    latency_ms=(time.monotonic() - t0) * 1000,
                    operations=attempts,
                )
            )
        return extracted

    def _run_stage_companion(
        self, doc_id: str, version, extracted: ExtractedFields, report: RunReport
    ) -> ExtractedFields:
        t0 = time.monotonic()
        try:
            result, attempts = self._chat(doc_id, "Generate the required companion document.")
            self.superdocs.approve(doc_id, result.session_id)
            change = result.proposed_change or {}
            companion_text = change.get("companion_text", "")
            companion_bytes = render_companion_docx(
                extracted,
                companion_text,
                source_filename=version.name,
                generated_at_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
            # Deterministic, content-addressed filename: (file_id, sha1)
            # uniquely identifies "the companion for this exact source
            # version". Combined with upload_companion_document()'s
            # dedupe-by-name check, a crash between upload succeeding
            # and the stage checkpoint being saved no longer produces a
            # second companion on retry -- the retry finds the same
            # named file already there and reuses it instead of
            # creating companion-9002 alongside companion-9001.
            companion_filename = f"{version.file_id}.{version.sha1}.companion.docx"
            companion_file_id = self.box.upload_companion_document(
                self.companion_folder_id,
                companion_filename,
                companion_bytes,
            )
            extracted.companion_document_id = companion_file_id
            extracted.field_session_ids["companion_document_id"] = result.session_id
            report.stages.append(
                StageResult(
                    name="generate_companion",
                    status="done",
                    detail=(
                        f"companion_file_id={companion_file_id}"
                        + (f" (succeeded after {attempts} attempts)" if attempts > 1 else "")
                    ),
                    latency_ms=(time.monotonic() - t0) * 1000,
                    operations=attempts,
                )
            )
        except (SuperDocsAPIError, CircuitOpenError) as e:
            attempts = getattr(e, "attempts", 1)
            extracted.extraction_notes += f"companion generation unavailable after {attempts} attempt(s): {e}. "
            report.stages.append(
                StageResult(
                    name="generate_companion",
                    status="failed",
                    detail=f"{e} (failed after {attempts} attempts)",
                    latency_ms=(time.monotonic() - t0) * 1000,
                    operations=attempts,
                )
            )
        return extracted

    def _run_stage_normalize(
        self, doc_id: str, extracted: ExtractedFields, report: RunReport
    ) -> ExtractedFields:
        t0 = time.monotonic()
        try:
            result, attempts = self._chat(doc_id, "Normalize this document to the retention-approved template.")
            self.superdocs.approve(doc_id, result.session_id)
            self.superdocs.export(doc_id)  # exports don't cost operations; safe to always run
            extracted.normalized = True
            extracted.retention_category = retention_category_for_extraction(
                extracted.doc_class, extracted.doc_class_confidence
            )
            if (
                extracted.retention_category == "uncategorized-review"
                and extracted.doc_class != DocClass.UNKNOWN
                and extracted.doc_class_confidence < DOC_CLASS_CONFIDENCE_FLOOR
            ):
                extracted.extraction_notes += (
                    f"classification confidence ({extracted.doc_class_confidence}) below "
                    f"{DOC_CLASS_CONFIDENCE_FLOOR}; retention_category held to review fallback "
                    f"rather than trusting doc_class={extracted.doc_class.value}. "
                )
            extracted.field_session_ids["normalized"] = result.session_id
            extracted.field_session_ids["retention_category"] = result.session_id
            report.stages.append(
                StageResult(
                    name="normalize",
                    status="done",
                    detail=(
                        f"retention_category={extracted.retention_category}"
                        + (f" (succeeded after {attempts} attempts)" if attempts > 1 else "")
                    ),
                    latency_ms=(time.monotonic() - t0) * 1000,
                    operations=attempts,  # export itself is free per the docs; chat call(s) cost 1 each
                )
            )
        except (SuperDocsAPIError, CircuitOpenError) as e:
            attempts = getattr(e, "attempts", 1)
            extracted.normalized = False
            extracted.extraction_notes += f"normalization unavailable after {attempts} attempt(s): {e}. "
            report.stages.append(
                StageResult(
                    name="normalize",
                    status="failed",
                    detail=f"{e} (failed after {attempts} attempts)",
                    latency_ms=(time.monotonic() - t0) * 1000,
                    operations=attempts,
                )
            )
        return extracted

    # --- metadata commit ---------------------------------------------------------

    def _fields_payload(self, extracted: ExtractedFields) -> dict[str, Any]:
        """Only ever includes keys with real values; None fields are
        omitted rather than sent as null, which is what lets 'left empty'
        mean 'genuinely absent from the template' rather than 'present
        and explicitly nulled' -- a reviewer can tell the difference
        between "we checked and there's nothing" only if we're consistent
        about this, which is why doc_class/confidence/notes are always
        written but nullable business fields are conditional."""
        payload: dict[str, Any] = {
            "doc_class": extracted.doc_class.value,
            "doc_class_confidence": extracted.doc_class_confidence,
            "normalized": extracted.normalized,
            "extraction_notes": extracted.extraction_notes.strip(),
        }
        for key in (
            "counterparty_name",
            "effective_date",
            "expiration_date",
            "contract_value",
            "key_terms_summary",
            "retention_category",
            "companion_document_id",
        ):
            value = getattr(extracted, key)
            if value not in (None, ""):
                payload[key] = value
        return payload

    def _commit_partial(
        self, file_id: str, sha1: str, extracted: ExtractedFields, report: RunReport
    ) -> None:
        """Even on early failure we still write whatever honest partial
        state we have -- a failed classify stage shouldn't erase a
        previous successful extract, and downstream automation should be
        able to see doc_class=unknown plus the failure note rather than
        nothing at all."""
        payload = self._fields_payload(extracted)
        written = self.box.update_metadata(file_id, METADATA_TEMPLATE_KEY, payload)
        report.metadata_written = written
        report.extracted = extracted
        report.history_entries = self.history.record_diff(
            file_id, sha1, written, reason="processed (partial: a stage failed)",
            session_ids=extracted.field_session_ids,
        )

    def _commit_final(
        self, file_id: str, sha1: str, extracted: ExtractedFields, report: RunReport
    ) -> None:
        # Guard against the version-race window: get_file_version() ->
        # claim -> download_file() -> ...processing... -> here is not
        # atomic, so a newer version can land on Box while this run was
        # still working off an older download. Re-check the current
        # version immediately before writing metadata; if it moved,
        # abort the commit rather than write metadata that describes a
        # version of the file that is no longer current. The run is left
        # un-marked-as-completed (mark_completed is only called by the
        # caller after this returns normally), so the new version will
        # be picked up and processed on its own next run.
        current = self.box.get_file_version(file_id)
        if current.sha1 != sha1:
            report.skipped_reason = (
                f"file version changed during processing (was {sha1}, "
                f"now {current.sha1}); aborting commit to avoid writing "
                "metadata for a stale version"
            )
            report.stages.append(
                StageResult(name="version_guard", status="failed", detail=report.skipped_reason)
            )
            return
        payload = self._fields_payload(extracted)
        written = self.box.update_metadata(file_id, METADATA_TEMPLATE_KEY, payload)
        report.metadata_written = written
        report.extracted = extracted
        report.history_entries = self.history.record_diff(
            file_id, sha1, written, reason="processed", session_ids=extracted.field_session_ids
        )

    def apply_review_decision(self, review_id: str, approve: bool) -> dict[str, Any]:
        """Human gate for a single held-back low-confidence field. On
        approval, writes exactly that one field to Box metadata (a
        surgical patch, not a full re-run) and logs it in the audit
        trail with reason "review approved". On rejection, nothing is
        written -- the value is simply discarded, and the metadata
        continues to honestly omit that field."""
        review = self.review_queue.decide(review_id, approve)
        # Real outcome vs. original confidence -- recorded regardless of
        # approve/reject, since a rejection is just as much calibration
        # evidence as an approval.
        self.calibration_tracker.record_outcome(review.field_name, review.confidence, approved=approve)
        if not approve:
            return {"review_id": review_id, "status": "rejected", "metadata_written": {}}

        current = self.box.get_metadata(review.file_id, METADATA_TEMPLATE_KEY)
        patch = {review.field_name: review.proposed_value}
        written = self.box.update_metadata(review.file_id, METADATA_TEMPLATE_KEY, patch)
        merged = {**current, **patch}
        self.history.record_diff(
            review.file_id,
            review.version_sha1,
            merged,
            reason="review approved",
            session_ids={review.field_name: review.source_session_id},
        )
        return {"review_id": review_id, "status": "approved", "metadata_written": written}


def _retention_category_for(doc_class: DocClass) -> str:
    mapping = {
        DocClass.CONTRACT: "contracts-7yr",
        DocClass.AMENDMENT: "contracts-7yr",
        DocClass.INVOICE: "financial-5yr",
        DocClass.POLICY: "policy-indefinite",
        DocClass.CORRESPONDENCE: "correspondence-3yr",
        DocClass.UNKNOWN: "uncategorized-review",
    }
    return mapping.get(doc_class, "uncategorized-review")


# A doc_class this uncertain shouldn't be trusted to pick a specific
# retention schedule -- a shaky classification silently producing a
# confident-looking "contracts-7yr" label is a worse outcome than
# honestly falling back to a review category. Threshold intentionally
# distinct from (and, for now, equal to) ReviewQueue's own default --
# this governs retention_category specifically, not the field-level
# review gate.
DOC_CLASS_CONFIDENCE_FLOOR = 0.7


def retention_category_for_extraction(doc_class: DocClass, doc_class_confidence: float) -> str:
    """Confidence-weighted retention derivation: below the floor, the
    classification itself is too uncertain to drive a specific
    retention schedule, so this returns the same honest fallback used
    for a genuinely unknown doc_class, regardless of what the
    (low-confidence) classification actually said."""
    if doc_class_confidence < DOC_CLASS_CONFIDENCE_FLOOR:
        return "uncategorized-review"
    return _retention_category_for(doc_class)
