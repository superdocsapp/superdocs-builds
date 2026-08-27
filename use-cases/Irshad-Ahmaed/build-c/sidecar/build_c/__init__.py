"""Build C: Study-Guide & Equation-Bearing Revision Synthesizer.

An EdTech application that transforms raw, unorganized lecture notes (including
mathematical equations and shorthand formulas) into structured, pedagogical
study guides with rendered LaTeX math, Cornell summary notes, Feynman breakdowns,
active recall quizzes, and publication-grade vector PDF exports.
"""

from .guide_generator import (
    StudyGuideGenerator,
    StudyGuideRequest,
    ChatRefineRequest,
    normalize_math_delimiters,
)
from .guide_exporter import StudyGuideExporter

__all__ = [
    "StudyGuideGenerator",
    "StudyGuideRequest",
    "ChatRefineRequest",
    "StudyGuideExporter",
    "normalize_math_delimiters",
]
