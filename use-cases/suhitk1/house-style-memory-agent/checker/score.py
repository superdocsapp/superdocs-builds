"""Scoring orchestration.

The instrument. Takes document text plus a rubric id and returns per-rule
capped and uncapped violation counts. It is handed nothing else — no arm label,
no run id, no ordinal, no prior score — because that is the blinding contract in
the rubric files, and the cheapest way to keep a contract is to have no way to
break it: `score_document` has no parameter that could carry the arm.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from .client_detectors import (EMBER_DETECTORS, HEADING_CASE_RULES,
                               NORTHWIND_DETECTORS)
from .detectors import DETERMINISTIC_DETECTORS, Violation
from .document import Document
from .h3 import H3Provider, score_h3

ALL_DETECTORS = {**DETERMINISTIC_DETECTORS, **NORTHWIND_DETECTORS,
                 **EMBER_DETECTORS}

RUBRIC_DIR = Path(__file__).resolve().parent.parent / "rubrics"


def load_rubric(rubric_id: str) -> dict:
    with open(RUBRIC_DIR / f"{rubric_id}.json", encoding="utf-8") as fh:
        return json.load(fh)


@dataclass
class RuleScore:
    rule_id: str
    count_raw: int
    count_capped: int
    detector: str
    spans: list[str] = field(default_factory=list)
    status: str = "ok"


@dataclass
class DocumentScore:
    rubric_id: str
    rubric_version: str
    content_hash: str
    rules: dict[str, RuleScore]

    def _sum(self, detector: str, field_name: str) -> int:
        return sum(getattr(r, field_name) for r in self.rules.values()
                   if r.detector == detector)

    @property
    def deterministic_capped(self) -> int:
        return self._sum("deterministic", "count_capped")

    @property
    def deterministic_raw(self) -> int:
        return self._sum("deterministic", "count_raw")

    @property
    def llm_capped(self) -> int:
        return self._sum("llm", "count_capped")

    @property
    def llm_raw(self) -> int:
        return self._sum("llm", "count_raw")

    @property
    def total_capped(self) -> int:
        return self.deterministic_capped + self.llm_capped

    @property
    def total_raw(self) -> int:
        return self.deterministic_raw + self.llm_raw

    def as_dict(self) -> dict:
        return {
            "rubric_id": self.rubric_id,
            "rubric_version": self.rubric_version,
            "content_hash": self.content_hash,
            "rules": {rid: {"count_raw": r.count_raw,
                            "count_capped": r.count_capped,
                            "detector": r.detector,
                            "status": r.status,
                            "spans": r.spans}
                      for rid, r in self.rules.items()},
            "totals": {
                "deterministic_capped": self.deterministic_capped,
                "deterministic_raw": self.deterministic_raw,
                "llm_capped": self.llm_capped,
                "llm_raw": self.llm_raw,
                "total_capped": self.total_capped,
                "total_raw": self.total_raw,
            },
        }


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def score_document(text: str, rubric: dict,
                   h3_provider: H3Provider | None = None) -> DocumentScore:
    """Score one document. No arm, run, ordinal or client id is accepted."""
    doc = Document.parse(text)
    allowlist = set(rubric.get("proper_noun_allowlist", []))
    scores: dict[str, RuleScore] = {}

    for rule in rubric["rules"]:
        rid, cap = rule["id"], rule["cap"]
        if rule["detector"] == "llm":
            if h3_provider is None:
                scores[rid] = RuleScore(rid, 0, 0, "llm", status="skipped")
                continue
            result = score_h3(doc, h3_provider, cap=cap)
            scores[rid] = RuleScore(rid, result.count_raw,
                                    min(result.count_raw, cap), "llm",
                                    spans=result.clauses, status=result.status)
            continue

        detector = ALL_DETECTORS.get(rid)
        if detector is None:
            scores[rid] = RuleScore(rid, 0, 0, "deterministic",
                                    status="no_detector")
            continue
        violations: list[Violation] = (
            detector(doc, rule, allowlist) if rid in HEADING_CASE_RULES
            else detector(doc, rule)
        )
        raw = len(violations)
        scores[rid] = RuleScore(rid, raw, min(raw, cap), "deterministic",
                                spans=[v.span for v in violations])

    return DocumentScore(rubric_id=rubric["id"],
                         rubric_version=rubric["version"],
                         content_hash=content_hash(text),
                         rules=scores)


def blind_batch(documents: dict[str, str], seed: int) -> list[tuple[str, str]]:
    """Shuffle documents and replace identifiers with content hashes.

    Input maps caller-side ids (which may encode arm and ordinal) to text.
    Output is a shuffled list of (content_hash, text): the scorer sees neither
    the original id nor the original order. The caller rejoins scores to ids by
    content hash after scoring, never before.
    """
    items = [(content_hash(text), text) for text in documents.values()]
    random.Random(seed).shuffle(items)
    return items
