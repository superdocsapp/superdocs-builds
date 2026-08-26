"""
rfi_patch.py — forces every Status-bearing surface in the RFI document
(the header table's Status cell AND the Response block's Status,
Responded By, Date Responded, Cost Impact, Schedule Impact, and
response text) to match the known-correct values from the response
event, the same way Build 1's value_patch.py force-patches derived
costing values after an AI edit.

WHY THIS EXISTS, logged honestly up front rather than discovered the
hard way a second time: Build 1's live testing proved, repeatedly, that
SuperDocs' AI edit does not reliably update every field it's asked to
touch in one instruction — sometimes a "derived"/secondary field gets
left stale even though the primary field updates correctly (see Build
1's README, Bugs 8-9). There is no reason to assume a differently-
shaped document is immune to the same failure mode, and re-discovering
it live here — on a build that's explicitly graded on whether the
document "carries both references correctly" — would be a worse use of
a live run than simply defending against a known class of bug up front.
This module is that defense: never trust the AI's edit was complete,
always force the known-correct values afterward, and raise loudly if a
field can't be found rather than silently leaving it stale.

BUG FOUND (documented, not just fixed): the header table's own Status
cell is written once from `rfi.status` at initial upload and is never
part of the chat_async edit instruction or the response chunk — so
without the fix below, it stays "Open" forever, even in a fully
answered RFI. The Response block correctly says "Answered" a few lines
down, so the exported document contradicted itself. Caught by manually
reading a live-exported .docx field-by-field, not by the test suite —
the test that used to guard exactly this (a stale header Status cell)
predated the chunk_id redesign and was never updated to call this
function's current 3-arg signature, so it silently stopped running the
check it was written for. Status is a response-derived field, not an
initial-upload-only field like Question/Spec Section/Drawing Reference,
so patching it here — alongside the Response block — is the same class
of fix as everything else in this module, not an exception to it.

What this must never do:
  - never invent a value — every patched field comes directly from the
    response event dict passed in, verbatim
  - never touch the Question, Spec Section, or Drawing Reference fields
    — those were correct from the initial upload and are never part of
    the response event, so patching them would risk masking a real bug
    in the initial document instead of the response
  - never silently skip a field it can't find — raises loudly, same
    fail-closed discipline as Build 1's export-staleness and
    value-patch fixes
"""

from __future__ import annotations

import re

_HEADER_STATUS_PATTERN = re.compile(
    r"(<tr><td><strong>Status</strong></td><td)([^>]*)(>)[^<]*(</td></tr>)"
)


def _patch_header_status(html: str, status: str) -> str:
    """
    Fixes the header table's Status cell, which lives outside the
    Response chunk entirely (it's written once at initial upload and
    never touched by the chat_async edit), so the chunk-scoped patch
    below can never reach it. Preserves any attributes the server may
    have added to the cell (see the data-chunk-id precedent in the
    Response-block tests) — only the value inside changes.
    """
    patched, count = _HEADER_STATUS_PATTERN.subn(
        rf"\g<1>\g<2>\g<3>{status}\g<4>", html, count=1
    )
    if count == 0:
        raise RuntimeError(
            "rfi_patch: could not locate the header table's Status cell to patch it."
        )
    return patched


def patch_response_fields(html: str, response_event: dict, chunk_id: str) -> str:
    """
    Forces both the header table's Status cell and the Response block's
    fields to match `response_event` (the dict returned by
    construction_data.fetch_rfi_response_event()), regardless of what
    the AI's edit did or didn't update correctly. Every substitution is
    capped at count=1 as defense-in-depth, the same discipline Build
    1's value_patch.py uses after finding a cross-dish leak there —
    there is only one RFI in this document, but a scoped, capped
    substitution costs nothing and rules out an entire class of future
    bug for free.
    """
    html = _patch_header_status(html, response_event["status"])

    pattern = re.compile(
        rf'<(\w+)[^>]*data-chunk-id="{re.escape(chunk_id)}"[^>]*>.*?</\1>',
        re.DOTALL,
    )
    replacement_block = (
        f'<p data-chunk-id="{chunk_id}">'
        f"<strong>Status:</strong> {response_event['status']}<br/>\n"
        f"<strong>Responded By:</strong> {response_event['responded_by']}<br/>\n"
        f"<strong>Date Responded:</strong> {response_event['date_responded']}<br/>\n"
        f"<strong>Cost Impact:</strong> {response_event['cost_impact']}<br/>\n"
        f"<strong>Schedule Impact:</strong> {response_event['schedule_impact']}<br/>\n"
        f"<strong>Response:</strong> {response_event['response']}"
        f"</p>"
    )
    patched, count = pattern.subn(replacement_block, html, count=1)
    if count == 0:
        raise RuntimeError(
            f"rfi_patch: could not locate the Response block (chunk_id={chunk_id!r}) to patch it."
        )
    return patched
