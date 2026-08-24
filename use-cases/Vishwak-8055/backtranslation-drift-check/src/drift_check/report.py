"""Bilingual drift report generation — markdown, JSON, and HTML."""

from __future__ import annotations

import html
import json
from typing import Any

from drift_check.models import DriftFinding, Severity
from drift_check.pipeline import RunResult
from drift_check.serialize import finding_to_dict

_SEVERITY_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]


def summary_metrics(result: RunResult) -> dict[str, Any]:
    findings = result.findings
    counts = {sev.value: 0 for sev in Severity}
    for f in findings:
        counts[f.severity.value] += 1
    review_counts: dict[str, int] = {}
    for f in findings:
        review_counts[f.review_status.value] = review_counts.get(f.review_status.value, 0) + 1
    integrity_ok = all(v.ok for v in result.integrity_verifications)
    return {
        "run_id": result.run_id,
        "sections_total": result.metrics.sections_total,
        "sections_processed": result.metrics.sections_processed,
        "sections_skipped_cached": result.metrics.sections_skipped_cached,
        "findings_total": len(findings),
        "critical": counts[Severity.CRITICAL.value],
        "high": counts[Severity.HIGH.value],
        "medium": counts[Severity.MEDIUM.value],
        "low": counts[Severity.LOW.value],
        "info_pass": counts[Severity.INFO.value],
        "review_status_breakdown": review_counts,
        "source_integrity_status": "VERIFIED" if integrity_ok else "FAILED",
        "integrity_checks_run": len(result.integrity_verifications),
        "provider_calls": result.metrics.provider_calls,
        "provider_retries": result.metrics.provider_retries,
    }


def to_json(result: RunResult) -> str:
    payload = {
        "summary": summary_metrics(result),
        "source_document": {
            "id": result.source_document.id,
            "title": result.source_document.title,
            "language": result.source_document.language,
            "hash": result.source_document.source_hash,
        },
        "target_document": {
            "id": result.target_document.id,
            "title": result.target_document.title,
            "language": result.target_document.language,
            "hash": result.target_document.source_hash,
        },
        "findings": [finding_to_dict(f) for f in result.findings],
        "audit_events": result.audit.as_list(),
    }
    return json.dumps(payload, indent=2, default=str)


def _sorted_findings(findings: list[DriftFinding]) -> list[DriftFinding]:
    return sorted(findings, key=lambda f: (f.section_index, _SEVERITY_ORDER.index(f.severity)))


def to_markdown(result: RunResult) -> str:
    s = summary_metrics(result)
    lines: list[str] = []
    lines.append(f"# Back-Translation Drift Report — {result.source_document.title}")
    lines.append("")
    lines.append(f"**Run ID:** `{s['run_id']}`  ")
    lines.append(
        f"**Source language:** {result.source_document.language} · "
        f"**Target language:** {result.target_document.language}  "
    )
    lines.append(
        f"**Source integrity:** SOURCE INTEGRITY: {s['source_integrity_status']} "
        f"({s['integrity_checks_run']} checkpoints)  "
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    for key in (
        "sections_total", "sections_processed", "sections_skipped_cached", "findings_total",
        "critical", "high", "medium", "low", "info_pass", "provider_calls", "provider_retries",
    ):
        lines.append(f"| {key.replace('_', ' ')} | {s[key]} |")
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    lines.append(
        "| # | Section | Severity | Category | Source | Translation | Back-translation | "
        "Detected drift | Proposed correction | Review |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for f in _sorted_findings(result.findings):
        correction = f.proposed_correction.instruction if f.proposed_correction else "—"
        section_ref = f.target_section_id or f.source_section_id
        cells = [
            str(f.section_index),
            section_ref,
            f.severity.value.upper(),
            f.category.value,
            _md_cell(f.source_text),
            _md_cell(f.target_text),
            _md_cell(f.back_translation),
            _md_cell(f.difference),
            _md_cell(correction),
            f.review_status.value,
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _md_cell(text: str, limit: int = 140) -> str:
    text = text.replace("\n", " ").replace("|", "\\|").strip()
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


# --- HTML report -------------------------------------------------------

_SEVERITY_COLOR = {
    Severity.CRITICAL: "#A0271E",
    Severity.HIGH: "#A5680E",
    Severity.MEDIUM: "#3B5B7A",
    Severity.LOW: "#6B6456",
    Severity.INFO: "#2E6A45",
}


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _finding_card_html(f: DriftFinding) -> str:
    color = _SEVERITY_COLOR[f.severity]
    provenance = "Deterministic" if f.verified_deterministically else "AI-assessed"
    if f.semantic_corroborated:
        provenance += " + semantic corroboration"
    correction_html = ""
    if f.proposed_correction:
        suggested = (
            f'<div class="suggested"><span class="label">Suggested text</span>'
            f'<div class="mono">{_esc(f.proposed_correction.suggested_text)}</div></div>'
            if f.proposed_correction.suggested_text
            else ""
        )
        correction_html = f"""
        <div class="correction">
          <div class="label">Proposed correction · targets translation only</div>
          <p>{_esc(f.proposed_correction.instruction)}</p>
          {suggested}
        </div>
        """
    is_pass = f.is_pass
    card_class = "pass" if is_pass else "finding"
    body = ""
    if not is_pass:
        body = f"""
        <div class="triple">
          <div><span class="label">Source</span><div class="mono">{_esc(f.source_text)}</div></div>
          <div><span class="label">Translation</span><div class="mono">{_esc(f.target_text)}</div></div>
          <div><span class="label">Back-translation</span><div class="mono">{_esc(f.back_translation)}</div></div>
        </div>
        <p class="difference">{_esc(f.difference)}</p>
        {correction_html}
        <div class="actions" data-finding-id="{_esc(f.id)}">
          <button class="approve" onclick="reviewAction(this, 'approved')">Approve</button>
          <button class="reject" onclick="reviewAction(this, 'rejected')">Reject</button>
          <button class="edit" onclick="reviewAction(this, 'edited')">Edit</button>
          <span class="status">{_esc(f.review_status.value.replace('_', ' '))}</span>
        </div>
        """
    else:
        body = f'<p class="difference">{_esc(f.difference)}</p>'

    return f"""
    <article class="card {card_class}" style="--sev-color:{color}">
      <header>
        <span class="idx">§{f.section_index}</span>
        <span class="stamp" style="--sev-color:{color}">{_esc(f.severity.value.upper())}</span>
        <span class="category">{_esc(f.category.value.replace('_', ' '))}</span>
        <span class="provenance">{_esc(provenance)}</span>
      </header>
      {body}
    </article>
    """


def to_html(result: RunResult) -> str:
    s = summary_metrics(result)
    findings = _sorted_findings(result.findings)
    cards = "\n".join(_finding_card_html(f) for f in findings)
    integrity_ok = s["source_integrity_status"] == "VERIFIED"

    severity_rows = "".join(
        f'<div class="bar-row"><span class="bar-label">{sev.value.upper()}</span>'
        f'<div class="bar-track"><div class="bar-fill" style="--sev-color:{_SEVERITY_COLOR[sev]};'
        f'width:{(s[sev.value if sev != Severity.INFO else "info_pass"] / max(1, s["findings_total"])) * 100:.0f}%">'
        f'</div></div><span class="bar-count">{s[sev.value if sev != Severity.INFO else "info_pass"]}</span></div>'
        for sev in _SEVERITY_ORDER
    )

    source_lang_esc = _esc(result.source_document.language)
    target_lang_esc = _esc(result.target_document.language)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Drift Report — {_esc(result.source_document.title)}</title>
<style>
{_HTML_CSS}
</style>
</head>
<body>
<div class="layout">
  <aside class="rail">
    <h1>{_esc(result.source_document.title)}</h1>
    <p class="run-id">Run <span class="mono">{_esc(result.run_id)}</span></p>
    <div class="stamp-block {'ok' if integrity_ok else 'fail'}">
      <div class="stamp big">SOURCE INTEGRITY<br>{_esc(s['source_integrity_status'])}</div>
      <p>{s['integrity_checks_run']} checkpoints verified</p>
    </div>
    <div class="lang-pair">{source_lang_esc} → {target_lang_esc} → {source_lang_esc}</div>
    <h2>Severity</h2>
    <div class="bars">{severity_rows}</div>
    <h2>Sections</h2>
    <table class="meta-table">
      <tr><td>Total</td><td>{s['sections_total']}</td></tr>
      <tr><td>Processed</td><td>{s['sections_processed']}</td></tr>
      <tr><td>Cached (resumed)</td><td>{s['sections_skipped_cached']}</td></tr>
      <tr><td>Provider calls</td><td>{s['provider_calls']}</td></tr>
      <tr><td>Provider retries</td><td>{s['provider_retries']}</td></tr>
    </table>
    <p class="footnote">
      Corrections always target the translation. The source shown here is
      read-only and independently hash-verified at every pipeline checkpoint.
    </p>
  </aside>
  <main class="ledger">
    {cards}
  </main>
</div>
<script>
function reviewAction(btn, decision) {{
  const actions = btn.closest('.actions');
  const status = actions.querySelector('.status');
  status.textContent = decision.replace('_',' ');
  actions.dataset.decision = decision;
  actions.querySelectorAll('button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  // Client-side only: this demo report does not persist review decisions.
}}
</script>
</body>
</html>
"""


_HTML_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:wght@600;700;900&display=swap');
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap');
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&display=swap');

:root {
  --paper: #EEF0EC;
  --paper-raised: #FFFFFF;
  --ink: #1C2321;
  --ink-muted: #5B655F;
  --rule: #CBD1C6;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: 'IBM Plex Sans', -apple-system, sans-serif;
  -webkit-font-smoothing: antialiased;
}
.layout { display: grid; grid-template-columns: 300px 1fr; gap: 0; min-height: 100vh; }
.rail {
  position: sticky; top: 0; align-self: start; height: 100vh; overflow-y: auto;
  padding: 28px 22px; background: var(--paper-raised); border-right: 1px solid var(--rule);
}
.rail h1 {
  font-family: 'Fraunces', serif; font-weight: 700; font-size: 1.35rem;
  line-height: 1.25; margin: 0 0 6px; letter-spacing: -0.01em;
}
.run-id { font-size: 0.78rem; color: var(--ink-muted); margin: 0 0 18px; }
.mono { font-family: 'IBM Plex Mono', ui-monospace, monospace; }
.stamp-block { border: 2px solid var(--rule); border-radius: 4px; padding: 14px; margin-bottom: 18px; }
.stamp-block.ok { border-color: #2E6A45; }
.stamp-block.fail { border-color: #A0271E; }
.stamp.big {
  font-family: 'Fraunces', serif; font-weight: 900; font-size: 1.05rem; text-align: center;
  color: #2E6A45; border: 3px double #2E6A45; border-radius: 4px; padding: 8px; transform: rotate(-1.5deg);
  letter-spacing: 0.03em;
}
.stamp-block.fail .stamp.big { color: #A0271E; border-color: #A0271E; }
.stamp-block p { font-size: 0.75rem; color: var(--ink-muted); text-align: center; margin: 8px 0 0; }
.lang-pair {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.85rem;
  color: var(--ink-muted); margin-bottom: 18px;
}
.rail h2 {
  font-family: 'Fraunces', serif; font-size: 0.95rem; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--ink-muted); margin: 22px 0 10px;
}
.bars { display: flex; flex-direction: column; gap: 6px; }
.bar-row { display: grid; grid-template-columns: 52px 1fr 20px; align-items: center; gap: 8px; font-size: 0.72rem; }
.bar-label { color: var(--ink-muted); font-weight: 500; }
.bar-track { background: var(--paper); border-radius: 2px; height: 8px; overflow: hidden; }
.bar-fill { background: var(--sev-color); height: 100%; }
.bar-count { text-align: right; font-family: 'IBM Plex Mono', monospace; }
.meta-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.meta-table td { padding: 3px 0; border-bottom: 1px solid var(--paper); }
.meta-table td:last-child { text-align: right; font-family: 'IBM Plex Mono', monospace; }
.footnote { font-size: 0.72rem; color: var(--ink-muted); margin-top: 22px; line-height: 1.4; }

.ledger { padding: 28px 32px 80px; max-width: 920px; }
.card {
  background: var(--paper-raised); border: 1px solid var(--rule); border-left: 4px solid var(--sev-color);
  border-radius: 3px; padding: 18px 20px; margin-bottom: 16px;
}
.card.pass { border-left-color: #2E6A45; opacity: 0.85; }
.card header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.idx { font-family: 'IBM Plex Mono', monospace; color: var(--ink-muted); font-size: 0.85rem; }
.stamp {
  font-family: 'Fraunces', serif; font-weight: 700; font-size: 0.7rem; letter-spacing: 0.05em;
  color: var(--sev-color); border: 1.5px solid var(--sev-color); border-radius: 3px; padding: 2px 8px;
  transform: rotate(-1deg);
}
.category { font-size: 0.78rem; color: var(--ink-muted); text-transform: capitalize; }
.provenance {
  margin-left: auto; font-size: 0.7rem; color: var(--ink-muted);
  background: var(--paper); padding: 2px 8px; border-radius: 10px;
}
.triple { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 10px; }
.triple .label {
  display: block; font-size: 0.68rem; text-transform: uppercase;
  letter-spacing: 0.05em; color: var(--ink-muted); margin-bottom: 4px;
}
.triple .mono {
  font-size: 0.82rem; line-height: 1.45; background: var(--paper);
  padding: 8px 10px; border-radius: 3px;
}
.difference { font-size: 0.88rem; margin: 10px 0; }
.correction { background: #F5F1E6; border: 1px solid #E4D9BC; border-radius: 3px; padding: 10px 12px; margin: 10px 0; }
.correction .label {
  display: block; font-size: 0.68rem; text-transform: uppercase;
  letter-spacing: 0.05em; color: #7A6A33; margin-bottom: 4px;
}
.correction p { margin: 0 0 6px; font-size: 0.85rem; }
.suggested .mono { font-size: 0.82rem; background: #FFFFFF; padding: 6px 8px; border-radius: 3px; margin-top: 4px; }
.actions { display: flex; align-items: center; gap: 8px; margin-top: 12px; }
.actions button {
  font-family: 'IBM Plex Sans', sans-serif; font-size: 0.78rem; font-weight: 500; padding: 5px 12px;
  border-radius: 3px; border: 1px solid var(--rule); background: var(--paper-raised); cursor: pointer;
}
.actions button.approve.active { background: #2E6A45; color: white; border-color: #2E6A45; }
.actions button.reject.active { background: #A0271E; color: white; border-color: #A0271E; }
.actions button.edit.active { background: #3B5B7A; color: white; border-color: #3B5B7A; }
.actions .status { margin-left: auto; font-size: 0.72rem; color: var(--ink-muted); text-transform: capitalize; }

@media (max-width: 800px) {
  .layout { grid-template-columns: 1fr; }
  .rail { position: static; height: auto; }
  .triple { grid-template-columns: 1fr; }
}
"""
