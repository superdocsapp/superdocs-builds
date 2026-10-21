"""Renders a `FidelityReport` as a machine-readable JSON document and a
human-readable Markdown/HTML report.

Both renderers are pure functions over `FidelityReport` (plus an optional
run/case id for filenames) — neither one touches the filesystem itself,
so callers decide where artifacts land (see `artifacts/fidelity-report/`
for the convention used by this app, and
`tests/fidelity/test_fidelity_reports.py` for how tests assert on the
written files).
"""

from __future__ import annotations

import json
from pathlib import Path

from src.fidelity.compare import DiffClassification, FidelityReport, IdentityVerdict

_VERDICT_LABEL = {
    IdentityVerdict.BYTE_IDENTICAL: "Byte-identical",
    IdentityVerdict.STRUCTURALLY_IDENTICAL: "Structurally identical",
    IdentityVerdict.SEMANTICALLY_UNCHANGED: "Semantically unchanged (only approved edits differ)",
    IdentityVerdict.NOT_VERIFIED: "NOT VERIFIED — unintended differences found",
}


def to_json(report: FidelityReport, *, indent: int = 2) -> str:
    return json.dumps(report.to_dict(), indent=indent, sort_keys=False)


def write_json_report(report: FidelityReport, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_json(report), encoding="utf-8")
    return path


def _escape_md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def to_markdown(report: FidelityReport) -> str:
    lines: list[str] = []
    lines.append(f"# Fidelity Report — {report.document_id}")
    lines.append("")
    lines.append(f"**Verdict:** {_VERDICT_LABEL[report.verdict]}")
    lines.append(f"**Surgical (no unintended diffs):** {'YES' if report.is_surgical else 'NO'}")
    lines.append(f"**Byte-identical:** {report.byte_identical}")
    lines.append(f"**Original SHA-256:** `{report.original_sha256}`")
    lines.append(f"**Exported SHA-256:** `{report.exported_sha256}`")
    if report.excluded_contract:
        lines.append(f"**Excluded contract:** YES — {report.excluded_reason}")
    lines.append("")

    lines.append("## Facet checks")
    lines.append("")
    lines.append("| Facet | Status | Reason |")
    lines.append("| --- | --- | --- |")
    for fc in report.facet_checks:
        lines.append(f"| {fc.facet} | {fc.status.value} | {fc.reason or ''} |")
    lines.append("")

    lines.append("## Intended edits considered")
    lines.append("")
    if not report.intended_edits_considered:
        lines.append("_No proposed changes were associated with this document (no SuperDocs session, or nothing proposed)._")
    else:
        lines.append("| change_id | chunk_id | disposition | should appear in export |")
        lines.append("| --- | --- | --- | --- |")
        for e in report.intended_edits_considered:
            lines.append(
                f"| {e.change_id} | {e.chunk_id} | {e.disposition.value} | {e.should_appear_in_export} |"
            )
    lines.append("")

    unintended = [d for d in report.diffs if d.classification == DiffClassification.UNINTENDED]
    intended = [d for d in report.diffs if d.classification == DiffClassification.INTENDED]

    lines.append(f"## Unintended differences ({len(unintended)})")
    lines.append("")
    if not unintended:
        lines.append("_None. Every observed difference is attributable to an approved change._")
    else:
        lines.append("| Facet | Location | Original | Exported | Reason |")
        lines.append("| --- | --- | --- | --- | --- |")
        for d in unintended:
            lines.append(
                f"| {d.facet} | {d.location} | {_escape_md(d.original_value or '(absent)')} | "
                f"{_escape_md(d.exported_value or '(absent)')} | {_escape_md(d.reason)} |"
            )
    lines.append("")

    lines.append(f"## Intended differences ({len(intended)})")
    lines.append("")
    if not intended:
        lines.append("_None._")
    else:
        lines.append("| Facet | Location | Original | Exported | Matched change |")
        lines.append("| --- | --- | --- | --- | --- |")
        for d in intended:
            lines.append(
                f"| {d.facet} | {d.location} | {_escape_md(d.original_value or '(absent)')} | "
                f"{_escape_md(d.exported_value or '(absent)')} | {d.matched_change_id or ''} |"
            )
    lines.append("")

    return "\n".join(lines)


def write_markdown_report(report: FidelityReport, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_markdown(report), encoding="utf-8")
    return path


_VERDICT_COLOR = {
    IdentityVerdict.BYTE_IDENTICAL: "#1a7f37",
    IdentityVerdict.STRUCTURALLY_IDENTICAL: "#1a7f37",
    IdentityVerdict.SEMANTICALLY_UNCHANGED: "#9a6700",
    IdentityVerdict.NOT_VERIFIED: "#cf222e",
}


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def to_html(report: FidelityReport) -> str:
    color = _VERDICT_COLOR[report.verdict]
    label = _VERDICT_LABEL[report.verdict]

    def diff_rows(diffs) -> str:
        if not diffs:
            return '<tr><td colspan="5"><em>None</em></td></tr>'
        rows = []
        for d in diffs:
            rows.append(
                "<tr>"
                f"<td>{_escape_html(d.facet)}</td>"
                f"<td>{_escape_html(d.location)}</td>"
                f"<td><code>{_escape_html(d.original_value or '(absent)')}</code></td>"
                f"<td><code>{_escape_html(d.exported_value or '(absent)')}</code></td>"
                f"<td>{_escape_html(d.reason)}{' — matched ' + d.matched_change_id if d.matched_change_id else ''}</td>"
                "</tr>"
            )
        return "\n".join(rows)

    unintended = [d for d in report.diffs if d.classification == DiffClassification.UNINTENDED]
    intended = [d for d in report.diffs if d.classification == DiffClassification.INTENDED]

    facet_rows = "\n".join(
        f"<tr><td>{_escape_html(fc.facet)}</td><td>{fc.status.value}</td><td>{_escape_html(fc.reason or '')}</td></tr>"
        for fc in report.facet_checks
    )

    edit_rows = "\n".join(
        f"<tr><td>{_escape_html(e.change_id)}</td><td>{_escape_html(e.chunk_id)}</td>"
        f"<td>{e.disposition.value}</td><td>{e.should_appear_in_export}</td></tr>"
        for e in report.intended_edits_considered
    ) or '<tr><td colspan="4"><em>No proposed changes for this document</em></td></tr>'

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Fidelity Report — {_escape_html(report.document_id)}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, sans-serif; margin: 2rem; color: #1f2328; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }}
  th, td {{ border: 1px solid #d0d7de; padding: 6px 10px; text-align: left; font-size: 0.9rem; vertical-align: top; }}
  th {{ background: #f6f8fa; }}
  .verdict {{ display: inline-block; padding: 4px 12px; border-radius: 6px; color: white; background: {color}; font-weight: 600; }}
  code {{ font-size: 0.85em; }}
  h1, h2 {{ border-bottom: 1px solid #d0d7de; padding-bottom: 4px; }}
</style>
</head>
<body>
<h1>Fidelity Report — {_escape_html(report.document_id)}</h1>
<p><span class="verdict">{_escape_html(label)}</span></p>
<ul>
  <li><strong>Surgical (no unintended diffs):</strong> {"YES" if report.is_surgical else "NO"}</li>
  <li><strong>Byte-identical:</strong> {report.byte_identical}</li>
  <li><strong>Original SHA-256:</strong> <code>{report.original_sha256}</code></li>
  <li><strong>Exported SHA-256:</strong> <code>{report.exported_sha256}</code></li>
  {"<li><strong>Excluded contract:</strong> YES — " + _escape_html(report.excluded_reason or "") + "</li>" if report.excluded_contract else ""}
</ul>

<h2>Facet checks</h2>
<table>
<tr><th>Facet</th><th>Status</th><th>Reason</th></tr>
{facet_rows}
</table>

<h2>Intended edits considered</h2>
<table>
<tr><th>change_id</th><th>chunk_id</th><th>disposition</th><th>should appear in export</th></tr>
{edit_rows}
</table>

<h2>Unintended differences ({len(unintended)})</h2>
<table>
<tr><th>Facet</th><th>Location</th><th>Original</th><th>Exported</th><th>Reason</th></tr>
{diff_rows(unintended)}
</table>

<h2>Intended differences ({len(intended)})</h2>
<table>
<tr><th>Facet</th><th>Location</th><th>Original</th><th>Exported</th><th>Reason</th></tr>
{diff_rows(intended)}
</table>

</body>
</html>
"""


def write_html_report(report: FidelityReport, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_html(report), encoding="utf-8")
    return path
