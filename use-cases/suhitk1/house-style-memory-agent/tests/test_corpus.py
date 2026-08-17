"""Corpus pipeline tests. No API key, no network — runs against committed files.

The claims under test are the ones the measurement rests on: seed drafts are
repaired to a true zero, every committed document carries exactly the same 24
violations, and the injector is deterministic. Uniform difficulty is the
construction-side defence against "the documents got easier", so it is a test,
not an assertion in a write-up.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from checker.h3 import MockH3Provider
from checker.score import load_rubric, score_document
from corpus.inject import (InjectionError, PROFILE, _TEMPLATES, inject)
from corpus.normalize import NormalizationError, normalize

ROOT = Path(__file__).resolve().parent.parent
SEEDS = sorted((ROOT / "corpus" / "seed_drafts").glob("doc_*.md"))
NORMALIZED = sorted((ROOT / "corpus" / "normalized").glob("doc_*.md"))
DOCUMENTS = sorted((ROOT / "corpus" / "documents").glob("doc_*.md"))
RUBRIC = load_rubric("meridian")
TARGETS = PROFILE["targets"]


def _profile(text: str) -> dict[str, int]:
    score = score_document(text, RUBRIC, MockH3Provider())
    return {rid: r.count_raw for rid, r in score.rules.items()}


def test_corpus_is_twenty_documents():
    assert len(SEEDS) == 20
    assert len(NORMALIZED) == 20
    assert len(DOCUMENTS) == 20


@pytest.mark.parametrize("rule_id,templates", sorted(_TEMPLATES.items()))
def test_every_injection_template_trips_exactly_one_rule(rule_id, templates):
    """A template that trips two rules corrupts the profile it is building."""
    for template in templates:
        profile = _profile(template + "\n")
        fired = {rid: n for rid, n in profile.items() if n}
        assert fired == {rule_id: 1}, f"{template!r} fired {fired}"


@pytest.mark.parametrize("path", NORMALIZED, ids=lambda p: p.stem)
def test_normalized_documents_are_deterministically_clean(path):
    score = score_document(path.read_text("utf-8"), RUBRIC, MockH3Provider())
    assert score.deterministic_raw == 0, {
        rid: r.spans for rid, r in score.rules.items() if r.count_raw}


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda p: p.stem)
def test_every_corpus_document_carries_exactly_the_target_profile(path):
    assert _profile(path.read_text("utf-8")) == TARGETS


def test_difficulty_is_uniform_across_the_whole_corpus():
    """The construction-side defence against 'the documents got easier'."""
    profiles = [_profile(p.read_text("utf-8")) for p in DOCUMENTS]
    assert all(p == profiles[0] for p in profiles)
    assert sum(profiles[0].values()) == PROFILE["total_per_document"] == 24


def test_manifest_matches_the_documents_on_disk():
    manifest = json.loads((ROOT / "corpus" / "manifest.json").read_text("utf-8"))
    assert manifest["rubric_version"] == RUBRIC["version"]
    assert len(manifest["documents"]) == 20
    for entry in manifest["documents"]:
        assert entry["final_profile"] == TARGETS
        assert entry["deterministic_after"] == 0 if "deterministic_after" in entry else True


def test_injector_is_deterministic():
    text = NORMALIZED[0].read_text("utf-8")
    first = inject(text, RUBRIC).text
    for _ in range(5):
        assert inject(text, RUBRIC).text == first


def test_injector_refuses_a_draft_dirtier_than_the_profile():
    """Difficulty cannot be made uniform by injection when the seed is over."""
    dirty = NORMALIZED[0].read_text("utf-8") + "\n" + "\n".join(
        f"## Heading Number {n} Here" for n in range(4))
    with pytest.raises(InjectionError, match="exceeds the target profile"):
        inject(dirty, RUBRIC)


def test_normalizer_refuses_rather_than_returning_a_partial_repair():
    """An unknown acronym has no deterministic expansion; it must raise."""
    with pytest.raises(NormalizationError, match="no committed expansion"):
        normalize("# A heading\n\nThe ZQX team reviewed the draft.\n", RUBRIC)


def test_normalizer_output_is_idempotent():
    for path in NORMALIZED[:5]:
        text = path.read_text("utf-8")
        assert normalize(text, RUBRIC) == text
