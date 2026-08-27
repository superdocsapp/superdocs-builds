import shutil
import tempfile
from pathlib import Path

import pytest

from benchmark.corpus import generate_document, build_corpus, SIZE_TIERS, WORDS_PER_PAGE


def test_generation_is_deterministic():
    d1 = generate_document("x", "vendor_contract", target_pages=2, seed=123)
    d2 = generate_document("x", "vendor_contract", target_pages=2, seed=123)
    assert d1.full_text() == d2.full_text()


def test_different_seed_yields_different_text():
    d1 = generate_document("x", "vendor_contract", target_pages=2, seed=1)
    d2 = generate_document("x", "vendor_contract", target_pages=2, seed=2)
    assert d1.full_text() != d2.full_text()


def test_word_count_roughly_matches_target_pages():
    doc = generate_document("x", "vendor_contract", target_pages=10, seed=1)
    target_words = 10 * WORDS_PER_PAGE
    # generation stops at/after target, allow some overshoot from the last section
    assert doc.word_count >= target_words
    assert doc.word_count < target_words * 1.3


def test_sections_have_stable_ids():
    doc = generate_document("x", "vendor_contract", target_pages=3, seed=1)
    ids = [s.id for s in doc.sections]
    assert ids == sorted(ids)
    assert doc.get_section(ids[0]).id == ids[0]


def test_get_section_missing_raises():
    doc = generate_document("x", "vendor_contract", target_pages=1, seed=1)
    with pytest.raises(KeyError):
        doc.get_section("does-not-exist")


def test_build_corpus_covers_all_tiers():
    tmp = Path(tempfile.mkdtemp())
    try:
        docs = build_corpus(tmp, docs_per_tier=1, seed=1)
        tiers_seen = {d.doc_id.split("-")[0] for d in docs}
        expected_tiers = {name for name, _ in SIZE_TIERS}
        assert tiers_seen == expected_tiers
        assert (tmp / "manifest.json").exists()
        for d in docs:
            assert (tmp / f"{d.doc_id}.md").exists()
            assert (tmp / f"{d.doc_id}.json").exists()
    finally:
        shutil.rmtree(tmp)


def test_page_estimate_reasonable_for_tiny_tier():
    doc = generate_document("tiny-00", "vendor_contract", target_pages=1, seed=1)
    assert 0.5 <= doc.page_estimate <= 2.0
