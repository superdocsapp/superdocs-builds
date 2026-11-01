from __future__ import annotations

import html as htmlmod
import re

from soc2_index.models import IndexDiff, IndexDoc, IndexRow

COLUMNS = [
    "Control ID",
    "Criterion",
    "Status",
    "Evidence title",
    "Date",
    "Owner",
    "Source",
    "SHA-256",
    "Gap reason",
]

EM = "—"


def slug(row_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", row_id).strip("-")


def _cell(value: str | None, gap: bool) -> str:
    if gap or value is None or value == "":
        return EM
    return value


def row_cells(row: IndexRow) -> list[str]:
    gap = row.status == "GAP"
    if gap:
        return [
            row.control_id,
            row.criterion,
            "GAP",
            EM,
            EM,
            EM,
            EM,
            EM,
            row.gap_reason or EM,
        ]
    return [
        row.control_id,
        row.criterion,
        "Present",
        row.evidence_title or EM,
        row.date or EM,
        row.owner or EM,
        row.source_path or EM,
        row.sha256 or EM,
        EM,
    ]


def serialize_tr(row: IndexRow) -> str:
    cells = "".join(f"<td>{htmlmod.escape(c)}</td>" for c in row_cells(row))
    return f'<tr id="idx-{slug(row.row_id)}" data-row-id="{htmlmod.escape(row.row_id, quote=True)}">{cells}</tr>'


def _thead() -> str:
    th = "".join(f"<th>{htmlmod.escape(c)}</th>" for c in COLUMNS)
    return f"<thead><tr>{th}</tr></thead>"


def html(index: IndexDoc) -> str:
    body_rows = "\n".join(serialize_tr(r) for r in index.rows)
    gaps = [r for r in index.rows if r.status == "GAP"]
    gap_rows = "\n".join(serialize_tr(r) for r in gaps) if gaps else "<tr><td colspan=\"9\">None</td></tr>"
    unmapped = index.unmapped
    flagged = index.flagged
    um = (
        "<ul>"
        + "".join(
            f"<li>{htmlmod.escape(u.relative_path)} ({htmlmod.escape(u.reason)})</li>" for u in unmapped
        )
        + "</ul>"
        if unmapped
        else "<p>None</p>"
    )
    fl = (
        "<ul>"
        + "".join(
            f"<li>{htmlmod.escape(f.relative_path)} flags={htmlmod.escape(','.join(f.injection_flags))}</li>"
            for f in flagged
        )
        + "</ul>"
        if flagged
        else "<p>None</p>"
    )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head><meta charset=\"utf-8\"><title>SOC2 Evidence Index</title></head>\n"
        "<body>\n"
        "<h1>SOC2 Evidence Index</h1>\n"
        f"<p>Organization: {htmlmod.escape(index.org)}</p>\n"
        f"<p>Period: {htmlmod.escape(index.period)}</p>\n"
        f"<p>Generated: {htmlmod.escape(index.generated_at)}</p>\n"
        "<h2>Method</h2>\n"
        "<p>Deterministic mapping from catalog + front-matter + filename rules. "
        "SuperDocs renders the live table from this register. "
        "This file is a local spec / offline-quality fallback, not an attestation.</p>\n"
        "<h2>Master index</h2>\n"
        f'<table class="soc2-index" data-table="master">{_thead()}<tbody>\n{body_rows}\n</tbody></table>\n'
        "<h2>Gap register</h2>\n"
        f'<table class="soc2-index" data-table="gaps">{_thead()}<tbody>\n{gap_rows}\n</tbody></table>\n'
        "<h2>Unmapped appendix</h2>\n"
        f"{um}\n"
        "<h2>Flagged appendix</h2>\n"
        f"{fl}\n"
        "</body>\n</html>\n"
    )


def markdown(index: IndexDoc) -> str:
    header = "| " + " | ".join(COLUMNS) + " |"
    sep = "| " + " | ".join("---" for _ in COLUMNS) + " |"
    lines = [
        "# SOC2 Evidence Index",
        "",
        f"Organization: {index.org}",
        f"Period: {index.period}",
        f"Generated: {index.generated_at}",
        "",
        header,
        sep,
    ]
    for row in index.rows:
        lines.append("| " + " | ".join(row_cells(row)) + " |")
    return "\n".join(lines) + "\n"


def _enclosing_tr(html_src: str, row_id: str) -> str | None:
    needle = f'data-row-id="{row_id}"'
    i = html_src.find(needle)
    if i < 0:
        return None
    start = html_src.rfind("<tr", 0, i)
    if start < 0:
        return None
    end = html_src.find("</tr>", i)
    if end < 0:
        return None
    return html_src[start : end + len("</tr>")]


def apply_patch(old_html: str, new_index: IndexDoc, diff: IndexDiff) -> str:
    keep: dict[str, str] = {}
    for rid in diff.unchanged_ids:
        tr = _enclosing_tr(old_html, rid)
        if tr is None:
            raise ValueError(f"unchanged row missing from old html: {rid}")
        keep[rid] = tr
    new_by_id = {r.row_id: r for r in new_index.rows}
    generate = set(diff.added) | {c.row_id for c in diff.changed} | {r.to_row_id for r in diff.renamed}
    pieces: list[str] = []
    for row in new_index.rows:
        if row.row_id in keep:
            pieces.append(keep[row.row_id])
        elif row.row_id in generate or row.row_id in new_by_id:
            if row.row_id in generate:
                pieces.append(serialize_tr(row))
            else:
                # should have been unchanged; fall back to serialize only if missing
                tr = keep.get(row.row_id) or serialize_tr(row)
                pieces.append(tr)
        else:
            pieces.append(serialize_tr(row))
    body = "\n".join(pieces)
    m = re.search(r'(<table class="soc2-index" data-table="master">.*?<tbody>)\n?.*?\n?(</tbody></table>)', old_html, re.S)
    if not m:
        raise ValueError("master table tbody not found")
    return old_html[: m.start()] + m.group(1) + "\n" + body + "\n" + m.group(2) + old_html[m.end() :]
