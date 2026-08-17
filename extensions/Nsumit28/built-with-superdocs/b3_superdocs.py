#!/usr/bin/env python3
"""
Stage B3 — use SuperDocs on a document Build B actually needs, and measure what
it did.

The document is CURATION.md, the rule the whole gallery rests on. That choice is
not decoration: the rule has eight numbered decline reasons that submitters are
shown, and revising one section of it while the other eight stay byte-identical
is precisely the counterfactual the bar itself describes. If section-precision
does not hold on a document this long, the claim in the entry card is wrong and
should be withdrawn.

Ops discipline (TASK.md): a run can work silently for minutes, and **retrying
spends operations**. So: one attempt, long timeout, nothing automatic. Every
response is written to out/ before anything is parsed, so a parse bug never costs
a second call.

Usage:
  export SUPERDOCS_API_KEY=your-key-here
  python3 b3_superdocs.py --edit     # one chat operation
  python3 b3_superdocs.py --export   # export (free)
  python3 b3_superdocs.py --check                        # offline: precision report
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
CURATION = HERE / "CURATION.md"
API = "https://api.superdocs.app/v1"
SESSION = "doctask-b3-curation-rule"
TIMEOUT = 300  # a run can be silent for minutes; waiting is cheaper than resending

# The edit asked for. Written here, in the file, before it was sent — so what was
# requested cannot be quietly restated afterwards to match what came back.
EDIT_REQUEST = (
    "In the section headed '2. SuperDocs did work that mattered to the outcome', "
    "immediately after the blockquote, add one short worked example contrasting a "
    "qualifying use with a non-qualifying one. Two sentences at most. "
    "Change nothing in any other section, and do not touch the numbered decline "
    "reasons table."
)


# Attempt 2. Attempt 1 came back with an example about whether it is appropriate
# to ask an AI for legal advice — fluent, on-topic-sounding, and about a
# completely different axis than the section argues. Two explanations fit: the
# model misread the section, or the brief was too loose. This brief names the
# axis explicitly while still letting it write the sentence, so the answer is a
# diagnosis rather than dictation. Sent in a fresh session so attempt 1 cannot
# prime it.
EDIT_REQUEST_2 = (
    "In the section '2. SuperDocs did work that mattered to the outcome', insert one "
    "sentence directly BELOW the blockquote — after the closing </blockquote>, before "
    "the paragraph starting 'This is the test'. The sentence must give a concrete "
    "example on the axis of the blockquote itself: work SuperDocs did on a document "
    "that a plain text editor could not have done as safely. It must NOT be about "
    "legal advice, or about what an AI should or should not be asked to do. "
    "Change nothing else in the document."
)
SESSION_2 = "doctask-b3-curation-rule-v2"


def api_key() -> str:
    key = os.environ.get("SUPERDOCS_API_KEY")
    if not key:
        sys.exit("SUPERDOCS_API_KEY not set — export SUPERDOCS_API_KEY=your-key-here")
    return key


def post(path: str, payload: dict, raw: bool = False):
    """One request. No retry loop anywhere in this file, by design."""
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key()}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        body = r.read()
        return body if raw else json.loads(body)


def to_html() -> str:
    import markdown
    md = markdown.Markdown(extensions=["extra", "sane_lists"])
    return md.convert(CURATION.read_text(encoding="utf-8"))


def strip_chunk_ids(html: str) -> str:
    """Remove the data-chunk-id attributes SuperDocs stamps on every block.

    Measured on the first pass: the returned document carries a fresh
    data-chunk-id on *every* block element, including ones the edit never
    touched. That is addressing metadata, not content — but it means a raw
    byte-diff of the returned HTML reports the entire document as changed and
    tells you nothing. Comparing content requires normalising it away first.
    Both numbers get reported, because the raw one matters to anyone diffing
    SuperDocs output in CI and would otherwise be a nasty surprise.
    """
    html = re.sub(r'\s*data-chunk-id="[^"]*"', "", html)
    # Second normalisation: void tags come back re-serialised, `<hr />` -> `<hr/>`.
    # Also not content. Two separate normalisations are needed before a diff of
    # SuperDocs output means anything — which is worth knowing before wiring one
    # into a build.
    return re.sub(r"\s*/>", "/>", html)


def sections(html: str) -> dict[str, str]:
    """Split on <h2>/<h3> so 'what changed' is answered per section, not per file."""
    parts = re.split(r"(?=<h[23][^>]*>)", html)
    out: dict[str, str] = {}
    for i, p in enumerate(parts):
        m = re.match(r"<h[23][^>]*>(.*?)</h[23]>", p, re.S)
        title = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else f"(preamble {i})"
        out[title] = p
    return out


def do_edit(attempt: int = 1) -> int:
    OUT.mkdir(exist_ok=True)
    message, session, tag = ((EDIT_REQUEST, SESSION, "")
                             if attempt == 1 else
                             (EDIT_REQUEST_2, SESSION_2, "-2"))
    before = to_html()
    (OUT / "b3-before.html").write_text(before, encoding="utf-8")

    print(f"attempt {attempt}: {len(before):,} chars, {len(sections(before))} sections")
    print(f"request:  {message[:90]}…")
    print("sending one chat operation; this can be silent for minutes. Do not resend.")

    resp = post("/chat", {"message": message,
                          "session_id": session,
                          "document_html": before})
    # Written before anything is parsed: a KeyError must never cost a second call.
    (OUT / f"b3-chat-response{tag}.json").write_text(json.dumps(resp, indent=2),
                                                     encoding="utf-8")
    print(f"response saved: {OUT/f'b3-chat-response{tag}.json'}")

    updated = (resp.get("document_changes") or {}).get("updated_html")
    if not updated:
        print("no updated_html in document_changes — inspect the saved response")
        return 1
    (OUT / f"b3-after{tag}.html").write_text(updated, encoding="utf-8")
    if attempt != 1:
        (OUT / "b3-after.html").write_text(updated, encoding="utf-8")

    usage = resp.get("usage")
    if usage:
        print(f"usage reported: {json.dumps(usage)}")
    return report()


def report() -> int:
    raw_before = (OUT / "b3-before.html").read_text(encoding="utf-8")
    raw_after = (OUT / "b3-after.html").read_text(encoding="utf-8")

    raw_a, raw_b = sections(raw_before), sections(raw_after)
    raw_changed = [k for k in raw_a if k in raw_b and raw_a[k] != raw_b[k]]
    print(f"\nraw HTML: {len(raw_changed)} of {len(raw_a)} sections differ "
          f"(data-chunk-id is stamped on every block, so this number is annotation, "
          f"not content)")

    before, after = strip_chunk_ids(raw_before), strip_chunk_ids(raw_after)
    a, b = sections(before), sections(after)

    changed = [k for k in a if k in b and a[k] != b[k]]
    dropped = [k for k in a if k not in b]
    added = [k for k in b if k not in a]
    identical = [k for k in a if k in b and a[k] == b[k]]

    print(f"\nsections before {len(a)}, after {len(b)}")
    print(f"  byte-identical : {len(identical)}")
    print(f"  changed        : {changed or 'none'}")
    print(f"  dropped        : {dropped or 'none'}")
    print(f"  added          : {added or 'none'}")

    target = "2. SuperDocs did work that mattered to the outcome"
    precise = changed == [target] and not dropped and not added
    print(f"\n{'PASS' if precise else 'FAIL'} — section precision: "
          f"{'only the requested section moved' if precise else 'more moved than was asked for'}")

    for k in changed:
        d = list(difflib.unified_diff(a[k].splitlines(), b[k].splitlines(),
                                      lineterm="", n=1))
        print(f"\n--- diff: {k} ({len(d)} lines) ---")
        print("\n".join(d[:40]))

    # The decline table is what submitters are shown; it must be untouched.
    tbl_a = re.search(r"<table[^>]*>.*?</table>", before, re.S)
    tbl_b = re.search(r"<table[^>]*>.*?</table>", after, re.S)
    same_tbl = bool(tbl_a and tbl_b and tbl_a.group() == tbl_b.group())
    print(f"\n{'PASS' if same_tbl else 'FAIL'} — the R1–R8 decline table is "
          f"{'byte-identical' if same_tbl else 'NOT identical'}")

    return 0 if (precise and same_tbl) else 1


def do_export() -> int:
    """Export is free per the ops table — worth doing for the artifact trail."""
    OUT.mkdir(exist_ok=True)
    html = (OUT / "b3-after.html").read_text(encoding="utf-8")
    body = post("/documents/export",
                {"document_html": html, "format": "html", "session_id": SESSION},
                raw=True)
    # Documented gotcha, learned in Build A: this returns a FILE, not JSON.
    path = OUT / "b3-export.html"
    path.write_bytes(body)
    print(f"export saved: {path} ({len(body):,} bytes)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--edit", action="store_true")
    ap.add_argument("--edit2", action="store_true")
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.edit:
        return do_edit(1)
    if args.edit2:
        return do_edit(2)
    if args.export:
        return do_export()
    if args.check:
        return report()
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
