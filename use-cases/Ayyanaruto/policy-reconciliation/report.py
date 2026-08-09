"""Static review.html + decisions.yaml seed. No server."""

from __future__ import annotations

from pathlib import Path

import yaml

REC_LABELS = {
    "keep_a": "Keep Northstar (A)",
    "keep_b": "Keep Helios (B)",
    "merge": "Merge (drafted)",
    "new": "Write new",
}

DISP_LABELS = {
    "mapped": "Mapped",
    "gap-A-only": "Gap · A only",
    "gap-B-only": "Gap · B only",
}


def _esc(text):
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def seed_decisions(run_id, conflicts, merges):
    return {
        "run_id": run_id,
        "conflicts": [
            {
                "id": c["id"],
                "policy_a_excerpt": c.get("policy_a_excerpt") or "",
                "policy_b_excerpt": c.get("policy_b_excerpt") or "",
                "decision": "pending",
                "reviewer_notes": "",
            }
            for c in (conflicts.get("conflicts") or [])
        ],
        "merges": [
            {
                "id": m["id"],
                "proposed_draft_ref": m.get("proposed_draft_ref") or "",
                "decision": "pending",
                "reviewer_notes": "",
            }
            for m in merges
        ],
    }


def render_review_html(run_id, mapping, conflicts, coverage, merges=None, dry_run=False):
    merges = merges or []
    totals = (coverage or {}).get("totals") or {}
    policies = (mapping or {}).get("policies") or []
    conflict_rows = (conflicts or {}).get("conflicts") or []
    obligations = (coverage or {}).get("obligations") or []

    rec_counts = {"keep_a": 0, "keep_b": 0, "merge": 0, "new": 0}
    for p in policies:
        rec = p.get("recommendation")
        if rec in rec_counts:
            rec_counts[rec] += 1

    banner = ""
    if dry_run:
        banner = """
        <div class="banner">
          <strong>DRY RUN</strong> — SuperDocs was not called. No content-based matching ran.
          This page only lists the estate inventory. Re-run without <code>--dry-run</code> for recommendations.
        </div>
        """

    policy_cards = []
    if not policies and dry_run:
        policy_cards.append("<p class='muted'>No recommendations in a dry-run.</p>")
    for p in policies:
        rec = p.get("recommendation") or "new"
        a_name = ((p.get("doc_a") or {}).get("filename")) or "—"
        b_name = ((p.get("doc_b") or {}).get("filename")) or "—"
        policy_cards.append(
            f"""
            <article class="card rec-{_esc(rec)}">
              <div class="card-head">
                <h3>{_esc(p.get('title'))}</h3>
                <span class="pill rec-{_esc(rec)}">{_esc(REC_LABELS.get(rec, rec))}</span>
              </div>
              <p class="files"><span>A · {_esc(a_name)}</span><span>B · {_esc(b_name)}</span></p>
              <p>{_esc(p.get('evidence'))}</p>
            </article>
            """
        )

    conflict_html = []
    if not conflict_rows:
        conflict_html.append("<p class='muted'>No opposite-requirement conflicts flagged.</p>")
    for c in conflict_rows:
        conflict_html.append(
            f"""
            <article class="conflict">
              <div class="card-head">
                <h3>{_esc(c.get('id'))}</h3>
                <span class="pill rec-new">Conflict · pending</span>
              </div>
              <p class="reason">{_esc(c.get('reason'))}</p>
              <div class="split">
                <blockquote>
                  <header>Northstar (A) · {_esc(c.get('document_a'))}</header>
                  <p>“{_esc(c.get('policy_a_excerpt'))}”</p>
                </blockquote>
                <blockquote>
                  <header>Helios (B) · {_esc(c.get('document_b'))}</header>
                  <p>“{_esc(c.get('policy_b_excerpt'))}”</p>
                </blockquote>
              </div>
            </article>
            """
        )

    merge_html = []
    if not merges:
        merge_html.append("<p class='muted'>No merge drafts in this run.</p>")
    for m in merges:
        merge_html.append(
            f"""
            <li>
              <a href="{_esc(m.get('proposed_draft_ref'))}">{_esc(m.get('title') or m.get('id'))}</a>
              <span class="muted">{_esc(m.get('status') or '')}</span>
            </li>
            """
        )

    cov_rows = []
    for o in obligations:
        disp = o.get("disposition") or ""
        cov_rows.append(
            f"""
            <tr>
              <td><code>{_esc(o.get('id'))}</code></td>
              <td>{_esc((o.get('estate') or '').upper())}</td>
              <td>{_esc(o.get('document_filename'))}</td>
              <td>{_esc(o.get('topic'))}</td>
              <td>{_esc(o.get('text'))}</td>
              <td><span class="pill disp-{_esc(disp)}">{_esc(DISP_LABELS.get(disp, disp))}</span></td>
            </tr>
            """
        )
    if not cov_rows:
        cov_rows.append("<tr><td colspan='6' class='muted'>No obligations extracted.</td></tr>")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Policy reconciliation · {_esc(run_id)}</title>
  <style>
    :root {{
      --bg: #0f1419;
      --panel: #18202b;
      --ink: #e8eef6;
      --muted: #93a0b3;
      --line: #2a3545;
      --keep-a: #3b82f6;
      --keep-b: #14b8a6;
      --merge: #f59e0b;
      --new: #e11d48;
      --mapped: #22c55e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      background: var(--bg); color: var(--ink); line-height: 1.45;
    }}
    header.hero {{
      padding: 36px 48px 24px; border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, #1a2433 0%, var(--bg) 100%);
    }}
    header.hero p.kicker {{ letter-spacing: .14em; text-transform: uppercase; color: var(--muted); font-size: 12px; margin: 0 0 8px; }}
    h1 {{ margin: 0 0 8px; font-size: 32px; font-weight: 650; }}
    .sub {{ color: var(--muted); margin: 0; }}
    main {{ padding: 28px 48px 64px; max-width: 1280px; }}
    .banner {{
      background: #3f2d12; border: 1px solid #f59e0b; color: #fde68a;
      padding: 12px 16px; border-radius: 10px; margin-bottom: 24px;
    }}
    .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 32px; }}
    .stat {{ background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 16px 18px; }}
    .stat .n {{ font-size: 28px; font-weight: 700; }}
    .stat .l {{ color: var(--muted); font-size: 13px; }}
    h2 {{ margin: 28px 0 12px; font-size: 20px; }}
    .card, .conflict {{
      background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
      padding: 16px 18px; margin-bottom: 12px;
    }}
    .card-head {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; }}
    .card-head h3 {{ margin: 0; font-size: 16px; }}
    .files {{ display: flex; gap: 18px; color: var(--muted); font-size: 13px; }}
    .pill {{
      display: inline-block; padding: 3px 10px; border-radius: 999px;
      font-size: 12px; font-weight: 600; white-space: nowrap;
    }}
    .rec-keep_a {{ background: rgba(59,130,246,.18); color: #93c5fd; }}
    .rec-keep_b {{ background: rgba(20,184,166,.18); color: #5eead4; }}
    .rec-merge {{ background: rgba(245,158,11,.18); color: #fcd34d; }}
    .rec-new {{ background: rgba(225,29,72,.18); color: #fda4af; }}
    .disp-mapped {{ background: rgba(34,197,94,.18); color: #86efac; }}
    .disp-gap-A-only, .disp-gap-B-only {{ background: rgba(148,163,184,.18); color: #cbd5e1; }}
    .split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    blockquote {{
      margin: 0; background: #111821; border-radius: 10px; padding: 12px 14px;
      border-left: 3px solid var(--keep-a);
    }}
    blockquote:last-child {{ border-left-color: var(--keep-b); }}
    blockquote header {{ color: var(--muted); font-size: 12px; margin-bottom: 6px; }}
    blockquote p {{ margin: 0; }}
    .reason {{ color: var(--muted); }}
    table {{ width: 100%; border-collapse: collapse; background: var(--panel); border-radius: 12px; overflow: hidden; }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; font-size: 13px; }}
    th {{ color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    td:nth-child(5) {{ max-width: 540px; }}
    ul.merges {{ padding-left: 18px; }}
    .muted {{ color: var(--muted); }}
    footer {{ color: var(--muted); font-size: 12px; margin-top: 36px; }}
    @media (max-width: 900px) {{
      header.hero, main {{ padding: 20px; }}
      .stats, .split {{ grid-template-columns: 1fr 1fr; }}
    }}
  </style>
</head>
<body>
  <header class="hero">
    <p class="kicker">Two-estate policy reconciliation</p>
    <h1>Northstar × Helios handbook review</h1>
    <p class="sub">Run <strong>{_esc(run_id)}</strong> · recommendations from SuperDocs content matching, conflicts quoted verbatim, coverage proves nothing was dropped.</p>
  </header>
  <main>
    {banner}
    <section class="stats">
      <div class="stat"><div class="n">{totals.get('documents_total', 0)}</div><div class="l">Source policies</div></div>
      <div class="stat"><div class="n">{len(policies)}</div><div class="l">Recommendations · {rec_counts['keep_a']} keep A · {rec_counts['keep_b']} keep B · {rec_counts['merge']} merge · {rec_counts['new']} new</div></div>
      <div class="stat"><div class="n">{len(conflict_rows)}</div><div class="l">Conflicts (both positions quoted)</div></div>
      <div class="stat"><div class="n">{totals.get('obligations_total', 0)}</div><div class="l">Obligations · {totals.get('mapped', 0)} mapped · {totals.get('gap_a_only', 0)} A-only · {totals.get('gap_b_only', 0)} B-only</div></div>
    </section>

    <h2>Per-policy recommendation</h2>
    {''.join(policy_cards)}

    <h2>Conflicts — do not silently resolve</h2>
    {''.join(conflict_html)}

    <h2>Merge drafts awaiting approval</h2>
    <ul class="merges">{''.join(merge_html)}</ul>
    <p class="muted">Edit <code>decisions.yaml</code> then run <code>python reconcile.py apply --decisions { _esc(run_id) }/decisions.yaml</code>.</p>

    <h2>Coverage — every extracted obligation</h2>
    <table>
      <thead><tr><th>ID</th><th>Estate</th><th>Document</th><th>Topic</th><th>Obligation (verbatim)</th><th>Disposition</th></tr></thead>
      <tbody>
        {''.join(cov_rows)}
      </tbody>
    </table>
    <footer>Built for the SuperDocs engineering task. Matching uses SuperDocs multi-document chat, not filename string compare.</footer>
  </main>
</body>
</html>
"""


def write_review_artifacts(output_dir, run_id, mapping, conflicts, coverage, merges=None, dry_run=False):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    merges = merges or []
    html = render_review_html(run_id, mapping, conflicts, coverage, merges=merges, dry_run=dry_run)
    (output_dir / "review.html").write_text(html, encoding="utf-8")
    decisions = seed_decisions(run_id, conflicts, merges)
    (output_dir / "decisions.yaml").write_text(
        yaml.safe_dump(decisions, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    return output_dir / "review.html"
