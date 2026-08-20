"""Part three. A fifty page document, in and out, and the things that go wrong.

    export SUPERDOCS_API_KEY=sk_...
    python3 sample/make_samples.py --big 55
    python3 part3_files_export/large_documents.py                  # the whole run
    python3 part3_files_export/large_documents.py --demo-failures  # the failures, deliberately
    python3 part3_files_export/large_documents.py --inline         # force the small file path

Costs one operation for the edit. Building the .docx and exporting it are free.

Parts one and two used a two page agreement, which is the wrong size to learn
anything about file handling. At fifty pages four things change:

1. The file no longer belongs in the request body. Above roughly 20 MB of file
   bytes an inline base64 upload is refused by the gateway, which answers with
   HTML rather than JSON, so the error does not even look like an API error. The
   pre-signed flow exists for this and the bytes never pass through your process.
2. The parsed document is worth keeping out of your context. response_mode
   "compact" returns per section diffs instead of the whole document, which is
   the difference between a few hundred tokens and a few hundred thousand.
3. Editing gets slow enough to need the async job, and long edits can pause to
   ask whether to keep going. That pause is a different endpoint from approval.
4. Export can outlast an HTTP request. The signed download URL covers most of it,
   and there is an email fallback for the rest.

Every failure handled here is one this script actually hit while it was written.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from superdocs import (  # noqa: E402
    INLINE_UPLOAD_LIMIT_BYTES,
    PayloadTooLarge,
    QuotaExhausted,
    SuperDocs,
    SuperDocsError,
    Usage,
    save_export,
)

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_HTML = ROOT / "sample" / "tender-response.html"
SAMPLE_DOCX = ROOT / "sample" / "tender-response.docx"
OUT = ROOT / "out"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

EDIT = """In the section titled "Data protection", replace the whole section body with this text, keeping the heading and its number as they are:

All personal data processed under this contract is held within the United Kingdom. Access is limited to named personnel listed in the resourcing section. Retention follows the schedule in the appendix, and data is destroyed within thirty days of contract exit unless a statutory retention period applies.

Change nothing anywhere else in the document. Do not renumber any section. Do not touch any table."""


def build_docx_sample(client: SuperDocs) -> Path:
    """Turn the generated HTML into a real .docx to upload.

    Export is not billable, so the sample costs nothing, and it means part three
    uploads a genuine Word file rather than HTML pretending to be one.
    """
    if SAMPLE_DOCX.exists():
        print(f"sample    {SAMPLE_DOCX.name} already built ({SAMPLE_DOCX.stat().st_size / 1e6:.2f} MB)")
        return SAMPLE_DOCX
    if not SAMPLE_HTML.exists():
        raise SystemExit("Run python3 sample/make_samples.py --big 55 first.")
    print("sample    building a .docx from the generated HTML (export is free)")
    payload = client.export(html=SAMPLE_HTML.read_text(encoding="utf-8"), fmt="docx",
                            filename="tender-response.docx")
    written = save_export(payload, SAMPLE_DOCX)
    print(f"sample    wrote {SAMPLE_DOCX.name} ({written / 1e6:.2f} MB)")
    return SAMPLE_DOCX


def upload(client: SuperDocs, session_id: str, path: Path, force_inline: bool,
           force_presigned: bool = False) -> dict:
    """Choose a path by size, and say out loud which one and why.

    Page count and byte count are different problems. Fifty pages of text is a
    40 KB .docx, which uploads inline happily; the same fifty pages with scanned
    appendices is 30 MB and cannot. Pages drive what the edit costs, bytes drive
    which upload path works, and only one of those is visible in a page count.
    """
    size = path.stat().st_size
    print(f"upload    {path.name} is {size / 1e6:.2f} MB, inline limit is {INLINE_UPLOAD_LIMIT_BYTES / 1e6:.0f} MB")

    if not force_presigned and (force_inline or size <= INLINE_UPLOAD_LIMIT_BYTES):
        try:
            started = time.time()
            out = client.upload_base64(path.name, path.read_bytes(), session_id=session_id)
            out["_path_used"] = "inline"
            print(f"upload    inline, {time.time() - started:.1f}s")
            return out
        except PayloadTooLarge as exc:
            # The guard fires before the request leaves, or the gateway refuses it.
            # Either way the answer is the same: stop trying to inline it.
            print(f"upload    inline refused: {exc}")
            print("upload    falling back to the pre-signed flow")

    started = time.time()
    ticket = client.request_upload_url(path.name, DOCX_TYPE, path.stat().st_size)
    print(f"upload    ticket {ticket['upload_id']}, PUT url valid {ticket['expires_in_seconds']}s")
    client.put_bytes(ticket["upload_url"], path.read_bytes(), DOCX_TYPE)
    print(f"upload    bytes are in storage, {time.time() - started:.1f}s, and never went through the API")
    out = client.process_upload(ticket["upload_id"], session_id, path.name)
    out["_path_used"] = "presigned"
    out["_upload_id"] = ticket["upload_id"]
    return out


def edit_compact(client: SuperDocs, session_id: str, message: str, max_wait: float) -> dict:
    """Async edit in compact mode, handling the pause that long edits can raise."""
    job_id = client.chat_async(session_id=session_id, message=message, response_mode="compact")
    print(f"edit      job {job_id}, compact mode, polling")

    while True:
        job = client.wait_for_job(
            job_id,
            interval=4.0,
            max_wait=max_wait,
            on_progress=lambda j: print(f"          {j.get('status'):<18} {j.get('progress')}%"),
        )
        status = job.get("status")
        meta = job.get("metadata") or {}
        if status != "awaiting_approval":
            return job
        if meta.get("awaiting_kind") == "continue_prompt":
            # A long edit ran out of its step budget and is asking whether to go on.
            # Saying yes gives it a fresh budget; saying no keeps what is applied.
            print("edit      the job paused to ask whether to continue. answering yes")
            client.continue_job(session_id, job_id, keep_going=True)
            continue
        # No approval mode was requested, so anything else waiting here is a
        # surprise worth surfacing rather than auto-approving.
        raise SuperDocsError(
            f"job is waiting on {meta.get('awaiting_kind') or 'an approval'} and this script "
            "did not ask for an approval gate. See part two for how to answer it."
        )


def export_with_fallback(client: SuperDocs, session_id: str, fmt: str, stem: str) -> Path | None:
    """Signed URL first, email fallback if the export cannot finish in time."""
    try:
        ticket = client.download_url(session_id, fmt=fmt, filename=f"{stem}.{fmt}")
        dest = OUT / f"{stem}.{fmt}"
        written = client.save_from_url(ticket["download_url"], dest)
        print(f"export    {dest.name} {written / 1e6:.2f} MB, link valid {ticket['expires_in_seconds']}s")
        return dest
    except SuperDocsError as exc:
        print(f"export    signed download failed: {exc}")
        try:
            out = client.request_export_by_email(session_id, fmt=fmt, filename=f"{stem}.{fmt}")
            print(f"export    queued as an email export instead: {json.dumps(out)[:200]}")
        except SuperDocsError as inner:
            print(f"export    email fallback also failed: {inner}", file=sys.stderr)
        return None


def demo_failures(client: SuperDocs, session_id: str) -> None:
    """Trigger the three failures on purpose, so the handling is visible."""
    print("\n--- failure 1: processing an upload whose bytes were never sent")
    ticket = client.request_upload_url("never-sent.docx", DOCX_TYPE, 1024)
    try:
        client.process_upload(ticket["upload_id"], session_id, "never-sent.docx")
        print("          no error, which was not expected")
    except SuperDocsError as exc:
        print(f"          handled: {exc}")

    print("\n--- failure 2: a pre-signed PUT that does not match its ticket")
    ticket = client.request_upload_url("mismatch.docx", DOCX_TYPE, 5_000_000)
    try:
        client.put_bytes(ticket["upload_url"], b"not five megabytes", "text/plain")
        print("          no error, so storage accepted a mismatched body")
    except SuperDocsError as exc:
        print(f"          handled: {exc}")

    print("\n--- failure 3: an inline upload that is too large to inline")
    try:
        client.upload_base64("too-big.docx", b"x" * (INLINE_UPLOAD_LIMIT_BYTES + 1), session_id=session_id)
        print("          no error, which means the guard did not fire")
    except PayloadTooLarge as exc:
        print(f"          handled before a single byte left the process: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inline", action="store_true", help="force the inline upload path")
    ap.add_argument("--presigned", action="store_true",
                    help="force the pre-signed path even for a small file, to see it work")
    ap.add_argument("--demo-failures", action="store_true", help="trigger the handled failures on purpose")
    ap.add_argument("--max-wait", type=float, default=1200.0)
    ap.add_argument("--formats", default="docx,pdf")
    args = ap.parse_args()

    client = SuperDocs()
    me = client.whoami()
    print(f"account   tier {me['tier']}, {me['quota'].get('remaining')} monthly operations left")

    OUT.mkdir(exist_ok=True)
    docx = build_docx_sample(client)
    session_id = client.init_session()
    print(f"session   {session_id}")

    if args.demo_failures:
        demo_failures(client, session_id)
        return 0

    parsed = upload(client, session_id, docx, force_inline=args.inline, force_presigned=args.presigned)
    chunks = parsed.get("chunks_count")
    print(f"parsed    {chunks} chunks via the {parsed['_path_used']} path, parsing is not billable")
    if parsed.get("warnings"):
        print(f"parsed    warnings: {parsed['warnings']}")

    try:
        job = edit_compact(client, session_id, EDIT, args.max_wait)
    except QuotaExhausted as exc:
        print(f"edit      out of operations: {exc}", file=sys.stderr)
        return 1

    result = job.get("result") or {}
    changes = result.get("document_changes") or {}
    usage = Usage.from_response(result.get("usage"))
    diffs = changes.get("chunk_diffs") or changes.get("changes") or []
    print(f"edit      done, {usage.ops_charged} operation, {len(diffs)} section diff(s) returned")
    if changes.get("changes_summary"):
        print(f"edit      {changes['changes_summary'][:200]}")

    # The point of compact mode, in one number.
    full_html = changes.get("updated_html") or ""
    compact_chars = len(json.dumps(diffs))
    if full_html:
        print(f"edit      compact mode still returned the full document ({len(full_html):,} chars)")
    else:
        print(f"edit      response carried {compact_chars:,} chars of diffs instead of the whole document")

    for fmt in [f.strip() for f in args.formats.split(",") if f.strip()]:
        export_with_fallback(client, session_id, fmt, "tender-response.edited")

    # Verify the edit against the exported text rather than trusting the summary.
    txt = export_with_fallback(client, session_id, "txt", "tender-response.edited")
    if txt and txt.exists():
        body = txt.read_text(encoding="utf-8", errors="replace")
        landed = "held within the United Kingdom" in body
        print(f"check     the new data protection wording is {'present' if landed else 'MISSING'} in the export")
        headings = re.findall(r"^\s*(\d+)\.\s+[A-Z]", body, flags=re.M)
        print(f"check     {len(headings)} numbered sections in the export")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SuperDocsError as exc:
        print(f"SuperDocs: {exc}", file=sys.stderr)
        raise SystemExit(1)
