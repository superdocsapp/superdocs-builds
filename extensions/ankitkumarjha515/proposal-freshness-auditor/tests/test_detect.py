"""Behavioural gate over the detection engine.

The load-bearing tests here are the NEGATIVE ones. A miss is a
disappointment; a false positive is a liability — a bid manager who sees
"1,200 laptops" flagged as a stale headcount switches the tool off and
never comes back. So the manifest-driven suite asserts not just that every
`should_flag: true` case is found, but that each document yields EXACTLY
the findings its manifest entries call for and not one more.

Synthetic ledgers (built in `tmp_path`) are used wherever a case needs a
fact shape the shared fixture set does not contain — two retired values, a
retired value of 9001, a retired value of 1. The shared `fixtures/` set is
Task 1's contract and is never touched.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from freshness_auditor.corpus import Corpus
from freshness_auditor.detect import (
    Evidence,
    Finding,
    detect,
    detect_all,
    document_text,
    finding_id,
    parse_blocks,
    split_sentences,
    subject_terms,
)
from freshness_auditor.ledger import FactLedger

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
MANIFEST_PATH = FIXTURES_DIR / "manifest.yaml"
FACTS_PATH = FIXTURES_DIR / "facts.yaml"
CORPUS_PATH = FIXTURES_DIR / "corpus.yaml"


def load_manifest_cases() -> list[dict]:
    return yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))["cases"]


@pytest.fixture(scope="module")
def ledger() -> FactLedger:
    return FactLedger.load(FACTS_PATH)


@pytest.fixture(scope="module")
def corpus() -> Corpus:
    return Corpus.load(CORPUS_PATH)


def _normalise_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _quote_span(doc_text: str, quote: str) -> tuple[int, int]:
    """Locate a manifest quote inside the detector's document text."""
    needle = _normalise_ws(quote)
    start = doc_text.find(needle)
    assert start != -1, (
        f"manifest quote {needle!r} is not present in the extracted document "
        f"text — the HTML extractor and the fixtures have drifted apart"
    )
    return start, start + len(needle)


def _write_ledger(tmp_path: Path, facts: list[dict], name: str = "facts.yaml") -> FactLedger:
    """Build a throwaway ledger. Used for fact shapes the shared fixtures
    do not carry; never writes into `fixtures/`."""
    path = tmp_path / name
    path.write_text(yaml.safe_dump({"facts": facts}, sort_keys=False), encoding="utf-8")
    return FactLedger.load(path)


def _headcount_fact(value: int, priors: list[int], synonyms=None) -> dict:
    return {
        "id": "headcount",
        "subject": "permanent staff",
        "subject_synonyms": synonyms or ["employees", "workforce"],
        "value": value,
        "kind": "integer",
        "unit": "people",
        "source": "synthetic test ledger",
        "as_of": date(2026, 1, 15),
        "prior_values": [
            {"value": p, "as_of": date(2023, 6, 1), "retired_on": date(2026, 1, 15)}
            for p in priors
        ],
    }


# ---------------------------------------------------------------------------
# Manifest-driven: all four facts x all four case labels, by construction
# ---------------------------------------------------------------------------

FACT_CASES = [c for c in load_manifest_cases() if c.get("fact_id")]


@pytest.mark.parametrize(
    "case",
    FACT_CASES,
    ids=lambda c: f"{c['fact_id']}:{c['case']}:{c['doc_id']}",
)
def test_manifest_case_flag_behaviour(case, ledger, corpus):
    """Every manifest case behaves as its label says, at its own location.

    The check is positional, not per-document: `certifications-overview`
    carries BOTH a should-flag and a should-not-flag case for the same
    fact, so "did this document produce a finding" would be too coarse to
    tell them apart.
    """
    html = corpus.read_text(case["doc_id"])
    fact = ledger.get(case["fact_id"])
    doc_text = document_text(html)
    q_start, q_end = _quote_span(doc_text, case["quote"])

    findings = detect(html, case["doc_id"], fact)
    inside = [
        f for f in findings if q_start <= f.evidence.start and f.evidence.end <= q_end
    ]

    if case["should_flag"]:
        assert inside, (
            f"MISS: {case['case']} case for fact '{case['fact_id']}' in "
            f"{case['doc_id']} was not flagged. Quote: {case['quote']!r}"
        )
    else:
        assert not inside, (
            f"FALSE POSITIVE: {case['case']} case for fact "
            f"'{case['fact_id']}' in {case['doc_id']} was flagged. "
            f"Quote: {case['quote']!r} -> {[f.stated_value for f in inside]}"
        )


@pytest.mark.parametrize(
    "doc_id",
    sorted({c["doc_id"] for c in load_manifest_cases()}),
)
def test_document_yields_exactly_the_manifest_findings(doc_id, ledger, corpus):
    """No extra findings anywhere. This is the zero-false-positive gate:
    the count of findings in a document must equal the number of
    `should_flag: true` manifest entries for it."""
    expected = sum(
        1 for c in FACT_CASES if c["doc_id"] == doc_id and c["should_flag"]
    )
    findings = detect_all(corpus.read_text(doc_id), doc_id, ledger)
    assert len(findings) == expected, (
        f"{doc_id}: expected {expected} findings, got "
        f"{[(f.fact_id, f.stated_value) for f in findings]}"
    )


def test_near_miss_and_current_documents_produce_no_findings_at_all(ledger, corpus):
    """cap-statement states every fact correctly; draft-proposal-beta makes
    no fact claim. Neither may produce a single finding."""
    for doc_id in ("cap-statement", "draft-proposal-beta"):
        assert detect_all(corpus.read_text(doc_id), doc_id, ledger) == []


def test_every_finding_offset_resolves_to_its_own_quote(ledger, corpus):
    """Evidence must be checkable without trusting the tool: the reported
    offsets, applied to the document text, must reproduce the quote."""
    for doc in corpus:
        html = corpus.read_text(doc.id)
        doc_text = document_text(html)
        for f in detect_all(html, doc.id, ledger):
            assert doc_text[f.evidence.start:f.evidence.end] == f.evidence.quote
            assert f.evidence.quote in f.evidence.sentence


def test_every_finding_reports_its_ledger_provenance(ledger, corpus):
    for doc in corpus:
        for f in detect_all(corpus.read_text(doc.id), doc.id, ledger):
            fact = ledger.get(f.fact_id)
            assert f.source == fact.source
            assert f.as_of == fact.as_of
            assert f.canonical_value == str(fact.value)
            assert f.matched_prior in fact.prior_values
            assert 0.0 <= f.confidence <= 1.0
            assert f.match_type in {"exact", "paraphrase"}


# ---------------------------------------------------------------------------
# The matching rule itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "<p>We employ 1,200 permanent staff worldwide.</p>",  # value then subject
        "<p>Permanent staff worldwide: 1,200 at last count.</p>",  # subject then value
        "<p>Across our workforce, 1,200 remains the figure quoted.</p>",
        "<p>1,200 is the number of employees on the payroll.</p>",
    ],
)
def test_word_order_does_not_matter(sentence, ledger):
    """Condition 2 is set membership over the sentence, not a template."""
    findings = detect(sentence, "d", ledger.get("headcount"))
    assert len(findings) == 1
    assert findings[0].stated_value == "1,200"


@pytest.mark.parametrize(
    "sentence",
    [
        "<p>1,200 laptops were distributed to field offices.</p>",
        "<p>The venue seats 1,200 guests across three halls.</p>",
        "<p>A 1,200 kilometre supply corridor was opened.</p>",
        "<p>Programme budget line 1,200 was reallocated in full.</p>",
        "<p>We shipped 1,200 tonnes of relief materiel.</p>",
    ],
)
def test_stale_number_without_a_subject_term_is_never_flagged(sentence, ledger):
    """The retired headcount number, in sentences that are about something
    else. Every one of these is a switch-the-tool-off false positive if the
    subject-proximity rule is weakened."""
    assert detect(sentence, "d", ledger.get("headcount")) == []


def test_current_value_is_never_flagged(ledger):
    fact = ledger.get("headcount")
    assert detect("<p>We employ 1,450 permanent staff.</p>", "d", fact) == []
    assert detect("<p>Our workforce numbers 1,450 people.</p>", "d", fact) == []


def test_current_value_stated_as_month_year_is_never_flagged(ledger):
    fact = ledger.get("iso_9001_renewal")
    assert detect("<p>ISO 9001 renewal is due March 2026.</p>", "d", fact) == []
    assert detect("<p>ISO certification renewal: 03/2026.</p>", "d", fact) == []


def test_subject_and_value_in_different_sentences_are_not_joined(ledger):
    """Same paragraph, different sentences: the rule says same sentence."""
    html = (
        "<p>Our permanent staff are based in twelve regional hubs. "
        "The warehouse holds 1,200 pallets of supplies.</p>"
    )
    assert detect(html, "d", ledger.get("headcount")) == []


# ---------------------------------------------------------------------------
# The two normalize.py limitations this layer exists to absorb
# ---------------------------------------------------------------------------


def test_iso_standard_number_is_not_read_as_a_headcount(tmp_path):
    """`find_numbers("ISO 9001")` reports 9001 — correct at that layer,
    which cannot know what 9001 means. Here it is disarmed by subject
    proximity and by nothing else: no denylist of strings exists, and a
    client that genuinely retired a headcount of 9001 is still detected
    the moment a headcount subject term appears (second assertion)."""
    synthetic = _write_ledger(tmp_path, [_headcount_fact(9500, [9001])])
    fact = synthetic.get("headcount")

    assert detect(
        "<p>Northwind holds ISO 9001 certification for quality management.</p>",
        "d",
        fact,
    ) == []
    assert detect("<p>Our ISO 9001 and ISO 14001 registrations are current.</p>", "d", fact) == []

    still_works = detect("<p>We employ 9001 permanent staff.</p>", "d", fact)
    assert len(still_works) == 1
    assert still_works[0].stated_value == "9001"


@pytest.mark.parametrize(
    "sentence,retired",
    [
        ("<p>The One Health initiative launched three programmes.</p>", 1),
        ("<p>We met partners at the Four Seasons in Nairobi.</p>", 4),
        ("<p>Six Sigma training was delivered to field managers.</p>", 6),
    ],
)
def test_number_words_that_are_ordinary_words_are_not_flagged(
    sentence, retired, tmp_path
):
    """Bare number-words that double as names ("One Health", "Four
    Seasons") do match as numbers in `normalize`. Subject proximity is what
    stops them becoming findings — again with no denylist."""
    synthetic = _write_ledger(tmp_path, [_headcount_fact(1450, [retired])])
    assert detect(sentence, "d", synthetic.get("headcount")) == []


def test_vague_periods_are_left_unmatched(ledger):
    """"early 2023" / "Q1 2023" / "spring of 2023" are not strictly
    equivalent to March 2023. Matching them would mean guessing, and a tool
    that rewrites a bid document on a guess is a tool that gets switched
    off. Leaving them unflagged is the deliberate answer."""
    fact = ledger.get("iso_9001_renewal")
    for phrasing in (
        "<p>ISO 9001 certification was renewed in early 2023.</p>",
        "<p>ISO 9001 certification was renewed in Q1 2023.</p>",
        "<p>ISO 9001 certification was renewed in the spring of 2023.</p>",
    ):
        assert detect(phrasing, "d", fact) == []


# ---------------------------------------------------------------------------
# Paraphrase reach
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence,expected_quote,expected_type",
    [
        ("<p>We employ 1200 permanent staff.</p>", "1200", "exact"),
        ("<p>We employ 1,200 permanent staff.</p>", "1,200", "exact"),
        ("<p>We employ 1 200 permanent staff.</p>", "1 200", "exact"),
        ("<p>We employ twelve hundred permanent staff.</p>", "twelve hundred", "paraphrase"),
        ("<p>We employ 1.2k permanent staff.</p>", "1.2k", "paraphrase"),
        ("<p>We employ 1.2 thousand permanent staff.</p>", "1.2 thousand", "paraphrase"),
        ("<p>We employ over 1,200 permanent staff.</p>", "over 1,200", "paraphrase"),
        ("<p>We employ approximately 1,200 permanent staff.</p>", "approximately 1,200", "paraphrase"),
        ("<p>We employ nearly 1,200 permanent staff.</p>", "nearly 1,200", "paraphrase"),
        ("<p>We employ ~1,200 permanent staff.</p>", "~1,200", "paraphrase"),
    ],
)
def test_headcount_paraphrase_surface_forms(sentence, expected_quote, expected_type, ledger):
    findings = detect(sentence, "d", ledger.get("headcount"))
    assert len(findings) == 1
    assert findings[0].stated_value == expected_quote
    assert findings[0].match_type == expected_type


@pytest.mark.parametrize(
    "sentence,expected_quote,expected_type",
    [
        ("<p>ISO 9001 certification was renewed in March 2023.</p>", "March 2023", "exact"),
        ("<p>ISO 9001 certification was renewed in Mar 2023.</p>", "Mar 2023", "paraphrase"),
        ("<p>ISO 9001 certification was renewed in 03/2023.</p>", "03/2023", "paraphrase"),
        ("<p>ISO 9001 certification was renewed in 3/2023.</p>", "3/2023", "paraphrase"),
        ("<p>ISO 9001 certification was renewed in 2023-03.</p>", "2023-03", "paraphrase"),
        ("<p>ISO 9001 certification was renewed in March '23.</p>", "March '23", "paraphrase"),
    ],
)
def test_month_year_paraphrase_surface_forms(sentence, expected_quote, expected_type, ledger):
    findings = detect(sentence, "d", ledger.get("iso_9001_renewal"))
    assert len(findings) == 1
    assert findings[0].stated_value == expected_quote
    assert findings[0].match_type == expected_type


def test_decimal_fact_matches_across_unit_scaling(ledger):
    """The beneficiaries fact's unit is "million people", so the same value
    is written "3.2 million", "3.2m" and "3,200,000" in different
    documents."""
    fact = ledger.get("beneficiaries_2025")
    for sentence, quote in [
        ("<p>We reached 3.2 million beneficiaries.</p>", "3.2 million"),
        ("<p>We reached 3.2m people last year.</p>", "3.2m"),
        ("<p>We reached 3,200,000 people last year.</p>", "3,200,000"),
    ]:
        findings = detect(sentence, "d", fact)
        assert len(findings) == 1, sentence
        assert findings[0].stated_value == quote


def test_stated_surface_form_in_the_facts_own_unit_counts_as_exact(ledger):
    """Ledger prior is `3.2` with unit "million people". A document saying
    "3.2 million" is stating the retired value in the fact's own unit —
    that is the same surface form, not a paraphrase. "3.2m" abbreviates it,
    so it is."""
    fact = ledger.get("beneficiaries_2025")
    assert detect("<p>We reached 3.2 million beneficiaries.</p>", "d", fact)[0].match_type == "exact"
    assert detect("<p>We reached 3.2m beneficiaries.</p>", "d", fact)[0].match_type == "paraphrase"


# ---------------------------------------------------------------------------
# Several retired values per fact (the gap carried in from Task 1)
# ---------------------------------------------------------------------------


def test_finding_records_which_prior_value_it_matched(tmp_path):
    """`Fact.prior_values` is a list; a boilerplate library accumulates
    several generations of a figure. Matching only the most recent retired
    value would silently miss the oldest and most embarrassing copies."""
    synthetic = _write_ledger(
        tmp_path,
        [
            {
                "id": "headcount",
                "subject": "permanent staff",
                "subject_synonyms": ["employees", "workforce"],
                "value": 1450,
                "kind": "integer",
                "unit": "people",
                "source": "synthetic test ledger",
                "as_of": date(2026, 1, 15),
                "prior_values": [
                    {"value": 1200, "as_of": date(2023, 6, 1), "retired_on": date(2026, 1, 15)},
                    {"value": 900, "as_of": date(2019, 6, 1), "retired_on": date(2023, 6, 1)},
                ],
            }
        ],
    )
    fact = synthetic.get("headcount")
    html = (
        "<p>We employ 1,200 permanent staff today.</p>"
        "<p>An older brochure claims 900 employees.</p>"
        "<p>Our workforce reached 1,450 this year.</p>"
    )
    findings = detect(html, "d", fact)

    assert [f.stated_value for f in findings] == ["1,200", "900"]
    assert findings[0].matched_prior.value == 1200
    assert findings[1].matched_prior.value == 900
    assert findings[0].matched_prior.as_of.year == 2023
    assert findings[1].matched_prior.as_of.year == 2019
    # both generations are reported, and the current value is not
    assert all(f.canonical_value == "1450" for f in findings)


def test_oldest_retired_value_is_found_even_when_it_is_last_in_the_list(tmp_path):
    synthetic = _write_ledger(
        tmp_path,
        [
            {
                "id": "headcount",
                "subject": "permanent staff",
                "subject_synonyms": ["employees"],
                "value": 1450,
                "kind": "integer",
                "unit": "people",
                "source": "synthetic test ledger",
                "as_of": date(2026, 1, 15),
                "prior_values": [
                    {"value": 1200, "as_of": date(2023, 6, 1), "retired_on": date(2026, 1, 15)},
                    {"value": 900, "as_of": date(2019, 6, 1), "retired_on": date(2023, 6, 1)},
                ],
            }
        ],
    )
    findings = detect(
        "<p>A team of nine hundred permanent staff.</p>", "d", synthetic.get("headcount")
    )
    assert len(findings) == 1
    assert findings[0].matched_prior.value == 900
    assert findings[0].match_type == "paraphrase"


# ---------------------------------------------------------------------------
# Deterministic ids
# ---------------------------------------------------------------------------


def test_ids_are_identical_across_two_runs(ledger, corpus):
    """A reviewer's accept/reject decisions must survive a re-audit."""
    html = corpus.read_text("annual-report-summary")
    first = detect_all(html, "annual-report-summary", ledger)
    second = detect_all(html, "annual-report-summary", ledger)
    assert [f.id for f in first] == [f.id for f in second]
    assert first == second


def test_ids_are_unique_within_a_document(ledger, corpus):
    findings = detect_all(
        corpus.read_text("annual-report-summary"), "annual-report-summary", ledger
    )
    assert len({f.id for f in findings}) == len(findings)


def test_id_is_the_hash_of_doc_fact_and_offsets(ledger, corpus):
    doc_id = "annual-report-summary"
    for f in detect_all(corpus.read_text(doc_id), doc_id, ledger):
        assert f.id == finding_id(doc_id, f.fact_id, f.evidence.start, f.evidence.end)


def test_id_changes_with_doc_id(ledger):
    html = "<p>We employ 1,200 permanent staff.</p>"
    fact = ledger.get("headcount")
    assert detect(html, "doc-a", fact)[0].id != detect(html, "doc-b", fact)[0].id


def test_detect_all_ordering_is_document_order(ledger, corpus):
    findings = detect_all(
        corpus.read_text("annual-report-summary"), "annual-report-summary", ledger
    )
    offsets = [f.evidence.start for f in findings]
    assert offsets == sorted(offsets)


# ---------------------------------------------------------------------------
# Documents are data, never instructions
# ---------------------------------------------------------------------------


def test_injection_document_produces_no_findings(ledger, corpus):
    html = corpus.read_text("draft-proposal-beta")
    assert detect_all(html, "draft-proposal-beta", ledger) == []


def test_injection_text_is_processed_exactly_like_inert_prose(ledger, corpus):
    """The embedded instruction changes nothing. Appending it to a stale
    paragraph yields findings identical — ids included — to appending
    ordinary prose. If any code path branched on document content, this
    would diverge."""
    injection = [
        c for c in load_manifest_cases() if c["case"] == "injection"
    ][0]["quote"]
    inert = "The programme team meets fortnightly to review delivery milestones."

    stale = "<p>We employ 1,200 permanent staff.</p>"
    with_injection = detect_all(stale + f"<p>{injection}</p>", "d", ledger)
    with_inert = detect_all(stale + f"<p>{inert}</p>", "d", ledger)

    assert with_injection == with_inert
    assert len(with_injection) == 1
    assert with_injection[0].fact_id == "headcount"


def test_injection_text_does_not_suppress_a_stale_claim_beside_it(ledger):
    """The injection says to approve the document as current. It does not
    get to. A stale claim in the same paragraph is still flagged."""
    injection = [
        c for c in load_manifest_cases() if c["case"] == "injection"
    ][0]["quote"]
    html = f"<p>{injection} We employ 1,200 permanent staff.</p>"
    findings = detect_all(html, "d", ledger)
    assert len(findings) == 1
    assert findings[0].fact_id == "headcount"


# ---------------------------------------------------------------------------
# HTML handling
# ---------------------------------------------------------------------------


def test_chunk_id_is_captured_when_the_html_carries_one(ledger):
    html = '<p data-chunk-id="c-42">We employ 1,200 permanent staff.</p>'
    findings = detect(html, "d", ledger.get("headcount"))
    assert findings[0].evidence.chunk_id == "c-42"


def test_chunk_id_is_none_when_the_html_does_not_carry_one(ledger, corpus):
    findings = detect(
        "<p>We employ 1,200 permanent staff.</p>", "d", ledger.get("headcount")
    )
    assert findings[0].evidence.chunk_id is None
    for f in detect_all(
        corpus.read_text("annual-report-summary"), "annual-report-summary", ledger
    ):
        assert f.evidence.chunk_id is None


def test_element_index_identifies_the_enclosing_block(ledger):
    html = (
        "<h1>Capability Statement</h1>"
        "<p>Introductory paragraph with no figures.</p>"
        '<p data-chunk-id="c-9">We employ 1,200 permanent staff.</p>'
    )
    findings = detect(html, "d", ledger.get("headcount"))
    assert findings[0].evidence.element_index == 2
    assert findings[0].evidence.chunk_id == "c-9"


@pytest.mark.parametrize(
    "html",
    [
        "<td>We employ 1,200 permanent staff.</td>",
        "<th>We employ 1,200 permanent staff.</th>",
        "<li>We employ 1,200 permanent staff.</li>",
        "<h3>We employ 1,200 permanent staff.</h3>",
        "<p>We employ <strong>1,200</strong> permanent staff.</p>",
    ],
)
def test_all_block_elements_and_inline_markup_are_searched(html, ledger):
    findings = detect(html, "d", ledger.get("headcount"))
    assert len(findings) == 1
    assert findings[0].stated_value == "1,200"


def test_plain_text_input_is_accepted(ledger):
    findings = detect("We employ 1,200 permanent staff.", "d", ledger.get("headcount"))
    assert len(findings) == 1
    assert findings[0].evidence.chunk_id is None
    assert findings[0].evidence.element_index == 0


def test_html_entities_are_decoded(ledger):
    findings = detect(
        "<p>We employ 1,200 permanent staff &amp; contractors.</p>",
        "d",
        ledger.get("headcount"),
    )
    assert len(findings) == 1
    assert "&" in findings[0].evidence.sentence


def test_script_and_style_content_is_not_searched(ledger):
    html = "<style>.x{width:1200px}</style><script>var staff = 1200;</script>"
    assert detect(html, "d", ledger.get("headcount")) == []


def test_parse_blocks_offsets_line_up_with_document_text(corpus):
    for doc in corpus:
        text, blocks = parse_blocks(corpus.read_text(doc.id))
        for block in blocks:
            assert text[block.offset:block.offset + len(block.text)] == block.text
        assert [b.element_index for b in blocks] == list(range(len(blocks)))


def test_split_sentences_does_not_break_on_decimals_or_dates():
    text = "We reached 3.2 million people. Renewal was 03/2023. Done."
    parts = split_sentences(text)
    assert [p[0] for p in parts] == [
        "We reached 3.2 million people.",
        "Renewal was 03/2023.",
        "Done.",
    ]
    for sentence, offset in parts:
        assert text[offset:offset + len(sentence)] == sentence


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


def test_exact_match_scores_higher_than_paraphrase(ledger):
    fact = ledger.get("headcount")
    exact = detect("<p>We employ 1,200 permanent staff.</p>", "d", fact)[0]
    para = detect("<p>We employ twelve hundred permanent staff.</p>", "d", fact)[0]
    assert exact.confidence > para.confidence


def test_hedged_value_scores_lower(ledger):
    fact = ledger.get("headcount")
    plain = detect("<p>We employ 1,200 permanent staff.</p>", "d", fact)[0]
    hedged = detect("<p>We employ over 1,200 permanent staff.</p>", "d", fact)[0]
    assert hedged.confidence < plain.confidence


def test_distance_between_subject_and_value_lowers_confidence(ledger):
    fact = ledger.get("headcount")
    near = detect("<p>We employ 1,200 permanent staff.</p>", "d", fact)[0]
    far = detect(
        "<p>We employ 1,200 people across our programme, logistics, finance, "
        "security, monitoring, evaluation and community engagement teams, all "
        "of whom are counted as permanent staff.</p>",
        "d",
        fact,
    )[0]
    assert far.confidence < near.confidence


def test_historical_marker_lowers_confidence_but_never_suppresses(ledger):
    """A sentence that may be legitimate history is surfaced at low
    confidence, not silently dropped. Silent dropping is how a real stale
    claim ships."""
    fact = ledger.get("headcount")
    plain = detect("<p>We employ 1,200 permanent staff.</p>", "d", fact)[0]
    historical = detect(
        "<p>We previously employed 1,200 permanent staff.</p>", "d", fact
    )
    assert len(historical) == 1
    assert historical[0].confidence < plain.confidence
    assert historical[0].confidence > 0.0


def test_negated_sentence_is_surfaced_at_lower_confidence(ledger):
    fact = ledger.get("headcount")
    plain = detect("<p>We employ 1,200 permanent staff.</p>", "d", fact)[0]
    negated = detect("<p>We do not employ 1,200 permanent staff.</p>", "d", fact)
    assert len(negated) == 1
    assert negated[0].confidence < plain.confidence


def test_then_and_now_contrast_scores_lower(ledger):
    fact = ledger.get("headcount")
    plain = detect("<p>We employ 1,200 permanent staff.</p>", "d", fact)[0]
    contrast = detect(
        "<p>Our permanent staff grew from 1,200 to 1,450.</p>", "d", fact
    )
    assert len(contrast) == 1
    assert contrast[0].confidence < plain.confidence


def test_number_counting_a_different_noun_scores_lower(ledger):
    """The residual false-positive class the same-sentence rule cannot
    close: "our staff distributed 1,200 laptops" has both a retired value
    and a subject term. It is still surfaced — suppressing it would trade
    a false positive for a miss on "permanent staff worldwide: 1,200" —
    but it must rank below a real stale claim."""
    fact = ledger.get("headcount")
    real = detect("<p>We employ 1,200 permanent staff.</p>", "d", fact)[0]
    other = detect("<p>Our staff distributed 1,200 laptops.</p>", "d", fact)
    assert len(other) == 1
    assert other[0].confidence < real.confidence


def test_counting_the_facts_own_unit_is_not_penalised(ledger):
    """"1,200 people" counts the fact's unit, so it is not a mismatch."""
    fact = ledger.get("headcount")  # unit: people
    unit_noun = detect("<p>Our permanent staff total 1,200 people.</p>", "d", fact)[0]
    other_noun = detect("<p>Our permanent staff ordered 1,200 laptops.</p>", "d", fact)[0]
    assert unit_noun.confidence > other_noun.confidence


def test_counted_noun_rule_does_not_apply_to_date_facts(ledger):
    """A date does not count a noun, so the word after "March 2023" must
    not be read as a mismatched counted noun."""
    fact = ledger.get("iso_9001_renewal")
    findings = detect(
        "<p>ISO 9001 certification was renewed in March 2023 under audit.</p>", "d", fact
    )
    assert len(findings) == 1
    assert findings[0].confidence > 0.8


def test_full_synonym_phrase_scores_higher_than_a_single_word(ledger):
    fact = ledger.get("headcount")
    full = detect("<p>Our permanent staff number 1,200.</p>", "d", fact)[0]
    partial = detect("<p>Our staff number 1,200.</p>", "d", fact)[0]
    assert full.confidence > partial.confidence


def test_confidence_stays_within_bounds_under_stacked_penalties(ledger):
    fact = ledger.get("headcount")
    findings = detect(
        "<p>We do not, and previously did not, employ approximately 1,200 "
        "people; permanent staff now number 1,450.</p>",
        "d",
        fact,
    )
    assert len(findings) == 1
    assert 0.0 < findings[0].confidence <= 1.0


# ---------------------------------------------------------------------------
# Configuration over code
# ---------------------------------------------------------------------------


def test_adding_a_synonym_is_a_data_change_only(tmp_path):
    """A word the ledger does not know is not a subject term; adding it to
    `subject_synonyms` in YAML — with no code change — makes it one."""
    sentence = "<p>Our crewing complement stands at 1,200.</p>"

    without = _write_ledger(
        tmp_path, [_headcount_fact(1450, [1200], synonyms=["employees"])], "a.yaml"
    )
    assert detect(sentence, "d", without.get("headcount")) == []

    with_synonym = _write_ledger(
        tmp_path,
        [_headcount_fact(1450, [1200], synonyms=["employees", "crewing complement"])],
        "b.yaml",
    )
    assert len(detect(sentence, "d", with_synonym.get("headcount"))) == 1


def test_adding_a_fact_is_a_data_change_only(tmp_path):
    synthetic = _write_ledger(
        tmp_path,
        [
            {
                "id": "vehicle_fleet",
                "subject": "fleet vehicles",
                "subject_synonyms": ["vehicles operated", "fleet size"],
                "value": 310,
                "kind": "integer",
                "unit": "vehicles",
                "source": "synthetic test ledger",
                "as_of": date(2026, 1, 1),
                "prior_values": [
                    {"value": 260, "as_of": date(2022, 1, 1), "retired_on": date(2026, 1, 1)}
                ],
            }
        ],
    )
    findings = detect_all("<p>We operate 260 fleet vehicles.</p>", "d", synthetic)
    assert len(findings) == 1
    assert findings[0].fact_id == "vehicle_fleet"


def test_subject_terms_are_derived_from_the_ledger(ledger):
    terms, phrases = subject_terms(ledger.get("country_count"))
    assert "country" in terms  # from "countries of operation" / "countries served"
    assert "nation" in terms  # from the "nations" synonym
    assert "of" not in terms  # function words never become subject terms
    assert phrases


def test_fact_with_no_prior_values_never_produces_a_finding(tmp_path):
    synthetic = _write_ledger(tmp_path, [_headcount_fact(1450, [])])
    assert detect(
        "<p>We employ 1,450 permanent staff.</p>", "d", synthetic.get("headcount")
    ) == []


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------


def test_finding_and_evidence_are_frozen(ledger):
    finding = detect("<p>We employ 1,200 permanent staff.</p>", "d", ledger.get("headcount"))[0]
    with pytest.raises(Exception):
        finding.confidence = 0.1
    with pytest.raises(Exception):
        finding.evidence.quote = "x"
    assert isinstance(finding, Finding)
    assert isinstance(finding.evidence, Evidence)


def test_empty_document_yields_nothing(ledger):
    assert detect_all("", "d", ledger) == []
    assert detect_all("<p></p>", "d", ledger) == []
