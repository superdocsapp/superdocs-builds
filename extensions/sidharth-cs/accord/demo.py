#!/usr/bin/env python3
"""Drive ACCORD end to end without a Zoom account, a Mac, or any install.

The live-meeting path needs macOS, screen-recording permission and a Swift
capture binary. None of that is needed to see what the system actually does:
the transcript endpoint takes the same TranscriptEvent the live capture
produces, so feeding it text exercises the identical pipeline — batching,
addition/correction classification, section routing, the validation gate,
SuperDocs edits, approval, export.

    python3 demo.py                 # against the deployed backend
    python3 demo.py --correction    # watch a spoken correction replace a value
    python3 demo.py --url http://localhost:8010

Standard library only, so there is nothing to install.
"""

from __future__ import annotations

import argparse
import base64
import json
import ssl
import sys
import time
import urllib.error
import urllib.request

DEPLOYED = "https://live-deliverable-zoom-app-production.up.railway.app"


def _via_curl(url: str, data, method: str | None):
    """Same request through curl, which carries its own CA bundle.

    Returns (status, parsed_body) or None if curl cannot be used at all.
    Certificate verification stays enabled: no -k, no --insecure. If curl
    cannot verify the certificate either, the request genuinely should fail.

    The body goes to a file and only the status and content type come back on
    stdout, because /export returns a binary .docx — reading the two together
    as text died on the first non-UTF-8 byte, at the very last step of an
    otherwise complete run.
    """
    import subprocess, tempfile, os
    fd, tmp = tempfile.mkstemp()
    os.close(fd)
    cmd = ["curl", "-sS", "-o", tmp, "-w", "%{http_code} %{content_type}",
           "-X", method or ("POST" if data is not None else "GET"), url]
    if data is not None:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", data.decode()]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=120)
        if out.returncode != 0:
            return None
        head = out.stdout.decode(errors="replace").split()
        if not head or not head[0].isdigit():
            return None
        status, ctype = int(head[0]), (head[1] if len(head) > 1 else "")
        body = open(tmp, "rb").read()
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if "json" in ctype:
        try:
            return status, json.loads(body)
        except json.JSONDecodeError:
            return status, body.decode(errors="replace")
    return status, body


def _ssl_context() -> ssl.SSLContext:
    """A python.org or Homebrew Python on macOS ships no CA bundle of its own
    and cannot verify any HTTPS certificate until someone runs
    'Install Certificates.command'. certifi carries one and is already present
    in this project's venv (httpx depends on it), so prefer it and fall back
    to the system trust store. Never disables verification — an unverified
    demo is worse than one that says what to fix."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_CTX = _ssl_context()

# A fictional client and a fabricated project — the task asks for invented
# test data, never a real company's paperwork.
TRANSCRIPT = [
    "Hi, I'd like to discuss a website development project for North Star Goods.",
    "We need a modern responsive website where customers can browse products, "
    "add items to a cart, and complete payments online.",
    "The project should start on September 15th, and the final website should "
    "be delivered by October 30th.",
    "Our total budget for this is $45,000.",
    "The deliverables should include the website, payment integration, mobile "
    "responsive design, and basic analytics.",
    "We'll provide the product images, descriptions, pricing, branding assets, "
    "and access to our existing domain.",
    "We expect weekly progress updates and will review each milestone before "
    "moving on.",
    "This project does not include ongoing marketing, SEO, or content creation "
    "after launch.",
    "We want to have a kick-off meeting next week to finalize the requirements.",
]

# Spoken mid-sentence, exactly as a person corrects themselves out loud. The
# classifier has to notice this supersedes the $45,000 above rather than
# adding a second budget line.
CORRECTION = "Actually, no, make it $55,000."

# Spoken a beat later, once the budget is already written into the document.
# This is the path the task's brief describes as the headline behaviour: the
# document already holds $45,000, and this has to REPLACE it rather than add
# a second figure alongside it.
LATE_CORRECTION = "Sorry, correction — the total budget is $55,000, not $45,000."


def call(url: str, path: str, payload=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    # Built once and reused by BOTH transports below. Passing the bare base
    # URL to the curl fallback sent every request to "/" instead, where a
    # POST answers 405 and the /health check passes against the panel's own
    # HTML — a fallback that silently talks to the wrong endpoint is worse
    # than no fallback.
    target = url + path
    req = urllib.request.Request(
        target,
        data=data,
        method=method or ("POST" if data is not None else "GET"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60, context=_CTX) as r:
            body = r.read()
            ctype = r.headers.get("Content-Type", "")
            return r.status, (json.loads(body) if "json" in ctype else body)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLCertVerificationError):
            # A Homebrew or python.org Python on macOS ships no CA bundle of
            # its own, so urllib cannot verify ANY certificate until someone
            # installs certifi or runs Install Certificates.command. That is
            # a fair thing to ask of a contributor and an unfair thing to ask
            # of someone who just wants to see whether this works.
            #
            # curl carries its own trust store and is present on every macOS
            # and effectively every Linux, so borrow it rather than telling a
            # reviewer to go and fix their Python first. Verification is
            # still ON — this is a different verifier, never a disabled one.
            got = _via_curl(target, data, method)
            if got is not None:
                return got
            sys.exit(
                "\nHTTPS certificate verification failed: this Python has no CA "
                "bundle, and curl is not available to fall back on.\n\nThe cause "
                "is the Python install, not this project or the server. Fix it "
                "with either:\n"
                "  pip3 install certifi\n"
                '  open "/Applications/Python 3.x/Install Certificates.command"\n'
                "\nOr run against a local backend instead:  "
                "python3 demo.py --url http://localhost:8010\n"
            )
        # A backend that goes away mid-run (restarted, redeployed, or never
        # started) otherwise surfaces as a bare urllib traceback pointing at
        # this file, which reads like a bug in the demo rather than a server
        # that is not there.
        sys.exit(
            f"\nCannot reach the backend at {url.split('/api')[0]}: {e.reason}\n\n"
            "If you are running it locally, start it first:\n"
            "  make dev\n"
            "Otherwise drop --url to use the deployed backend.\n"
        )


def wait_until_idle(url: str, meeting: str, timeout=420, settle_reads=4) -> dict:
    """Poll until the drafting pipeline stops working. Printing the status as
    it changes is the point — a reviewer should see the queue drain.

    A single 'idle' read does not mean finished. The batcher waits out a
    silence gap before the first batch even forms, and goes briefly idle
    between batches, so the first read after the last line is almost always
    idle with nothing drafted yet. Finished means idle and empty for several
    consecutive reads, with something actually drafted (or a reported error).
    """
    deadline = time.time() + timeout
    last, quiet, state = None, 0, {}
    while time.time() < deadline:
        status, state = call(url, f"/api/meetings/{meeting}/state")
        if status != 200:
            print(f"  state read failed: {status} {state}")
            return {}
        s = state.get("job_status")
        pending = state.get("pending_batches", 0)
        version = state.get("draft_version", 0)
        if (s, pending, version) != last:
            print(f"  job_status={s} pending={pending} draft_version={version}")
            last = (s, pending, version)
        if s in ("idle", "completed", "error", "blocked") and not pending:
            quiet += 1
            if quiet >= settle_reads and (version or s in ("error", "blocked")):
                return state
        else:
            quiet = 0
        time.sleep(3)
    print("  timed out waiting for the pipeline to settle")
    return state


def text_of(html: str) -> str:
    import re
    html = re.sub(r"<h([12])[^>]*>(.*?)</h\1>", r"\n## \2\n", html or "", flags=re.S)
    html = re.sub(r"</(p|li|tr)>", "\n", html)
    html = re.sub(r"<[^>]+>", " ", html)
    import html as h
    return "\n".join(
        " ".join(line.split()) for line in h.unescape(html).splitlines() if line.strip()
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEPLOYED, help="backend base URL")
    ap.add_argument("--correction", action="store_true",
                    help="speak a mid-sentence budget correction")
    ap.add_argument("--late-correction", action="store_true",
                    help="correct the budget AFTER it has been written — the "
                         "harder path, and the realistic one")
    ap.add_argument("--template", default="statement_of_work")
    ap.add_argument("--meeting", help="feed a session already open in the panel")
    # Must be paced like speech, not like a paste. The batcher closes a batch
    # on a 7s silence gap or a 15s ceiling, so lines fired faster than that
    # never let a batch close and the entire meeting arrives as one batch with
    # many operations — the case most likely to trip the preservation guard,
    # and nothing like the live path, where 6s audio chunks produce 3-4
    # batches. 4s keeps several lines per batch while still letting the
    # ceiling close them, which is what real speech does here.
    ap.add_argument("--pace", type=float, default=4.0,
                    help="seconds between spoken lines (keep above ~3s)")
    args = ap.parse_args()
    url = args.url.rstrip("/")

    # Zoom meeting UUIDs contain '/' and '+', so every route takes them
    # base64url-encoded (backend/app/api/encoding.py). A demo id is no
    # different — the routes decode unconditionally.
    name = args.meeting or f"demo-{int(time.time())}"
    meeting = base64.urlsafe_b64encode(name.encode()).decode().rstrip("=")
    print(f"backend : {url}")
    print(f"meeting : {name}")
    print(f"watch   : {url}/?meeting={name}")
    print("          (open that in a browser to see the document build live)")

    status, _ = call(url, "/health")
    if status != 200:
        print(f"backend not reachable (/health returned {status})")
        return 1

    status, doc = call(url, f"/api/meetings/{meeting}/documents",
                       {"template_key": args.template})
    if status != 200:
        print(f"could not create the document: {status} {doc}")
        return 1
    print(f"template: {args.template}\n")

    if args.late_correction:
        args.correction = False  # the budget must land as $45,000 first
    lines = list(TRANSCRIPT)
    if args.correction:
        # Right after the budget is stated, the way it happens in a real room.
        lines.insert(4, CORRECTION)

    print("--- speaking ---")
    for line in lines:
        status, _ = call(url, f"/api/meetings/{meeting}/transcript", {"text": line})
        marker = "  (correction)" if line is CORRECTION else ""
        print(f"  {line[:68]}{'...' if len(line) > 68 else ''}{marker}")
        if status != 200:
            print(f"    submit failed: {status}")
        time.sleep(args.pace)

    print("\n--- drafting ---")
    state = wait_until_idle(url, meeting)
    if not state:
        return 1

    if args.late_correction:
        # The genuinely hard case, and the one a real meeting produces: the
        # figure is already written and approved into the document before
        # anyone corrects it. The intra-batch path never reaches the document
        # at all — the superseded value is resolved away before the first
        # write — so it exercises none of the correction machinery: finding
        # the old value in the draft, replacing rather than appending, and
        # leaving every other section untouched.
        print("\n--- speaking (after the budget is already in the document) ---")
        print(f"  {LATE_CORRECTION}")
        call(url, f"/api/meetings/{meeting}/transcript", {"text": LATE_CORRECTION})
        state = wait_until_idle(url, meeting) or state
    if state.get("error"):
        print(f"\npipeline reported: {state['error']}")

    print("\n--- document ---")
    print(text_of(state.get("current_draft_html", "")))

    if args.correction or args.late_correction:
        html = state.get("current_draft_html", "")
        print("\n--- did the correction land? ---")
        print(f"  $45,000 removed : {'$45,000' not in html}")
        print(f"  $55,000 present : {'$55,000' in html}")

    version = state.get("draft_version", 0)
    if not version:
        print("\nnothing was drafted, so there is nothing to approve.")
        return 1

    # Export is gated on approval by the server, not by the UI — asking for
    # the file before approving is a 409, deliberately.
    status, body = call(url, f"/api/meetings/{meeting}/export", {"exporter": "demo"})
    print(f"\nexport before approval : {status} (409 is the correct answer)")

    status, _ = call(url, f"/api/meetings/{meeting}/approve",
                     {"draft_version": version, "approver": "demo reviewer"})
    print(f"approve v{version}            : {status}")

    # A late batch — or the reconciliation pass — can land AFTER the reviewer
    # approves, which correctly invalidates the approval and then makes export
    # 409. Re-read the version and approve once more rather than reporting a
    # failure that is really a race between the reviewer and a straggler.
    _s, fresh = call(url, f"/api/meetings/{meeting}/state")
    latest = fresh.get("draft_version", version) if isinstance(fresh, dict) else version
    if latest != version:
        status, _ = call(url, f"/api/meetings/{meeting}/approve",
                         {"draft_version": latest, "approver": "demo reviewer"})
        print(f"  draft moved to v{latest} after approval — re-approved: {status}")

    status, body = call(url, f"/api/meetings/{meeting}/export", {"exporter": "demo reviewer"})
    print(f"export after approval  : {status}")
    if status == 200 and isinstance(body, dict):
        print(f"  {body.get('filename') or body}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
