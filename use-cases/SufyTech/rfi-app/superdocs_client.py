"""
superdocs_client.py — thin wrapper around the real SuperDocs REST API
(api.superdocs.app), built against docs.superdocs.app's documented
endpoints as of this build (fetched and read directly, not guessed).

Endpoints used here, all confirmed to accept sk_ API keys per the docs'
own "Endpoints that accept API keys" list:
  - POST /v1/documents/upload-base64   (load the costed recipe doc)
  - POST /v1/chat                      (synchronous AI edit / polish)
  - POST /v1/chat/async                (HITL-approved targeted re-cost edit)
  - GET  /v1/jobs/{job_id}             (poll an async job)
  - POST /v1/chat/{session_id}/approve (approve/deny proposed changes)
  - GET  /v1/sessions/{session_id}/history (fetch the session's real
    current document state - used by verify_and_get_final_html below)
  - POST /v1/documents/export          (export final docx, from either
    a session_id OR raw html directly - both accepted per the docs)

REAL BUG FOUND AND FIXED HERE, logged honestly: a live run showed
menu-costing-sheet-updated.docx still had the OLD ingredient price
after approve_change() returned success - export_document(session_id=...)
called immediately after approval doesn't reliably reflect the just-
approved edit yet (a server-side timing issue, not a client bug).
verify_and_get_final_html() below is the real fix: instead of trusting
export's session-based snapshot, it fetches the session's actual
current state via GET /v1/sessions/{id}/history, checks whether each
approved change genuinely landed, patches locally (verbatim old_html
-> new_html replacement, same proven-correct technique already used for
manual recovery) if it hasn't, and raises loudly rather than exporting
something possibly wrong if a change can't be verified either way.
export_html() then exports from that VERIFIED html directly, never
from the session's own (possibly still-stale) state.

SECOND REAL BUG FOUND AND FIXED HERE, logged honestly: a live run
corrupted an UNAFFECTED dish (Truffle Fries) with a different dish's
numbers in the exported file. Root cause: verify_and_get_final_html's
local-patch fallback did `doc_html.replace(old_html, new_html, 1)` -
a blind, whole-document string replace that patches whichever
occurrence of old_html it finds FIRST, with no check that the match it
found actually belongs to the chunk it's supposed to belong to. If two
dishes happen to share identical HTML text for a changed chunk (same
ingredient line, same formatting), this could silently patch the WRONG
dish's occurrence while leaving the right one untouched - exactly the
"only affected lines are touched" guarantee this build promises,
broken silently. Fixed by counting occurrences first: a single match
patches safely as before; more than one match is now treated exactly
like "can't verify" already was - raise loudly, naming the chunk and
the match count, rather than guessing which occurrence is the right
one. This is the same fail-closed discipline this function already
used for the "neither old nor new text found" case, now extended to
cover "found, but ambiguously."
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Optional

import requests

API_BASE = "https://api.superdocs.app/v1"
DEFAULT_TIMEOUT_SECONDS = 60


def _normalize_for_compare(html_str: str) -> str:
    """
    REAL BUG FOUND AND FIXED HERE, logged honestly: a live Build 2 run
    showed a change that had genuinely landed correctly (the document
    already contained the right answered-RFI content) still fail
    verify_and_get_final_html's exact containment check, because the
    server self-closes void elements ("<br>" -> "<br/>") and
    HTML-escapes bare ampersands ("&" -> "&amp;") when it stores a
    document. A freshly-built old_html/new_html fragment uses plain
    "<br>" and a raw "&", so it can never byte-for-byte match the
    server's stored form even when the underlying content is identical.
    This canonicalizes both sides to the server's known serialization
    style before any containment/count check, so genuine content
    matches aren't missed on formatting differences alone. It does
    NOT touch the "neither old nor new found" fail-closed raise for
    genuinely-ambiguous cases - only widens what counts as a match.
    """
    import re

    normalized = re.sub(r"<br\s*/?>", "<br/>", html_str, flags=re.IGNORECASE)
    normalized = re.sub(r"&(?!amp;|lt;|gt;|quot;|#39;|apos;)", "&amp;", normalized)
    return normalized


@dataclass
class SuperDocsClient:
    api_key: str

    def _headers(self, json_body: bool = True) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def upload_document_html_as_base64(self, html: str, filename: str, session_id: str) -> dict:
        """
        Loads `html` as the active editable document in `session_id` via
        POST /v1/documents/upload-base64. Using base64-encoded HTML
        rather than a real .docx keeps this build self-contained (no
        binary fixture files to ship), and the docs explicitly note this
        endpoint also works for "AI-generated content ... uploaded as
        the working doc" - exactly this build's use case.
        """
        encoded = base64.b64encode(html.encode("utf-8")).decode("ascii")
        response = requests.post(
            f"{API_BASE}/documents/upload-base64",
            headers=self._headers(),
            json={
                "file_base64": encoded,
                "filename": filename,
                "content_type": "text/html",
                "session_id": session_id,
            },
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def chat(self, session_id: str, message: str, document_html: Optional[str] = None) -> dict:
        """Synchronous AI edit — POST /v1/chat. Used for the initial
        polish pass (write plating-note prose, tidy formatting)."""
        payload = {"session_id": session_id, "message": message}
        if document_html is not None:
            payload["document_html"] = document_html
        response = requests.post(
            f"{API_BASE}/chat",
            headers=self._headers(),
            json=payload,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def chat_async(self, session_id: str, message: str, approval_mode: str = "ask_every_time") -> dict:
        """
        Starts an HITL-approved async edit — POST /v1/chat/async. Used
        for the re-cost pass so every targeted ingredient-line edit is
        reviewed before it lands, per required "approve" step of this
        build's minimum-4-calls requirement (upload, chat, approve,
        export).
        """
        response = requests.post(
            f"{API_BASE}/chat/async",
            headers=self._headers(),
            json={"session_id": session_id, "message": message, "approval_mode": approval_mode},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def get_job(self, job_id: str) -> dict:
        """GET /v1/jobs/{job_id} — poll an async job's status."""
        response = requests.get(
            f"{API_BASE}/jobs/{job_id}",
            headers=self._headers(json_body=False),
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def wait_for_job(self, job_id: str, poll_seconds: float = 2.0, max_wait_seconds: float = 300.0) -> dict:
        """
        Polls get_job until status is no longer pending/processing/
        in_progress. Returns the final job dict. Raises TimeoutError
        past max_wait_seconds rather than hanging silently forever.

        REAL BUG FOUND AND FIXED HERE, logged honestly: this originally
        only waited while status was "pending" or "processing", but a
        live run showed the API actually reports "in_progress" while a
        job is still running - a status this method didn't recognize,
        so it returned on the very first poll while the job was still
        working, with 0 pending_changes, and run_build1.py silently
        skipped the approval step and exported a pre-edit snapshot
        without erroring. Confirmed against run_build1.py's own 409-retry
        loop, which already polls with `status != "in_progress"` - this
        method just hadn't matched that. Fixed to wait through
        "in_progress" too.
        """
        BUSY_STATUSES = ("pending", "processing", "in_progress")
        waited = 0.0
        while waited < max_wait_seconds:
            job = self.get_job(job_id)
            if job.get("status") not in BUSY_STATUSES:
                return job
            time.sleep(poll_seconds)
            waited += poll_seconds
        raise TimeoutError(f"job {job_id} did not settle within {max_wait_seconds}s")

    def approve_change(
        self,
        session_id: str,
        job_id: str,
        approved: bool,
        chunk_id: Optional[str] = None,
        changes: Optional[list[dict]] = None,
        feedback: Optional[str] = None,
    ) -> dict:
        """
        POST /v1/chat/{session_id}/approve — approve or deny AI-proposed
        change(s).

        CORRECTED AGAIN based on live server evidence, not a docs-based
        theory (logged honestly, since the previous version of this
        method was itself a "fix" that turned out wrong): a real live
        run's 422 response explicitly reported `job_id` and `approved`
        as required fields, even when a `changes` array was also
        supplied:

            {"detail":[
                {"loc":["body","job_id"],"msg":"Field required",...},
                {"loc":["body","approved"],"msg":"Field required",...}
            ]}

        That's direct proof the "two distinct modes, never combine
        job_id/approved with changes" theory (from an earlier pass,
        based on reading the docs) was incorrect. The live API's own
        validation error is the real contract here - `job_id` and
        `approved` are always required, `chunk_id`/`changes`/`feedback`
        are added on top as applicable.

        Prefer approve_changes() below for batches — it wraps this
        method with a fallback strategy for the real 500 error a
        subsequent live run hit when passing a `changes` array here.
        """
        payload: dict = {"job_id": job_id, "approved": approved}
        if chunk_id is not None:
            payload["chunk_id"] = chunk_id
        if changes is not None:
            payload["changes"] = changes
        if feedback is not None:
            payload["feedback"] = feedback

        response = requests.post(
            f"{API_BASE}/chat/{session_id}/approve",
            headers=self._headers(),
            json=payload,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def approve_changes(
        self,
        session_id: str,
        job_id: str,
        change_records: list[dict],
        approved: bool,
    ) -> dict:
        """
        Approves or rejects a whole batch of changes for one job.

        REAL BUG FOUND HERE, logged honestly: a live run sent a batch
        `changes` array where each item was `{"chunk_id": ..., "approved":
        ...}` (chunk_id copied straight from each pending_changes record)
        and got a genuine 500 Internal Server Error with no further detail
        in the response body - unlike the earlier 422, a 500 gives no clue
        about which field was wrong. Best-supported theory, not confirmed:
        each pending_changes record actually carries BOTH a `change_id`
        (that specific change's own identifier) and a `chunk_id` (which
        part of the document it touches) - `change_id` is more likely the
        correct per-item key for a batch decision than `chunk_id` is.

        Rather than gamble an entire live run on that theory alone, this
        method tries it first, and if the batch call fails for ANY reason,
        automatically falls back to approving every change ONE AT A TIME
        via the simple, already-proven single-decision shape (`job_id` +
        `approved` + `chunk_id`, no `changes` array) - a much smaller
        surface area for a batch-specific server-side bug to hide in.
        This makes the approval step self-healing across two independent
        strategies in one live run, instead of needing another
        guess-fix-rerun round trip if the first theory is also wrong.

        Returns {"mode": "batch" | "fallback_per_item", "results": [...]}
        so the caller (and this build's README) can report which path
        actually worked.
        """
        changes_payload = [
            {
                "change_id": record.get("change_id", record.get("chunk_id")),
                "chunk_id": record["chunk_id"],
                "approved": approved,
            }
            for record in change_records
        ]
        try:
            result = self.approve_change(
                session_id=session_id, job_id=job_id, approved=approved, changes=changes_payload
            )
            return {"mode": "batch", "results": [result]}
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            print(
                f"    [approve_changes] batch approval failed (HTTP {status}) - "
                f"falling back to approving {len(change_records)} change(s) one at a time..."
            )
            results = []
            for record in change_records:
                result = self.approve_change(
                    session_id=session_id, job_id=job_id, approved=approved, chunk_id=record["chunk_id"]
                )
                results.append(result)
            return {"mode": "fallback_per_item", "results": results}

    def get_session_history(self, session_id: str) -> dict:
        """
        GET /v1/sessions/{session_id}/history — the session's real
        current state, including document_state.html_content. This is
        the source of truth verify_and_get_final_html checks against,
        since (per the real bug found here) export_document's own
        snapshot can lag behind a just-approved edit.
        """
        response = requests.get(
            f"{API_BASE}/sessions/{session_id}/history",
            headers=self._headers(json_body=False),
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def wait_for_upload_to_settle(
        self,
        session_id: str,
        expected_marker: str,
        poll_seconds: float = 2.0,
        max_wait_seconds: float = 30.0,
    ) -> None:
        """
        THIRD REAL BUG FOUND AND FIXED HERE, logged honestly: a live run
        showed the fixed `time.sleep(5)` guess this build used after
        upload was NOT always long enough - a subsequent chat_async call
        ran against a session that still held a completely different,
        unrelated document (a generic "Professional Services Proposal"
        template, not the uploaded menu), and the AI correctly reported
        it couldn't find any of the requested dishes. This is far worse
        than a cosmetic delay: silently proceeding on an unverified
        upload risks running the whole re-cost edit against the wrong
        document entirely. (The build's own fail-closed "0
        pending_changes -> raise, don't export" guard caught this
        specific run rather than silently shipping a wrong result - but
        that's a safety net, not a fix for the actual race.)

        Fixed the same way every other "did this really happen" question
        in this build is answered - not by waiting longer and hoping,
        but by fetching the session's REAL current state via
        get_session_history and checking `expected_marker` (a string
        unique to the uploaded document, e.g. its title) is actually
        present before proceeding. Retries on a short poll until it
        shows up or max_wait_seconds is exhausted, then raises loudly
        rather than letting the caller proceed against an unverified
        document.
        """
        waited = 0.0
        while waited < max_wait_seconds:
            history = self.get_session_history(session_id)
            doc_html = history.get("document_state", {}).get("html_content", "") or ""
            if expected_marker in doc_html:
                return
            time.sleep(poll_seconds)
            waited += poll_seconds
        raise RuntimeError(
            f"wait_for_upload_to_settle: session {session_id!r} still did not contain "
            f"{expected_marker!r} after {max_wait_seconds}s. The upload may not have "
            f"landed, or landed on the wrong session - refusing to proceed and risk "
            f"running an edit instruction against the wrong document."
        )

    def verify_and_get_final_html(self, session_id: str, expected_changes: list[dict]) -> str:
        """
        THE FIX for the real export-staleness bug (see module docstring).

        `expected_changes` is the same list of {"chunk_id", "old_html",
        "new_html"} dicts already used to build the approve_change()
        payload (i.e. job["metadata"]["pending_changes"]).

        For each expected change:
          - if new_html is already present in the session's real current
            HTML (fetched fresh via get_session_history) -> it genuinely
            landed, nothing to do.
          - elif old_html is present EXACTLY ONCE -> it has NOT landed
            yet; patch it locally with a single verbatim replacement
            (the same proven-correct technique already used for manual
            recovery), so the exported file is correct even though the
            server hadn't caught up yet.
          - elif old_html is present MORE THAN ONCE -> ambiguous: this
            function has no way to know which occurrence is the one
            this chunk actually refers to, and guessing risks silently
            patching a different, unaffected section (the real
            Truffle-Fries-corruption bug found on a live run - see
            module docstring). NEVER guess - raise RuntimeError instead.
          - else -> neither the old nor the new text can be found
            verbatim. This is genuinely ambiguous (the AI may have
            reworded the surrounding HTML) and must NEVER be silently
            exported as either "it worked" or "it didn't" - raises
            RuntimeError naming the chunk_id instead, so a human sees
            the ambiguity rather than getting a possibly-wrong .docx.

        Returns the verified (and, if needed, locally patched) HTML,
        ready to hand directly to export_html().
        """
        history = self.get_session_history(session_id)
        doc_html = history["document_state"]["html_content"]

        for change in expected_changes:
            chunk_id = change.get("chunk_id", "<unknown>")
            old_html = change.get("old_html")
            new_html = change.get("new_html")
            if new_html is None:
                # Nothing to verify for this entry - approve_change()
                # decisions built purely from chunk_id (no old/new text)
                # never reach here in practice, but skip rather than
                # crash if they ever do.
                continue
            if _normalize_for_compare(new_html) in doc_html:
                continue  # already landed for real (normalization-tolerant)

            if old_html is not None:
                old_html_norm = _normalize_for_compare(old_html)
                new_html_norm = _normalize_for_compare(new_html)
                match_count = doc_html.count(old_html_norm)
                if match_count == 1:
                    doc_html = doc_html.replace(old_html_norm, new_html_norm, 1)
                    continue
                if match_count > 1:
                    raise RuntimeError(
                        f"verify_and_get_final_html: chunk {chunk_id!r}'s old_html appears "
                        f"{match_count} times in the current document - ambiguous, refusing "
                        f"to guess which occurrence belongs to this chunk. Patching the wrong "
                        f"occurrence would silently corrupt an unaffected section. Inspect the "
                        f"document manually before re-running."
                    )

            raise RuntimeError(
                f"verify_and_get_final_html: change for chunk {chunk_id!r} could not be "
                f"verified as landed OR as still-pending - neither its old_html nor its "
                f"new_html was found verbatim in the session's current document. Refusing "
                f"to export a document that might not reflect this approved change."
            )

        return doc_html

    def export_document(
        self,
        session_id: str,
        output_path: str,
        format: str = "docx",
        filename: Optional[str] = None,
    ) -> str:
        """
        POST /v1/documents/export — exports the SESSION'S CURRENT state
        (whatever the server has on file for session_id right now) and
        writes the binary response to output_path. Returns output_path.

        Only safe to use directly when nothing was just approved on this
        session (e.g. the exceptions report's plain upload-then-export
        flow, with no chat_async/approve step in between). For any
        export that follows an approval, use verify_and_get_final_html()
        + export_html() instead - see the module docstring's "REAL BUG
        FOUND AND FIXED HERE" note for why.
        """
        options = {}
        if filename:
            options["filename"] = filename

        response = requests.post(
            f"{API_BASE}/documents/export",
            headers=self._headers(),
            json={"session_id": session_id, "format": format, "options": options},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(response.content)
        return output_path

    def export_html(
        self,
        html: str,
        output_path: str,
        format: str = "docx",
        filename: Optional[str] = None,
    ) -> str:
        """
        POST /v1/documents/export — exports RAW HTML DIRECTLY (never a
        session_id), so the exported file reflects exactly the verified
        HTML the caller hands it, not whatever a session's own snapshot
        happens to contain at that moment. This is what
        verify_and_get_final_html()'s result should always be exported
        through.
        """
        options = {}
        if filename:
            options["filename"] = filename

        response = requests.post(
            f"{API_BASE}/documents/export",
            headers=self._headers(),
            json={"html": html, "format": format, "options": options},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(response.content)
        return output_path
