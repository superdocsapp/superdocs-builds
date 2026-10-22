from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from ..config import APPROVAL_POLICIES, Settings
from ..slack.cards import (
    build_boundary_alert_blocks,
    build_contract_changed_blocks,
    build_deal_closed_blocks,
    build_deal_started_blocks,
    build_decision_notice_blocks,
    build_document_added_blocks,
    build_job_expired_blocks,
    build_outcome_card_blocks,
    build_progress_blocks,
    build_proposal_card_blocks,
    build_provenance_error_blocks,
    build_revision_card_blocks,
    build_text_blocks,
    flatten_blocks_text,
)
from ..superdocs.client import SuperDocsClient, wait_for_turnpoint
from ..superdocs.models import OPEN_MODE_BACKGROUND, ApprovalDecision, JobSnapshot
from ..superdocs.transport import SuperDocsAPIError
from . import boundary
from .documents import extract_document_text
from .search import SearchHit, search_deal
from .store import DealRow, DocumentRow, JobRow, ProposalRow, Store

SIDES = ("vendor", "customer")

JOB_RUNNING = "running"
JOB_AWAITING_REVIEW = "awaiting_review"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"
ALL_JOB_STATES = (JOB_RUNNING, JOB_AWAITING_REVIEW, JOB_COMPLETED, JOB_FAILED, JOB_CANCELLED)

ROLE_CONTRACT = "contract"
ROLE_SUPPORTING = "supporting"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class MessengerPort(Protocol):
    async def post_message(
        self,
        channel: str,
        blocks: list[dict[str, Any]],
        text: str,
        thread_ts: str | None = None,
    ) -> str: ...

    async def update_message(
        self, channel: str, ts: str, blocks: list[dict[str, Any]], text: str
    ) -> None: ...

    async def upload_file(
        self, channel: str, filename: str, content: bytes, initial_comment: str = ""
    ) -> None: ...


class NegotiationError(Exception):
    pass


@dataclass(frozen=True)
class ExportedFile:
    filename: str
    content: bytes


class NegotiationService:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        client: SuperDocsClient,
        messenger: MessengerPort,
    ):
        self.settings = settings
        self.store = store
        self.client = client
        self.messenger = messenger

    # ------------------------------------------------------------------
    # shared-channel boundary guard
    # ------------------------------------------------------------------

    async def _post_shared(
        self,
        deal: DealRow,
        blocks: list[dict[str, Any]],
        text: str,
        thread_ts: str | None = None,
    ) -> str:
        internal_materials = boundary.collect_internal_material(
            note["body"] for note in self.store.internal_notes(deal.id)
        )
        combined = f"{text} {flatten_blocks_text(blocks)}"
        try:
            boundary.assert_shared_payload_is_clean(
                combined, internal_materials, context=f"deal:{deal.id}:shared_post"
            )
        except boundary.BoundaryViolation as exc:
            self.store.add_audit(
                deal.id,
                actor="system",
                side="system",
                action="boundary_violation_blocked",
                reason=exc.reason,
            )
            alert_blocks, alert_text = build_boundary_alert_blocks(exc.reason)
            for side in SIDES:
                await self.messenger.post_message(
                    self.settings.internal_channel_for(side), alert_blocks, alert_text
                )
            raise
        return await self.messenger.post_message(
            deal.shared_channel_id, blocks, text, thread_ts=thread_ts
        )

    # ------------------------------------------------------------------
    # deal lifecycle
    # ------------------------------------------------------------------

    async def start_deal(
        self,
        name: str,
        started_by_side: str,
        started_by_user: str,
        filename: str,
        file_bytes: bytes,
        approval_policy: str | None = None,
    ) -> DealRow:
        policy = approval_policy or self.settings.approval_policy
        if policy not in APPROVAL_POLICIES:
            raise NegotiationError(f"unknown approval policy {policy!r}")
        deal_id = new_id("deal")
        upload = await self.client.upload_document(filename, file_bytes, session_id=deal_id)
        deal = self.store.create_deal(
            deal_id=deal_id,
            name=name,
            session_id=upload.session_id,
            filename=filename,
            original_bytes=file_bytes,
            approval_policy=policy,
            shared_channel_id=self.settings.shared_channel,
        )
        self.store.add_document(
            DocumentRow(
                id=new_id("doc"),
                deal_id=deal.id,
                superdocs_document_id=upload.document_id,
                filename=filename,
                original_bytes=file_bytes,
                role=ROLE_CONTRACT,
                added_by_side=started_by_side,
            )
        )
        self.store.add_audit(
            deal.id,
            actor=started_by_user,
            side=started_by_side,
            action="deal_started",
            filename=filename,
            policy=policy,
        )
        blocks, text = build_deal_started_blocks(name, filename, started_by_side, deal.id)
        await self._post_shared(deal, blocks, text)
        return deal

    # ------------------------------------------------------------------
    # proposing edits
    # ------------------------------------------------------------------

    async def propose(
        self,
        deal_id: str,
        side: str,
        user: str,
        instruction: str,
        source_channel_id: str,
        document_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> JobRow:
        deal = self.store.get_deal(deal_id)
        audience = boundary.classify_source(source_channel_id, deal.shared_channel_id)
        try:
            boundary.assert_instruction_is_shareable(
                instruction, audience, context=f"deal:{deal.id}:propose"
            )
        except boundary.BoundaryViolation as exc:
            self.store.add_audit(
                deal.id, actor=user, side=side, action="propose_refused", reason=exc.reason
            )
            error_blocks, error_text = build_provenance_error_blocks(exc.reason)
            await self.messenger.post_message(
                self.settings.internal_channel_for(side), error_blocks, error_text
            )
            raise

        target_document = self._resolve_document(deal.id, document_id)

        # Starting an edit costs a SuperDocs operation, so a repeated request must not
        # buy a second one. The key is derived from what actually determines the work --
        # the deal, the target document and the instruction -- so a double-clicked slash
        # command dedupes without the caller doing anything. A caller that wants to
        # control the boundary itself (a retrying script, say) supplies its own key.
        resolved_key = idempotency_key or self._derive_idempotency_key(
            deal.id,
            target_document.id if target_document else None,
            instruction,
        )
        existing = self.store.find_job_by_idempotency_key(
            deal.id,
            resolved_key,
            active_states=(JOB_RUNNING, JOB_AWAITING_REVIEW),
            window_seconds=self.settings.idempotency_window_seconds,
        )
        if existing is not None:
            self.store.add_audit(
                deal.id,
                actor=user,
                side=side,
                action="propose_deduplicated",
                job_id=existing.job_id,
                reason="an identical instruction is already in flight or was just run",
            )
            return existing

        job_id = await self.client.start_edit(
            deal.superdocs_session_id,
            instruction,
            approval_mode="ask_every_time",
            document_id=target_document.superdocs_document_id if target_document else None,
        )
        job = JobRow(
            job_id=job_id,
            deal_id=deal.id,
            instruction=instruction,
            requested_by_side=side,
            requested_by_user=user,
            state=JOB_RUNNING,
            document_id=target_document.id if target_document else None,
            idempotency_key=resolved_key,
        )
        self.store.create_job(job)
        self.store.add_audit(
            deal.id,
            actor=user,
            side=side,
            action="propose_started",
            job_id=job_id,
            document=target_document.filename if target_document else None,
        )
        return self.store.get_job(job_id)

    @staticmethod
    def _derive_idempotency_key(
        deal_id: str, document_id: str | None, instruction: str
    ) -> str:
        """Hash the three things that decide what work a propose actually does.

        Whitespace and case are normalised so that a re-typed instruction counts as the
        same request; anything genuinely different produces a different key and is
        allowed through.
        """
        normalized = " ".join((instruction or "").split()).casefold()
        raw = f"{deal_id}\x00{document_id or ''}\x00{normalized}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _resolve_document(self, deal_id: str, document_id: str | None) -> DocumentRow | None:
        documents = self.store.documents_for_deal(deal_id)
        if not documents:
            return None
        if document_id is None:
            return next((d for d in documents if d.role == ROLE_CONTRACT), documents[0])
        for document in documents:
            if document_id in (document.id, document.superdocs_document_id):
                return document
            if document_id.lower() in document.filename.lower():
                return document
        known = ", ".join(f"{d.filename} ({d.id})" for d in documents)
        raise NegotiationError(
            f"no document matching {document_id!r} in this deal; open documents are: {known}"
        )

    async def add_document(
        self,
        deal_id: str,
        side: str,
        user: str,
        filename: str,
        file_bytes: bytes,
        role: str = ROLE_SUPPORTING,
        source_channel_id: str | None = None,
    ) -> DocumentRow:
        """Attach a supporting document (an amendment, an SOW, a counterparty markup) to
        an existing deal without disturbing the authoritative contract.

        The upload uses SuperDocs' `background` open mode so the new file joins the same
        session -- making it available to edit instructions and to search -- while the
        contract stays the focused document, so a later untargeted `/redline propose`
        still edits the contract rather than whatever was uploaded most recently.
        """
        deal = self.store.get_deal(deal_id)
        if source_channel_id is not None:
            audience = boundary.classify_source(source_channel_id, deal.shared_channel_id)
            if audience != boundary.AUDIENCE_SHARED:
                raise boundary.BoundaryViolation(
                    "documents must be shared in the shared channel so both sides see"
                    " the same file",
                    context=f"deal:{deal.id}:add_document",
                )
        upload = await self.client.upload_document(
            filename,
            file_bytes,
            session_id=deal.superdocs_session_id,
            open_mode=OPEN_MODE_BACKGROUND,
        )
        document = self.store.add_document(
            DocumentRow(
                id=new_id("doc"),
                deal_id=deal.id,
                superdocs_document_id=upload.document_id,
                filename=filename,
                original_bytes=file_bytes,
                role=role,
                added_by_side=side,
            )
        )
        self.store.add_audit(
            deal.id,
            actor=user,
            side=side,
            action="document_added",
            filename=filename,
            role=role,
        )
        blocks, text = build_document_added_blocks(deal.name, filename, role, side)
        await self._post_shared(deal, blocks, text)
        return document

    def list_documents(self, deal_id: str) -> list[DocumentRow]:
        return self.store.documents_for_deal(deal_id)

    def latest_open_deal(self, channel_id: str) -> DealRow | None:
        return self.store.latest_active_deal_for_channel(channel_id)

    async def close_deal(self, deal_id: str, side: str, user: str) -> DealRow:
        """End a negotiation, freeing the channel for the next contract.

        A file shared into a channel joins whatever deal is open there, which is right
        while one contract is being negotiated and wrong the moment the next one starts.
        Closing is how a human says "that one is finished" -- nothing else can know it.
        Everything is kept: the deal, its history and its exports stay readable.
        """
        deal = self.store.get_deal(deal_id)
        if deal.status != "active":
            raise NegotiationError(f"deal {deal_id!r} is already {deal.status}")
        pending = self.store.pending_proposals_for_deal(deal_id)
        if pending:
            raise NegotiationError(
                f"{len(pending)} proposal(s) are still awaiting a decision; decide them "
                "first, or the negotiation trail would end with changes nobody resolved"
            )
        self.store.set_deal_status(deal_id, "closed")
        self.store.add_audit(deal_id, actor=user, side=side, action="deal_closed")
        blocks, text = build_deal_closed_blocks(deal.name, deal.display_version, side)
        await self._post_shared(self.store.get_deal(deal_id), blocks, text)
        return self.store.get_deal(deal_id)

    async def promote_document(
        self, deal_id: str, document_id: str, side: str, user: str
    ) -> DocumentRow:
        """Make an already-attached document the authoritative contract.

        Supporting documents arrive as context; sometimes one of them turns out to be
        the thing actually being negotiated -- a restated agreement, a superseding
        amendment. Promoting swaps the roles rather than starting a new deal, so the
        history built up so far stays attached to it.
        """
        deal = self.store.get_deal(deal_id)
        target = self._resolve_document(deal_id, document_id)
        if target is None:
            raise NegotiationError(f"deal {deal_id!r} has no documents to promote")
        if target.role == ROLE_CONTRACT:
            raise NegotiationError(f"{target.filename} is already the contract")
        previous = next(
            (d for d in self.store.documents_for_deal(deal_id) if d.role == ROLE_CONTRACT),
            None,
        )
        if previous is not None:
            self.store.set_document_role(previous.id, ROLE_SUPPORTING)
        self.store.set_document_role(target.id, ROLE_CONTRACT)
        self.store.add_audit(
            deal_id,
            actor=user,
            side=side,
            action="contract_replaced",
            document=target.filename,
            previous=previous.filename if previous else None,
        )
        blocks, text = build_contract_changed_blocks(
            deal.name, target.filename, previous.filename if previous else None, side
        )
        await self._post_shared(deal, blocks, text)
        return self.store.get_document(target.id)

    def search(
        self,
        deal_id: str,
        query: str,
        *,
        source_channel_id: str,
        side: str,
        limit: int = 10,
    ) -> list[SearchHit]:
        """Search the deal corpus, with the same boundary rule as every other read path.

        A search issued from the shared channel can only ever return shared material; the
        internal-note index is reachable only from an internal channel, and only for the
        searching side's own notes.
        """
        deal = self.store.get_deal(deal_id)
        audience = boundary.classify_source(source_channel_id, deal.shared_channel_id)
        text_by_filename = {
            document.filename: extract_document_text(document.filename, document.original_bytes)
            for document in self.store.documents_for_deal(deal.id)
        }
        hits = search_deal(
            self.store,
            deal.id,
            query,
            requester_audience=audience,
            requester_side=side,
            document_text_by_filename=text_by_filename,
            limit=limit,
        )
        self.store.add_audit(
            deal.id,
            actor=side,
            side=side,
            action="search",
            query=query,
            audience=audience,
            hits=len(hits),
        )
        return hits

    async def drive_job(self, job_id: str) -> JobRow:
        job = self.store.get_job(job_id)
        deal = self.store.get_deal(job.deal_id)

        if job.state == JOB_RUNNING:
            job = await self._advance_running_job(deal, job)

        if job.state == JOB_AWAITING_REVIEW:
            await self._post_missing_cards(deal, job)

        return self.store.get_job(job_id)

    def _progress_reporter(self, deal: DealRow, job: JobRow):
        """Post a 'still working' note into the shared thread for a slow SuperDocs job.

        SuperDocs documents that large documents or deep model tiers can run from thirty
        seconds to several minutes with no visible progress, and that the correct read is
        'still processing', not 'crashed'. Without this the channel just goes quiet and
        both sides assume the bot died. Posting is best-effort: a Slack failure here must
        never abort a job that is otherwise progressing fine.
        """

        async def on_progress(elapsed: float, snapshot: JobSnapshot) -> None:
            blocks, text = build_progress_blocks(deal.name, elapsed, snapshot.status)
            try:
                await self._post_shared(deal, blocks, text, thread_ts=job.thread_ts)
            except Exception as exc:  # noqa: BLE001 - progress pings are never load-bearing
                self.store.add_audit(
                    deal.id,
                    actor="system",
                    side="system",
                    action="progress_ping_failed",
                    job_id=job.job_id,
                    error=str(exc),
                )

        return on_progress

    async def _advance_running_job(self, deal: DealRow, job: JobRow) -> JobRow:
        while True:
            snapshot = await wait_for_turnpoint(
                self.client,
                job.job_id,
                interval_seconds=self.settings.poll_interval_seconds,
                max_wait_seconds=self.settings.max_job_wait_seconds,
                warn_after_seconds=self.settings.warn_after_seconds,
                on_progress=self._progress_reporter(deal, job),
            )
            if snapshot.is_continue_prompt:
                await self.client.continue_job(deal.superdocs_session_id, job.job_id, cont=True)
                continue
            if snapshot.is_change_review:
                if not self.store.proposals_for_job(job.job_id):
                    rows = [
                        ProposalRow(
                            id=new_id("prop"),
                            deal_id=deal.id,
                            job_id=job.job_id,
                            change_id=change.change_id,
                            operation=change.operation,
                            old_html=change.old_html,
                            new_html=change.new_html,
                            ai_explanation=change.ai_explanation,
                            proposed_by_side=job.requested_by_side,
                            document_id=job.document_id,
                            chunk_id=change.chunk_id,
                            insert_after_chunk_id=change.insert_after_chunk_id,
                        )
                        for change in snapshot.pending_changes
                    ]
                    self.store.insert_proposals(rows)
                    self.store.add_audit(
                        deal.id,
                        actor="system",
                        side="system",
                        action="proposals_drafted",
                        job_id=job.job_id,
                        count=len(rows),
                    )
                self.store.set_job_state(job.job_id, JOB_AWAITING_REVIEW)
                return self.store.get_job(job.job_id)
            if snapshot.status == "failed":
                self.store.set_job_state(job.job_id, JOB_FAILED)
                self.store.add_audit(
                    deal.id, actor="system", side="system", action="job_failed",
                    job_id=job.job_id, error=snapshot.error,
                )
                return self.store.get_job(job.job_id)
            if snapshot.status == "cancelled":
                self.store.set_job_state(job.job_id, JOB_CANCELLED)
                return self.store.get_job(job.job_id)
            # completed with no pending changes (e.g. auto mode edge case)
            self.store.set_job_state(job.job_id, JOB_COMPLETED)
            if snapshot.result and snapshot.result.version_id:
                self.store.set_deal_version(deal.id, snapshot.result.version_id)
            return self.store.get_job(job.job_id)

    async def _post_missing_cards(self, deal: DealRow, job: JobRow) -> None:
        proposals = self.store.proposals_for_job(job.job_id)
        pending = [p for p in proposals if p.state == "pending"]
        missing = [p for p in pending if p.card_ts is None]
        if not missing:
            return
        for proposal in missing:
            blocks, text = build_proposal_card_blocks(proposal, deal.name, deal.display_version)
            ts = await self._post_shared(deal, blocks, text, thread_ts=job.thread_ts)
            self.store.set_proposal_card_ts(proposal.id, ts)
            if job.thread_ts is None:
                self.store.set_job_state(job.job_id, JOB_AWAITING_REVIEW, thread_ts=ts)
                job = self.store.get_job(job.job_id)

    async def recover_pending(self) -> None:
        for job in self.store.jobs_in_states(JOB_RUNNING, JOB_AWAITING_REVIEW):
            await self.drive_job(job.job_id)

    async def refresh_cards(self, deal_id: str) -> int:
        """Re-render every still-pending proposal card for a deal.

        A Slack card is a remote copy of state we already own; it can drift or be
        clobbered (a stray edit, a failed update, an app that replaced the message).
        The database stays authoritative, so redrawing from it is always safe and
        idempotent -- it never invents a decision, it only makes Slack agree with what
        was already recorded. Returns how many cards were redrawn.
        """
        deal = self.store.get_deal(deal_id)
        redrawn = 0
        for proposal in self.store.pending_proposals_for_deal(deal_id):
            blocks, text = build_proposal_card_blocks(proposal, deal.name, deal.display_version)
            if proposal.card_ts:
                # The message still exists at this ts even if something overwrote its
                # content, so updating in place restores the card where people expect it.
                await self.messenger.update_message(
                    deal.shared_channel_id, proposal.card_ts, blocks, text
                )
            else:
                ts = await self._post_shared(deal, blocks, text)
                self.store.set_proposal_card_ts(proposal.id, ts)
            redrawn += 1
        self.store.add_audit(
            deal_id,
            actor="system",
            side="system",
            action="cards_refreshed",
            count=redrawn,
        )
        return redrawn

    # ------------------------------------------------------------------
    # decisions
    # ------------------------------------------------------------------

    @staticmethod
    def _is_gating_side(policy: str, proposal: ProposalRow, side: str) -> bool:
        if policy == "proposer_only":
            return side == proposal.proposed_by_side
        return True

    @staticmethod
    def _proposal_ready(policy: str, proposal: ProposalRow) -> bool:
        if policy == "proposer_only":
            decision = (
                proposal.vendor_decision
                if proposal.proposed_by_side == "vendor"
                else proposal.customer_decision
            )
            return decision is not None
        return proposal.vendor_decision is not None and proposal.customer_decision is not None

    @staticmethod
    def _proposal_final_approved(policy: str, proposal: ProposalRow) -> bool:
        if policy == "proposer_only":
            decision = (
                proposal.vendor_decision
                if proposal.proposed_by_side == "vendor"
                else proposal.customer_decision
            )
            return decision == "approved"
        return proposal.vendor_decision == "approved" and proposal.customer_decision == "approved"

    async def decide(
        self,
        deal_id: str,
        proposal_id: str,
        side: str,
        user: str,
        approved: bool,
        feedback: str | None = None,
    ) -> ProposalRow:
        if side not in SIDES:
            raise NegotiationError(f"unknown side {side!r}")
        deal = self.store.get_deal(deal_id)
        proposal = self.store.get_proposal(proposal_id)
        if proposal.deal_id != deal.id:
            raise NegotiationError(
                f"proposal {proposal_id!r} does not belong to deal {deal_id!r}"
            )
        if proposal.state != "pending":
            raise NegotiationError(
                f"proposal {proposal_id!r} is already resolved ({proposal.state})"
            )

        proposal = self.store.record_decision(proposal_id, side, approved, feedback)
        self.store.add_audit(
            deal.id,
            actor=user,
            side=side,
            action="decision_recorded",
            proposal_id=proposal_id,
            approved=approved,
            feedback=feedback,
        )

        if proposal.card_ts:
            blocks, text = build_proposal_card_blocks(proposal, deal.name, deal.display_version)
            try:
                await self.messenger.update_message(
                    deal.shared_channel_id, proposal.card_ts, blocks, text
                )
            except Exception as exc:  # noqa: BLE001 - a stale Slack UI card must not block a decision
                self.store.add_audit(
                    deal.id,
                    actor="system",
                    side="system",
                    action="card_update_failed",
                    proposal_id=proposal_id,
                    error=str(exc),
                )

        job = self.store.get_job(proposal.job_id)
        policy = deal.approval_policy
        await self._announce_decision(deal, job, proposal, side, approved, policy)

        pending_for_job = [
            p for p in self.store.proposals_for_job(job.job_id) if p.state == "pending"
        ]
        if all(self._proposal_ready(policy, p) for p in pending_for_job):
            await self._finalize_job_batch(deal, job, pending_for_job)

        return self.store.get_proposal(proposal_id)

    async def _announce_decision(
        self,
        deal: DealRow,
        job: JobRow,
        proposal: ProposalRow,
        side: str,
        approved: bool,
        policy: str,
    ) -> None:
        """Post what just happened, so the state is readable without hunting for the card.

        Never load-bearing: the decision is already committed to the store by the time
        this runs, so a Slack failure here must not undo it or block the batch.
        """
        waiting_on = [
            other
            for other in SIDES
            if self._is_gating_side(policy, proposal, other)
            and self._decision_of(proposal, other) is None
        ]
        blocks, text = build_decision_notice_blocks(
            deal.name, proposal, side, approved, waiting_on
        )
        try:
            await self._post_shared(deal, blocks, text, thread_ts=job.thread_ts)
        except Exception as exc:  # noqa: BLE001 - a notification must never undo a decision
            self.store.add_audit(
                deal.id,
                actor="system",
                side="system",
                action="decision_notice_failed",
                proposal_id=proposal.id,
                error=str(exc),
            )

    @staticmethod
    def _decision_of(proposal: ProposalRow, side: str) -> str | None:
        return proposal.vendor_decision if side == "vendor" else proposal.customer_decision

    async def _finalize_job_batch(
        self, deal: DealRow, job: JobRow, proposals: list[ProposalRow]
    ) -> None:
        policy = deal.approval_policy
        decisions: list[ApprovalDecision] = []
        for proposal in proposals:
            final_approved = self._proposal_final_approved(policy, proposal)
            fb = proposal.customer_feedback or proposal.vendor_feedback
            decisions.append(
                ApprovalDecision(
                    change_id=proposal.change_id,
                    approved=final_approved,
                    feedback=None if final_approved else fb,
                )
            )

        try:
            result = await self.client.submit_decisions(
                deal.superdocs_session_id, job.job_id, decisions
            )
        except SuperDocsAPIError as exc:
            if exc.status_code != 404:
                raise
            # SuperDocs forgets a pending job after a while. Both sides had already
            # decided by then, so failing silently would leave everyone believing an
            # edit landed that never did -- the one outcome worse than an error.
            await self._abandon_expired_job(deal, job, proposals, exc)
            return
        snapshot = await wait_for_turnpoint(
            self.client,
            job.job_id,
            interval_seconds=self.settings.poll_interval_seconds,
            max_wait_seconds=self.settings.max_job_wait_seconds,
        )

        if snapshot.is_change_review:
            # SuperDocs drafted a revision round (e.g. everything was rejected with feedback).
            for proposal in proposals:
                self.store.resolve_proposal(proposal.id, "revised")
            new_rows = [
                ProposalRow(
                    id=new_id("prop"),
                    deal_id=deal.id,
                    job_id=job.job_id,
                    change_id=change.change_id,
                    operation=change.operation,
                    old_html=change.old_html,
                    new_html=change.new_html,
                    ai_explanation=change.ai_explanation,
                    proposed_by_side=job.requested_by_side,
                    document_id=job.document_id,
                    chunk_id=change.chunk_id,
                    insert_after_chunk_id=change.insert_after_chunk_id,
                )
                for change in snapshot.pending_changes
            ]
            self.store.insert_proposals(new_rows)
            self.store.add_audit(
                deal.id, actor="system", side="system", action="revision_round",
                job_id=job.job_id, count=len(new_rows),
            )
            round_number = sum(
                1
                for entry in self.store.history(deal.id)
                if entry.action == "revision_round" and entry.detail.get("job_id") == job.job_id
            )
            revision_blocks, revision_text = build_revision_card_blocks(deal.name, round_number)
            await self._post_shared(deal, revision_blocks, revision_text, thread_ts=job.thread_ts)
            for proposal in new_rows:
                blocks, text = build_proposal_card_blocks(proposal, deal.name, deal.display_version)
                ts = await self._post_shared(deal, blocks, text, thread_ts=job.thread_ts)
                self.store.set_proposal_card_ts(proposal.id, ts)
            return

        # terminal: resolve every proposal as committed or rejected. The fake and real
        # SuperDocs APIs both apply exactly the changes marked approved=True in the batch,
        # so the local decision is authoritative for which side of the line each change fell.
        committed: list[ProposalRow] = []
        rejected: list[ProposalRow] = []
        for proposal, decision in zip(proposals, decisions, strict=True):
            final_state = "committed" if decision.approved else "rejected"
            resolved = self.store.resolve_proposal(proposal.id, final_state)
            (committed if final_state == "committed" else rejected).append(resolved)
            self.store.add_audit(
                deal.id, actor="system", side="system", action="proposal_resolved",
                proposal_id=proposal.id, state=final_state,
            )

        version = deal.current_version
        if snapshot.result and snapshot.result.version_id:
            version = snapshot.result.version_id
            self.store.set_deal_version(deal.id, version)
            deal = self.store.get_deal(deal.id)

        self.store.set_job_state(job.job_id, JOB_COMPLETED)
        self.store.add_audit(
            deal.id, actor="system", side="system", action="job_completed",
            job_id=job.job_id, version=version, superdocs_result=result.get("status"),
        )

        outcome_blocks, outcome_text = build_outcome_card_blocks(
            deal.name, deal.display_version, committed, rejected
        )
        # Top level, not a thread reply: the outcome is the point of the whole exchange
        # and should be visible without opening anything.
        await self._post_shared(deal, outcome_blocks, outcome_text)
        await self._notify_both_sides(deal, outcome_blocks, outcome_text)

    async def _abandon_expired_job(
        self,
        deal: DealRow,
        job: JobRow,
        proposals: list[ProposalRow],
        exc: SuperDocsAPIError,
    ) -> None:
        """Close out a batch SuperDocs can no longer apply, without inventing a result.

        The decisions themselves are real and stay in the history; what is gone is the
        chance to apply them. The proposals are marked `expired` rather than committed
        or rejected, because neither of those would be true.
        """
        for proposal in proposals:
            self.store.resolve_proposal(proposal.id, "expired")
        self.store.set_job_state(job.job_id, JOB_FAILED)
        self.store.add_audit(
            deal.id,
            actor="system",
            side="system",
            action="job_expired",
            job_id=job.job_id,
            error=exc.message,
        )
        blocks, text = build_job_expired_blocks(deal.name, exc.message)
        await self._post_shared(deal, blocks, text)
        await self._notify_both_sides(deal, blocks, text)

    async def _notify_both_sides(
        self, deal: DealRow, blocks: list[dict[str, Any]], text: str
    ) -> None:
        """Mirror a shared-channel announcement into each side's internal channel.

        Only ever called with a payload already cleared for the shared channel, so this
        can never widen what one side is allowed to see.
        """
        for side in SIDES:
            try:
                await self.messenger.post_message(
                    self.settings.internal_channel_for(side), blocks, text
                )
            except Exception as exc:  # noqa: BLE001 - notifications are never load-bearing
                self.store.add_audit(
                    deal.id,
                    actor="system",
                    side="system",
                    action="internal_notify_failed",
                    error=str(exc),
                )

    # ------------------------------------------------------------------
    # internal notes (never posted to the shared channel)
    # ------------------------------------------------------------------

    async def add_internal_note(
        self, deal_id: str, side: str, author: str, body: str
    ) -> None:
        deal = self.store.get_deal(deal_id)
        note_id = new_id("note")
        self.store.save_internal_note(note_id, deal.id, side, author, body)
        self.store.add_audit(
            deal.id, actor=author, side=side, action="internal_note_added", note_id=note_id
        )
        blocks, text = build_text_blocks(f":lock: Internal note from {author}: {body}")
        await self.messenger.post_message(self.settings.internal_channel_for(side), blocks, text)

    # ------------------------------------------------------------------
    # export
    # ------------------------------------------------------------------

    async def export_clean(self, deal_id: str) -> ExportedFile:
        deal = self.store.get_deal(deal_id)
        result = await self.client.export_document(deal.superdocs_session_id, fmt="docx")
        self.store.add_audit(deal.id, actor="system", side="system", action="exported_clean")
        return ExportedFile(filename=result.filename, content=result.content_bytes())

    async def export_redline(self, deal_id: str) -> ExportedFile:
        from ..export.track_changes import build_redline_docx

        deal = self.store.get_deal(deal_id)
        proposals = [
            row
            for row in self._all_resolved_proposals(deal.id)
            if row.state in ("committed", "rejected")
        ]
        content = build_redline_docx(deal.original_filename, deal.original_bytes, proposals)
        self.store.add_audit(deal.id, actor="system", side="system", action="exported_redline")
        base = deal.original_filename.rsplit(".", 1)[0]
        return ExportedFile(filename=f"{base}_redline.docx", content=content)

    def _all_resolved_proposals(self, deal_id: str) -> list[ProposalRow]:
        jobs = self.store.jobs_in_states(*ALL_JOB_STATES)
        seen: dict[str, ProposalRow] = {}
        for job in jobs:
            if job.deal_id != deal_id:
                continue
            for proposal in self.store.proposals_for_job(job.job_id):
                seen[proposal.id] = proposal
        return list(seen.values())

    # ------------------------------------------------------------------
    # read-only views
    # ------------------------------------------------------------------

    def status(self, deal_id: str) -> dict[str, Any]:
        deal = self.store.get_deal(deal_id)
        pending = self.store.pending_proposals_for_deal(deal.id)
        return {
            "deal_id": deal.id,
            "name": deal.name,
            # `current_version` stays the SuperDocs id: it is the REST surface's
            # contract and the value that ties a deal back upstream. `version` is the
            # readable counter the Slack cards show.
            "current_version": deal.current_version,
            "version": deal.display_version,
            "approval_policy": deal.approval_policy,
            "status": deal.status,
            "pending_proposals": len(pending),
        }

    def history_lines(self, deal_id: str) -> list[str]:
        entries = self.store.history(deal_id)
        lines = []
        for entry in entries:
            detail = ", ".join(f"{k}={v}" for k, v in entry.detail.items() if v is not None)
            suffix = f" ({detail})" if detail else ""
            lines.append(f"[{entry.ts}] {entry.side}/{entry.actor}: {entry.action}{suffix}")
        return lines
