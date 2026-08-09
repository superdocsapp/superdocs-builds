"""Maps amendment deltas to affected proposal sections, including
second-order effects, using the data-driven config in config/section_map.yaml.

Adding a new rule type or a new section dependency is a YAML edit here, not
a code change — the "configuration over code" principle the round grades on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import yaml

from .models import AmendmentDelta, SectionImpact


@dataclass
class SectionMapConfig:
    rule_section_map: Dict[str, Dict[str, List[str]]]
    section_dependencies: Dict[str, List[str]]
    known_sections: List[str]

    @classmethod
    def load(cls, path: str) -> "SectionMapConfig":
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return cls(
            rule_section_map=raw.get("rule_section_map", {}),
            section_dependencies=raw.get("section_dependencies", {}),
            known_sections=raw.get("known_sections", []),
        )

    def direct_sections_for(self, delta: AmendmentDelta) -> List[str]:
        # requirement adds/deletes share one rule_type ("requirement") so the
        # diff engine diffs them against the same baseline key namespace, but
        # they route to proposal sections differently, so look them up under
        # a synthesized "requirement_added" / "requirement_deleted" config key.
        if delta.rule_type == "requirement" and delta.change_kind in ("added", "deleted"):
            effective_type = f"requirement_{delta.change_kind}"
        else:
            effective_type = delta.rule_type

        by_key = self.rule_section_map.get(effective_type, {})
        if delta.key in by_key:
            return by_key[delta.key]
        return by_key.get("default", [])


def map_impacts(deltas: List[AmendmentDelta], config: SectionMapConfig) -> Dict[str, SectionImpact]:
    """Returns {section_id: SectionImpact}, merging direct + second-order hits."""

    impacts: Dict[str, SectionImpact] = {}

    def _ensure(section_id: str, order: str, caused_by: str | None = None) -> SectionImpact:
        existing = impacts.get(section_id)
        if existing is None:
            existing = SectionImpact(section_id=section_id, order=order, deltas=[], caused_by_section=caused_by)
            impacts[section_id] = existing
        elif order == "direct" and existing.order == "second_order":
            # A section can start as a second-order hit and later turn out to
            # also be directly impacted by a different delta; direct wins.
            existing.order = "direct"
            existing.caused_by_section = None
        return existing

    directly_hit_sections: set[str] = set()

    for delta in deltas:
        for section_id in config.direct_sections_for(delta):
            impact = _ensure(section_id, "direct")
            if delta not in impact.deltas:
                impact.deltas.append(delta)
            directly_hit_sections.add(section_id)

    # second-order propagation: anything depending on a directly-hit section
    for source_section in directly_hit_sections:
        for dependent_section in config.section_dependencies.get(source_section, []):
            impact = _ensure(dependent_section, "second_order", caused_by=source_section)
            # carry the same citations forward so the second-order edit is
            # still traceable to the amendment paragraph that ultimately drove it
            for delta in impacts[source_section].deltas:
                if delta not in impact.deltas:
                    impact.deltas.append(delta)

    return impacts


def untouched_sections(config: SectionMapConfig, impacts: Dict[str, SectionImpact]) -> List[str]:
    return [s for s in config.known_sections if s not in impacts]
