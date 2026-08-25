"""
@file: backend/agents/nodes/draft.py
@description: Builds the digest content. Produces one instruction per document section
    rather than one full-document rewrite, because SuperDocs applies targeted edits and
    because per-section granularity is what lets the approval gate accept some sections
    and reject others. Content is assembled from database facts, not from model memory.
@flow: run() -> load themes with quotes, evidence and QoQ data -> render each section
    (summary, theme table, deep dives, fastest-growing, what-changed, methodology) as a
    SuperDocs instruction string -> store on state.draft_sections -> the superdocs node
    sends them one at a time.
@dependencies:
    - backend.models.Theme: the source of every factual claim in the draft
    - backend.services.groq_client.GroqClient: prose for the executive summary only
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy import select

from backend.agents.nodes.base import BaseNode, NodeInputMissing
from backend.agents.state import DigestState
from backend.db.database import session_scope
from backend.models import RunStatus, Theme, TrendDirection
from backend.services.charts import (
    build_comparison_chart,
    build_growth_chart,
    build_volume_chart,
    chart_block,
    render_comparison_text,
)

logger = logging.getLogger(__name__)

# Growth above this rate qualifies a theme for the "fastest growing" section.
FAST_GROWTH_THRESHOLD = 0.25

_SUMMARY_SYSTEM = """\
You write the two-to-three sentence executive summary of a Voice-of-Customer digest.

You are given the quarter's themes with their volumes and quarter-over-quarter changes.
Write only what those numbers support. Do not speculate about causes, do not recommend
actions, and do not mention any theme that is not in the data you were given. If the
data shows no clear trend, say that plainly.

Return plain prose only. No headings, no bullet points, no preamble.
"""


def _trend_label(theme: Theme) -> str:
    """Human-readable trend, honest about missing comparison data."""
    if theme.volume_trend == TrendDirection.NEW:
        return "New this quarter"
    if theme.volume_trend == TrendDirection.UNKNOWN:
        return "No comparison available"
    if theme.growth_rate is None:
        return f"Present last quarter ({theme.prior_theme_name or 'unnamed'}), change unknown"
    pct = round(theme.growth_rate * 100)
    sign = "+" if pct > 0 else ""
    return f"{theme.volume_trend.value.title()} ({sign}{pct}%)"


class DraftNode(BaseNode):
    stage = "draft"
    running_status = RunStatus.DRAFTING
    requires = ("theme",)

    async def run(self, state: DigestState, run_id: uuid.UUID) -> DigestState:
        async with session_scope() as session:
            themes = list(
                (
                    await session.execute(
                        select(Theme)
                        .where(Theme.run_id == run_id)
                        .order_by(Theme.volume_count.desc())
                    )
                ).scalars()
            )

        if not themes:
            raise NodeInputMissing(
                "No themes to draft. A digest with no themes has no content, so the "
                "run stops here rather than assembling an empty document.",
                upstream_stage="theme",
            )

        quarter = state.get("quarter_label", "This quarter")
        prior = state.get("prior_quarter_label", "last quarter")
        comparison_available = bool(state.get("comparison_available"))
        total_conversations = state.get("conversations_relevant", 0)
        warnings: list[str] = []

        # --- executive summary (the only generated prose) ---
        facts_block = "\n".join(
            f"- {t.name}: {t.volume_count} conversations, {_trend_label(t)}"
            for t in themes[:10]
        )
        from backend.services.groq_client import GroqClient
        from backend.services.heuristics import heuristic_summary
        from backend.services.llm_gate import run_with_fallback

        theme_rows_for_summary = [
            {
                "name": t.name,
                "volume_count": t.volume_count,
                "volume_share": t.volume_share,
                "growth_rate": t.growth_rate,
            }
            for t in themes
        ]

        async def _llm_summary():
            groq = GroqClient()
            try:
                result = await groq.complete(
                    _SUMMARY_SYSTEM,
                    f"Quarter: {quarter}. Total conversations analysed: "
                    f"{total_conversations}. "
                    f"{'QoQ comparison is available.' if comparison_available else 'No prior-quarter comparison is available.'}\n\n"
                    f"Themes:\n{facts_block}",
                    max_tokens=512,
                )
                return result.content.strip(), result.usage
            finally:
                await groq.aclose()

        gated_summary = await run_with_fallback(
            "draft",
            _llm_summary,
            lambda: heuristic_summary(
                theme_rows_for_summary, total_conversations, quarter, comparison_available
            ),
        )
        summary_text = str(gated_summary.data)
        self.usage.merge(gated_summary.usage)

        degraded_stages = list(state.get("degraded_stages") or [])
        degraded_caveats = list(state.get("degraded_caveats") or [])
        if gated_summary.degraded:
            warnings.append(
                "Executive summary was assembled from counts rather than written"
            )
            degraded_stages = sorted(set(degraded_stages) | {"draft"})
            degraded_caveats = list(dict.fromkeys(degraded_caveats + gated_summary.caveats))
            state["degraded_stages"] = degraded_stages
            state["degraded_caveats"] = degraded_caveats

        sections: dict[str, str] = {}

        sections["header"] = (
            f"Set the document title to '{quarter} Voice-of-Customer Digest' and add a "
            f"subtitle line reading 'Generated {date.today().isoformat()} from "
            f"{total_conversations} support conversations'."
        )

        sections["executive_summary"] = (
            "Replace the Executive Summary section body with exactly this text, "
            f"unchanged:\n\n{summary_text}"
        )

        # --- theme table ---
        table_rows = "\n".join(
            f"| {t.name} | {t.volume_count} | {round(t.volume_share * 100, 1)}% | "
            f"{_trend_label(t)} |"
            for t in themes
        )
        sections["theme_table"] = (
            "In the 'Top Themes This Quarter' section, insert a table with the columns "
            "Theme, Volume, Share, Change. Use exactly these rows and do not add, "
            f"reorder, or invent any:\n\n"
            f"| Theme | Volume | Share | Change |\n{table_rows}"
        )

        # --- charts ---
        # Themes are serialised to plain dicts so the chart builders never touch the ORM
        # and stay trivially unit-testable.
        theme_dicts = [
            {
                "name": t.name,
                "volume_count": t.volume_count,
                "volume_share": t.volume_share,
                "prior_quarter_count": t.prior_quarter_count,
                "growth_rate": t.growth_rate,
            }
            for t in themes
        ]

        volume_chart = build_volume_chart(theme_dicts)
        sections["chart_volume"] = (
            "In the 'Top Themes This Quarter' section, immediately after the table, "
            "insert this chart markup exactly as given. Do not redraw it, restyle it, "
            "or convert it to a different chart type:\n\n"
            f"{chart_block(volume_chart)}"
        )

        if comparison_available:
            comparison_chart = build_comparison_chart(theme_dicts, prior)
            if comparison_chart.series:
                sections["chart_comparison"] = (
                    f"In the 'What Changed Since {prior}' section, insert this chart "
                    f"markup exactly as given:\n\n"
                    f"{chart_block(comparison_chart)}\n\n"
                    f"<pre>{render_comparison_text(comparison_chart)}</pre>"
                )

            growth_chart = build_growth_chart(theme_dicts, FAST_GROWTH_THRESHOLD)
            if growth_chart.series:
                sections["chart_growth"] = (
                    "In the 'Fastest Growing Issues' section, insert this chart markup "
                    "exactly as given:\n\n"
                    f"{chart_block(growth_chart)}"
                )
            else:
                # No chart rather than an empty one: a chart with no bars implies the
                # data was measured and came back flat, which is a different claim.
                warnings.append(
                    "No theme exceeded the growth threshold, so no growth chart was drawn"
                )
        else:
            warnings.append(
                "No prior-quarter data, so comparison and growth charts were omitted "
                "rather than drawn against zero"
            )

        # --- per-theme deep dives ---
        for idx, theme in enumerate(themes, start=1):
            quotes = theme.representative_quotes or []
            quote_block = "\n".join(
                f'  - "{q["anonymized"]}"'
                + (f" — {q['date']}" if q.get("date") else "")
                + (" [contains an unresolved possible name — review before publication]"
                   if q.get("needs_review") else "")
                for q in quotes
            ) or "  - (no quote met the length threshold for this theme)"

            citations = ", ".join(
                f"[{i}] {ref['citation']}"
                for i, ref in enumerate(theme.evidence_refs[:8], start=1)
            )
            caveat = f"\n\nConfidence note: {theme.confidence_note}" if theme.confidence_note else ""

            sections[f"theme_{idx}"] = (
                f"Add a subsection under 'Theme Deep Dives' titled "
                f"'{theme.name} — {theme.volume_count} conversations "
                f"({_trend_label(theme)})'. Its body must contain, in order:\n\n"
                f"{theme.description}\n\n"
                f"What customers said:\n{quote_block}\n\n"
                f"Evidence: {len(theme.evidence_refs)} conversations. "
                f"Citations: {citations}{caveat}\n\n"
                f"Do not add commentary, causes, or recommendations beyond this text."
            )

        # --- fastest growing ---
        growing = [
            t
            for t in themes
            if t.growth_rate is not None and t.growth_rate >= FAST_GROWTH_THRESHOLD
        ]
        growing.sort(key=lambda t: t.growth_rate or 0, reverse=True)

        if not comparison_available:
            growth_body = (
                f"No {prior} digest was available for comparison, so growth rates "
                f"cannot be calculated. This section is intentionally empty rather than "
                f"populated with estimates."
            )
        elif not growing:
            growth_body = (
                f"No theme grew more than {round(FAST_GROWTH_THRESHOLD * 100)}% versus "
                f"{prior}."
            )
        else:
            growth_body = "\n".join(
                f"- {t.name}: {t.prior_quarter_count} → {t.volume_count} conversations "
                f"({'+' if (t.growth_rate or 0) > 0 else ''}"
                f"{round((t.growth_rate or 0) * 100)}%)"
                for t in growing
            )
        sections["fastest_growing"] = (
            f"Replace the 'Fastest Growing Issues' section body with exactly:\n\n{growth_body}"
        )

        # --- what changed ---
        if not comparison_available:
            changed_body = state.get("comparison_note") or (
                f"No {prior} digest was supplied, so no comparison is available."
            )
        else:
            lines = []
            for t in themes:
                if t.volume_trend == TrendDirection.NEW:
                    lines.append(f"- NEW: {t.name} ({t.volume_count} conversations)")
                elif t.prior_quarter_count is not None and t.growth_rate is not None:
                    lines.append(
                        f"- {t.volume_trend.value}: {t.name} "
                        f"{t.prior_quarter_count} → {t.volume_count} "
                        f"({'+' if t.growth_rate > 0 else ''}{round(t.growth_rate * 100)}%)"
                    )
            for gone in state.get("disappeared_themes") or []:
                lines.append(
                    f"- NO LONGER PRESENT: {gone['name']} "
                    f"(was {gone.get('prior_volume') or 'unstated'} last quarter)"
                )
            changed_body = "\n".join(lines) or "No material changes detected."
        sections["what_changed"] = (
            f"Replace the 'What Changed Since {prior}' section body with exactly:\n\n"
            f"{changed_body}"
        )

        # --- methodology (this is where honesty is made explicit to the reader) ---
        skipped = state.get("conversations_skipped", 0)
        needing_review = state.get("quotes_needing_review", 0)
        injections = state.get("injection_attempts", 0)
        method_lines = [
            f"Themes were derived by clustering {total_conversations} support "
            f"conversations on semantic similarity, then labelled from their member "
            f"issue phrases. Volumes are conversation counts, not ticket counts.",
            f"{skipped} ingested record(s) were excluded as non-support content "
            f"(marketing, automated notifications, or unusable text).",
            "Quotes were anonymized in two passes: deterministic pattern matching for "
            "emails, phone numbers, URLs and identifiers, then a language-model pass for "
            "names and company names. Spans the model could not classify confidently are "
            "marked [POSSIBLE-NAME] rather than removed silently or passed through "
            "silently. Anonymization is reviewed by a human before publication and is not "
            "claimed to be exhaustive.",
        ]
        if needing_review:
            method_lines.append(
                f"{needing_review} quote(s) contained at least one span the anonymizer "
                f"could not resolve and were flagged for reviewer decision."
            )
        if injections:
            method_lines.append(
                f"{injections} conversation(s) contained text attempting to issue "
                f"instructions to an automated system. That text was treated as data, "
                f"recorded, and not executed."
            )
        if degraded_stages:
            # Disclosure, not a footnote. A reader must be able to tell that parts of
            # this document were produced by keyword methods rather than by a model.
            method_lines.append(
                "IMPORTANT: the following stages ran WITHOUT a language model and used "
                "keyword heuristics instead: "
                + ", ".join(degraded_stages)
                + ". This materially reduces quality. Specifically: "
                + " ".join(degraded_caveats)
            )

        if comparison_available:
            method_lines.append(
                f"Quarter-over-quarter comparison matched this quarter's themes to "
                f"{prior}'s by embedding similarity, so a renamed theme is still "
                f"recognised as the same issue. Matches below the similarity threshold "
                f"are reported as new rather than forced onto a prior theme."
            )
        else:
            method_lines.append(
                f"No {prior} digest was available, so no quarter-over-quarter figures "
                f"appear anywhere in this document."
            )
        sections["methodology"] = (
            "Replace the 'Methodology' section body with exactly:\n\n"
            + "\n\n".join(method_lines)
        )

        await self.log_decision(
            run_id,
            "DRAFTED",
            f"Prepared {len(sections)} targeted section edits for {len(themes)} themes",
            {"sections": list(sections.keys()), "themes": len(themes)},
        )

        state["draft_sections"] = sections
        state["draft_warnings"] = warnings
        return state
