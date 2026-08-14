"""Evidence availability and conservative grounding rules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from .models import PaperInputs, SectionStatus


@dataclass(frozen=True)
class SupportDecision:
    status: SectionStatus
    reason: str
    source_keys: tuple[str, ...]


def _normalized_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()


def semantic_role_for(title: str) -> str:
    """Map common heading labels to evidence policies without journal branches."""

    normalized = _normalized_title(title)
    exact_roles = {
        "research question": "research_question",
        "research questions": "research_question",
        "objective": "research_question",
        "objectives": "research_question",
        "aim": "research_question",
        "aims": "research_question",
        "methods": "methodology",
        "methodology": "methodology",
        "materials and methods": "methodology",
        "study design": "methodology",
        "research design": "methodology",
        "data": "dataset",
        "dataset": "dataset",
        "data description": "dataset",
        "dataset description": "dataset",
        "data source": "dataset",
        "data sources": "dataset",
        "study data": "dataset",
        "results": "results",
        "findings": "results",
        "discussion": "discussion",
        "conclusion": "conclusion",
        "conclusions": "conclusion",
        "references": "references",
        "bibliography": "references",
        "abstract": "abstract",
        "summary": "abstract",
        "introduction": "background",
        "background": "background",
        "literature review": "background",
        "related work": "background",
        "title": "title",
        "title page": "title",
        "authors": "authors",
        "author information": "authors",
        "acknowledgements": "acknowledgements",
        "acknowledgments": "acknowledgements",
    }
    return exact_roles.get(normalized, "unsupported")


def decide_support(role: str, inputs: PaperInputs) -> SupportDecision:
    """State whether supplied evidence is sufficient for one semantic role."""

    if role == "research_question":
        return SupportDecision(
            SectionStatus.AVAILABLE,
            "Can be generated directly from the supplied research question.",
            ("research_question",),
        )
    if role == "methodology":
        if inputs.methodology:
            return SupportDecision(
                SectionStatus.AVAILABLE,
                "Can be generated extractively from the supplied methodology.",
                ("methodology",),
            )
        return SupportDecision(
            SectionStatus.INSUFFICIENT_INFORMATION,
            "No verified methodology was provided.",
            (),
        )
    if role == "dataset":
        if inputs.dataset_description:
            return SupportDecision(
                SectionStatus.AVAILABLE,
                "Can be generated extractively from the supplied dataset description.",
                ("dataset_description",),
            )
        return SupportDecision(
            SectionStatus.INSUFFICIENT_INFORMATION,
            "No verified dataset information was provided.",
            (),
        )

    reasons = {
        "results": "No verified research results were provided.",
        "discussion": "A discussion cannot be generated without verified results and supported context.",
        "conclusion": "A conclusion cannot be generated without verified results.",
        "references": "No verified citations or bibliography entries were provided.",
        "abstract": "A complete abstract requires verified results and conclusions, which were not provided.",
        "background": "No verified background sources or citations were provided.",
        "title": "No manuscript title was supplied; the research question is not automatically converted into a title.",
        "authors": "No verified author information was provided.",
        "acknowledgements": "No verified acknowledgement information was provided.",
        "unsupported": "No safe mapping exists from the supplied information to this section.",
    }
    return SupportDecision(
        SectionStatus.INSUFFICIENT_INFORMATION,
        reasons[role],
        (),
    )


def evidence_for(source_keys: tuple[str, ...], inputs: PaperInputs) -> dict[str, str]:
    available = {
        "research_question": inputs.research_question,
        "methodology": inputs.methodology,
        "dataset_description": inputs.dataset_description,
    }
    return {key: available[key] for key in source_keys if available.get(key)}


class ExactEvidenceGroundingGuard:
    """Milestone 1 guard: accept only exact researcher-supplied text.

    This deliberately permits extractive generation only. Later paraphrasing support
    requires claim-level evidence validation rather than weakening this guard.
    """

    @staticmethod
    def accepts(content: str, evidence: Mapping[str, str]) -> bool:
        normalized_content = re.sub(r"\s+", " ", content).strip()
        normalized_evidence = [
            re.sub(r"\s+", " ", value).strip() for value in evidence.values()
        ]
        combined_evidence = " ".join(normalized_evidence)
        return bool(normalized_content) and (
            normalized_content in normalized_evidence
            or normalized_content == combined_evidence
        )
