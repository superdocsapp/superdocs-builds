"""Integrity of the shipped legal content itself.

Everything above this file tests the engine. This file tests the *data* — the
jurisdiction rules a user actually relies on. It is the closest thing a
non-lawyer can build to a check on "correct and dated": it cannot tell whether a
statute says what the rule claims, but it can guarantee that every claim carries
an authority, a source, a verification date and a review deadline, that the
dates are internally coherent, and that the jurisdictions genuinely differ.

The last of those is the card's actual premise. `test_the_four_jurisdictions_differ_meaningfully`
would fail if someone added four states that all required the same things.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from real_estate_pack.io_yaml import load_request
from real_estate_pack.rules import available_jurisdictions, load_jurisdiction_file, load_ruleset
from real_estate_pack.validate import validate_pack

RULES_DIR = Path(__file__).resolve().parent.parent / "jurisdictions"
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
STATES = ["US-CA", "US-TX", "US-NY", "US-FL"]

#: The date the shipped content was researched. Nothing may claim to have been
#: verified after it — a future verification date is a fabricated one.
RESEARCH_DATE = date(2025, 8, 1)


def all_rule_files():
    return sorted(RULES_DIR.glob("*.yaml"))


def all_rules():
    for path in all_rule_files():
        for rule in load_jurisdiction_file(path).rules:
            yield path.name, rule


def test_every_shipped_file_loads():
    assert all_rule_files(), "no jurisdiction files found"
    for path in all_rule_files():
        load_jurisdiction_file(path)


def test_every_shipped_jurisdiction_resolves_with_the_federal_layer():
    for code in available_jurisdictions(RULES_DIR):
        assert load_ruleset(code, RULES_DIR).rules


@pytest.mark.parametrize("file_name,rule", list(all_rules()), ids=lambda v: getattr(v, "id", str(v)))
def test_every_rule_is_cited_dated_and_sourced(file_name, rule):
    citation = rule.citation
    assert citation.authority.strip(), f"{file_name}:{rule.id} has an empty authority"
    assert citation.source_url.startswith(("http://", "https://")), (
        f"{file_name}:{rule.id} source_url is not a URL: {citation.source_url!r}"
    )
    assert "example.invalid" not in citation.source_url, f"{file_name}:{rule.id} still points at a placeholder"
    assert citation.review_by > citation.verified_on, f"{file_name}:{rule.id} review_by must be after verified_on"
    assert citation.verified_on <= RESEARCH_DATE, (
        f"{file_name}:{rule.id} claims verification on {citation.verified_on}, after the research date "
        f"{RESEARCH_DATE}. A verification date in the future is a fabricated one."
    )


@pytest.mark.parametrize("file_name,rule", list(all_rules()), ids=lambda v: getattr(v, "id", str(v)))
def test_rule_ids_are_namespaced_to_their_file(file_name, rule):
    """Prevents the collision the loader would otherwise have to catch, and keeps
    a grep for `ca_` honest."""
    expected_prefix = {"us_fed.yaml": "fed_", "us_ca.yaml": "ca_", "us_tx.yaml": "tx_",
                       "us_ny.yaml": "ny_", "us_fl.yaml": "fl_"}[file_name]
    assert rule.id.startswith(expected_prefix), f"{file_name}:{rule.id} should start with {expected_prefix!r}"


@pytest.mark.parametrize("file_name,rule", list(all_rules()), ids=lambda v: getattr(v, "id", str(v)))
def test_disclosures_have_substantive_bodies(file_name, rule):
    if rule.kind != "disclosure":
        return
    assert len(rule.body.strip()) > 80, f"{file_name}:{rule.id} body is too short to be a real disclosure"


@pytest.mark.parametrize("file_name,rule", list(all_rules()), ids=lambda v: getattr(v, "id", str(v)))
def test_verbatim_rules_carry_enough_text_to_be_worth_protecting(file_name, rule):
    if not rule.verbatim_statutory:
        return
    assert len(rule.body.strip()) > 150, (
        f"{file_name}:{rule.id} is marked verbatim_statutory but carries almost no text"
    )


def test_rule_ids_are_unique_across_the_whole_corpus():
    ids = [rule.id for _, rule in all_rules()]
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, f"duplicate rule ids across files: {sorted(duplicates)}"


def test_fast_moving_rules_carry_a_note_explaining_the_short_cadence():
    """A short review window is a judgement call, and an unexplained one is
    indistinguishable from a typo."""
    for file_name, rule in all_rules():
        window_days = (rule.citation.review_by - rule.citation.verified_on).days
        if window_days < 400:
            assert rule.citation.note.strip(), (
                f"{file_name}:{rule.id} has a {window_days}-day review window but no note saying why"
            )


def test_every_derived_fact_is_actually_asked_for_by_a_rule():
    """Derived facts are where speculative helpers accumulate. Two of them
    (`is_pre_1978`, `is_pre_1960`) were computed on every run and referenced by
    nothing — the rules that care about construction year express it directly.
    The bar is that something asks for it."""
    from real_estate_pack.facts import derive_facts
    from real_estate_pack.io_yaml import load_request

    req = load_request(EXAMPLES / "compare_all_jurisdictions.yaml")
    derived = set(derive_facts(req))
    asked_for = {name for _, rule in all_rules() for name in rule.required_facts()}
    unused = derived - asked_for
    assert not unused, f"derived but never referenced by any rule: {sorted(unused)}"


def test_every_fact_a_rule_asks_for_is_answerable():
    """A rule referencing a fact no example can supply would block every pack in
    that jurisdiction with no way forward. Each referenced fact must either be a
    field on the lease record, derivable, or answered by a shipped example."""
    from real_estate_pack.facts import derive_facts
    from real_estate_pack.io_yaml import load_request
    from real_estate_pack.models import Property, Tenancy

    record_fields = set(Property.__dataclass_fields__) | set(Tenancy.__dataclass_fields__)
    answerable = set(record_fields)
    for path in EXAMPLES.glob("*.yaml"):
        req = load_request(path)
        answerable |= set(req.disclosure_facts) | set(derive_facts(req))

    for file_name, rule in all_rules():
        for name in rule.required_facts():
            assert name in answerable, (
                f"{file_name}:{rule.id} asks for {name!r}, which no lease record field, "
                f"derivation, or shipped example can supply — likely a typo in the rule file"
            )


def test_every_state_defines_a_deposit_position_one_way_or_the_other():
    """Silence about deposits is indistinguishable from an unfinished file. Each
    state must either cap the deposit or say explicitly that it does not."""
    for code in STATES:
        jurisdiction = load_jurisdiction_file(RULES_DIR / f"{code.lower().replace('-', '_')}.yaml")
        has_cap = bool(jurisdiction.limits())
        says_no_cap = any("no_deposit_cap" in r.id for r in jurisdiction.rules)
        assert has_cap or says_no_cap, f"{code} takes no position on security deposits"


# ------------------------------------------------- the card's premise, asserted


def _decisions_for(code):
    req = load_request(EXAMPLES / "compare_all_jurisdictions.yaml")
    jurisdiction = load_ruleset(code, RULES_DIR)
    result = validate_pack(req, jurisdiction, today=RESEARCH_DATE, allow_stale=True)
    return result, {d.rule.title for d in result.decisions if d.applies and d.rule.kind == "disclosure"}


def test_the_four_jurisdictions_differ_meaningfully():
    """The premise of the card. Same property, four rulesets, four different
    required-disclosure sets — and every pair genuinely differs."""
    sets = {code: _decisions_for(code)[1] for code in STATES}
    for i, a in enumerate(STATES):
        for b in STATES[i + 1:]:
            assert sets[a] != sets[b], f"{a} and {b} require identical disclosures — they do not differ"


def test_each_jurisdiction_requires_something_none_of_the_others_do():
    """Not just 'different sets' — each state must contribute a requirement that
    is unique to it, which is what makes it worth modelling separately."""
    sets = {code: _decisions_for(code)[1] for code in STATES}
    for code in STATES:
        others = set().union(*(sets[o] for o in STATES if o != code))
        unique = sets[code] - others
        assert unique, f"{code} requires nothing that the other jurisdictions do not also require"


def test_the_federal_layer_is_shared_by_every_state():
    sets = {code: _decisions_for(code)[1] for code in STATES}
    common = set.intersection(*sets.values())
    assert any("Lead-Based Paint" in title for title in common), (
        "the pre-1978 federal lead disclosure must fire in every jurisdiction"
    )


def test_the_same_deposit_is_lawful_in_some_jurisdictions_and_not_others():
    """Two months' rent: fine in Texas and Florida, over the cap in California
    and New York. Arithmetic, from one record, across four rulesets."""
    blocked, allowed = [], []
    for code in STATES:
        result, _ = _decisions_for(code)
        over_cap = any(f.location.endswith("security_deposit") for f in result.blocking)
        (blocked if over_cap else allowed).append(code)
    assert set(blocked) == {"US-CA", "US-NY"}, f"expected CA and NY to block, got {blocked}"
    assert set(allowed) == {"US-TX", "US-FL"}, f"expected TX and FL to allow, got {allowed}"


def test_florida_radon_is_unique_to_florida():
    """The single cleanest example of a genuinely market-specific disclosure."""
    for code in STATES:
        _, titles = _decisions_for(code)
        has_radon = any("Radon" in t for t in titles)
        assert has_radon is (code == "US-FL"), f"{code} radon expectation violated"
