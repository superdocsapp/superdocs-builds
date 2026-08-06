#!/usr/bin/env python3
"""Competitor comparison-table document generator, built on SuperDocs.

Reads a JSON config (product, fictional competitors, capability rows, brand
accents), builds a branded template document, then drives SuperDocs through
upload -> chat (fill the table from config values, verbatim) -> human-in-the-loop
approval -> export (docx/pdf).

Configuration over code: add a competitor column or a capability row by editing
the config and re-running. No code changes.

Stdlib only. Auth: SUPERDOCS_API_KEY env var (fallback: ~/.superdocs/agent_credentials.json).
"""
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.superdocs.app"
POLL_SECONDS = 5
POLL_LIMIT = 120  # x5s = 10 min ceiling


# ---------- auth ----------

def api_key():
    k = os.environ.get("SUPERDOCS_API_KEY")
    if k:
        return k
    cred = Path.home() / ".superdocs" / "agent_credentials.json"
    if cred.exists():
        return json.loads(cred.read_text(encoding="utf-8-sig"))["api_key"]
    sys.exit("No SUPERDOCS_API_KEY env var and no ~/.superdocs/agent_credentials.json")


# ---------- api ----------

def call(method, path, body=None, retries=1, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + api_key())
    if data:
        req.add_header("Content-Type", "application/json")
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if "json" in r.headers.get("Content-Type", ""):
                    return json.loads(raw)
                return raw
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            detail = e.read().decode(errors="replace")[:300] if isinstance(e, urllib.error.HTTPError) else str(e)
            print(f"  ! {method} {path}: {detail}")
            if attempt < retries:
                # First request in a fresh session can flake while warming up.
                time.sleep(5)
                continue
            raise


# ---------- template ----------

def build_template_html(cfg):
    brand = cfg.get("brand", {})
    accent = brand.get("accent_color", "#1a4f8b")
    product = cfg["product"]
    columns = [product] + cfg["competitors"]
    header_cells = "".join(
        f'<th style="background:{accent};color:#ffffff;padding:10px 14px;'
        f'text-align:left;border:1px solid {accent};">{c}</th>'
        for c in ["Capability"] + columns
    )
    rows = []
    for i, cap in enumerate(cfg["capabilities"]):
        shade = "#f5f7fa" if i % 2 else "#ffffff"
        empty = "".join(
            f'<td style="padding:9px 14px;border:1px solid #d9dee5;background:{shade};"></td>'
            for _ in columns
        )
        rows.append(
            f'<tr><td style="padding:9px 14px;border:1px solid #d9dee5;'
            f'background:{shade};font-weight:600;">{cap["name"]}</td>{empty}</tr>'
        )
    footer = brand.get(
        "footer",
        "Competitor names are fictional. Comparison prepared for illustration.",
    )
    return f"""<html><body>
<h1 style="color:{accent};font-family:Georgia,serif;">{cfg.get('title', product + ' — Feature Comparison')}</h1>
<p>{cfg.get('intro', 'How ' + product + ' compares, capability by capability.')}</p>
<table style="border-collapse:collapse;width:100%;">
<thead><tr>{header_cells}</tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody>
</table>
<p style="color:#6a7480;font-size:10pt;">{footer}</p>
</body></html>"""


def build_fill_message(cfg):
    """One chat op: fill every empty cell with the exact config value."""
    columns = [cfg["product"]] + cfg["competitors"]
    matrix = {
        cap["name"]: {col: cap["values"][col] for col in columns}
        for cap in cfg["capabilities"]
    }
    return (
        "Fill the empty cells of the comparison table using EXACTLY the values in this JSON "
        "(rows are capability names, keys are column headers):\n"
        + json.dumps(matrix, indent=2)
        + "\n\nRendering rules:\n"
        '- "yes" -> exactly the character ✓ (U+2713), colored green, nothing else in the cell\n'
        '- "no" -> exactly the character ✗ (U+2717), colored grey, nothing else in the cell\n'
        '- "partial" -> exactly the word "Partial" in amber\n'
        "- any other string -> use it verbatim as text\n"
        "Do NOT invent, soften, or embellish any claim. Do not add rows, columns, or "
        "commentary. Do not change ANY existing text: every header cell (including the "
        'first one, "Capability"), every row label, the title, the intro paragraph and '
        "the footer note must remain character-for-character identical."
    )


# ---------- verification (free: html export + local diff) ----------

def _cell_texts(row_html):
    cells = re.findall(r"<t[hd][ >].*?</t[hd]>|<t[hd]>.*?</t[hd]>", row_html, re.S)
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in cells]


def expected_cell(value):
    return {"yes": "✓", "no": "✗", "partial": "Partial"}.get(value, value)


def verify(session, cfg):
    """Export html (free) and diff the table against the config. Returns mismatch list."""
    blob = call("POST", "/v1/documents/export", {"session_id": session, "format": "html"})
    html = blob.decode("utf-8", errors="replace") if isinstance(blob, bytes) else json.dumps(blob)
    tbl = re.search(r"<table[ >].*?</table>", html, re.S)
    if not tbl:
        return ["no <table> found in exported html"]
    rows = re.findall(r"<tr[ >].*?</tr>|<tr>.*?</tr>", tbl.group(0), re.S)
    columns = [cfg["product"]] + cfg["competitors"]
    problems = []
    header = _cell_texts(rows[0]) if rows else []
    want_header = ["Capability"] + columns
    if header != want_header:
        problems.append(f"header is {header}, expected {want_header}")
    body = {r[0]: r[1:] for r in (_cell_texts(x) for x in rows[1:]) if r}
    for cap in cfg["capabilities"]:
        got = body.get(cap["name"])
        want = [expected_cell(cap["values"][c]) for c in columns]
        if got is None:
            problems.append(f"row '{cap['name']}' missing")
        elif got != want:
            problems.append(f"row '{cap['name']}' is {got}, expected {want}")
    if len(rows) - 1 != len(cfg["capabilities"]):
        problems.append(f"{len(rows) - 1} body rows, expected {len(cfg['capabilities'])}")
    return problems


# ---------- flow ----------

def wait_for(job_id, states, label):
    for i in range(POLL_LIMIT):
        time.sleep(POLL_SECONDS)
        j = call("GET", f"/v1/jobs/{job_id}")
        s = j.get("status")
        print(f"  [{i * POLL_SECONDS:>4}s] {label}: {s}")
        if s in states or s in ("failed", "cancelled"):
            return s, j
    sys.exit(f"Timed out waiting for {states} on job {job_id}")


def summarize_change(pc):
    op = pc.get("operation")
    new = re.sub(r"<[^>]+>", " ", pc.get("new_html") or "")
    new = re.sub(r"\s+", " ", new).strip()
    return f"{op} on chunk {pc.get('chunk_id')}: {new[:220]}{'...' if len(new) > 220 else ''}"


def run(cfg_path, auto_yes, out_dir):
    cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    slug = re.sub(r"[^a-z0-9.-]+", "-", Path(cfg_path).stem.lower())
    session = f"cmp-{slug}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"session: {session}")
    print(f"1) upload branded template ({len(cfg['competitors']) + 1} product columns, "
          f"{len(cfg['capabilities'])} capability rows)")
    html = build_template_html(cfg)
    call("POST", "/v1/documents/upload-base64", {
        "filename": f"{slug}.html",
        "file_base64": base64.b64encode(html.encode()).decode(),
        "session_id": session,
    })

    print("2) chat: fill table from config (1 operation)")
    job = call("POST", "/v1/chat/async", {
        "session_id": session,
        "message": build_fill_message(cfg),
        "approval_mode": "ask_every_time",
    })
    job_id = job["job_id"]

    state, j = wait_for(job_id, ("awaiting_approval", "completed"), "fill")
    if state == "awaiting_approval":
        pcs = (j.get("metadata") or {}).get("pending_changes") or []
        print(f"3) {len(pcs)} proposed change(s):")
        for pc in pcs:
            print("   - " + summarize_change(pc))
        if not auto_yes:
            ans = input("Approve these changes? [y/N] ").strip().lower()
            if ans != "y":
                call("POST", f"/v1/chat/{session}/approve", {
                    "job_id": job_id, "approved": False,
                    "changes": [{"change_id": p["change_id"], "approved": False,
                                 "feedback": "Rejected by operator"} for p in pcs],
                })
                sys.exit("Rejected. No operation billed beyond the proposal.")
        # NOTE: a bare {job_id, approved:true} is a silent no-op (SuperDocs quirk);
        # the explicit changes array is required for the job to proceed.
        ap = call("POST", f"/v1/chat/{session}/approve", {
            "job_id": job_id, "approved": True,
            "changes": [{"change_id": p["change_id"], "approved": True} for p in pcs],
        })
        if not ap.get("batch_complete"):
            sys.exit(f"Approval did not complete the batch: {ap}")
        state, j = wait_for(job_id, ("completed",), "apply")
    if state != "completed":
        sys.exit(f"Job ended in state {state}")

    print("4) verify filled table against config (free html export)")
    problems = verify(session, cfg)
    if problems:
        print("   drift detected:")
        for p in problems:
            print(f"   - {p}")
        print("   one repair operation:")
        job = call("POST", "/v1/chat/async", {
            "session_id": session,
            "message": ("The comparison table has drifted from the specification. Fix ONLY these "
                        "problems, changing nothing else:\n- " + "\n- ".join(problems)
                        + "\nReminder: header row must be exactly "
                        + json.dumps(["Capability", cfg["product"]] + cfg["competitors"])
                        + '; "yes" cells are exactly ✓, "no" cells exactly ✗, '
                          '"partial" cells exactly the word "Partial".'),
            "approval_mode": "ask_every_time",
        })
        state, j = wait_for(job["job_id"], ("awaiting_approval", "completed"), "repair")
        if state == "awaiting_approval":
            pcs = (j.get("metadata") or {}).get("pending_changes") or []
            call("POST", f"/v1/chat/{session}/approve", {
                "job_id": job["job_id"], "approved": True,
                "changes": [{"change_id": p["change_id"], "approved": True} for p in pcs],
            })
            state, j = wait_for(job["job_id"], ("completed",), "repair-apply")
        problems = verify(session, cfg)
        if problems:
            sys.exit("Still drifting after one repair round: " + "; ".join(problems))
        print("   repaired and verified clean")
    else:
        print("   verified: headers, rows and every cell match the config")

    usage = (j.get("result") or {}).get("usage") or {}
    print(f"5) export ({', '.join(cfg.get('outputs', ['docx']))})  [ops used this run: "
          f"{usage.get('operations', usage) or 'n/a'}]")
    for fmt in cfg.get("outputs", ["docx"]):
        blob = call("POST", "/v1/documents/export", {"session_id": session, "format": fmt})
        target = out_dir / f"{slug}.{fmt}"
        if isinstance(blob, bytes):
            target.write_bytes(blob)
        else:  # tolerate a JSON envelope
            b64 = blob.get("file_base64") or blob.get("content_base64")
            target.write_bytes(base64.b64decode(b64))
        print(f"   wrote {target} ({target.stat().st_size} bytes)")
    print("DONE")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("config", help="path to a JSON config (see configs/)")
    ap.add_argument("--yes", action="store_true", help="auto-approve proposed changes")
    ap.add_argument("--out", default="out", help="output directory (default: out/)")
    args = ap.parse_args()
    run(args.config, args.yes, Path(args.out))


if __name__ == "__main__":
    main()
