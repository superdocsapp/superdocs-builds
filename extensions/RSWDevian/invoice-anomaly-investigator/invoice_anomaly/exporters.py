from __future__ import annotations

from html import escape
import json
from typing import Any


def _html(report: dict[str, Any]) -> bytes:
    rows = []
    for finding in report["findings"]:
        evidence = "<br>".join(
            f"{escape(item['source'])} ({escape(item['pointer'])}): {escape(item['excerpt'])}"
            for item in finding["evidence"]
        ) or "none"
        rows.append(
            "<tr>"
            f"<td>{escape(finding['code'])}</td>"
            f"<td>{escape(finding['severity'])}</td>"
            f"<td>{escape(finding['message'])}</td>"
            f"<td>{evidence}</td>"
            "</tr>"
        )
    decisions = "".join(
        f"<li>{escape(item['item_id'])}: {escape(item['decision'])} by {escape(item.get('reviewer') or '')}"
        f" - {escape(item.get('rationale') or '')}</li>"
        for item in report["decisions"]
    )
    body = "".join(rows) or '<tr><td colspan="4">No anomalies detected.</td></tr>'
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Invoice anomaly investigation</title>
<style>body{{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #bbb;padding:.5rem;text-align:left;vertical-align:top}}.critical{{color:#9b1c1c}}</style>
</head><body><h1>Invoice anomaly investigation</h1>
<p><strong>Status:</strong> {escape(report['state'])}</p>
<p><strong>Input hash:</strong> {escape(report['input_hash'])}</p>
<h2>Findings</h2><table><thead><tr><th>Code</th><th>Severity</th><th>Message</th><th>Evidence</th></tr></thead><tbody>{body}</tbody></table>
<h2>Review decisions</h2><ul>{decisions}</ul>
<p>This fixture report is for investigation support and requires human review; it is not a fraud determination.</p>
</body></html>"""
    return html.encode()


def export_report(report: dict[str, Any], format_name: str = "html") -> tuple[str, bytes]:
    if format_name == "json":
        return "application/json", json.dumps(report, sort_keys=True, indent=2).encode()
    if format_name == "html":
        return "text/html", _html(report)
    raise ValueError("format must be html or json")
