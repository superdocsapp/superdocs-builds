"""Take the recovered structure through SuperDocs to get a properly styled file.

The local rebuild always runs first and always produces a valid file. This is
the optional second pass: hand the recovered structure to SuperDocs as HTML,
have it normalise the document, and export a styled DOCX.

Why HTML and not the rebuilt .docx bytes: the documentation is explicit that
SuperDocs takes documents and HTML and that there is no endpoint for raw Word
XML. Sending clean HTML built from structure we have already parsed is both
supported and lossless in the directions that matter -- headings stay headings,
tables stay tables.

The four calls, in order, are exactly the required contract:
  upload -> edit instruction -> approve -> export
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .docx import Block, blocks_to_html
from .superdocs_client import QuotaExhausted, SuperDocsClient

INSTRUCTION = (
    "Formatting only. This document was recovered from a damaged file and its "
    "text is the only record of what its owner wrote. Apply consistent heading "
    "styles, table formatting and paragraph spacing. Do NOT add, remove, "
    "expand, summarise, complete or reword any text. Do not add sections, "
    "headings, rows, totals, placeholders, disclaimers, signature blocks, "
    "headers, footers or dates. Do not fill gaps. If a passage looks "
    "incomplete, leave it exactly as it is. The word-for-word text of the "
    "output must be identical to the input."
)

#: How many words of difference count as "it only restyled it". Zero: a
#: formatting pass has no reason to change a single word, and the one thing
#: this product cannot do is hand somebody a recovered document containing
#: sentences they never wrote.
ALLOWED_WORD_DRIFT = 0


def _words(text: str) -> list[str]:
    """Text reduced to what a reader would call the words, so that a formatting
    pass -- which may re-wrap, re-space or re-escape -- reads as no change."""
    import html as _html
    import re

    plain = _html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.findall(r"[a-z0-9]+", plain.lower())


def _without_data_uris(html: str) -> str:
    import re

    return re.sub(r'src="data:[^"]*"', 'src=""', html)


def docx_text(blob: bytes) -> str:
    """The text of a .docx, run by run. Deliberately not a full parse: this is
    asked only "what does it say"."""
    import io
    import re
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            body = z.read("word/document.xml").decode("utf-8", "replace")
    except Exception:
        return ""
    return " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", body))


def content_drift(sent_html: str, got_docx: bytes) -> tuple[int, int]:
    """(words added, words removed) between what we sent and what came back.

    A multiset rather than a sequence: reordering a table's cells is not this
    guard's business, and inventing a paragraph is.
    """
    from collections import Counter

    # Base64 image payloads are not words and must not be counted as any: a
    # data URI is megabytes of [a-z0-9]+ that the styled file will never echo
    # back, which would read as an enormous deletion and fail every document
    # that has a picture in it.
    before = Counter(_words(_without_data_uris(sent_html)))
    after = Counter(_words(docx_text(got_docx)))
    added = sum((after - before).values())
    removed = sum((before - after).values())
    return added, removed


@dataclass
class Allowance:
    """What the platform says is left, before anything is spent.

    `known` is false when the balance could not be read. That is not the same
    as zero and is never reported as one: a personal key is not an agent key,
    and `/v1/agents/whoami` answers only the latter. An unreadable balance lets
    the work proceed and says the number is unknown — refusing on a number
    nobody read would be its own kind of bluff.
    """

    known: bool = False
    remaining: int = 0
    tier: str = ""


def allowance(client: SuperDocsClient) -> Allowance:
    """Trap 3, asked before the loop rather than discovered inside it.

    `GET /v1/agents/whoami` carries `quota: {tier, monthly_limit, used,
    remaining}` — the one balance read available in advance of doing work.
    """
    try:
        r = client.whoami()
    except Exception:
        return Allowance()
    body = r.body if isinstance(r.body, dict) else {}
    quota = body.get("quota") or {}
    if "remaining" not in quota:
        return Allowance()
    try:
        return Allowance(known=True, remaining=int(quota["remaining"]),
                         tier=str(quota.get("tier", "")))
    except (TypeError, ValueError):
        return Allowance()


@dataclass
class StyledResult:
    ok: bool = False
    output: bytes = b""
    #: Set when a styled file came back but was thrown away because its text no
    #: longer matched. Kept apart from a transport failure: one is nobody's
    #: fault, the other is a claim we refused to pass on.
    rejected_for_content: bool = False
    warnings: list = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ops_charged: int = 0
    ops_confirmed: bool = False   # the async endpoints return no usage block
    allowance_known: bool = False
    allowance_remaining: int = 0


def styled_export(client: SuperDocsClient, session_id: str, blocks: list[Block],
                  filename: str = "recovered.html",
                  on_progress=None) -> StyledResult:
    """Best effort, and it never costs the caller their local result.

    Every failure path returns ok=False with a reason. The engine's own rebuild
    has already succeeded by the time this runs, so a failure here degrades to
    "you get the plain rebuild" rather than to "you get nothing".
    """
    r = StyledResult()

    def say(msg: str) -> None:
        r.notes.append(msg)
        if on_progress:
            on_progress("superdocs", msg)

    # `inline_images=True` is not a preview nicety here: without it
    # `blocks_to_html` drops every picture on the floor, so the styled document
    # came back with none of them and the word-only drift guard waved it through.
    # If this path is ever preferred over sending the rebuilt file, the pictures
    # should go up via POST /v1/documents/images/upload-base64 and be referenced
    # by the URL it returns, rather than as data URIs.
    html = blocks_to_html(blocks, inline_images=True)

    # 0 -- the allowance, before a single billable call. Starting a styling pass
    # that cannot finish would leave someone watching a progress line for work
    # that was refused at the far end.
    left = allowance(client)
    r.allowance_known = left.known
    r.allowance_remaining = left.remaining
    if left.known and left.remaining < 1:
        say("There is no styling allowance left this month, so nothing was sent "
            "and nothing was spent. The rebuilt file is unchanged and still yours.")
        return r

    try:
        # 1 -- upload. Free.
        say("Sending the recovered content to SuperDocs for styling…")
        client.upload(session_id, filename, html.encode("utf-8"))

        # 2 -- edit instruction, with a human gate on every proposed change.
        started = client.edit(session_id, INSTRUCTION)
        r.ops_charged += int(started.usage.get("ops_charged", 0))
        job_id = started.body.get("job_id")
        if not job_id:
            say("SuperDocs did not start a job; keeping the plain rebuild.")
            return r

        # 3 -- wait. A long silence is still processing.
        say("Waiting for SuperDocs to finish — large documents can take minutes.")
        job = client.poll_job(job_id)
        r.ops_charged += int(job.usage.get("ops_charged", 0))

        if job.body.get("status") == "awaiting_approval":
            from .superdocs_client import pending_changes

            changes = pending_changes(job.body)
            if changes:
                # Formatting-only changes on a document we just rebuilt: approve
                # them. The instruction forbids content edits, so a change that
                # rewrote text would be a bug on their side, not a judgement
                # call on ours -- and the export below is what gets checked.
                approved = client.approve(
                    session_id, job_id,
                    [{"change_id": c.get("change_id"), "approved": True} for c in changes],
                )
                r.ops_charged += int(approved.usage.get("ops_charged", 0))
                say(f"Approved {len(changes)} formatting change(s).")

                # Approval is asynchronous: the call returns ok, then the job
                # resumes and applies the change. Exporting before it settles
                # returns the pre-edit document with a 200 and no warning.
                settled = client.poll_job(job_id, deadline_s=300, interval_s=2)
                r.ops_charged += int(settled.usage.get("ops_charged", 0))
                if settled.body.get("status") != "completed":
                    say("SuperDocs did not finish applying the changes; "
                        "keeping the plain rebuild.")
                    return r

        # 4 -- export. Free.
        exported = client.export(session_id, "docx")
        r.warnings = client.export_warnings(exported)
        blob = exported.body.get("raw") if isinstance(exported.body, dict) else None
        if not blob:
            say("SuperDocs returned no file; keeping the plain rebuild.")
            return r
        candidate = blob if isinstance(blob, bytes) else bytes(blob)

        # The guard. The instruction forbids content changes; this checks
        # rather than trusts, because a document-editing model handed a sparse
        # recovered file will fill it out -- observed live on 2026-08-20, where
        # a four-line report came back with invented paragraphs, a subtotal
        # row, a disclaimer and a signature block. Handing that to somebody who
        # came here to get their own words back is the worst output this
        # product could produce: it opens cleanly, it looks better than the
        # plain rebuild, and it is partly fiction.
        added, removed = content_drift(html, candidate)
        if added + removed > ALLOWED_WORD_DRIFT:
            r.rejected_for_content = True
            say("The styled version came back with the wording changed, so it "
                "was thrown away rather than handed over. Your document should "
                "say what you wrote. The rebuilt file is unchanged and still "
                "yours.")
            return r

        r.output = candidate
        r.ok = True
        if not r.ops_charged:
            # The async endpoints return no usage block (see BUG-017), so a
            # zero here means "not reported", not "free". Saying "0 operations"
            # about a billable request would be the same bluff in a new place.
            r.ops_charged = 1
            r.ops_confirmed = False
        else:
            r.ops_confirmed = True
        say("SuperDocs returned a styled file.")
        if r.warnings:
            say(f"The export completed with {len(r.warnings)} non-fatal warning(s).")
    except QuotaExhausted:
        say("The SuperDocs allowance is exhausted; keeping the plain rebuild.")
    except TimeoutError:
        # Not a failure on their side -- the job may still be running. But we
        # cannot export until it settles, so the local rebuild is what ships.
        say("SuperDocs did not finish applying the changes in time; "
            "keeping the plain rebuild.")
    except Exception:
        # Deliberately no exception class name: this string reaches a user.
        say("Styling through SuperDocs did not work; keeping the plain rebuild.")
    return r
