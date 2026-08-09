"""Ties parsing, diffing, section mapping, the SuperDocs HITL workflow, the
untouched-section proof, and the amendment-response log into one run.

One call per impacted section is sent to SuperDocs, and each is fully
resolved (proposed -> reviewed -> approved/denied -> applied) before the
next section is staged. This matches a real constraint of the API: a
session with a pending `awaiting_approval` job blocks new turns until it is
resolved, so sections cannot be proposed in parallel on one session.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .diff_engine import apply_batch, build_baseline_state
from .integrity import verify_untouched
from .log_generator import build_amendment_response_log
from .models import AmendmentDelta, Confirmation, Conflict, ReviewItem, SectionImpact
from .parsing import parse_amendment, parse_qna, parse_solicitation
from .section_mapper import SectionMapConfig, map_impacts, untouched_sections
from .superdocs_client import SuperDocsClientProtocol

# decide_fn receives the list of ReviewItems for one staged section and must
# return {change_id: (approved: bool, feedback: Optional[str])} for every item.
DecideFn = Callable[[List[ReviewItem]], Dict[str, Tuple[bool, Optional[str]]]]

_SECTION_ID_ATTR_RE = re.compile(r'data-section-id="([^"]+)"')
_CHUNK_ID_ATTR_RE = re.compile(r'data-chunk-id="([^"]+)"')


def approve_all(items: List[ReviewItem]) -> Dict[str, Tuple[bool, Optional[str]]]:
    return {i.change_id: (True, None) for i in items}


class DeltaApplierRun:
    def __init__(self, client: SuperDocsClientProtocol, section_map_path: str, session_id: str):
        self.client = client
        self.config = SectionMapConfig.load(section_map_path)
        self.session_id = session_id

        self.state: dict = {}
        self.deltas: List[AmendmentDelta] = []
        self.confirmations: List[Confirmation] = []
        self.conflicts: List[Conflict] = []
        self.impacts: Dict[str, SectionImpact] = {}
        self.review_items: List[ReviewItem] = []

        self.proposal_html_before: Optional[str] = None
        self.proposal_html_after: Optional[str] = None
        # Populated by load_proposal(). SuperDocs discards our own
        # data-section-id attribute on ingest and assigns its own
        # data-chunk-id per chunk; this maps our human-readable section ids
        # to the real ids that appear in the html SuperDocs hands back, so
        # instructions and the untouched-section proof can address chunks
        # by an id that actually exists in the document. Empty when the
        # document round-trips with data-section-id intact (e.g. the fakes
        # used in tests), in which case we address sections directly.
        self.section_id_to_chunk_id: Dict[str, str] = {}

    # ---- ingestion --------------------------------------------------

    def ingest_baseline(self, solicitation_text: str, document: str = "solicitation.txt") -> None:
        self.state = build_baseline_state(parse_solicitation(solicitation_text, document))

    def ingest_amendment(self, text: str, document: str) -> None:
        result = apply_batch(self.state, parse_amendment(text, document))
        self.deltas.extend(result.deltas)
        self.confirmations.extend(result.confirmations)
        self.conflicts.extend(result.conflicts)

    def ingest_qna(self, text: str, document: str) -> None:
        result = apply_batch(self.state, parse_qna(text, document))
        self.deltas.extend(result.deltas)
        self.confirmations.extend(result.confirmations)
        self.conflicts.extend(result.conflicts)

    # ---- mapping ------------------------------------------------------

    def compute_impacts(self) -> Dict[str, SectionImpact]:
        self.impacts = map_impacts(self.deltas, self.config)
        return self.impacts

    def untouched_sections(self) -> List[str]:
        return untouched_sections(self.config, self.impacts)

    # ---- SuperDocs workflow --------------------------------------------

    def load_proposal(self, proposal_path: str) -> dict:
        upload = self.client.upload_document(proposal_path, self.session_id)
        self.proposal_html_before = upload["html"]
        self.proposal_html_after = upload["html"]
        self.section_id_to_chunk_id = self._build_chunk_id_map(proposal_path, self.proposal_html_before)
        return upload

    def _build_chunk_id_map(self, proposal_path: str, uploaded_html: str) -> Dict[str, str]:
        original_html = Path(proposal_path).read_text(encoding="utf-8")
        section_ids = _SECTION_ID_ATTR_RE.findall(original_html)
        chunk_ids = _CHUNK_ID_ATTR_RE.findall(uploaded_html)
        if not chunk_ids or len(chunk_ids) != len(section_ids):
            # Either the round trip preserved data-section-id (no chunk
            # ids present at all -- true for the fakes in tests), or the
            # chunk count didn't line up 1:1 with our sections. Either way,
            # fall back to addressing sections by our own attribute rather
            # than guessing a positional mapping we can't trust.
            return {}
        return dict(zip(section_ids, chunk_ids))

    def _target_ref(self, section_id: str) -> Tuple[str, str]:
        """Returns (attr, value) identifying `section_id` in the live document."""
        chunk_id = self.section_id_to_chunk_id.get(section_id)
        if chunk_id:
            return "data-chunk-id", chunk_id
        return "data-section-id", section_id

    def _build_instruction(self, section_id: str, impact: SectionImpact) -> str:
        citation_lines = "\n".join(
            f'- {d.source.citation()}: {d.change_kind} {d.rule_type}/{d.key} '
            f'from {d.old_value!r} to {d.new_value!r} — "{d.source.paragraph_text}"'
            for d in impact.deltas
        )
        order_note = (
            f"This section is a SECOND-ORDER effect of the change to {impact.caused_by_section}."
            if impact.order == "second_order"
            else "This section is DIRECTLY named by the amendment."
        )
        attr, value = self._target_ref(section_id)
        return (
            f'Update the proposal section with {attr}="{value}" (solicitation section {section_id}) so it stays '
            f"compliant with the solicitation change(s) below. {order_note}\n{citation_lines}\n"
            "Only change this section's own content. Do not alter any other section."
        )

    def run_section(
        self,
        section_id: str,
        impact: SectionImpact,
        decide_fn: DecideFn,
        model_tier: Optional[str] = None,
        is_first_call: bool = False,
    ) -> List[ReviewItem]:
        message = self._build_instruction(section_id, impact)
        job_id = self.client.start_edit(
            self.session_id,
            message,
            document_html=self.proposal_html_after if is_first_call else None,
            approval_mode="ask_every_time",
            model_tier=model_tier,
        )
        job = self.client.poll_job(job_id)

        if job.get("status") != "awaiting_approval":
            # Honest reporting, not a bluff: the model proposed nothing for
            # this section (or the job failed upstream and was already
            # raised by the client). Nothing to review, nothing to commit.
            return []

        pending = (job.get("metadata") or {}).get("pending_changes") or []
        items = [
            ReviewItem(
                change_id=change["change_id"],
                job_id=job_id,
                session_id=self.session_id,
                section_id=section_id,
                operation=change.get("operation", "edit"),
                old_html=change.get("old_html"),
                new_html=change.get("new_html"),
                ai_explanation=change.get("ai_explanation", ""),
                deltas=list(impact.deltas),
            )
            for change in pending
        ]

        decisions = decide_fn(items)
        now = datetime.now(timezone.utc).isoformat()
        decision_payload = []
        for item in items:
            approved, feedback = decisions.get(item.change_id, (False, None))
            item.approved = approved
            item.feedback = feedback
            item.decided_at = now
            entry = {"change_id": item.change_id, "approved": bool(approved)}
            if feedback:
                entry["feedback"] = feedback
            decision_payload.append(entry)

        self.client.approve(self.session_id, job_id, decision_payload, default_approved=True)
        final_job = self.client.poll_job(job_id)
        if final_job.get("status") == "completed":
            result = final_job.get("result") or {}
            updated_html = (result.get("document_changes") or {}).get("updated_html")
            if updated_html:
                self.proposal_html_after = updated_html

        self.review_items.extend(items)
        return items

    def run_all(self, decide_fn: DecideFn = approve_all, model_tier: Optional[str] = None) -> List[ReviewItem]:
        if not self.impacts:
            self.compute_impacts()
        first = True
        for section_id, impact in self.impacts.items():
            self.run_section(section_id, impact, decide_fn, model_tier=model_tier, is_first_call=first)
            first = False
        return self.review_items

    # ---- proof + reporting ---------------------------------------------

    def verify_untouched(self):
        section_ids = self.untouched_sections()
        if self.section_id_to_chunk_id:
            attr = "data-chunk-id"
            target_ids = [self.section_id_to_chunk_id.get(sid, sid) for sid in section_ids]
        else:
            attr = "data-section-id"
            target_ids = section_ids
        proofs_by_target = verify_untouched(
            self.proposal_html_before or "",
            self.proposal_html_after or "",
            target_ids,
            attr=attr,
        )
        chunk_to_section = {v: k for k, v in self.section_id_to_chunk_id.items()}
        return {chunk_to_section.get(target_id, target_id): proof for target_id, proof in proofs_by_target.items()}

    def build_log(self, solicitation_no: str) -> str:
        return build_amendment_response_log(
            solicitation_no=solicitation_no,
            deltas=self.deltas,
            confirmations=self.confirmations,
            conflicts=self.conflicts,
            impacts=self.impacts,
            review_items=self.review_items,
            untouched_proofs=self.verify_untouched(),
        )

    def export_proposal(self, out_path: str, format: str = "docx", options: Optional[dict] = None) -> str:
        content = self.client.export(session_id=self.session_id, format=format, options=options)
        with open(out_path, "wb") as f:
            f.write(content)
        return out_path
