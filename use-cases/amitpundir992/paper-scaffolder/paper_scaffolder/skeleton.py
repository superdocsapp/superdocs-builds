"""Manuscript skeleton construction."""

from __future__ import annotations

import hashlib
import json
import re

from .grounding import decide_support, evidence_for, semantic_role_for
from .models import ManuscriptSection, ManuscriptSkeleton, PaperInputs


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "section"


class SkeletonGenerator:
    """Build an ordered skeleton with only directly supplied grounded content."""

    def create(
        self, inputs: PaperInputs, section_titles: tuple[str, ...]
    ) -> ManuscriptSkeleton:
        fingerprint = json.dumps(
            {
                "research_question": inputs.research_question,
                "methodology": inputs.methodology,
                "dataset_description": inputs.dataset_description,
                "journal_template": inputs.journal_template,
            },
            sort_keys=True,
        ).encode("utf-8")
        manuscript_id = hashlib.sha256(fingerprint).hexdigest()[:16]

        roles = tuple(semantic_role_for(title) for title in section_titles)
        has_dataset_section = "dataset" in roles
        used_ids: dict[str, int] = {}
        sections: list[ManuscriptSection] = []
        for title, role in zip(section_titles, roles, strict=True):
            base_id = _slug(title)
            occurrence = used_ids.get(base_id, 0) + 1
            used_ids[base_id] = occurrence
            section_id = base_id if occurrence == 1 else f"{base_id}-{occurrence}"
            decision = decide_support(role, inputs)
            source_keys = decision.source_keys
            reason = decision.reason
            if (
                role == "methodology"
                and not has_dataset_section
                and inputs.dataset_description
                and "methodology" in source_keys
            ):
                source_keys = (*source_keys, "dataset_description")
                reason = (
                    "Can be generated extractively from the supplied methodology "
                    "and dataset description."
                )
            evidence = evidence_for(source_keys, inputs)
            grounded_content = "\n\n".join(evidence.values())
            sections.append(
                ManuscriptSection(
                    section_id=section_id,
                    title=title,
                    semantic_role=role,
                    status=decision.status,
                    content=grounded_content,
                    reason=reason,
                    available_sources=source_keys,
                )
            )

        return ManuscriptSkeleton(
            manuscript_id=manuscript_id,
            journal_template=inputs.journal_template,
            sections=tuple(sections),
        )
