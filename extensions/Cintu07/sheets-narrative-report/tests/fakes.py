"""Offline stand-ins for the SuperDocs surface.

Kept separate from conftest so tests can import the fake explicitly rather than
relying on fixture magic when they need to configure its failure modes.
"""

from __future__ import annotations

from narrative_report.superdocs import JobState

QUARTERLY = [
    ["Line item", "Q1", "Q2", "Q3", "Q4"],
    ["Revenue", "$1,200,000", "$1,320,000", "$1,180,000", "$1,455,000"],
    ["COGS", "(480,000)", "(528,000)", "(472,000)", "(560,000)"],
    ["Headcount", "42", "44", "44", "51"],
]

# What a well-behaved model returns: prose whose every quantity is a token.
GOOD_DOCUMENT = (
    '<div class="report-body">'
    '<div data-section-id="summary"><p>Revenue {{fact:series.revenue.direction}} to '
    "{{fact:series.revenue.latest}} in {{fact:period.last}}, "
    "{{fact:series.revenue.delta_pct}} against the prior period.</p></div>"
    '<div data-section-id="performance"><p>Cost of goods sold reached '
    "{{fact:series.cogs.latest}} and headcount closed at "
    "{{fact:series.headcount.latest}}.</p></div>"
    '<div data-section-id="movers"><p>The largest move was {{fact:top_mover.name}} at '
    "{{fact:top_mover.delta_pct}}.</p></div>"
    "</div>"
)


class FakeClient:
    """Stand-in for :class:`SuperDocsClient` that records what it was asked to do."""

    def __init__(
        self,
        document: str = GOOD_DOCUMENT,
        *,
        fail_chat: Exception | None = None,
        fail_image: Exception | None = None,
        fail_export: Exception | None = None,
        pauses: list[str] | None = None,
    ) -> None:
        self.document = document
        self.fail_chat = fail_chat
        self.fail_image = fail_image
        self.fail_export = fail_export
        # Pause flavours to emit before completing, e.g. ["continue_prompt"].
        self.pauses = list(pauses or [])
        self.chat_calls: list[dict] = []
        self.saves: list[dict] = []
        self.exports: list[dict] = []
        self.continues: list[dict] = []
        self.approvals: list[dict] = []
        self.cancelled: list[str] = []
        self.images: int = 0

    async def upload_image(self, png: bytes, filename: str = "chart.png") -> str:
        if self.fail_image:
            raise self.fail_image
        self.images += 1
        return f"https://cdn.example.test/{filename}"

    async def start_chat(self, message, session_id, **kw):
        if self.fail_chat:
            raise self.fail_chat
        self.chat_calls.append({"message": message, "session_id": session_id, **kw})
        return f"job-{len(self.chat_calls)}"

    async def wait_for_job(self, job_id, **kw) -> JobState:
        if self.pauses:
            kind = self.pauses.pop(0)
            changes = []
            if kind != "continue_prompt":
                from narrative_report.superdocs import ProposedChange

                changes = [
                    ProposedChange("ch_1", "edit", "chunk-a", "<p>a</p>", "<p>b</p>", "why")
                ]
            return JobState(
                job_id=job_id,
                status="awaiting_approval",
                session_id="s",
                awaiting_kind=kind if kind == "continue_prompt" else None,
                pending_changes=changes,
                result=None,
            )
        return JobState(
            job_id=job_id,
            status="completed",
            session_id="s",
            awaiting_kind=None,
            pending_changes=[],
            result={"document_changes": {"updated_html": self.document}},
        )

    async def continue_chat(self, session_id, job_id, keep_going=True):
        self.continues.append({"job_id": job_id, "continue": keep_going})
        return {"status": "ok"}

    async def approve(self, session_id, job_id, decisions, **kw):
        self.approvals.append({"job_id": job_id, "decisions": decisions})
        return {"status": "ok"}

    async def cancel_job(self, job_id):
        self.cancelled.append(job_id)

    async def save_document(self, *a, **kw):
        self.saves.append(kw)
        return {"status": "ok"}

    async def export(self, **kw):
        if self.fail_export:
            raise self.fail_export
        self.exports.append(kw)
        return b"PK\x03\x04fake-docx", []


