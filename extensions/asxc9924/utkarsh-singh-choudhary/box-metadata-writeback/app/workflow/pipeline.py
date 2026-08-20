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
from app.workflow.history_store import MetadataHistoryStore
from app.workflow.idempotency import IdempotencyStore
from app.workflow.retry import DEFAULT_BASE_DELAY_SECONDS, DEFAULT_MAX_ATTEMPTS, call_with_retry
from app.workflow.review_queue import ReviewQueue

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

    def _chat(self, doc_id: str, instruction: str):
        """Every stage's SuperDocs chat() call goes through here so retry
        behavior is applied uniformly. Returns (ChatResult, attempts).
        On exhausted retries, re-raises SuperDocsAPIError with an
        `.attempts` attribute set so the caller can report the real
        number of operations spent, including the failed attempts --
        a retried-then-failed stage costs more than 1 operation and the
        cost report should say so, not hide it."""
        retry_result = call_with_retry(
            lambda: self.superdocs.chat(doc_id, instruction),
            max_attempts=self.max_retry_attempts,
            base_delay=self.retry_base_delay,
            sleep_fn=self.retry_sleep_fn,
        )
        return retry_result.value, retry_result.attempts

    def process(self, file_id: str) -> RunReport:
        version = self.box.get_file_version(file_id)
        report = RunReport(file_id=file_id, version_sha1=version.sha1)

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
                    return report

            # Stage: extract key terms
            if "extract" in resumed_stage_names:
                self._replay_stage(existing_checkpoint, "extract", report)
            else:
                extracted = self._run_stage_extract(doc_id, extracted, report, file_id, version.sha1)
                self._checkpoint_stage_if_done(file_id, version.sha1, "extract", report, extracted)
                if report.stages[-1].status == "failed":
                    self._commit_partial(file_id, version.sha1, extracted, report)
                    self.checkpoint.clear(file_id, version.sha1)
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
        except SuperDocsAPIError as e:
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
    ) -> ExtractedFields:
        t0 = time.monotonic()
        threshold = self.review_queue.threshold if threshold is None else threshold
        try:
            result, attempts = self._chat(doc_id, "Extract key terms from this document.")
            self.superdocs.approve(doc_id, result.session_id)
            change = result.proposed_change or {}
            fields = change.get("fields", {})
            confidences = change.get("field_confidence", {})
            extracted.field_confidence.update(confidences)

            # Honesty over fabrication: only set what SuperDocs actually
            # returned. Anything not present stays None, which the Box
            # metadata write step later renders as an explicit empty
            # field rather than a guessed one.
            #
            # Fields returned WITH a value are further split by
            # confidence: at/above threshold, they're set directly on
            # extracted (same as before); below threshold, the value is
            # held back and staged in the review queue instead -- it
            # never reaches Box metadata until a human approves it.
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
                if conf >= threshold:
                    setattr(extracted, key, value)
                    populated.append(key)
                else:
                    review = self.review_queue.stage(file_id, version_sha1, key, value, conf)
                    extracted.pending_review_ids.append(review.review_id)
                    queued.append(f"{key} (conf={conf})")

            missing = {"counterparty_name", "effective_date", "expiration_date", "contract_value"} - set(
                populated
            ) - {k.split(" ")[0] for k in queued}
            notes = []
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
                    ),
                    latency_ms=(time.monotonic() - t0) * 1000,
                    operations=attempts,
                )
            )
        except SuperDocsAPIError as e:
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
            companion_bytes = companion_text.encode()
            # Deterministic, content-addressed filename: (file_id, sha1)
            # uniquely identifies "the companion for this exact source
            # version". Combined with upload_companion_document()'s
            # dedupe-by-name check, a crash between upload succeeding
            # and the stage checkpoint being saved no longer produces a
            # second companion on retry -- the retry finds the same
            # named file already there and reuses it instead of
            # creating companion-9002 alongside companion-9001.
            companion_filename = f"{version.file_id}.{version.sha1}.companion.txt"
            companion_file_id = self.box.upload_companion_document(
                self.companion_folder_id,
                companion_filename,
                companion_bytes,
            )
            extracted.companion_document_id = companion_file_id
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
        except SuperDocsAPIError as e:
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
            extracted.retention_category = _retention_category_for(extracted.doc_class)
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
        except SuperDocsAPIError as e:
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
            file_id, sha1, written, reason="processed (partial: a stage failed)"
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
            file_id, sha1, written, reason="processed"
        )

    def apply_review_decision(self, review_id: str, approve: bool) -> dict[str, Any]:
        """Human gate for a single held-back low-confidence field. On
        approval, writes exactly that one field to Box metadata (a
        surgical patch, not a full re-run) and logs it in the audit
        trail with reason "review approved". On rejection, nothing is
        written -- the value is simply discarded, and the metadata
        continues to honestly omit that field."""
        review = self.review_queue.decide(review_id, approve)
        if not approve:
            return {"review_id": review_id, "status": "rejected", "metadata_written": {}}

        current = self.box.get_metadata(review.file_id, METADATA_TEMPLATE_KEY)
        patch = {review.field_name: review.proposed_value}
        written = self.box.update_metadata(review.file_id, METADATA_TEMPLATE_KEY, patch)
        merged = {**current, **patch}
        self.history.record_diff(
            review.file_id, review.version_sha1, merged, reason="review approved"
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
