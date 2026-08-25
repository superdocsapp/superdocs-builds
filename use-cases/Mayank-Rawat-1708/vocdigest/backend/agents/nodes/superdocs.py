"""
@file: backend/agents/nodes/superdocs.py
@description: The SuperDocs integration stage. Creates a session, uploads the digest
    template, optionally attaches last quarter's digest as searchable reference, then
    sends one targeted edit per approved section. Each edit runs in review mode, so
    SuperDocs proposes changes and we approve them explicitly. Finally exports the
    finished document to disk.
@flow: run() -> derive a stable session_id from run_id -> upload template ->
    for each approved section: send_edit() -> if it pauses for review, approve the
    proposed changes -> if it pauses to continue, answer continue -> verify via the free
    structure read -> export_document() -> write bytes to DATA_DIR.
@dependencies:
    - backend.services.superdocs_client.SuperDocsClient: all API interaction
    - backend.models.Run: stores session/document/job ids for resume
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from backend.agents.nodes.base import BaseNode, NodePause
from backend.agents.state import DigestState
from backend.config import MissingCredentialError, settings
from backend.db.checkpoint import set_run_status
from backend.db.database import session_scope
from backend.models import Run, RunStatus
from backend.services.local_render import render_digest
from backend.services.superdocs_client import (
    SuperDocsAuthError,
    SuperDocsClient,
    SuperDocsError,
    SuperDocsQuotaError,
    SuperDocsSessionBusy,
    SuperDocsTimeout,
)

logger = logging.getLogger(__name__)

# Order sections are applied in. Header first so later edits can anchor to real
# headings; methodology last so it can honestly describe what actually happened.
SECTION_ORDER = [
    "header",
    "executive_summary",
    "theme_table",
    # Charts go immediately after the section they annotate, so the anchor heading
    # already exists in the document when the chart edit is applied.
    "chart_volume",
    "fastest_growing",
    "chart_growth",
    "what_changed",
    "chart_comparison",
    "methodology",
]

# Per-theme deep-dive keys only. Excludes theme_table, which shares the prefix.
_DEEP_DIVE_KEY = re.compile(r"^theme_(\d+)$")

# Minimal starting document. SuperDocs edits target sections by name, so the template
# must contain the headings the instructions refer to.
TEMPLATE_HTML = """\
<h1>Voice-of-Customer Digest</h1>
<p>Generated from support conversations.</p>
<h2>Executive Summary</h2>
<p>To be completed.</p>
<h2>Top Themes This Quarter</h2>
<p>To be completed.</p>
<h2>Theme Deep Dives</h2>
<p>To be completed.</p>
<h2>Fastest Growing Issues</h2>
<p>To be completed.</p>
<h2>What Changed Since Last Quarter</h2>
<p>To be completed.</p>
<h2>Methodology</h2>
<p>To be completed.</p>
"""


class SuperDocsNode(BaseNode):
    stage = "superdocs"
    running_status = RunStatus.UPLOADING

    async def _render_locally(
        self, state: DigestState, run_id: uuid.UUID, reason: str
    ) -> DigestState:
        """Produce the digest without SuperDocs.

        Every analysis stage has already completed and been human-approved by the time
        this runs. Pausing here would strand all of that work over a service the content
        does not actually depend on, so we render the same approved sections locally and
        say plainly on the document which path produced it.
        """
        sections = state.get("draft_sections") or {}
        data_dir = Path(settings.data_dir) / "exports"
        quarter_slug = state.get("quarter_label", "digest").replace(" ", "-").lower()
        out_path = data_dir / f"{quarter_slug}-digest-{run_id}.docx"

        result = render_digest(
            sections,
            out_path,
            quarter_label=state.get("quarter_label", "This quarter"),
            conversation_count=state.get("conversations_relevant", 0),
            reason=reason,
        )

        async with session_scope() as session:
            run = await session.get(Run, run_id)
            if run:
                run.export_path = result["path"]
            await set_run_status(session, run_id, RunStatus.COMPLETE)

        await self.log_decision(
            run_id,
            "RENDERED_LOCALLY",
            f"SuperDocs unavailable ({reason}). Rendered the approved digest locally to "
            f"{Path(result['path']).name} ({result['bytes']} bytes, "
            f"{result['sections_rendered']} sections) rather than discarding the run.",
            {"path": result["path"], "format": result["format"]},
        )

        state["export_path"] = result["path"]
        state["rendered_locally"] = True
        state["superdocs_edits_sent"] = 0
        return state

    async def run(self, state: DigestState, run_id: uuid.UUID) -> DigestState:
        sections = state.get("draft_sections") or {}
        if not sections:
            raise NodePause(
                "Every draft section was rejected at the gate; nothing to publish",
                status=RunStatus.PAUSED,
            )

        # Deterministic session id derived from the run id. Reusing it on resume means
        # we reconnect to the same SuperDocs session rather than starting a new one.
        session_id = f"vocdigest-{run_id}"
        state["superdocs_session_id"] = session_id

        # No key configured at all.
        if not settings.superdocs_api_key:
            if settings.allow_local_render:
                return await self._render_locally(
                    state, run_id, "SUPERDOCS_API_KEY is not configured."
                )
            raise MissingCredentialError("SUPERDOCS_API_KEY", "publishing the digest")

        try:
            client = SuperDocsClient()
        except MissingCredentialError as exc:
            if settings.allow_local_render:
                return await self._render_locally(state, run_id, str(exc))
            raise

        edits_sent = 0
        approved_total = 0
        rejected_total = 0
        attempt_fresh_session = False

        try:
            try:
                key_ok = await client.verify_key()
            except SuperDocsError as exc:
                # Unreachable, DNS failure, TLS problem — indistinguishable from an
                # outage, and equally not worth stranding a completed run over.
                if settings.allow_local_render:
                    await client.aclose()
                    return await self._render_locally(
                        state, run_id, f"SuperDocs unreachable ({exc})."
                    )
                raise

            if not key_ok:
                if settings.allow_local_render:
                    await client.aclose()
                    return await self._render_locally(
                        state,
                        run_id,
                        "SuperDocs rejected the API key (check SUPERDOCS_API_KEY).",
                    )
                raise NodePause(
                    "SuperDocs rejected the API key. Check SUPERDOCS_API_KEY in .env.",
                    status=RunStatus.PAUSED,
                )

            # Load the template. document_html on the first turn is what creates the
            # document; every later turn omits it so the server's copy is authoritative.
            #
            # Deep dives are keyed theme_1, theme_2, ... The theme TABLE is keyed
            # theme_table, which also starts with "theme_". Matching on the prefix put it
            # in the list twice: confirmed against the live API, where it produced a
            # duplicate "Top Themes This Quarter" heading in the exported document and
            # spent an extra metered operation. Match the numeric form only, and sort
            # numerically so theme_10 follows theme_2 rather than preceding it.
            ordered_keys = [k for k in SECTION_ORDER if k in sections]

            deep_dive_matches = [
                (int(m.group(1)), k)
                for k in sections
                if (m := _DEEP_DIVE_KEY.match(k)) is not None
            ]
            deep_dives = [k for _, k in sorted(deep_dive_matches)]
            ordered_keys += deep_dives

            # Anything else the draft produced that is not already placed. dict.fromkeys
            # preserves order while removing duplicates, so a key cannot slip in twice.
            ordered_keys += [k for k in sections if k not in set(ordered_keys)]
            ordered_keys = list(dict.fromkeys(ordered_keys))

            # A retried run reuses its session id so it reconnects rather than
            # re-uploading. That means an abandoned job from the previous attempt is
            # still active, and SuperDocs allows only one per session — so the retry is
            # rejected with 409 session_busy. Clear those first.
            try:
                cleared = await client.clear_active_jobs(session_id)
                if cleared:
                    await self.log_decision(
                        run_id,
                        "CLEARED_STALE_JOBS",
                        f"Cancelled {cleared} unfinished job(s) left in session "
                        f"{session_id} by a previous attempt, which would otherwise have "
                        f"blocked this one with 409 session_busy.",
                        {"cancelled": cleared},
                    )
            except Exception as exc:
                # Non-fatal: if clearing fails we fall back to a fresh session below.
                logger.warning("Could not clear stale jobs: %s", exc)

            # Attach last quarter's digest so the AI can cite it if an instruction
            # references it. Read-only: it never becomes the editable document.
            prior = state.get("last_digest_path")
            if prior and Path(prior).is_file():
                try:
                    await client.upload_attachment(prior, session_id)
                    await self.log_decision(
                        run_id,
                        "ATTACHED_PRIOR",
                        f"Attached {Path(prior).name} as read-only reference",
                    )
                except Exception as exc:
                    # Non-fatal: the comparison numbers already live in our own DB.
                    logger.warning("Prior digest attachment failed: %s", exc)

            document_html: str | None = TEMPLATE_HTML

            index = 0
            while index < len(ordered_keys):
                key = ordered_keys[index]
                index += 1
                instruction = sections[key]

                # A completed job id does not mean a free session: approving changes can
                # leave follow-on work in flight. Sending the next edit on that assumption
                # is what produced 409 session_busy partway through a run.
                if edits_sent:
                    freed = await client.wait_for_session_free(session_id)
                    if not freed:
                        cleared = await client.clear_active_jobs(session_id)
                        await self.log_decision(
                            run_id,
                            "SESSION_STUCK",
                            f"Session did not free itself before section '{key}'. "
                            f"Cancelled {cleared} lingering job(s) and continued.",
                            {"section": key, "cancelled": cleared},
                        )

                try:
                    result = await client.send_edit(
                        session_id,
                        instruction,
                        document_html=document_html,
                        require_approval=True,
                    )
                except (SuperDocsQuotaError, SuperDocsAuthError) as exc:
                    # Out of credits, or the key stopped working mid-run. Neither is
                    # fixable by waiting inside this run, and the content is already
                    # approved, so finish locally rather than stranding it.
                    if settings.allow_local_render:
                        return await self._render_locally(
                            state,
                            run_id,
                            f"SuperDocs stopped accepting requests after {edits_sent} "
                            f"section(s): {exc}",
                        )
                    raise NodePause(
                        f"SuperDocs quota or credentials failed after {edits_sent} "
                        f"section(s): {exc}",
                        status=RunStatus.PAUSED,
                    ) from exc
                except SuperDocsSessionBusy as exc:
                    # Clearing did not work — the job may be uncancellable. Rather than
                    # blocking the run permanently on a session we cannot reclaim, move
                    # to a fresh one and re-upload. Costs one extra upload; the
                    # alternative is a run that can never complete.
                    if attempt_fresh_session:
                        raise NodePause(
                            f"SuperDocs session is still busy after a fresh session was "
                            f"tried: {exc}",
                            status=RunStatus.PAUSED,
                        ) from exc
                    attempt_fresh_session = True
                    session_id = f"{session_id}-r{uuid.uuid4().hex[:6]}"
                    state["superdocs_session_id"] = session_id
                    await self.log_decision(
                        run_id,
                        "NEW_SESSION",
                        f"Previous session had an unclearable active job. Continuing in "
                        f"a fresh session {session_id} and re-uploading the template.",
                    )
                    document_html = TEMPLATE_HTML
                    remaining = ordered_keys[ordered_keys.index(key):]
                    ordered_keys = remaining
                    index = 0
                    continue

                except SuperDocsTimeout as exc:
                    # The operation is very likely still running server-side. Record the
                    # job id and pause rather than declaring the run dead.
                    async with session_scope() as session:
                        run = await session.get(Run, run_id)
                        if run:
                            run.superdocs_job_id = exc.job_id
                    raise NodePause(
                        f"SuperDocs edit for section '{key}' exceeded the poll budget. "
                        f"Job {exc.job_id} is probably still running — resume this run "
                        f"to continue polling.",
                        status=RunStatus.PAUSED,
                    ) from exc

                document_html = None  # server holds it from here on
                edits_sent += 1
                self.superdocs_operations += max(result.ops_charged, 1)

                # A large edit can pause to ask whether to keep going. That is a
                # different pause from change review and needs a different endpoint.
                while result.awaiting_continue:
                    await self.log_decision(
                        run_id,
                        "CONTINUE_PROMPT",
                        f"Section '{key}' paused mid-edit; continuing. "
                        f"{result.continue_prompt}",
                    )
                    result = await client.continue_edit(
                        session_id, result.job_id, proceed=True
                    )

                if result.awaiting_approval:
                    change_ids = [c.change_id for c in result.pending_changes]
                    # The gate already ran. Sections that reached this point are
                    # human-approved content, so we accept the edits that implement
                    # them; anything SuperDocs proposes beyond the instruction would
                    # show up here as an extra change and can be rejected.
                    approved_ids = change_ids
                    rejected_ids: list[str] = []
                    result = await client.approve_changes(
                        session_id,
                        result.job_id,
                        approved_ids=approved_ids,
                        rejected_ids=rejected_ids,
                    )
                    approved_total += len(approved_ids)
                    rejected_total += len(rejected_ids)

                    await self.log_decision(
                        run_id,
                        "SECTION_APPLIED",
                        f"Section '{key}': approved {len(approved_ids)} proposed change(s)",
                        {"section": key, "changes": len(approved_ids)},
                    )

                if not result.completed:
                    logger.warning(
                        "Section %s settled in unexpected state %s", key, result.status
                    )

            # Record ids so a resumed run reconnects instead of re-uploading.
            documents = await client.list_session_documents(session_id)
            document_id = None
            if documents:
                document_id = documents[0].get("durable_document_id") or documents[
                    0
                ].get("document_id")
                state["superdocs_document_id"] = document_id

            # Free structural verification. Exporting just to check would be wasteful,
            # and the docs are explicit that this is the intended check.
            if document_id:
                try:
                    structure = await client.get_document_structure(document_id)
                    headings = [h.get("text") for h in structure.get("headings", [])]
                    await self.log_decision(
                        run_id,
                        "VERIFIED",
                        f"Document structure confirms {structure.get('section_count', 0)} "
                        f"sections: {headings[:8]}",
                        {"section_count": structure.get("section_count")},
                    )
                except Exception as exc:
                    logger.warning("Structure verification failed (non-fatal): %s", exc)

            # --- export ---
            data_dir = Path(settings.data_dir) / "exports"
            data_dir.mkdir(parents=True, exist_ok=True)
            quarter_slug = state.get("quarter_label", "digest").replace(" ", "-").lower()
            out_path = data_dir / f"{quarter_slug}-digest-{run_id}.docx"

            content = await client.export_document(
                session_id, fmt="docx", filename=out_path.stem
            )
            out_path.write_bytes(content)

            async with session_scope() as session:
                run = await session.get(Run, run_id)
                if run:
                    run.superdocs_session_id = session_id
                    run.superdocs_document_id = document_id
                    run.export_path = str(out_path)
                await set_run_status(session, run_id, RunStatus.COMPLETE)

            await self.log_decision(
                run_id,
                "EXPORTED",
                f"Exported digest to {out_path.name} ({len(content)} bytes) after "
                f"{edits_sent} section edits",
                {"path": str(out_path), "bytes": len(content)},
            )

            state["superdocs_edits_sent"] = edits_sent
            state["superdocs_changes_approved"] = approved_total
            state["superdocs_changes_rejected"] = rejected_total
            state["export_path"] = str(out_path)
            return state

        finally:
            await client.aclose()