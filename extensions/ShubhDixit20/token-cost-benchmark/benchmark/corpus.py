"""
Synthetic document corpus generator.

Generates documents at several size tiers (one page -> several hundred pages)
with realistic section structure, so edit tasks can target "the target section"
meaningfully. Documents are synthetic/fabricated on purpose (per the task brief:
"Fictional clients and fabricated test data are expected").

Each document is a list of sections. A section has:
  - id: stable identifier (e.g. "s03")
  - heading: string
  - body: paragraph text
  - word_count: len(body.split())

Size tiers are expressed in approximate pages, where 1 page ~= 500 words,
which is a documented assumption, not a measured constant.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List

WORDS_PER_PAGE = 500  # documented assumption, see module docstring

# Small deterministic vocabulary pool so generation is reproducible and
# offline (no network / no LLM call needed to build the corpus itself).
_TOPIC_SENTENCES = [
    "The vendor shall deliver the specified goods within the agreed timeline.",
    "Payment terms are net thirty days from the date of invoice receipt.",
    "Either party may terminate this agreement with sixty days written notice.",
    "The parties agree to maintain confidentiality of all shared materials.",
    "This section describes the acceptance criteria for the deliverable.",
    "Amendments to this agreement must be executed in writing by both parties.",
    "The service level agreement guarantees ninety-nine point five percent uptime.",
    "Liability under this clause is capped at the total contract value.",
    "The project milestone was completed ahead of the original schedule.",
    "Status reports are due on the first business day of every month.",
    "Risks identified this period include supply chain delays and staffing gaps.",
    "The compliance checklist requires annual review of data handling practices.",
    "Insurance coverage must remain active for the duration of the engagement.",
    "The claim was filed within the policy's stated notification window.",
    "Clinical documentation must be retained for a minimum of seven years.",
    "The audit found no material discrepancies in the reviewed records.",
    "A follow-up meeting was scheduled to resolve the outstanding action items.",
    "The invoice references purchase order number and delivery confirmation.",
    "Any dispute arising from this agreement shall be resolved by arbitration.",
    "The revised specification incorporates feedback from the last review cycle.",
]

_HEADINGS = [
    "Scope of Work", "Payment Terms", "Termination", "Confidentiality",
    "Acceptance Criteria", "Amendments", "Service Levels", "Limitation of Liability",
    "Project Timeline", "Status Reporting", "Risk Register", "Compliance",
    "Insurance Requirements", "Claims Handling", "Records Retention", "Audit Findings",
    "Action Items", "Invoicing", "Dispute Resolution", "Revision History",
]


@dataclass
class Section:
    id: str
    heading: str
    body: str

    @property
    def word_count(self) -> int:
        return len(self.body.split())


@dataclass
class Document:
    doc_id: str
    title: str
    domain: str
    sections: List[Section] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return sum(s.word_count for s in self.sections)

    @property
    def page_estimate(self) -> float:
        return round(self.word_count / WORDS_PER_PAGE, 2)

    def full_text(self) -> str:
        parts = [f"# {self.title}\n"]
        for s in self.sections:
            parts.append(f"\n## {s.id} — {s.heading}\n\n{s.body}\n")
        return "".join(parts)

    def get_section(self, section_id: str) -> Section:
        for s in self.sections:
            if s.id == section_id:
                return s
        raise KeyError(section_id)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["word_count"] = self.word_count
        d["page_estimate"] = self.page_estimate
        return d


def _gen_paragraph(rng: random.Random, target_words: int) -> str:
    sentences = []
    words_so_far = 0
    while words_so_far < target_words:
        s = rng.choice(_TOPIC_SENTENCES)
        sentences.append(s)
        words_so_far += len(s.split())
    return " ".join(sentences)


def generate_document(doc_id: str, domain: str, target_pages: float, seed: int) -> Document:
    """Deterministic generation: same doc_id + seed always yields the same document."""
    rng = random.Random(seed)
    target_words = int(target_pages * WORDS_PER_PAGE)

    # Split into sections of roughly 150-400 words each.
    sections: List[Section] = []
    words_remaining = target_words
    idx = 0
    while words_remaining > 0:
        sec_words = min(rng.randint(150, 400), max(words_remaining, 50))
        heading = _HEADINGS[idx % len(_HEADINGS)]
        body = _gen_paragraph(rng, sec_words)
        sections.append(Section(id=f"s{idx:02d}", heading=heading, body=body))
        words_remaining -= sec_words
        idx += 1
        if idx > 400:  # safety valve
            break

    title = f"{domain.title()} Document {doc_id} (~{target_pages}pg synthetic)"
    return Document(doc_id=doc_id, title=title, domain=domain, sections=sections)


# Size tiers as specified by the brief: "one page to several hundred".
SIZE_TIERS = [
    ("tiny", 1),
    ("small", 5),
    ("medium", 25),
    ("large", 100),
    ("xlarge", 400),
]

DOMAINS = ["vendor_contract", "project_status_report", "insurance_claim"]


def build_corpus(out_dir: Path, docs_per_tier: int = 2, seed: int = 42) -> List[Document]:
    """Builds the full corpus and writes each document as JSON + Markdown to out_dir.

    Returns the list of generated Document objects.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    docs: List[Document] = []

    for tier_name, pages in SIZE_TIERS:
        for i in range(docs_per_tier):
            domain = DOMAINS[(len(docs) + i) % len(DOMAINS)]
            doc_id = f"{tier_name}-{i:02d}"
            doc_seed = rng.randint(0, 1_000_000)
            doc = generate_document(doc_id=doc_id, domain=domain, target_pages=pages, seed=doc_seed)
            docs.append(doc)

            (out_dir / f"{doc_id}.md").write_text(doc.full_text(), encoding="utf-8")
            (out_dir / f"{doc_id}.json").write_text(
                json.dumps(doc.to_dict(), indent=2), encoding="utf-8"
            )

    manifest = {
        "generated_by": "benchmark/corpus.py",
        "words_per_page_assumption": WORDS_PER_PAGE,
        "docs": [
            {
                "doc_id": d.doc_id,
                "domain": d.domain,
                "word_count": d.word_count,
                "page_estimate": d.page_estimate,
                "num_sections": len(d.sections),
            }
            for d in docs
        ],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return docs


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/corpus")
    docs = build_corpus(out)
    print(f"Generated {len(docs)} documents into {out}/")
    for d in docs:
        print(f"  {d.doc_id:12s} domain={d.domain:22s} words={d.word_count:6d} pages~{d.page_estimate}")
