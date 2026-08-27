from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from series_bible.application.bible import BibleService
from series_bible.application.analysis_graph import AnalysisState, build_analysis_graph
from series_bible.application.extraction import GroundedRuleExtractor
from series_bible.application.llm import LLMProvider, OpenAICompatibleProvider
from series_bible.application.retrieval import FactRetriever
from series_bible.config import Settings, get_settings
from series_bible.domain.continuity import ContinuityService
from series_bible.domain.schemas import ExtractedFact, FactKind, FindingType, SourceRef
from series_bible.infrastructure.database import (
    AuditEvent,
    BibleFact,
    Chapter,
    ContinuityFinding,
    Document,
    DocumentChunk,
    Evidence,
    WorkflowEvent,
    WorkflowRun,
)


class WorkflowRunner:
    """Executes durable, idempotent ingest-to-review workflow stages."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.extractor = GroundedRuleExtractor()
        self.continuity = ContinuityService()
        self.llm = self._llm_provider()

    async def execute(self, run_id: UUID) -> WorkflowRun:
        run = await self.session.get(WorkflowRun, run_id, with_for_update=True)
        if run is None:
            raise ValueError("workflow run not found")
        run.status = "RUNNING"
        self.run = run
        graph = build_analysis_graph({
            "INGEST": self._ingest_node,
            "EXTRACT_FACTS": self._extract_node,
            "VALIDATE_FACTS": self._validate_node,
            "BUILD_OR_UPDATE_BIBLE": self._bible_node,
            "RETRIEVE_RELEVANT_FACTS": self._retrieve_node,
            "CHECK_CONTINUITY": self._continuity_node,
            "CLASSIFY_FINDINGS": self._classify_node,
            "PERSIST_FINDINGS": self._persist_node,
        })
        try:
            await graph.ainvoke({"run_id": str(run.id), "series_id": str(run.series_id)})
        except Exception as error:  # noqa: BLE001 - convert any stage failure into a visible, resumable run state
            return await self._fail(run_id, run.current_stage, error)
        findings = list((await self.session.scalars(select(ContinuityFinding).where(ContinuityFinding.run_id == run.id, ContinuityFinding.status == "OPEN"))).all())
        run.status = "AWAITING_REVIEW" if findings else "COMPLETED"
        run.current_stage = "HUMAN_REVIEW" if findings else "UPDATE_BIBLE"
        run.state = {**run.state, "finding_ids": [str(item.id) for item in findings]}
        await self.session.commit()
        return run

    async def _fail(self, run_id: UUID, failed_stage: str, error: Exception) -> WorkflowRun:
        """Discard the failed attempt's uncommitted writes and record a visible, resumable failure.

        Without this, an unexpected error (e.g. an invalid LLM key) would crash the request after
        the uploaded document was already committed, leaving no facts/findings and no explanation.
        """
        message = str(error)[:2000] or type(error).__name__
        await self.session.rollback()
        run = await self.session.get(WorkflowRun, run_id, with_for_update=True)
        run.status = "FAILED"
        run.current_stage = failed_stage
        run.errors = [*run.errors, {"stage": failed_stage, "message": message}]
        self.session.add(WorkflowEvent(run_id=run.id, stage=failed_stage, status="FAILED", payload={"error": message}))
        self.session.add(AuditEvent(run_id=run.id, actor="workflow", entity="workflow_run", entity_id=str(run.id), operation="WORKFLOW_RUN_FAILED", metadata_json={"stage": failed_stage, "error": message[:500]}))
        await self.session.commit()
        return run

    async def _ingest_node(self, state: AnalysisState) -> dict[str, object]:
        run = self.run
        document_ids = [UUID(value) for value in run.state.get("document_ids", [])]
        query = select(Document).where(Document.series_id == run.series_id)
        if document_ids:
            query = query.where(Document.id.in_(document_ids))
        else:
            query = query.where(Document.status == "IMPORTED")
        documents = list((await self.session.scalars(query.order_by(Document.created_at))).all())
        await self._checkpoint(run, "INGEST", {"documents": len(documents)})
        return {"documents": documents}

    async def _extract_node(self, state: AnalysisState) -> dict[str, object]:
        facts: list[ExtractedFact] = []
        for document in state.get("documents", []):
            chunks = list((await self.session.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id))).all())
            chapters = list((await self.session.scalars(select(Chapter).where(Chapter.document_id == document.id))).all())
            chapter_names = {chapter.id: chapter.title for chapter in chapters}
            facts.extend(await self._extract(chunks, chapter_names))
            document.status = "PROCESSED"
        await self._checkpoint(self.run, "EXTRACT_FACTS", {"facts": len(facts)})
        return {"facts": facts}

    async def _validate_node(self, state: AnalysisState) -> dict[str, object]:
        facts = [fact for fact in state.get("facts", []) if fact.supported and fact.source.evidence_text]
        await self._checkpoint(self.run, "VALIDATE_FACTS", {"supported": len(facts)})
        return {"facts": facts}

    async def _bible_node(self, state: AnalysisState) -> dict[str, object]:
        await self._checkpoint(self.run, "BUILD_OR_UPDATE_BIBLE", {})
        return {}

    async def _retrieve_node(self, state: AnalysisState) -> dict[str, object]:
        retriever = FactRetriever(self.session)
        candidates = []
        # Retain the first supported statement for each claim in this analysis
        # batch. This catches contradictions within one upload/chapter, before
        # either statement is written to the Series Bible.
        batch_facts: dict[tuple[str, str], ExtractedFact] = {}
        for fact in state.get("facts", []):
            matches = await retriever.retrieve(self.run.series_id, fact.entity, fact.attribute, limit=1)
            key = (fact.entity.casefold().strip(), fact.attribute.casefold().strip())
            candidates.append(matches[0] if matches else batch_facts.get(key))
            batch_facts.setdefault(key, fact)
        await self._checkpoint(self.run, "RETRIEVE_RELEVANT_FACTS", {"candidates": len(candidates)})
        return {"candidates": candidates}

    async def _continuity_node(self, state: AnalysisState) -> dict[str, object]:
        comparisons = []
        for fact, existing in zip(state.get("facts", []), state.get("candidates", []), strict=True):
            existing_fact = await self._as_fact(existing) if isinstance(existing, BibleFact) else existing
            result = self.continuity.compare(existing_fact, fact)
            if isinstance(existing, ExtractedFact) and result.type in (FindingType.CONTRADICTION, FindingType.POSSIBLE_CONTRADICTION):
                result = result.__class__(
                    result.type,
                    f"Two statements in the same analysis batch conflict: '{existing.value}' and '{fact.value}'.",
                    result.confidence,
                    result.severity,
                )
            comparisons.append(result)
        intra_comparisons = self._intra_chapter_comparisons(state.get("facts", []))
        await self._checkpoint(
            self.run,
            "CHECK_CONTINUITY",
            {"comparisons": len(comparisons), "intra_chapter_conflicts": len(intra_comparisons)},
        )
        return {"comparisons": comparisons, "intra_comparisons": intra_comparisons}

    async def _classify_node(self, state: AnalysisState) -> dict[str, object]:
        await self._checkpoint(self.run, "CLASSIFY_FINDINGS", {"classified": len(state.get("comparisons", []))})
        return {}

    async def _persist_node(self, state: AnalysisState) -> dict[str, object]:
        await self._persist_results(
            self.run,
            state.get("facts", []),
            state.get("candidates", []),
            state.get("comparisons", []),
        )
        await self._persist_intra_chapter_results(self.run, state.get("intra_comparisons", []))
        await self._checkpoint(self.run, "PERSIST_FINDINGS", {})
        return {}

    def _llm_provider(self) -> LLMProvider | None:
        if self.settings.extraction_provider == "grounded_rules":
            return None
        if self.settings.extraction_provider == "openai_compatible":
            if self.settings.llm_api_key is None:
                raise ValueError("LLM_API_KEY is required for openai_compatible extraction")
            return OpenAICompatibleProvider(
                self.settings.llm_base_url,
                self.settings.llm_api_key,
                self.settings.llm_model,
            )
        raise ValueError("Unsupported extraction provider")

    async def _extract(
        self,
        chunks: list[DocumentChunk],
        chapter_names: dict[UUID, str],
    ) -> list[ExtractedFact]:
        if self.llm is None:
            return self.extractor.extract(chunks, chapter_names)
        rule_facts = self.extractor.extract(chunks, chapter_names)
        sources = [
            {
                "document_id": str(chunk.document_id),
                "chapter": chapter_names.get(chunk.chapter_id, "Unknown chapter"),
                "section": chunk.section,
                "page": chunk.page,
                "chunk_id": chunk.source_chunk_id,
                "text": chunk.text,
            }
            for chunk in chunks
        ]
        try:
            facts = await self.llm.extract_facts(json.dumps(sources))
        except Exception:
            # An unavailable semantic provider must not prevent the chapter's
            # explicit claims from entering continuity review.
            return rule_facts
        by_chunk = {chunk.source_chunk_id: chunk.text for chunk in chunks}
        grounded = []
        for fact in facts:
            source_text = by_chunk.get(fact.source.chunk_id)
            if source_text is not None and fact.source.evidence_text in source_text:
                grounded.append(fact)
        # Semantic extraction broadens coverage; deterministic facts protect
        # known explicit patterns and ensure LLM omissions do not hide a conflict.
        merged: dict[tuple[str, str, str, str], ExtractedFact] = {}
        for fact in [*rule_facts, *grounded]:
            key = (
                fact.source.chunk_id,
                fact.entity.casefold().strip(),
                fact.attribute.casefold().strip(),
                fact.value.casefold().strip(),
            )
            merged[key] = fact
        return list(merged.values())

    async def _persist_results(self, run: WorkflowRun, facts, candidates, comparisons) -> None:
        bible = BibleService(self.session)
        for fact, existing, result in zip(facts, candidates, comparisons, strict=True):
            if result.type is FindingType.NEW_INFORMATION:
                record = await bible.add_version(run.series_id, fact)
                self.session.add(AuditEvent(run_id=run.id, actor="workflow", entity="bible_fact", entity_id=str(record.id), operation="BIBLE_FACT_CREATED", metadata_json={"entity": fact.entity, "attribute": fact.attribute}))
            elif result.type in (FindingType.CONTRADICTION, FindingType.POSSIBLE_CONTRADICTION):
                existing_id = existing.id if isinstance(existing, BibleFact) else None
                existing_value = existing.value if existing else None
                existing_source = await self._as_fact(existing) if isinstance(existing, BibleFact) else existing
                fingerprint = hashlib.sha256(f"{existing_id or existing_source.source.chunk_id if existing_source else ''}|{fact.entity}|{fact.attribute}|{fact.value}|{fact.source.chunk_id}".encode()).hexdigest()
                duplicate = await self.session.scalar(
                    select(ContinuityFinding).where(
                        ContinuityFinding.run_id == run.id,
                        ContinuityFinding.fingerprint == fingerprint,
                    )
                )
                if duplicate:
                    continue
                finding = ContinuityFinding(run_id=run.id, series_id=run.series_id, existing_fact_id=existing_id, fingerprint=fingerprint, type=result.type.value, entity=fact.entity, attribute=fact.attribute, existing_value=existing_value, new_value=fact.value, explanation=result.explanation, confidence=result.confidence, severity=result.severity, new_fact=fact.model_dump(mode="json"))
                self.session.add(finding)
                await self.session.flush()
                if existing_source is not None:
                    self.session.add(Evidence(finding_id=finding.id, document_id=existing_source.source.document_id, chapter=existing_source.source.chapter, section=existing_source.source.section, page=existing_source.source.page, chunk_id=existing_source.source.chunk_id, exact_text=existing_source.source.evidence_text, role="OLD"))
                self.session.add(Evidence(finding_id=finding.id, document_id=fact.source.document_id, chapter=fact.source.chapter, section=fact.source.section, page=fact.source.page, chunk_id=fact.source.chunk_id, exact_text=fact.source.evidence_text, role="NEW"))
                self.session.add(AuditEvent(run_id=run.id, actor="workflow", entity="finding", entity_id=str(finding.id), operation="FINDING_CREATED", metadata_json={"type": result.type.value}))

    def _intra_chapter_comparisons(
        self, facts: list[ExtractedFact]
    ) -> list[tuple[ExtractedFact, ExtractedFact, object]]:
        """Compare every distinct assertion for a claim within the same chapter.

        This deliberately does not rely on Bible retrieval: the chapter may be
        the first document in a series, or it may contradict itself while also
        contradicting established canon.
        """
        grouped: dict[tuple[str, str, str, str], list[ExtractedFact]] = {}
        for fact in facts:
            key = (
                str(fact.source.document_id), fact.source.chapter.casefold(),
                fact.entity.casefold().strip(), fact.attribute.casefold().strip(),
            )
            grouped.setdefault(key, []).append(fact)
        results: list[tuple[ExtractedFact, ExtractedFact, object]] = []
        for group in grouped.values():
            for index, fact in enumerate(group):
                for previous in group[:index]:
                    result = self.continuity.compare(previous, fact)
                    if result.type in (FindingType.CONTRADICTION, FindingType.POSSIBLE_CONTRADICTION):
                        results.append((previous, fact, result))
        return results

    async def _persist_intra_chapter_results(self, run: WorkflowRun, comparisons) -> None:
        """Persist both source passages for conflicts found inside one chapter."""
        for existing, fact, result in comparisons:
            fingerprint = hashlib.sha256(
                f"intra|{existing.source.chunk_id}|{fact.source.chunk_id}|"
                f"{fact.entity}|{fact.attribute}|{existing.value}|{fact.value}".encode()
            ).hexdigest()
            duplicate = await self.session.scalar(
                select(ContinuityFinding).where(
                    ContinuityFinding.run_id == run.id,
                    ContinuityFinding.fingerprint == fingerprint,
                )
            )
            if duplicate:
                continue
            finding = ContinuityFinding(
                run_id=run.id, series_id=run.series_id, existing_fact_id=None,
                fingerprint=fingerprint, type=result.type.value, entity=fact.entity,
                attribute=fact.attribute, existing_value=existing.value, new_value=fact.value,
                explanation=(
                    f"Conflicting statements in {fact.source.chapter}: '{existing.value}' and "
                    f"'{fact.value}'. Human review is required."
                ), confidence=result.confidence, severity=result.severity,
                new_fact=fact.model_dump(mode="json"),
            )
            self.session.add(finding)
            await self.session.flush()
            for compared_fact, role in ((existing, "OLD"), (fact, "NEW")):
                self.session.add(Evidence(
                    finding_id=finding.id, document_id=compared_fact.source.document_id,
                    chapter=compared_fact.source.chapter, section=compared_fact.source.section,
                    page=compared_fact.source.page, chunk_id=compared_fact.source.chunk_id,
                    exact_text=compared_fact.source.evidence_text, role=role,
                ))
            self.session.add(AuditEvent(
                run_id=run.id, actor="workflow", entity="finding", entity_id=str(finding.id),
                operation="INTRA_CHAPTER_FINDING_CREATED", metadata_json={"type": result.type.value},
            ))

    async def _as_fact(self, record: BibleFact) -> ExtractedFact:
        evidence = await self.session.scalar(select(Evidence).where(Evidence.fact_id == record.id).order_by(Evidence.created_at))
        if evidence is None:
            raise ValueError("Bible fact has no evidence")
        return ExtractedFact(kind=FactKind(record.kind), entity=record.entity, attribute=record.attribute, value=record.value, confidence=record.confidence, supported=True, source=SourceRef(document_id=evidence.document_id, chapter=evidence.chapter, section=evidence.section, page=evidence.page, chunk_id=evidence.chunk_id, evidence_text=evidence.exact_text))

    async def _checkpoint(self, run: WorkflowRun, stage: str, payload: dict[str, object]) -> None:
        if stage not in run.completed_stages:
            self.session.add(WorkflowEvent(run_id=run.id, stage=stage, status="COMPLETED", payload=payload))
            run.completed_stages = [*run.completed_stages, stage]
        run.current_stage = stage
        await self.session.flush()
