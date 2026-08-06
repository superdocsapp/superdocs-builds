"""AI Resume Analyzer — extract structured facts and create embeddings.

Rules:
- Extract ONLY facts supported by resume text.
- Every education/experience/project/achievement entry must include evidence spans.
- Do not infer missing employers, dates, degrees, metrics, or years of experience.
- years_of_experience is set only when explicitly stated (or clearly supported);
  otherwise null.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.llm import invoke_structured
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, http_bad_request
from app.core.logging import get_logger
from app.models.document import Document, IngestSession
from app.schemas.document import DocumentSource
from app.schemas.resume import (
    AchievementItem,
    EducationItem,
    EmbeddingInfo,
    ExperienceItem,
    ProjectItem,
    ResumeAnalysis,
    ResumeAnalyzerResponse,
    ResumeExtractionOutput,
)
from app.services.parsers.base import parse_file
from app.services.rag.ingestion import IngestionService

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are a strict resume information extractor.

Rules:
1. Use ONLY the provided resume text.
2. Do NOT invent education, jobs, projects, skills, achievements, technologies, or dates.
3. Do NOT infer facts that are not explicitly written.
4. Every education, experience, project, and achievement item MUST include an `evidence`
   field copying a short exact span from the resume that supports it.
5. If a field is not present in the resume, omit it or leave lists empty.
6. `years_of_experience`:
   - Set a number ONLY if the resume explicitly states years of experience
     (e.g. "5+ years of experience"), and set years_of_experience_explicitly_stated=true.
   - Otherwise set years_of_experience=null and years_of_experience_explicitly_stated=false.
   - Do NOT calculate years by guessing from incomplete dates.
7. Skills and technologies must appear in the resume text (skills section, tools listed, etc.).
8. Prefer precision over completeness. Empty is better than fabricated.
"""


class ResumeAnalyzerService:
    def __init__(self, db: AsyncSession, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    async def analyze_upload(
        self,
        *,
        resume: UploadFile,
        candidate_name: str | None = None,
    ) -> ResumeAnalyzerResponse:
        if not resume.filename:
            raise http_bad_request("Resume file is missing a filename")

        upload_root = Path(self.settings.upload_dir) / "resume_analysis"
        upload_root.mkdir(parents=True, exist_ok=True)
        path = await self._save_upload(resume, upload_root)

        try:
            resume_text = parse_file(path, resume.filename)
        except AppError as exc:
            raise http_bad_request(exc.message) from exc

        return await self.analyze_text(
            resume_text=resume_text,
            candidate_name=candidate_name,
            filename=resume.filename,
        )

    async def analyze_text(
        self,
        *,
        resume_text: str,
        candidate_name: str | None = None,
        filename: str | None = "resume.txt",
    ) -> ResumeAnalyzerResponse:
        cleaned = resume_text.strip()
        if not cleaned:
            raise http_bad_request("Resume text is empty")

        extraction = await invoke_structured(
            schema=ResumeExtractionOutput,
            system=SYSTEM_PROMPT,
            user=(
                "Extract structured resume fields from the text below.\n"
                "Return only supported facts with evidence spans.\n\n"
                f"RESUME TEXT:\n{cleaned[:24000]}"
            ),
        )
        analysis = self._normalize_analysis(extraction, cleaned)

        session = IngestSession(
            id=uuid.uuid4(),
            company_name="__resume_analysis__",
            company_url=None,
        )
        self.db.add(session)
        await self.db.flush()

        document = Document(
            id=uuid.uuid4(),
            session_id=session.id,
            source=DocumentSource.RESUME.value,
            filename=filename,
            content_text=cleaned,
        )
        self.db.add(document)
        await self.db.flush()

        chunk_count = await IngestionService(self.db).index_document(
            session_id=session.id,
            document_id=document.id,
            source=DocumentSource.RESUME.value,
            text=cleaned,
        )
        await self.db.flush()

        logger.info(
            "Resume analyzed session=%s document=%s chunks=%s education=%s experience=%s",
            session.id,
            document.id,
            chunk_count,
            len(analysis.education),
            len(analysis.experience),
        )

        return ResumeAnalyzerResponse(
            candidate_name=candidate_name,
            analysis=analysis,
            embeddings=EmbeddingInfo(
                session_id=session.id,
                document_id=document.id,
                chunk_count=chunk_count,
                embedding_model=self.settings.embedding_model,
                dimensions=self.settings.embedding_dimensions,
                source=DocumentSource.RESUME.value,
            ),
            resume_char_count=len(cleaned),
        )

    def _normalize_analysis(
        self,
        extraction: ResumeExtractionOutput,
        resume_text: str,
    ) -> ResumeAnalysis:
        """Drop entries without usable evidence; never keep unsupported years."""
        education = [
            item
            for item in extraction.education
            if self._has_evidence(item.evidence, resume_text)
        ]
        experience = [
            item
            for item in extraction.experience
            if self._has_evidence(item.evidence, resume_text)
        ]
        projects = [
            item
            for item in extraction.projects
            if self._has_evidence(item.evidence, resume_text)
        ]
        achievements = [
            item
            for item in extraction.achievements
            if item.description.strip() and self._has_evidence(item.evidence, resume_text)
        ]

        skills = self._filter_terms(extraction.skills, resume_text)
        technologies = self._filter_terms(extraction.technologies, resume_text)

        years: float | None = None
        years_evidence: str | None = None
        if (
            extraction.years_of_experience_explicitly_stated
            and extraction.years_of_experience is not None
            and extraction.years_of_experience >= 0
            and extraction.years_of_experience_evidence
            and self._has_evidence(extraction.years_of_experience_evidence, resume_text)
        ):
            years = float(extraction.years_of_experience)
            years_evidence = extraction.years_of_experience_evidence.strip()
        else:
            # Secondary safeguard: accept only explicit patterns in resume text.
            explicit = self._extract_explicit_years(resume_text)
            if explicit is not None:
                years, years_evidence = explicit

        return ResumeAnalysis(
            education=education,
            experience=experience,
            projects=projects,
            skills=skills,
            achievements=achievements,
            technologies=technologies,
            years_of_experience=years,
            years_of_experience_evidence=years_evidence,
        )

    def _filter_terms(self, terms: list[str], resume_text: str) -> list[str]:
        resume_lower = resume_text.lower()
        seen: set[str] = set()
        result: list[str] = []
        for term in terms:
            cleaned = term.strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            # Require term to appear in resume (case-insensitive).
            if key not in resume_lower and not self._fuzzy_term_in_resume(cleaned, resume_text):
                continue
            seen.add(key)
            result.append(cleaned)
        return result

    @staticmethod
    def _fuzzy_term_in_resume(term: str, resume_text: str) -> bool:
        # Allow simple punctuation differences: "Node.js" vs "Nodejs"
        compact_term = re.sub(r"[^a-z0-9]+", "", term.lower())
        compact_resume = re.sub(r"[^a-z0-9]+", "", resume_text.lower())
        return bool(compact_term) and compact_term in compact_resume

    @staticmethod
    def _has_evidence(evidence: str | None, resume_text: str) -> bool:
        if not evidence or not evidence.strip():
            return False
        span = evidence.strip()
        # Prefer exact containment; fall back to whitespace-normalized match.
        if span in resume_text:
            return True
        norm_span = " ".join(span.split()).lower()
        norm_resume = " ".join(resume_text.split()).lower()
        return bool(norm_span) and norm_span in norm_resume

    @staticmethod
    def _extract_explicit_years(resume_text: str) -> tuple[float, str] | None:
        patterns = [
            re.compile(
                r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years|yrs)\s+(?:of\s+)?(?:experience|exp)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?:experience|exp)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*\+?\s*(?:years|yrs)",
                re.IGNORECASE,
            ),
        ]
        for pattern in patterns:
            match = pattern.search(resume_text)
            if not match:
                continue
            try:
                value = float(match.group(1))
            except ValueError:
                continue
            return value, match.group(0).strip()
        return None

    async def _save_upload(self, upload: UploadFile, dest_dir: Path) -> Path:
        max_bytes = self.settings.max_upload_mb * 1024 * 1024
        content = await upload.read()
        if not content:
            raise http_bad_request("Uploaded resume is empty")
        if len(content) > max_bytes:
            raise http_bad_request(
                f"File exceeds max upload size of {self.settings.max_upload_mb}MB"
            )
        dest_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(upload.filename or "resume.bin").name
        dest = dest_dir / f"{uuid.uuid4().hex}_{safe_name}"
        dest.write_bytes(content)
        return dest
