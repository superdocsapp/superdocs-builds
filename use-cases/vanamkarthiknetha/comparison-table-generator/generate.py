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
import zipfile
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

ZEBRA = "#f5f7fa"


def _header_style(accent):
    # background-color (longhand) is deliberate: the docx/pdf exporter drops the
    # `background:` shorthand while keeping `color`, which renders white header
    # text on no fill - i.e. invisible. See README "Export fidelity".
    return (f"background-color:{accent};color:#ffffff;padding:10px 14px;"
            f"text-align:left;border:1px solid {accent};font-weight:700;")


def _body_style(shade, label=False):
    return (f"padding:9px 14px;border:1px solid #d9dee5;background-color:{shade};"
            + ("font-weight:600;" if label else ""))


def build_template_html(cfg):
    brand = cfg.get("brand", {})
    accent = brand.get("accent_color", "#1a4f8b")
    product = cfg["product"]
    columns = [product] + cfg["competitors"]
    header_cells = "".join(
        f'<th style="{_header_style(accent)}">{c}</th>'
        for c in ["Capability"] + columns
    )
    rows = []
    for i, cap in enumerate(cfg["capabilities"]):
        shade = ZEBRA if i % 2 else "#ffffff"
        empty = "".join(f'<td style="{_body_style(shade)}"></td>' for _ in columns)
        rows.append(
            f'<tr><td style="{_body_style(shade, label=True)}">{cap["name"]}</td>{empty}</tr>'
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


# ---------- deterministic branding pass ----------

def _set_decls(style, overrides):
    """Merge CSS declarations, dropping any prior background/background-color."""
    decls = []
    for part in (style or "").split(";"):
        if ":" not in part:
            continue
        prop, _, val = part.partition(":")
        prop = prop.strip()
        if prop.lower() in ("background", "background-color") or prop.lower() in overrides:
            continue
        decls.append(f"{prop}:{val.strip()}")
    decls.extend(f"{k}:{v}" for k, v in overrides.items())
    return ";".join(decls) + ";"


def enforce_branding(html, cfg):
    """Re-apply the brand styling to the final table locally.

    The AI owns the cell *content*; this pipeline owns the *look*. Doing it here
    (rather than trusting the model to preserve inline styles through a rewrite)
    makes the branding deterministic and immune to both model drift and the
    exporter's shorthand-background gap.
    """
    accent = cfg.get("brand", {}).get("accent_color", "#1a4f8b")
    table = re.search(r"<table\b[^>]*>.*?</table>", html, re.S)
    if not table:
        return html
    body_row = [0]

    def fix_row(m):
        row = m.group(0)
        if "<th" in row.lower():
            return re.sub(
                r"<th\b([^>]*)>",
                lambda c: "<th" + _swap_style(c.group(1), _header_style(accent)) + ">",
                row)
        shade = ZEBRA if body_row[0] % 2 else "#ffffff"
        body_row[0] += 1
        first = [True]

        def fix_cell(c):
            style = _set_decls(_style_of(c.group(1)),
                              {"background-color": shade,
                               **({"font-weight": "600"} if first[0] else {})})
            first[0] = False
            return "<td" + _swap_style(c.group(1), style) + ">"

        return re.sub(r"<td\b([^>]*)>", fix_cell, row)

    fixed = re.sub(r"<tr\b[^>]*>.*?</tr>", fix_row, table.group(0), flags=re.S)
    return html[:table.start()] + fixed + html[table.end():]


def _style_of(attrs):
    m = re.search(r'style\s*=\s*"([^"]*)"', attrs or "")
    return m.group(1) if m else ""


def _swap_style(attrs, style):
    attrs = attrs or ""
    if re.search(r'style\s*=\s*"[^"]*"', attrs):
        return re.sub(r'style\s*=\s*"[^"]*"', f'style="{style}"', attrs)
    return attrs + f' style="{style}"'


def assert_visible(docx_path):
    """Guard against the invisible-header failure mode ever shipping again."""
    with zipfile.ZipFile(docx_path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    tbl = re.search(r"<w:tbl>.*?</w:tbl>", xml, re.S)
    if not tbl:
        return ["no table in exported docx"]
    header = re.search(r"<w:tr[ >].*?</w:tr>", tbl.group(0), re.S).group(0)
    problems = []
    for cell in re.findall(r"<w:tc[ >].*?</w:tc>", header, re.S):
        text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", cell)).strip()
        fill = re.findall(r'<w:shd[^>]*w:fill="([^"]*)"', cell)
        color = re.findall(r'<w:color[^>]*w:val="([^"]*)"', cell)
        white_text = color and color[0].upper() == "FFFFFF"
        no_fill = not fill or fill[0].upper() in ("AUTO", "FFFFFF")
        if text and white_text and no_fill:
            problems.append(f"header cell '{text}' is white text on no fill (invisible)")
    return problems


# ---------- verification (free: html export + local diff) ----------

def _cell_texts(row_html):
    cells = re.findall(r"<t[hd][ >].*?</t[hd]>|<t[hd]>.*?</t[hd]>", row_html, re.S)
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in cells]


def expected_cell(value):
    return {"yes": "✓", "no": "✗", "partial": "Partial"}.get(value, value)


def export_html(session):
    """Free: the session's current document as html."""
    blob = call("POST", "/v1/documents/export", {"session_id": session, "format": "html"})
    return blob.decode("utf-8", errors="replace") if isinstance(blob, bytes) else json.dumps(blob)


def verify(session, cfg):
    """Export html (free) and diff the table against the config. Returns mismatch list."""
    html = export_html(session)
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

    print("5) re-apply brand styling locally (deterministic, free)")
    branded = enforce_branding(export_html(session), cfg)

    usage = (j.get("result") or {}).get("usage") or {}
    print(f"6) export ({', '.join(cfg.get('outputs', ['docx']))})  [ops used this run: "
          f"{usage.get('operations', usage) or 'n/a'}]")
    for fmt in cfg.get("outputs", ["docx"]):
        blob = call("POST", "/v1/documents/export", {"html": branded, "format": fmt})
        target = out_dir / f"{slug}.{fmt}"
        if isinstance(blob, bytes):
            target.write_bytes(blob)
        else:  # tolerate a JSON envelope
            b64 = blob.get("file_base64") or blob.get("content_base64")
            target.write_bytes(base64.b64decode(b64))
        print(f"   wrote {target} ({target.stat().st_size} bytes)")
        if fmt == "docx":
            invisible = assert_visible(target)
            if invisible:
                sys.exit("Export visibility check FAILED: " + "; ".join(invisible))
            print("   visibility check passed (header cells render)")
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
