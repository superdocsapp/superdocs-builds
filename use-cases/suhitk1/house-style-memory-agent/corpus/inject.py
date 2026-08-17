"""Violation injector — deterministic, no model call, no network.

Takes a clean seed draft and produces a document carrying EXACTLY the target
violation profile, verified by re-scoring with the committed checker. If the
result does not match the profile exactly, injection fails loudly rather than
committing a document whose difficulty is unknown.

Two properties the measurement depends on:

1. Every injected clause trips exactly ONE rule. Templates are written the same
   way the checker fixtures are, and `test_injector.py` pins that property.
2. Injections are spread across the document, not appended at the end, so the
   agent cannot learn "the errors live in the last paragraph" instead of
   learning the house style.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from checker.h3 import MockH3Provider
from checker.score import load_rubric, score_document

ROOT = Path(__file__).resolve().parent.parent
PROFILE = json.loads((ROOT / "corpus" / "profile.json").read_text("utf-8"))


class InjectionError(RuntimeError):
    """Raised when a document cannot be brought to the exact target profile."""


# Single-violation templates. Each trips exactly one rule; pinned by test.
_TEMPLATES: dict[str, list[str]] = {
    "H1": [
        "The team reviewed scope, budget and timeline.",
        "The group compared cost, quality and speed.",
        "We tracked intake, triage and delivery.",
    ],
    "H3": [
        "The summary was approved by the review group.",
        "The schedule was revised by the delivery team.",
        "The register was updated by the analyst.",
    ],
    "H4": [
        "We ran 3 sessions in the period.",
        "We logged twelve findings in total.",
        "We held 4 workshops for the group.",
    ],
    "H5": [
        "Adoption rose 12% across the period.",
        "Retention held at 87% for the quarter.",
    ],
    "H6": [
        "The window closed on August 13, 2026.",
        "The review opened on March 4, 2026.",
    ],
    "H7": [
        "The figure appears in the register (see Harlow 2024).",
        "The baseline appears in the appendix (see Okonjo 2023).",
    ],
    "H8": [
        "It's ready for the next stage.",
        "We don't expect further delay.",
        "That's the position at present.",
    ],
    "H9": [
        "The team prepared a summary of the work that the group had completed "
        "over the past period and then shared that summary with every person "
        "who had asked to see it before the close of the review window.",
    ],
    "H10": [
        "We leverage the same process here.",
        "The approach remains robust in practice.",
        "The handover was seamless for the group.",
    ],
    "H11": [
        "The team met the deadline - narrowly.",
        "The scope held firm - mostly.",
        "The estimate stood - broadly.",
    ],
    "H13": [
        "NRR held for the period.",
        "CAC moved little across the quarter.",
        "LTV stayed within the expected band.",
    ],
    "H14": [
        "I reviewed the draft before circulation.",
        "The reader will find the summary useful.",
        "I expect the position to hold.",
    ],
}

_MINOR = {"a", "an", "the", "and", "but", "or", "nor", "for", "as", "at", "by",
          "in", "of", "off", "on", "per", "to", "up", "via"}


@dataclass
class InjectionRecord:
    rule_id: str
    span: str
    method: str  # "insert" | "transform"


@dataclass
class InjectionResult:
    text: str
    records: list[InjectionRecord] = field(default_factory=list)
    base_profile: dict[str, int] = field(default_factory=dict)
    final_profile: dict[str, int] = field(default_factory=dict)


def _profile_of(text: str, rubric: dict) -> dict[str, int]:
    score = score_document(text, rubric, MockH3Provider())
    return {rid: r.count_raw for rid, r in score.rules.items()}


def _lines(text: str) -> list[str]:
    return text.splitlines()


def _paragraph_indices(lines: list[str]) -> list[int]:
    return [i for i, ln in enumerate(lines)
            if ln.strip() and not ln.lstrip().startswith(("#", "-", "*", "|", "`"))]


def _bullet_indices(lines: list[str]) -> list[int]:
    return [i for i, ln in enumerate(lines)
            if re.match(r"^\s*[-*+]\s+\S", ln)]


def _heading_indices(lines: list[str]) -> list[int]:
    return [i for i, ln in enumerate(lines) if re.match(r"^#{1,6}\s+\S", ln)]


def _insert_spread(lines: list[str], sentences: list[str],
                   offset: int) -> list[InjectionRecord]:
    """Append each sentence to a different paragraph, spread deterministically."""
    para = _paragraph_indices(lines)
    if not para:
        raise InjectionError("seed draft has no paragraphs to inject into")
    records = []
    for k, sentence in enumerate(sentences):
        idx = para[(offset + k * 3) % len(para)]
        lines[idx] = lines[idx].rstrip() + " " + sentence
        records.append(InjectionRecord("", sentence, "insert"))
    return records


def _title_case(heading_text: str) -> str:
    words = heading_text.split()
    out = []
    for i, w in enumerate(words):
        out.append(w if (i and w.lower() in _MINOR) else w[:1].upper() + w[1:])
    return " ".join(out)


def inject(text: str, rubric: dict,
           targets: dict[str, int] | None = None) -> InjectionResult:
    """Bring `text` to exactly the target profile, or raise."""
    targets = targets or PROFILE["targets"]
    base = _profile_of(text, rubric)

    over = {r: (base[r], targets[r]) for r in targets if base.get(r, 0) > targets[r]}
    if over:
        raise InjectionError(
            "seed draft already exceeds the target profile for "
            f"{over} — the draft is dirtier than the profile allows, so its "
            "difficulty cannot be made uniform by injection alone"
        )

    lines = _lines(text)
    records: list[InjectionRecord] = []

    # --- transforms on existing structure --------------------------------
    need_h2 = targets["H2"] - base.get("H2", 0)
    for i, idx in enumerate(_heading_indices(lines)):
        if need_h2 <= 0:
            break
        m = re.match(r"^(#{1,6})\s+(.*)$", lines[idx])
        if not m:
            continue
        titled = _title_case(m.group(2))
        if titled == m.group(2):
            continue  # already title case; would inject nothing
        lines[idx] = f"{m.group(1)} {titled}"
        records.append(InjectionRecord("H2", titled, "transform"))
        need_h2 -= 1
    if need_h2 > 0:
        raise InjectionError("not enough sentence-case headings to transform")

    need_h12 = targets["H12"] - base.get("H12", 0)
    for i, idx in enumerate(_bullet_indices(lines)):
        if need_h12 <= 0:
            break
        m = re.match(r"^(\s*[-*+]\s+)(.*)$", lines[idx])
        body = m.group(2).rstrip()
        if i % 2 == 0:
            body = body[:1].lower() + body[1:]          # bad initial case
        else:
            body = body.rstrip(".") + "."                # bad terminal punctuation
        lines[idx] = m.group(1) + body
        records.append(InjectionRecord("H12", body, "transform"))
        need_h12 -= 1
    if need_h12 > 0:
        raise InjectionError("not enough bullet items to transform")

    # --- inserted single-violation clauses --------------------------------
    for offset, (rule_id, templates) in enumerate(_TEMPLATES.items()):
        need = targets[rule_id] - base.get(rule_id, 0)
        if need <= 0:
            continue
        if need > len(templates):
            raise InjectionError(
                f"{rule_id} needs {need} injections but only "
                f"{len(templates)} single-violation templates exist"
            )
        for rec in _insert_spread(lines, templates[:need], offset):
            records.append(InjectionRecord(rule_id, rec.span, "insert"))

    out = "\n".join(lines)
    if not out.endswith("\n"):
        out += "\n"

    final = _profile_of(out, rubric)
    mismatch = {r: (final.get(r, 0), targets[r])
                for r in targets if final.get(r, 0) != targets[r]}
    if mismatch:
        raise InjectionError(
            f"injected profile does not match target (got, want): {mismatch}"
        )

    return InjectionResult(text=out, records=records,
                           base_profile=base, final_profile=final)


def inject_file(src: Path, dst: Path, rubric: dict | None = None) -> dict:
    rubric = rubric or load_rubric("meridian")
    result = inject(src.read_text("utf-8"), rubric)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(result.text, encoding="utf-8")
    return {
        "source": src.name,
        "output": dst.name,
        "base_profile": {k: v for k, v in result.base_profile.items() if v},
        "final_profile": result.final_profile,
        "injections": [{"rule": r.rule_id, "method": r.method, "span": r.span}
                       for r in result.records],
    }
