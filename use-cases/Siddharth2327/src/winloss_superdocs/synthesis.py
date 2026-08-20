"""create_quarterly_brief(): a quarter's debriefs -> one Quarterly Competitive Brief.

Orchestrates: pull index stats -> open all matching debrief Files in one
multi-document session -> build customer-redacted context -> reviewed chat draft
(with cross-session search/memory) -> schema check -> number cross-check ->
**redaction gate (blocks export on any leak)** -> export docx + pdf.
See architecture.md §9 for the data-flow diagram this implements.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .client import SuperDocsClient
from .index import DebriefRecord, Index, aggregate_competitor_stats, aggregate_segment_stats
from .redaction import RedactionBlockedExport, build_redacted_context, scan_for_leaks
from .review import ApprovalCallback, auto_approve_all, run_reviewed_chat
from .schema import check_brief_schema
from .templates import CompetitorStat, SegmentStat, build_synthesis_instruction
from .verification import verify_synthesis_numbers

NO_FINDINGS_TEMPLATE = """\
<h1>Quarterly Competitive Brief -- {quarter}</h1>
<h2>Overview &amp; Methodology</h2>
<p>No win/loss debriefs were recorded for {quarter}. This is an honest report of no
findings, not an omission -- see architecture.md for why an empty quarter produces
this explicit statement rather than a fabricated brief.</p>
<h2>Patterns by Competitor</h2>
<p>No data.</p>
<h2>Patterns by Segment</h2>
<p>No data.</p>
<h2>Wording That Worked</h2>
<p>No data.</p>
<h2>Losses Attributable to a Capability Gap</h2>
<p>No data.</p>
"""


@dataclass
class SynthesisResult:
    quarter: str
    debrief_count: int
    exported_docx_path: Path
    exported_pdf_path: Path | None
    competitor_stats: list[CompetitorStat]
    segment_stats: list[SegmentStat]


def _expected_number_rows(
    competitor_stats: list[CompetitorStat], segment_stats: list[SegmentStat]
) -> dict[str, tuple[int, int]]:
    rows = {c.competitor: (c.wins_against, c.losses_to) for c in competitor_stats}
    rows.update({s.segment: (s.wins, s.losses) for s in segment_stats})
    return rows


def preview_synthesis_call(quarter: str, index: Index, small_sample_threshold: int) -> dict:
    """Everything create_quarterly_brief() would do, with zero network calls. Used
    by `--dry-run`."""
    records = index.for_quarter(quarter)
    competitor_stats = aggregate_competitor_stats(records, small_sample_threshold)
    segment_stats = aggregate_segment_stats(records, small_sample_threshold)
    refs = build_redacted_context([asdict(r) for r in records])
    instruction = build_synthesis_instruction(quarter, competitor_stats, segment_stats, refs, small_sample_threshold)
    return {
        "quarter": quarter,
        "debrief_count": len(records),
        "document_ids_to_open": [r.superdocs_document_id for r in records if r.superdocs_document_id],
        "instruction": instruction,
        "export_targets": [f"outputs/briefs/{quarter}.docx", f"outputs/briefs/{quarter}.pdf"],
    }


def create_quarterly_brief(
    client: SuperDocsClient,
    index: Index,
    *,
    quarter: str,
    output_dir: Path,
    small_sample_threshold: int,
    approval_callback: ApprovalCallback = auto_approve_all,
) -> SynthesisResult:
    records: list[DebriefRecord] = index.for_quarter(quarter)
    output_dir.mkdir(parents=True, exist_ok=True)
    docx_path = output_dir / f"{quarter}.docx"

    if not records:
        html = NO_FINDINGS_TEMPLATE.format(quarter=quarter)
        docx_bytes = client.export(html=html, format="docx", options={"filename": f"brief-{quarter}"})
        docx_path.write_bytes(docx_bytes)
        return SynthesisResult(quarter, 0, docx_path, None, [], [])

    competitor_stats = aggregate_competitor_stats(records, small_sample_threshold)
    segment_stats = aggregate_segment_stats(records, small_sample_threshold)
    debrief_refs = build_redacted_context([asdict(r) for r in records])

    instruction = build_synthesis_instruction(
        quarter, competitor_stats, segment_stats, debrief_refs, small_sample_threshold
    )

    document_ids = [r.superdocs_document_id for r in records if r.superdocs_document_id]
    session = client.sessions_init(session_id=f"brief-{quarter}", document_ids=document_ids or None)
    session_id = session.get("session_id", f"brief-{quarter}")

    job = run_reviewed_chat(
        client,
        session_id,
        instruction,
        approval_callback,
        cross_session_search=True,
        cross_session_memory=True,
    )

    result = job.get("result", {})
    html = result.get("document_changes", {}).get("updated_html") or result.get("response", "")
    if not html:
        raise RuntimeError(f"No document HTML returned for quarterly brief {quarter}; job result: {result}")

    check_brief_schema(html).raise_if_failed(f"Quarterly Brief {quarter}")

    expected_rows = _expected_number_rows(competitor_stats, segment_stats)
    number_check = verify_synthesis_numbers(html, expected_rows)
    if not number_check.ok:
        raise RuntimeError(
            f"Quarterly Brief {quarter} number mismatch vs. index ground truth: "
            f"{number_check.mismatches}"
        )

    banned_terms = index.all_customer_terms()
    leak_scan = scan_for_leaks(html, banned_terms)
    leak_scan.raise_if_leaked(f"Quarterly Brief {quarter}")  # raises RedactionBlockedExport, halts before export

    docx_bytes = client.export(html=html, format="docx", options={"filename": f"brief-{quarter}"})
    docx_path.write_bytes(docx_bytes)

    pdf_bytes = client.export(html=html, format="pdf", options={"filename": f"brief-{quarter}"})
    pdf_path = output_dir / f"{quarter}.pdf"
    pdf_path.write_bytes(pdf_bytes)

    return SynthesisResult(
        quarter=quarter,
        debrief_count=len(records),
        exported_docx_path=docx_path,
        exported_pdf_path=pdf_path,
        competitor_stats=competitor_stats,
        segment_stats=segment_stats,
    )
