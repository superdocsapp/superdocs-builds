"""Negotiation summary, generated from the same change records as the redline."""

from __future__ import annotations

import re
from html import escape

VERDICT_LABEL = {
    "acceptable": "Acceptable — left untouched",
    "position_unacceptable": "Unacceptable — fallback wording applied",
    "missing_clause": "Missing — clause inserted",
    "not_present_ok": "Not present — no action required",
    "out_of_scope_proposal": "Out-of-scope proposal — denied",
    "no_change": "No change made",
}


def _strip_tags(html: str | None) -> str:
    return re.sub(r"<[^>]+>", " ", html or "").strip()


def build_summary_html(playbook, state: dict, ledger) -> str:
    rows = []
    for rec in state["records"]:
        old = _strip_tags(rec.get("old_html"))
        new = _strip_tags(rec.get("new_html"))
        position = {
            "approved": f"Replaced with playbook wording: “{escape(new[:300])}”",
            "denied": "Proposed change denied by reviewer; carrier wording stands pending negotiation.",
            "untouched": "Carrier wording accepted as-is.",
            "n/a": "No clause present; playbook does not require one.",
        }.get(rec["decision"], rec["decision"])
        rows.append(
            "<tr>"
            f"<td>{escape(rec['rule_id'])} — {escape(rec['rule_name'])}</td>"
            f"<td>{escape(VERDICT_LABEL.get(rec['verdict'], rec['verdict']))}</td>"
            f"<td>{escape(old[:300]) or '—'}</td>"
            f"<td>{position}</td>"
            f"<td>{escape(rec['detail'][:300])}</td>"
            "</tr>"
        )

    anomaly_html = ""
    if state.get("anomalies"):
        items = "".join(f"<li>{escape(a['text'])}</li>" for a in state["anomalies"])
        anomaly_html = (
            "<h2>Anomalies: embedded instructions found in the carrier's paper</h2>"
            "<p>The following passages address automated review systems directly. They were treated as "
            "content under review, reported here, and not acted upon.</p>"
            f"<ul>{items}</ul>"
        )

    approved = sum(1 for r in state["records"] if r["decision"] == "approved")
    untouched = sum(1 for r in state["records"] if r["decision"] == "untouched")

    return (
        f"<h1>Negotiation Summary — {escape(playbook.shipper)}</h1>"
        f"<p>Redline of the carrier's paper against the shipper playbook ({len(playbook.rules)} rules). "
        f"{approved} position(s) redlined to playbook wording; {untouched} clause(s) acceptable and untouched. "
        "Every position below cites the playbook rule that drove it; this summary and the redlined contract "
        "are generated from the same change records and cannot disagree.</p>"
        "<table><tr><th>Playbook rule</th><th>Finding</th><th>Carrier's position</th><th>Position taken</th><th>Basis / reviewer note</th></tr>"
        + "".join(rows)
        + "</table>"
        + anomaly_html
    )
