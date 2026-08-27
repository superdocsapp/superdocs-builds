"""The run: range in, reviewed report out.

Stages are explicit and timed, because "what did it decide, and what did that
cost" should be answerable without reading a log. The human gate sits between
:meth:`NarrativeReportPipeline.propose` and :meth:`commit`, nothing reaches the
document until a person has accepted it section by section.

Cost discipline is the other theme. A first run spends one operation. A re-run
where only figures moved spends **none**: the substitution happens locally and
lands through the non-AI save endpoint. The model is called when, and only when,
words need rewriting.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .chart import chart_digest, chart_html, render_chart
from .facts import Table, derive_facts, read_table
from .incremental import UpdatePlan, apply_plan, plan_update, verify_untouched
from .models import FactSet, ReportManifest, Section
from .narrative import (
    REPORT_OUTLINE,
    SectionSpec,
    build_correction,
    build_prompt,
    build_skeleton,
    fallback_plan,
    plan_from_document,
    scan_for_injection,
)
from .numbers import find_unverified_numerals, referenced_keys, substitute
from .store import ReportStore
from .superdocs import SuperDocsClient, SuperDocsError
from .template import assemble_document

log = logging.getLogger(__name__)

Action = Literal["create", "keep", "resubstitute", "regenerate"]


@dataclass(slots=True)
class ProposedSection:
    """One section awaiting a human decision.

    Carries both the rendered HTML the reviewer sees and the token-level
    ``template`` behind it. Persisting both is what lets :meth:`commit` run
    purely from stored state, a process killed during review resumes from disk
    instead of needing the proposal recomputed.
    """

    id: str
    heading: str
    action: Action
    reason: str
    html: str
    previous_html: str | None
    template: str = ""
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_change(self) -> bool:
        return self.action != "keep"


@dataclass(slots=True)
class RunReport:
    """Everything the reviewer and the operator need to see about one run."""

    report_id: str
    session_id: str
    revision: int
    status: Literal["awaiting_review", "committed", "failed"]
    sections: list[ProposedSection]
    findings: list[str] = field(default_factory=list)
    plan_summary: str = ""
    operations_spent: int = 0
    narrative_source: str = "model"
    chart_url: str | None = None
    stage_seconds: dict[str, float] = field(default_factory=dict)
    export_warnings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def changes(self) -> list[ProposedSection]:
        return [s for s in self.sections if s.is_change]

    @property
    def blocking_problems(self) -> list[str]:
        return [f"{s.id}: {p}" for s in self.sections for p in s.problems]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blocking_problems"] = self.blocking_problems
        return payload


class NarrativeReportPipeline:
    """Builds and updates one report."""

    def __init__(
        self,
        client: SuperDocsClient,
        store: ReportStore,
        *,
        outline: list[SectionSpec] | None = None,
        model_tier: str | None = None,
    ) -> None:
        self.client = client
        self.store = store
        self.outline = outline or REPORT_OUTLINE
        self.model_tier = model_tier

    # ------------------------------------------------------------- stage timing

    @contextmanager
    def _stage(self, report: RunReport, name: str) -> Iterator[None]:
        started = time.perf_counter()
        log.info("stage %s started", name)
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            report.stage_seconds[name] = round(elapsed, 3)
            log.info("stage %s finished in %.2fs", name, elapsed)

    # ------------------------------------------------------------------ propose

    async def propose(
        self,
        *,
        report_id: str | None,
        values: list[list[str]],
        sheet: str,
        a1: str,
        title: str | None = None,
    ) -> RunReport:
        """Compute what the report should say, and stop for review.

        Nothing is written to the document here. The return value is a proposal:
        a per-section diff, the findings, and what committing it would cost.
        """
        report_id = report_id or f"rpt-{uuid.uuid4().hex[:12]}"
        manifest = self.store.load_manifest(report_id)
        session_id = manifest.session_id if manifest else f"narrative-{report_id}"

        report = RunReport(
            report_id=report_id,
            session_id=session_id,
            revision=(manifest.revision + 1) if manifest else 1,
            status="awaiting_review",
            sections=[],
        )

        with self._stage(report, "parse"):
            table = read_table(values, sheet=sheet, a1=a1)
            report.findings.extend(scan_for_injection(table))
            if table.total_label:
                report.findings.append(
                    f"Treated the “{table.total_label}” column as a total, not a period, so "
                    "period-over-period figures compare the last two real periods."
                )
            # A stated total that disagrees with its own periods is reported,
            # never reconciled silently.
            report.findings.extend(table.total_conflicts)

        with self._stage(report, "facts"):
            facts = derive_facts(table)

        with self._stage(report, "chart"):
            await self._attach_chart(report, table, manifest, title)

        if manifest is None:
            await self._propose_create(report, table, facts, title)
        else:
            await self._propose_update(report, table, facts, manifest)

        self.store.save_run(
            report_id,
            {
                "stage": "awaiting_review",
                "revision": report.revision,
                "session_id": session_id,
                "sheet": sheet,
                "a1": a1,
                "title": title,
                "chart_url": report.chart_url,
                "chart_digest": chart_digest(table),
                "fact_digests": facts.digests(),
                "narrative_source": report.narrative_source,
                "sections": [asdict(s) for s in report.sections],
                "findings": report.findings,
                "operations_spent": report.operations_spent,
            },
        )
        return report

    async def _attach_chart(
        self,
        report: RunReport,
        table: Table,
        manifest: ReportManifest | None,
        title: str | None,
    ) -> None:
        """Render and upload the chart, reusing the old one when nothing moved."""
        digest = chart_digest(table)
        if manifest and manifest.chart_digest == digest and manifest.chart_url:
            report.chart_url = manifest.chart_url
            return
        try:
            png = render_chart(table, title=title or f"{table.sheet}, {table.a1}")
            report.chart_url = await self.client.upload_image(png, filename=f"{report.report_id}.png")
        except (ValueError, SuperDocsError) as exc:
            # A missing chart is a degraded report, not a failed one.
            report.findings.append(f"Chart could not be produced and was omitted: {exc}")
            report.chart_url = manifest.chart_url if manifest else None

    async def _propose_create(
        self, report: RunReport, table: Table, facts: FactSet, title: str | None
    ) -> None:
        """First run: author every section."""
        with self._stage(report, "narrative"):
            plan, problems, warnings = await self._author(report, table, facts)

        with self._stage(report, "verify"):
            for section in plan.sections:
                rendered = substitute(section.template, facts)
                issues = problems.get(section.id, [])
                issues += [str(v) for v in find_unverified_numerals(rendered)]
                report.sections.append(
                    ProposedSection(
                        id=section.id,
                        heading=section.heading,
                        action="create",
                        reason="new report",
                        html=rendered.text,
                        previous_html=None,
                        template=section.template,
                        problems=sorted(set(issues)),
                        warnings=sorted(set(warnings.get(section.id, []))),
                    )
                )
        report.plan_summary = f"new report with {len(report.sections)} sections"

    async def _propose_update(
        self, report: RunReport, table: Table, facts: FactSet, manifest: ReportManifest
    ) -> None:
        """Re-run: touch only what the data moved."""
        with self._stage(report, "plan"):
            plan = plan_update(manifest, facts, chart_digest=chart_digest(table))
            report.plan_summary = plan.summary()

        regenerated: dict[str, str] = {}
        problems: dict[str, list[str]] = {}
        warnings: dict[str, list[str]] = {}
        if plan.regenerating:
            with self._stage(report, "narrative"):
                regenerated, problems, warnings = await self._rewrite(report, table, facts, plan)

        with self._stage(report, "verify"):
            rendered = apply_plan(plan, facts, regenerated=regenerated)
            verify_untouched(plan, rendered)  # proves the promise, every run
            for entry in plan.sections:
                sid = entry.section.id
                template = regenerated.get(sid, entry.section.template)
                issues = problems.get(sid, [])
                issues += [str(v) for v in find_unverified_numerals(substitute(template, facts))]
                report.sections.append(
                    ProposedSection(
                        id=sid,
                        heading=entry.section.heading,
                        action=entry.action,
                        reason=entry.reason,
                        html=rendered[sid],
                        previous_html=entry.section.rendered,
                        template=template,
                        problems=sorted(set(issues)),
                        warnings=sorted(set(warnings.get(sid, []))),
                    )
                )

    # ------------------------------------------------------------------ model

    async def _run_turn(
        self, report: RunReport, message: str, skeleton: str, max_pauses: int = 4
    ) -> str:
        """Run one chat turn to completion and return the document HTML.

        A turn can pause for two unrelated reasons and they take different
        endpoints. Authoring a whole report is a large edit, so in practice it
        pauses on the continue prompt rather than finishing in one go, the
        first live run of this build mistook that for a failure and fell back
        to deterministic prose every time.

        Whatever happens, a paused job is never left behind: an abandoned pause
        makes the session reject every later instruction with ``session_busy``.
        """
        job_id = await self.client.start_chat(
            message,
            report.session_id,
            document_html=skeleton,
            approval_mode="approve_all",
            model_tier=self.model_tier,
        )
        report.operations_spent += 1

        try:
            for _ in range(max_pauses):
                state = await self.client.wait_for_job(job_id)

                if state.status == "completed":
                    updated = ((state.result or {}).get("document_changes") or {}).get(
                        "updated_html"
                    )
                    if not updated:
                        raise SuperDocsError("chat turn returned no document HTML")
                    return updated

                if state.status != "awaiting_approval":
                    raise SuperDocsError(f"chat turn ended as {state.status}")

                if state.awaiting_kind == "continue_prompt":
                    # A large edit kept its work and is asking for more budget.
                    await self.client.continue_chat(report.session_id, job_id, keep_going=True)
                    continue

                # A change review we did not ask for: accept everything, since
                # the human gate for this build is our own review step and the
                # numeric check runs over the result either way.
                if not state.pending_changes:
                    raise SuperDocsError("job awaiting approval with no pending changes")
                await self.client.approve(
                    report.session_id,
                    job_id,
                    {change.change_id: True for change in state.pending_changes},
                )

            raise SuperDocsError(f"chat turn still paused after {max_pauses} rounds")
        except BaseException:
            await self.client.cancel_job(job_id)
            raise

    async def _author(self, report: RunReport, table: Table, facts: FactSet):
        """Ask SuperDocs to write the narrative, falling back if it cannot."""
        skeleton = build_skeleton(
            table, self.outline, chart_html(report.chart_url, f"{table.sheet} {table.a1}")
            if report.chart_url
            else "",
        )
        try:
            return await self._draft(report, facts, self.outline, skeleton, table)
        except SuperDocsError as exc:
            report.narrative_source = "fallback"
            report.findings.append(f"Narrative fell back to deterministic prose: {exc}")
            return fallback_plan(facts, self.outline, reason=str(exc)), {}, {}

    async def _draft(
        self,
        report: RunReport,
        facts: FactSet,
        specs: list[SectionSpec],
        skeleton: str,
        table: Table,
    ):
        """Draft the prose, and hand a failed draft back with the reason.

        The checker knows exactly which numbers the model invented, so a failed
        draft is not thrown away: the violations are quoted back and the same
        sections are asked for again. Only if the second attempt also fails do
        we fall back to deterministic prose.

        This is the retry that changes the path. It costs one extra operation
        and only happens when the first draft was provably unusable.
        """
        updated = await self._run_turn(report, build_prompt(facts, specs, table), skeleton)
        plan, problems, warnings = plan_from_document(updated, facts, specs)

        if not problems:
            return plan, problems, warnings

        report.findings.append(
            f"First draft contained {sum(len(v) for v in problems.values())} unsupported "
            f"figure(s) in {len(problems)} section(s). Asked the model to correct them."
        )
        try:
            corrected = await self._run_turn(
                report, build_correction(problems, specs), updated
            )
        except SuperDocsError as exc:
            report.findings.append(f"Correction pass failed: {exc}")
            return plan, problems, warnings

        retry_plan, retry_problems, retry_warnings = plan_from_document(corrected, facts, specs)
        if len(retry_problems) < len(problems):
            return retry_plan, retry_problems, retry_warnings

        # The model did not improve. Deterministic prose is plainer and correct.
        report.narrative_source = "fallback"
        report.findings.append(
            "The model could not produce prose without inventing figures, so this "
            "report was written deterministically from the fact table instead."
        )
        return fallback_plan(facts, specs, reason="model kept inventing figures"), {}, {}

    async def _rewrite(
        self, report: RunReport, table: Table, facts: FactSet, plan: UpdatePlan
    ) -> tuple[dict[str, str], dict[str, list[str]], dict[str, list[str]]]:
        """Rewrite only the sections whose wording is now wrong."""
        specs = [s for s in self.outline if s.id in {p.section.id for p in plan.regenerating}]
        skeleton = build_skeleton(table, specs)
        try:
            new_plan, problems, warnings = await self._draft(
                report, facts, specs, skeleton, table
            )
            return {s.id: s.template for s in new_plan.sections}, problems, warnings
        except SuperDocsError as exc:
            report.narrative_source = "fallback"
            report.findings.append(f"Rewrite fell back to deterministic prose: {exc}")
            fallback = fallback_plan(facts, specs, reason=str(exc))
            return {s.id: s.template for s in fallback.sections}, {}, {}

    # ------------------------------------------------------------------ commit

    async def commit(
        self,
        report_id: str,
        decisions: dict[str, bool],
        *,
        export_format: str = "docx",
    ) -> tuple[RunReport, bytes | None]:
        """Apply the sections a human accepted, and export the result.

        Rejecting one section keeps the rest: each decision is applied on its
        own, and a rejected section retains exactly the text it had before.
        """
        pending = self.store.load_run(report_id)
        if not pending:
            raise SuperDocsError(
                f"no run awaiting review for {report_id}",
                fix="call propose() first, or re-run if the process restarted mid-review",
            )

        manifest = self.store.load_manifest(report_id)
        sections_state = {s["id"]: s for s in pending["sections"]}
        accepted = {sid: ok for sid, ok in decisions.items() if sid in sections_state}

        report = RunReport(
            report_id=report_id,
            session_id=pending["session_id"],
            revision=pending["revision"],
            status="committed",
            sections=[ProposedSection(**s) for s in pending["sections"]],
            findings=list(pending.get("findings", [])),
            operations_spent=int(pending.get("operations_spent", 0)),
            narrative_source=pending.get("narrative_source", "model"),
            chart_url=pending.get("chart_url"),
        )

        priors = {s.id: s for s in (manifest.sections if manifest else [])}
        final_sections: list[Section] = []
        rejected: list[str] = []

        for proposed in report.sections:
            prior = priors.get(proposed.id)
            was_rejected = accepted.get(proposed.id) is False

            if was_rejected and prior is None:
                # A brand-new section the reviewer turned down simply does not appear.
                rejected.append(proposed.id)
                continue

            if was_rejected:
                # Revert this one section to exactly what it said before, leaving
                # every other decision in this review untouched.
                rejected.append(proposed.id)
                template, html = prior.template, prior.rendered
            else:
                template, html = proposed.template, proposed.html

            section = Section(
                id=proposed.id,
                heading=proposed.heading,
                template=template,
                fact_keys=referenced_keys(template),
                chunk_id=prior.chunk_id if prior else None,
            )
            section.rendered = html
            final_sections.append(section)

        if rejected:
            report.findings.append(
                "Reviewer rejected " + ", ".join(sorted(rejected)) + "; those sections were left "
                "at their previous text and the rest were applied."
            )

        document_html = assemble_document(
            title=pending.get("title") or f"{pending['sheet']} narrative report",
            source_range=f"{pending['sheet']}!{pending['a1']}",
            sections=final_sections,
            chart_url=report.chart_url,
        )

        exported: bytes | None = None
        try:
            exported, warnings = await self.client.export(
                html=document_html,
                fmt=export_format,  # type: ignore[arg-type]
                filename=report_id,
            )
            report.export_warnings = warnings
        except SuperDocsError as exc:
            report.findings.append(f"Export failed; the document HTML is still available: {exc}")

        updated = ReportManifest(
            report_id=report_id,
            session_id=pending["session_id"],
            source_range=f"{pending['sheet']}!{pending['a1']}",
            sections=final_sections,
            fact_digests=self._digests_after_rejections(
                pending["fact_digests"], manifest, report.sections, rejected
            ),
            revision=pending["revision"],
            chart_url=report.chart_url,
            chart_digest=pending.get("chart_digest"),
            template_id=manifest.template_id if manifest else None,
        )
        self.store.save_manifest(updated)
        self.store.clear_run(report_id)
        return report, exported

    @staticmethod
    def _digests_after_rejections(
        fresh: dict[str, str],
        manifest: ReportManifest | None,
        proposed: list[ProposedSection],
        rejected: list[str],
    ) -> dict[str, str]:
        """Record the new fact state, except for facts a rejection left stale.

        A rejected section keeps its old text, so the data behind it is still
        unreported. Storing the fresh digest would mark it current and the
        section would never be offered again, silently stale forever.

        Where a fact feeds both a rejected and an accepted section, we hold the
        old digest anyway. That costs one redundant proposal next run; the other
        direction costs a report that quietly stops being true.
        """
        if not rejected or manifest is None:
            return dict(fresh)

        digests = dict(fresh)
        stale_keys = {
            key
            for section in proposed
            if section.id in rejected
            for key in referenced_keys(section.template)
        }
        for key in stale_keys:
            if key in manifest.fact_digests:
                digests[key] = manifest.fact_digests[key]
            else:
                digests.pop(key, None)
        return digests
