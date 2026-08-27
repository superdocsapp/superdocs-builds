"""The unattended round-trip: a returned file arrives, and the review runs itself.

One tick of this service does two things, and neither needs a person at a terminal:

1. **Intake.** Any review that came back is matched to its round (the file carries the id), parsed,
   and proposed through SuperDocs. The resulting changes appear in the round's Notion review queue.
2. **Advance.** For every round already waiting, the owner's decisions are read from that queue in
   Notion; approved changes are written to the page, outcomes are recorded, and the next batch —
   if the review is larger than one operation — is proposed and queued.

So the whole cycle is: reviewer returns the file → changes show up in Notion → the owner approves
them in Notion → the page updates. The human touches Word and Notion, and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from notion_review.config import Config
from notion_review.docx_markup.security import DocxError
from notion_review.docx_markup.stamp import identify_round, stamp_round_id
from notion_review.domain import ReviewRound, RoundStatus
from notion_review.logging import get_logger
from notion_review.notion.base import NotionClient, NotionError, NotionNotFoundError
from notion_review.roundtrip.delivery import Deliverable, Delivery
from notion_review.roundtrip.graph import InboundController, submission_key
from notion_review.roundtrip.intake import Intake, ReturnedReview
from notion_review.roundtrip.notion_gate import (
    announce_inline,
    publish_pending,
    read_decisions,
    read_inline_decisions,
    record_outcomes,
)
from notion_review.roundtrip.outbound import send_packet_for_review
from notion_review.roundtrip.requests import (
    STATUS_FAILED,
    STATUS_REQUESTED,
    STATUS_SENT,
    RequestBoards,
    ReviewRequest,
    mark_request,
    parse_request,
)
from notion_review.store import Store
from notion_review.superdocs.base import SuperDocsClient, SuperDocsError

_log = get_logger("notion_review.service")


@dataclass
class TickReport:
    """What one pass of the service did — the basis for logs, metrics, and a status command."""

    sent: list[str] = field(default_factory=list)  # rounds sent out from a Notion request
    ingested: list[str] = field(default_factory=list)  # round ids started from returned files
    rejected: list[str] = field(default_factory=list)  # files that could not be matched or parsed
    deferred: list[str] = field(default_factory=list)  # copies waiting for the gate to clear
    applied: int = 0  # changes written to Notion this tick
    queued: int = 0  # changes newly waiting for the owner in Notion
    completed: list[str] = field(default_factory=list)  # rounds that finished this tick

    def summary(self) -> str:
        return (
            f"sent={len(self.sent)} ingested={len(self.ingested)} queued={self.queued} "
            f"applied={self.applied} completed={len(self.completed)} "
            f"deferred={len(self.deferred)} rejected={len(self.rejected)}"
        )


class ReviewService:
    """Drives returned reviews to completion without a human at a terminal."""

    def __init__(
        self,
        *,
        intake: Intake,
        notion: NotionClient,
        superdocs: SuperDocsClient,
        store: Store,
        config: Config,
        checkpointer: Any | None = None,
        delivery: Delivery | None = None,
        boards: RequestBoards | None = None,
    ) -> None:
        self._intake = intake
        self._delivery = delivery
        self._boards = boards
        self._notion = notion
        self._superdocs = superdocs
        self._store = store
        self._config = config
        # One controller for the life of the service: a review is proposed on one tick and
        # resumed on a later one, so the graph's checkpointer has to be the same one both times.
        # Pass a durable checkpointer to survive a restart as well (the `watch` command does).
        self._controller = InboundController(
            notion=notion,
            superdocs=superdocs,
            store=store,
            config=config,
            checkpointer=checkpointer,
        )

    def tick(self) -> TickReport:
        """One pass: send what was requested, advance what is waiting, take in what arrived.

        Advancing comes before intake so the two stay in step. Applying what the owner decided is
        what frees the SuperDocs session, and a second reviewer's copy cannot be proposed until it
        is free — doing it the other way round would make every waiting copy sit out an extra
        pass. Nothing is lost by the order: a review taken in on this pass has only just been
        queued, so there are no decisions on it yet to advance.
        """
        report = TickReport()
        self._take_requests(report)
        for round_id in self._store.list_ids():
            round_ = self._store.get(round_id)
            if round_ is not None and round_.status == RoundStatus.AWAITING_APPROVAL:
                self._advance(round_, report)
        for item in self._intake.poll():
            self._ingest(item, report)
        _log.info("service_tick", extra={"summary": report.summary()})
        return report

    def _take_requests(self, report: TickReport) -> None:
        """Send out any page someone asked for in Notion, and tell the row what happened."""
        if not (self._boards and self._delivery):
            return  # the Notion trigger is optional; without it, `send` is the entry point
        rows = []
        for database_id in self._boards.ids():
            try:
                rows.extend(self._notion.query_database(database_id))
            except NotionNotFoundError:
                self._boards.forget(database_id)  # gone; stop rediscovering a stale entry
            except NotionError as exc:
                # One board being unreadable must not stop the others.
                _log.warning(
                    "requests_read_failed", extra={"board": database_id, "error": str(exc)}
                )
        for row in rows:
            if row.status != STATUS_REQUESTED:
                continue
            request = parse_request(row, row.properties)
            if request is None:
                mark_request(
                    self._notion,
                    row_id=row.page_id,
                    status=STATUS_FAILED,
                    result="could not find a Notion page id in this row",
                )
                report.rejected.append(row.page_id)
                continue
            self._send_requested(request, report)

    def _send_requested(self, request: ReviewRequest, report: TickReport) -> None:
        try:
            packet = send_packet_for_review(
                notion=self._notion,
                superdocs=self._superdocs,
                store=self._store,
                page_ids=[request.page_id],
            )
            filename = f"review-{packet.round.id}.docx"
            receipt = self._delivery.deliver(  # type: ignore[union-attr]
                Deliverable(
                    filename=filename,
                    content=stamp_round_id(packet.docx.content, packet.round.id),
                    recipients=request.reviewers,
                    subject=f"For review: {filename}",
                    body=(
                        "This document is out for review. Mark it up in Word with tracked "
                        "changes and comments, then send it back — it carries its own review "
                        "id, so it is matched automatically however it returns."
                    ),
                    reference=request.row_id,
                )
            )
        except (NotionError, SuperDocsError, DocxError, ValueError) as exc:
            mark_request(
                self._notion, row_id=request.row_id, status=STATUS_FAILED, result=str(exc)[:300]
            )
            report.rejected.append(request.page_id)
            _log.warning("request_failed", extra={"page_id": request.page_id, "error": str(exc)})
            return
        mark_request(
            self._notion,
            row_id=request.row_id,
            status=STATUS_SENT,
            round_id=packet.round.id,
            result=receipt,
        )
        report.sent.append(packet.round.id)
        _log.info(
            "review_sent",
            extra={
                "round_id": packet.round.id,
                "page_id": request.page_id,
                "reviewers": len(request.reviewers),
            },
        )

    def _ingest(self, item: ReturnedReview, report: TickReport) -> None:
        round_id = identify_round(item.content, item.filename)
        if not round_id:
            self._intake.reject(item, "no review-round id in the document or its filename")
            report.rejected.append(item.filename)
            return
        waiting = self._store.get(round_id)
        if waiting is None:
            self._intake.reject(item, f"review round {round_id} is not known to this service")
            report.rejected.append(item.filename)
            return
        if waiting.pending() and not waiting.has_submission(submission_key(item.content)):
            # A SuperDocs session holds one pending proposal set at a time, so a second reviewer's
            # copy cannot be proposed while the first is still at the gate. Leave it where it is
            # and take it in on a later pass, once the owner has decided what is already waiting —
            # the same reason the batch loop exists, and nothing is lost by waiting.
            report.deferred.append(item.filename)
            _log.info(
                "submission_deferred",
                extra={
                    "round_id": round_id,
                    "file": item.filename,
                    "pending": len(waiting.pending()),
                },
            )
            return
        try:
            gate = self._controller.start(
                round_id=round_id, docx_bytes=item.content, filename=item.filename
            )
        except DocxError as exc:
            self._intake.reject(item, f"could not read the document: {exc}")
            report.rejected.append(item.filename)
            return

        report.queued += self._offer(gate.round)
        self._intake.accept(item)
        report.ingested.append(round_id)
        _log.info(
            "review_ingested",
            extra={"round_id": round_id, "file": item.filename, "pending": len(gate.pending)},
        )

    def _offer(self, round_: ReviewRound) -> int:
        """Put each pending change to the owner both ways: on the line, and in the queue."""
        queued = publish_pending(round_, self._notion, self._store)
        announce_inline(round_, self._notion, self._store)
        return queued

    def _decisions(self, round_: ReviewRound) -> list[dict[str, object]]:
        """Whatever the owner decided, from either surface; a reply and a Status agree or the
        first one seen wins, since both mean the same thing for a given change."""
        merged: dict[str, dict[str, object]] = {}
        for decision in (
            *read_inline_decisions(round_, self._notion),
            *read_decisions(round_, self._notion),
        ):
            merged.setdefault(str(decision["proposal_id"]), decision)
        return list(merged.values())

    def _advance(self, round_: ReviewRound, report: TickReport) -> None:
        """Apply whatever the owner has decided in Notion, then queue the next batch."""
        decisions = self._decisions(round_)
        if not decisions:
            return  # still waiting on the owner; nothing to do this tick
        before = sum(1 for p in round_.proposals if p.status.value == "applied")
        final = self._controller.submit(round_id=round_.id, decisions=decisions)
        record_outcomes(final, self._notion, final.proposals)
        report.applied += sum(1 for p in final.proposals if p.status.value == "applied") - before
        if final.pending():
            report.queued += self._offer(final)
        else:
            report.completed.append(final.id)
        self._store.save(final)
