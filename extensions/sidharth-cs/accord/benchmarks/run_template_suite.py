#!/usr/bin/env python3
"""End-to-end check for the non-SOW templates.

The audio benchmark only ever exercised Statement of Work. Routing for the
other four was unit-tested but had never had text driven through the real
pipeline — batching, the gate, SuperDocs, integrity, export. This feeds each
committed transcript in through the manual-transcript route (same path the
audio route feeds after Groq returns text), then reports which sections
actually filled.

Run:  python benchmarks/run_template_suite.py [template_key ...]
"""

import json
import os
import re
import sys
import time
import urllib.request

BACKEND = os.environ.get("BENCHMARK_BACKEND", "http://localhost:8010")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sslctx import ssl_context_for  # noqa: E402

_SSL_CTX = ssl_context_for(BACKEND)
HERE = os.path.dirname(__file__)
TEMPLATES = ["meeting_minutes", "advice_note", "requirements_list", "proposal"]

# Sections that are table/metadata rows, not prose — never expected to fill
# from a section-body operation.
METADATA = {"Meeting Details", "Matter Details", "Project Details",
            "Client", "Date", "Prepared by"}


def b64u(s: str) -> str:
    import base64
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{BACKEND}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120, context=_SSL_CTX) as r:
        return json.loads(r.read())


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{BACKEND}{path}", timeout=60, context=_SSL_CTX) as r:
        return json.loads(r.read())


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def run_template(key: str) -> tuple[str, int, int, list[str], str]:
    """One template, start to finish. Templates run CONCURRENTLY — each is an
    independent meeting with its own SuperDocs session, so they share no
    state, and running them in sequence meant waiting out four separate
    settle periods back to back."""

    # Printed as it happens, not collected and dumped at the end. The
    # buffering here existed only to stop four concurrent templates
    # interleaving their logs; the suite runs sequentially now, and a run
    # that takes tens of minutes must show which template it is on.
    def log(msg: str) -> None:
        print(msg, flush=True)

    meeting = f"tmpl-{key}-{int(time.time())}"
    uid = b64u(meeting)
    get(f"/api/meetings/{uid}/state")            # create the session
    post(f"/api/meetings/{uid}/template", {"template_key": key})

    text = open(os.path.join(HERE, "transcripts", f"{key}.txt")).read().strip()
    # Feed in utterance-sized pieces, like speech arriving over the call.
    for chunk in sentences(text):
        post(f"/api/meetings/{uid}/transcript", {"text": chunk})
        time.sleep(1.0)

    log(f"  {key}: {len(sentences(text))} utterances sent, settling...")
    final = None
    # Settled = the pipeline is terminal, nothing is queued, and the draft
    # has stopped moving.
    #
    # This used to require len(activity) >= len(transcript_history), which
    # can essentially never be true: activity counts BATCHES and
    # transcript_history counts UTTERANCES, and batching exists precisely to
    # group several utterances into one batch. So every template sat out the
    # full 180 x 10s = 30 minutes no matter what — advice_note was finished,
    # 7/7 sections, job_status "completed", while the suite kept polling and
    # the next template never started.
    #
    # draft_version has to be quiet as well as the status terminal: between
    # two batches the status legitimately reads "completed" for a moment,
    # and stopping there reports a half-finished document as the result.
    stable = 0
    for _ in range(240):
        st = get(f"/api/meetings/{uid}/state")
        quiet = (
            st["job_status"] in ("completed", "error", "blocked", "idle")
            and not st.get("pending_batches")
        )
        if quiet and final is not None and st["draft_version"] == final["draft_version"]:
            stable += 1
            if stable >= 4:            # ~20s with no movement
                break
        else:
            stable = 0
        final = st
        time.sleep(5)
    final = final or get(f"/api/meetings/{uid}/state")

    html = final["current_draft_html"]
    filled, empty = [], []
    for m in re.finditer(r"<h2[^>]*>(.*?)</h2>(.*?)(?=<h2|\Z)", html, re.S):
        head = re.sub(r"<[^>]+>", "", m.group(1)).replace("&amp;", "&").strip()
        body = re.sub(r"<[^>]+>", " ", m.group(2)).strip()
        if head in METADATA:
            continue
        (filled if body else empty).append(head)

    log(f"    meeting={meeting}")
    log(f"    v{final['draft_version']} {final['job_status']} "
        f"({len(final['activity'])} batches) error={final.get('error') or 'none'}")
    for h in filled:
        log(f"      OK    {h}")
    for h in empty:
        log(f"      EMPTY {h}")
    return meeting, len(filled), len(filled) + len(empty), empty


def main() -> int:
    keys = sys.argv[1:] or TEMPLATES
    # SEQUENTIAL, deliberately. This used to run all four at once to save
    # wall-clock, and concurrent sessions measurably degrade SuperDocs'
    # output — so a template could "fail" here for no reason other than
    # three other meetings drafting alongside it. A suite whose verdict
    # depends on how many templates you happened to run is not a test.
    print(f"running {len(keys)} templates sequentially: {', '.join(keys)}\n")

    def safe(key: str):
        try:
            meeting, ok, total, empty = run_template(key)
            return key, ok, total, empty
        except Exception as exc:
            print(f"    FAILED: {exc}", flush=True)
            return key, 0, 0, [str(exc)[:80]]

    done = []
    for k in keys:
        print(f"=== {k} ===", flush=True)
        done.append(safe(k))

    results = []
    for key, ok, total, empty in done:
        results.append((key, ok, total, empty))

    print("\n=== SUMMARY ===")
    for key, ok, total, empty in results:
        status = "PASS" if total and ok == total else "FAIL"
        print(f"  {status} {key:20} {ok}/{total} sections filled"
              + (f"  empty={empty}" if empty else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
