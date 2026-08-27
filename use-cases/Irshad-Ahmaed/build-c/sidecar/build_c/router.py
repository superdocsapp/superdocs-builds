"""FastAPI APIRouter for Build C: Study-Guide & Equation Synthesizer."""

from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .guide_generator import StudyGuideGenerator, StudyGuideRequest, ChatRefineRequest
from .guide_exporter import StudyGuideExporter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/study-guide", tags=["Build C: Study Guide"])


class GenerateGuideRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=150, description="Subject name")
    topic: str = Field(..., min_length=1, max_length=200, description="Unit or topic name")
    target_exam: str = Field(default="University STEM / Competitive Exam", max_length=150)
    raw_notes: str = Field(..., min_length=5, max_length=30000, description="Raw lecture text and formulas")
    depth: str = Field(default="detailed", description="Synthesis depth")


class ChatGuideRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    current_markdown: str = Field(..., min_length=1)
    instruction: str = Field(..., min_length=2, max_length=2000)


class ExportGuideRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=150)
    topic: str = Field(..., min_length=1, max_length=200)
    guide_markdown: str = Field(..., min_length=10)


@router.post("/generate")
async def generate_study_guide(req: GenerateGuideRequest):
    """Synthesize raw student notes with equations into a 4-tier study guide."""
    try:
        gen = StudyGuideGenerator()
        return gen.generate_guide(
            StudyGuideRequest(
                subject=req.subject,
                topic=req.topic,
                target_exam=req.target_exam,
                raw_notes=req.raw_notes,
                depth=req.depth,
            )
        )
    except Exception as e:
        logger.exception("Failed to generate study guide: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/chat")
async def chat_study_guide(req: ChatGuideRequest):
    """Iteratively refine the study guide through conversational instructions."""
    try:
        gen = StudyGuideGenerator()
        return gen.refine_guide(
            ChatRefineRequest(
                session_id=req.session_id,
                current_markdown=req.current_markdown,
                instruction=req.instruction,
            )
        )
    except Exception as e:
        logger.exception("Failed to refine study guide: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/export")
async def export_study_guide(req: ExportGuideRequest):
    """Export the study guide to publication-grade vector PDF with running headers and centered footers."""
    try:
        exporter = StudyGuideExporter()
        return exporter.export_pdf(
            subject=req.subject,
            topic=req.topic,
            guide_markdown=req.guide_markdown,
        )
    except Exception as e:
        logger.exception("Failed to export study guide: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
