"""The structural gate over fixtures/manifest.yaml.

This is what stops fixture drift: it does NOT test detection behaviour
(that belongs to T2). It only proves the fixture set is internally
consistent — every manifest quote really is in the document it claims,
every fact has all four required cases, and the injection fixture exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from freshness_auditor.corpus import Corpus
from freshness_auditor.ledger import FactLedger

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
MANIFEST_PATH = FIXTURES_DIR / "manifest.yaml"
FACTS_PATH = FIXTURES_DIR / "facts.yaml"
CORPUS_PATH = FIXTURES_DIR / "corpus.yaml"

REQUIRED_CASES = {"verbatim", "paraphrase", "current", "near_miss"}


def load_manifest_cases() -> list[dict]:
    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    return data["cases"]


def test_manifest_is_non_empty():
    assert load_manifest_cases()


@pytest.mark.parametrize(
    "case",
    load_manifest_cases(),
    ids=lambda c: f"{c.get('fact_id')}:{c['case']}:{c['doc_id']}",
)
def test_every_quote_is_an_exact_substring_of_its_document(case):
    corpus = Corpus.load(CORPUS_PATH)
    text = corpus.read_text(case["doc_id"])
    assert case["quote"] in text, (
        f"manifest quote for fact={case.get('fact_id')} case={case['case']} "
        f"doc={case['doc_id']} is not an exact substring of that document"
    )


def test_every_manifest_doc_id_exists_in_corpus():
    corpus = Corpus.load(CORPUS_PATH)
    known_ids = {d.id for d in corpus.documents()}
    for case in load_manifest_cases():
        assert case["doc_id"] in known_ids, f"unknown doc_id '{case['doc_id']}' in manifest"


def test_every_manifest_fact_id_exists_in_ledger_or_is_injection():
    ledger = FactLedger.load(FACTS_PATH)
    known_fact_ids = {f.id for f in ledger}
    for case in load_manifest_cases():
        if case["case"] == "injection":
            continue
        assert case["fact_id"] in known_fact_ids, f"unknown fact_id '{case['fact_id']}' in manifest"


def test_each_fact_has_all_four_required_cases():
    ledger = FactLedger.load(FACTS_PATH)
    cases_by_fact: dict[str, set[str]] = {}
    for case in load_manifest_cases():
        if case["case"] == "injection":
            continue
        cases_by_fact.setdefault(case["fact_id"], set()).add(case["case"])

    for fact in ledger:
        assert fact.id in cases_by_fact, f"fact '{fact.id}' has no manifest cases at all"
        assert cases_by_fact[fact.id] == REQUIRED_CASES, (
            f"fact '{fact.id}' has cases {sorted(cases_by_fact[fact.id])}, "
            f"expected exactly {sorted(REQUIRED_CASES)}"
        )


def test_verbatim_and_paraphrase_cases_should_flag_true():
    for case in load_manifest_cases():
        if case["case"] in {"verbatim", "paraphrase"}:
            assert case["should_flag"] is True, case


def test_current_and_near_miss_cases_should_flag_false():
    for case in load_manifest_cases():
        if case["case"] in {"current", "near_miss"}:
            assert case["should_flag"] is False, case


def test_injection_case_exists():
    injection_cases = [c for c in load_manifest_cases() if c["case"] == "injection"]
    assert len(injection_cases) >= 1

    corpus = Corpus.load(CORPUS_PATH)
    for case in injection_cases:
        text = corpus.read_text(case["doc_id"])
        assert case["quote"] in text


def test_at_least_three_library_and_two_draft_documents():
    corpus = Corpus.load(CORPUS_PATH)
    assert len(corpus.by_role("library")) >= 3
    assert len(corpus.by_role("draft")) >= 2


def _normalize(text: str) -> str:
    """Case-insensitive, whitespace-collapsed form, for substring comparison."""
    return " ".join(text.lower().split())


def test_paraphrase_does_not_contain_verbatim_and_vice_versa():
    """A paraphrase fixture that contains its own verbatim string as a
    substring would let a naive str.find detector pass it — defeating the
    entire point of the paraphrase case. This is the structural invariant
    that stops the fixture set silently regressing into that weakness.
    """
    quotes_by_fact: dict[str, dict[str, str]] = {}
    for case in load_manifest_cases():
        if case["case"] in {"verbatim", "paraphrase"} and case.get("fact_id"):
            quotes_by_fact.setdefault(case["fact_id"], {})[case["case"]] = case["quote"]

    for fact_id, quotes in quotes_by_fact.items():
        assert "verbatim" in quotes and "paraphrase" in quotes, (
            f"fact '{fact_id}' is missing a verbatim or paraphrase quote"
        )
        verbatim = _normalize(quotes["verbatim"])
        paraphrase = _normalize(quotes["paraphrase"])
        assert verbatim not in paraphrase, (
            f"fact '{fact_id}': paraphrase quote {quotes['paraphrase']!r} contains the "
            f"verbatim quote {quotes['verbatim']!r} as a substring — reword the paraphrase "
            f"so it does not embed the literal stale value"
        )
        assert paraphrase not in verbatim, (
            f"fact '{fact_id}': verbatim quote {quotes['verbatim']!r} contains the "
            f"paraphrase quote {quotes['paraphrase']!r} as a substring"
        )
