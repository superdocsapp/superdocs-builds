"""Local index of generated debriefs.

Deliberately a single JSON file, not a database -- per the assignment's "do not
build unnecessary databases" and the scale here (dozens of debriefs a quarter, not
millions). All aggregation (win/loss counts per competitor/segment, small-sample
flagging) happens here in plain Python so the numbers handed to the synthesis prompt
are exact, not AI-estimated -- see architecture.md §4.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

from .templates import CompetitorStat, SegmentStat


@dataclass
class DebriefRecord:
    deal_code: str
    quarter: str
    segment: str
    outcome: str  # "win" | "loss"
    competitors: list[str] = field(default_factory=list)
    evidence_snippets: list[str] = field(default_factory=list)
    customer_name: str = ""
    customer_aliases: list[str] = field(default_factory=list)
    transcript_path: str = ""
    transcript_sha256: str = ""
    exported_path: str = ""
    superdocs_document_id: str | None = None
    unverified_evidence_count: int = 0


class Index:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, DebriefRecord] = self._load()

    def _load(self) -> dict[str, DebriefRecord]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text())
        return {k: DebriefRecord(**v) for k, v in raw.items()}

    def save(self) -> None:
        self.path.write_text(json.dumps({k: asdict(v) for k, v in self._records.items()}, indent=2, sort_keys=True))

    def upsert(self, record: DebriefRecord) -> None:
        """Idempotent by deal_code -- re-indexing the same deal overwrites, never
        duplicates."""
        self._records[record.deal_code] = record
        self.save()

    def get(self, deal_code: str) -> DebriefRecord | None:
        return self._records.get(deal_code)

    def all(self) -> list[DebriefRecord]:
        return list(self._records.values())

    def for_quarter(self, quarter: str) -> list[DebriefRecord]:
        return [r for r in self._records.values() if r.quarter == quarter]

    def by_competitor(self, competitor: str) -> list[DebriefRecord]:
        needle = competitor.strip().lower()
        return [r for r in self._records.values() if any(needle in c.lower() for c in r.competitors)]

    def by_segment(self, segment: str) -> list[DebriefRecord]:
        needle = segment.strip().lower()
        return [r for r in self._records.values() if needle in r.segment.lower()]

    def by_outcome(self, outcome: str) -> list[DebriefRecord]:
        return [r for r in self._records.values() if r.outcome == outcome]

    def all_customer_terms(self) -> list[str]:
        """Every known customer name + alias across the WHOLE index (not just one
        quarter) -- used as the banned-term list for redaction.scan_for_leaks."""
        terms: set[str] = set()
        for r in self._records.values():
            if r.customer_name:
                terms.add(r.customer_name)
            terms.update(r.customer_aliases)
        return sorted(terms)


def aggregate_competitor_stats(records: list[DebriefRecord], small_sample_threshold: int) -> list[CompetitorStat]:
    tally: dict[str, dict[str, int]] = {}
    for r in records:
        for competitor in r.competitors:
            bucket = tally.setdefault(competitor, {"win": 0, "loss": 0})
            bucket[r.outcome] = bucket.get(r.outcome, 0) + 1
    stats = []
    for competitor, counts in sorted(tally.items()):
        wins, losses = counts.get("win", 0), counts.get("loss", 0)
        stats.append(
            CompetitorStat(
                competitor=competitor,
                wins_against=wins,
                losses_to=losses,
                small_sample=(wins + losses) < small_sample_threshold,
            )
        )
    return stats


def aggregate_segment_stats(records: list[DebriefRecord], small_sample_threshold: int) -> list[SegmentStat]:
    tally: dict[str, dict[str, int]] = {}
    for r in records:
        bucket = tally.setdefault(r.segment, {"win": 0, "loss": 0})
        bucket[r.outcome] = bucket.get(r.outcome, 0) + 1
    stats = []
    for segment, counts in sorted(tally.items()):
        wins, losses = counts.get("win", 0), counts.get("loss", 0)
        stats.append(
            SegmentStat(
                segment=segment,
                wins=wins,
                losses=losses,
                small_sample=(wins + losses) < small_sample_threshold,
            )
        )
    return stats


def parse_debrief_html(html: str) -> dict:
    """Deterministic extraction of the structured facts out of a generated debrief's
    HTML -- NOT an LLM call. Returns a dict suitable for merging into a
    DebriefRecord (competitors, evidence_snippets)."""
    soup = BeautifulSoup(html, "html.parser")
    competitors: list[str] = []

    for heading in soup.find_all("h2"):
        if heading.get_text(strip=True).lower() == "competitors present":
            table = heading.find_next("table")
            if table:
                for row in table.find_all("tr")[1:]:  # skip header row
                    cells = row.find_all(["td", "th"])
                    if cells:
                        name = cells[0].get_text(strip=True)
                        if name and name.lower() != "none mentioned in transcript":
                            competitors.append(name)
            break

    evidence_snippets = [bq.get_text(strip=True) for bq in soup.find_all(attrs={"data-evidence": "true"})]

    return {"competitors": competitors, "evidence_snippets": evidence_snippets}
