"""8C — a clean copy, and the proof that it is clean.

In-place redaction (8B) edits the open document. This is the other half: a new
file with the confirmed text removed, produced through SuperDocs and then
measured. Four calls: upload → chat (instruction) → approve → export.

The approval step is the point. SuperDocs proposes edits; approving whatever
came back would let a model decide what leaves the document. So each change is
recomputed locally — old text plus the reviewer's confirmed substitutions — and
approved only if the result is character-for-character what the model produced.
Anything else is rejected, including a change that redacts *more* than asked.
The export is then searched part by part (`verify_package.check`); a confirmed
string surviving outside `docProps/*` is reported as failure, not handed back.

See extensions/redaction-pane/README.md § "The clean copy".
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field
from typing import Any

from service import verify_package
from service._portable.superdocs_client import ChangeDecision, PendingChange

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

MAX_ROUNDS = 3
"""Approval rounds. A rejection with feedback lets the AI revise and return with
another `awaiting_approval`, so more than one is expected — but three is enough
for a revision and a confirmation, and a document not converged by then needs a
person."""


@dataclass
class Result:
    content: bytes = b""
    filename: str = ""
    report: verify_package.Report | None = None
    approved: int = 0
    rejected: int = 0
    rounds: int = 0
    warnings: list[str] = field(default_factory=list)
    """Export warnings from SuperDocs, surfaced verbatim. An export that
    silently dropped formatting is a lie by omission."""

    @property
    def clean(self) -> bool:
        """False unless something was produced AND it verified. `report is None`
        matters: an export that never ran is not clean, and defaulting True here
        would be the worst bug in the file."""
        return bool(self.content) and self.report is not None and self.report.clean


def instruction(items: dict[str, str]) -> str:
    """`{original: marker}` → what we ask SuperDocs to do. Explicit pairs, not
    "redact the personal data": naming both halves is what makes the result
    checkable, since `expected_text` recomputes exactly this."""
    lines = "\n".join(f'  "{text}"  →  {marker}' for text, marker in items.items())
    return (
        "Redact this document by replacing each EXACT string below with the marker "
        "shown beside it.\n\n"
        f"{lines}\n\n"
        "Rules:\n"
        "- Replace only these strings. Do not rephrase, summarise, or tidy anything.\n"
        "- Leave every other character, including punctuation and spacing, as it is.\n"
        "- Replace every occurrence, including in headers, footers and comments.\n"
        "- If a string does not appear, skip it. Do not invent a replacement."
    )


def flatten(html: str) -> str:
    """HTML → the text to compare on: tags out, entities decoded, whitespace
    collapsed. `<br/>` vanishes from both sides equally, so the equality holds;
    keeping tags would reject a change for an attribute SuperDocs normalised."""
    return _WS.sub(" ", html_lib.unescape(_TAG.sub("", html))).strip()


def expected_text(old_html: str, items: dict[str, str]) -> str:
    """What the block must read once our substitutions are applied. Longest
    first, so a string containing another is replaced before its substring —
    else `Margaret Ellen Hollis` and `Margaret` leave `[NAME REDACTED] Ellen
    Hollis`."""
    text = flatten(old_html)
    for original in sorted(items, key=len, reverse=True):
        text = text.replace(original, items[original])
    return text


def decide(changes: list[PendingChange], items: dict[str, str]) -> tuple[list[ChangeDecision], int]:
    """Approve only what we can reproduce. Returns `(decisions, approved)`. An
    equality, not a heuristic: approved when the confirmed substitutions applied
    to the old text yield exactly the new text — not "contains a marker", which
    would approve a change that also deleted a paragraph."""
    decisions: list[ChangeDecision] = []
    approved = 0
    for change in changes:
        wanted = expected_text(change.old_html, items)
        actual = flatten(change.new_html)
        if wanted == actual:
            decisions.append(ChangeDecision(change_id=change.change_id, approved=True))
            approved += 1
            continue
        decisions.append(
            ChangeDecision(
                change_id=change.change_id,
                approved=False,
                feedback=(
                    "Rejected: this changes more than the confirmed redactions. "
                    "Replace only the exact strings given, leaving everything else "
                    f"byte for byte. Expected: {wanted[:300]}"
                ),
            )
        )
    return decisions, approved


def run(
    *,
    client: Any,
    session_id: str,
    filename: str,
    data: bytes,
    items: dict[str, str],
) -> Result:
    """Upload, instruct, approve what we asked for, export, verify. `client` is
    passed in, not constructed, so the flow replays against recorded fixtures
    with no key and no network."""
    result = Result()
    if not items:
        result.warnings.append("nothing confirmed — there is nothing to export")
        return result

    upload = client.upload_document(session_id=session_id, filename=filename, data=data)
    handle = client.chat_async(
        session_id=session_id,
        message=instruction(items),
        idempotency_marker=f"redaction-{upload.durable_document_id[:12]}",
    )

    job = client.wait_for_job(handle.job_id)
    for _ in range(MAX_ROUNDS):
        result.rounds += 1
        if job.status != "awaiting_approval":
            break
        from service._portable.superdocs_client import parse_pending_changes

        decisions, approved = decide(parse_pending_changes(job.metadata), items)
        result.approved += approved
        result.rejected += len(decisions) - approved
        if not decisions:
            break
        client.approve(session_id=session_id, job_id=handle.job_id, changes=decisions)
        job = client.wait_for_job(handle.job_id)

    if job.status == "awaiting_approval":
        # Still waiting after the last round. Exporting now would ship a file
        # missing the still-unapproved redactions — clean-looking, never cleaned.
        result.warnings.append(
            f"still awaiting approval after {MAX_ROUNDS} rounds — no file was exported"
        )
        return result

    exported = client.export(session_id=session_id, fmt="docx")
    result.content = exported.content
    result.filename = exported.filename
    result.warnings.extend(exported.warnings)
    result.report = verify_package.check(exported.content, list(items))
    return result
