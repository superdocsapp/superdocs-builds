from __future__ import annotations

import pathlib
from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    clause_keywords: tuple[str, ...]
    required_position: str
    fallback_wording: str
    when_missing: str
    severity: str


@dataclass(frozen=True)
class Playbook:
    shipper: str
    author_tag: str
    rules: tuple[Rule, ...]

    def rule(self, rule_id: str) -> Rule:
        for r in self.rules:
            if r.id == rule_id:
                return r
        raise KeyError(rule_id)


def load_playbook(path: str | pathlib.Path) -> Playbook:
    data = yaml.safe_load(pathlib.Path(path).read_text())
    rules = []
    seen: set[str] = set()
    for raw in data["rules"]:
        for key in ("id", "name", "clause_keywords", "required_position", "fallback_wording", "when_missing", "severity"):
            if key not in raw:
                raise ValueError(f"rule {raw.get('id', '?')} missing field: {key}")
        if raw["id"] in seen:
            raise ValueError(f"duplicate rule id: {raw['id']}")
        if raw["when_missing"] not in ("insert", "ignore"):
            raise ValueError(f"rule {raw['id']}: when_missing must be insert|ignore")
        seen.add(raw["id"])
        rules.append(
            Rule(
                id=raw["id"],
                name=raw["name"],
                clause_keywords=tuple(k.lower() for k in raw["clause_keywords"]),
                required_position=" ".join(str(raw["required_position"]).split()),
                fallback_wording=" ".join(str(raw["fallback_wording"]).split()),
                when_missing=raw["when_missing"],
                severity=raw["severity"],
            )
        )
    return Playbook(shipper=data["shipper"], author_tag=data.get("author_tag", "Redline Desk"), rules=tuple(rules))
