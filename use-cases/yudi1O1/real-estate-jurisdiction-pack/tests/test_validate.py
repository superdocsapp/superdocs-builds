"""The blocking gate: what refuses to draft, and why.

Every blocking condition here prevents a failure that would otherwise be
*silent* — a missing disclosure, a stale rule, an unlawful deposit. None of them
produce a visibly broken document, which is exactly why they need a gate.
"""
from __future__ import annotations

from datetime import date

import pytest

from real_estate_pack.models import LeasePackRequest, Party, Property, Tenancy
from real_estate_pack.rules import load_ruleset
from real_estate_pack.validate import validate_pack

TODAY = date(2025, 9, 1)  # before every shipped review date, so nothing is stale
LATER = date(2099, 1, 1)  # after every shipped review date, so everything is


def make_request(**overrides) -> LeasePackRequest:
    facts = {
        "death_on_premises_last_3_years": False,
        "known_mold_health_threat": False,
        "in_special_flood_hazard_area": False,
        "in_area_of_potential_flooding": False,
        "demolition_permit_applied_for": False,
        "utility_meter_serves_other_areas": False,
        "in_100_year_floodplain": False,
        "flooded_in_last_5_years": False,
        "sprinkler_system_present": True,
        "storeys_in_building": 4,
    }
    facts.update(overrides.pop("disclosure_facts", {}))
    tenancy_kwargs = {
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "monthly_rent": 2000.0,
        "security_deposit": 2000.0,
    }
    tenancy_kwargs.update(overrides.pop("tenancy", {}))
    property_kwargs = {
        "street_address": "1 Test Street",
        "city": "Testville",
        "state": "CA",
        "postal_code": "00000",
        "year_built": 1970,
        "units_in_building": 10,
    }
    property_kwargs.update(overrides.pop("property", {}))
    return LeasePackRequest(
        pack_id=overrides.pop("pack_id", "TEST-1"),
        jurisdiction=overrides.pop("jurisdiction", "US-CA"),
        property=Property(**property_kwargs),
        tenancy=Tenancy(**tenancy_kwargs),
        landlord=Party(name="Test Landlord LLC", role="landlord"),
        tenants=[Party(name="Test Tenant", role="tenant")],
        disclosure_facts=facts,
    )


def validate(code="US-CA", today=TODAY, **kwargs):
    allow_stale = kwargs.pop("allow_stale", False)
    small = kwargs.pop("small_landlord_exception", False)
    req = make_request(**kwargs)
    return req, validate_pack(
        req, load_ruleset(code), today=today, allow_stale=allow_stale, small_landlord_exception=small
    )


# ------------------------------------------------- unanswered applicability


def test_a_complete_record_passes():
    _, result = validate()
    assert result.ok_to_draft, [f.message for f in result.blocking]


def test_an_unanswered_applicability_question_blocks_and_names_the_fact():
    _, result = validate(disclosure_facts={"death_on_premises_last_3_years": None})
    blocking = [f for f in result.blocking if "death_on_premises_last_3_years" in f.message]
    assert blocking, "an unanswered California disclosure question must block"
    assert "never read as 'does not apply'" in blocking[0].message


def test_the_blocked_rule_is_not_silently_included_either():
    """Undetermined means undetermined. It is neither included nor dropped."""
    _, result = validate(disclosure_facts={"known_mold_health_threat": None})
    titles = [r.title for r in result.applicable()]
    assert "Known Mold Disclosure" not in titles


def test_a_half_answered_or_condition_still_blocks():
    """California's flood rule is an OR. One 'no' does not settle it."""
    _, result = validate(disclosure_facts={"in_area_of_potential_flooding": None})
    assert any("in_area_of_potential_flooding" in f.message for f in result.blocking)


def test_an_unrelated_jurisdictions_facts_are_never_demanded():
    """Running a Texas pack must not ask for California's bed bug or mold facts."""
    _, result = validate(
        code="US-TX",
        disclosure_facts={"known_mold_health_threat": None, "death_on_premises_last_3_years": None},
    )
    assert result.ok_to_draft, [f.message for f in result.blocking]


def test_missing_year_built_blocks_the_federal_lead_disclosure_rather_than_dropping_it():
    """The headline safety case. Without a construction year the pack cannot know
    whether a federally mandated disclosure is required, so it refuses."""
    _, result = validate(code="US-TX", property={"year_built": None})
    assert not result.ok_to_draft
    assert any("year_built" in f.message and "Lead-Based Paint" in f.message for f in result.blocking)


# ------------------------------------------------------------------ staleness


def test_a_stale_rule_blocks_by_default():
    _, result = validate(code="US-TX", today=LATER)
    assert not result.ok_to_draft
    assert any("due for review by" in f.message for f in result.blocking)


def test_allow_stale_downgrades_the_block_to_a_recorded_warning():
    _, result = validate(code="US-TX", today=LATER, allow_stale=True)
    assert result.ok_to_draft
    stale_warnings = [f for f in result.warnings if "due for review by" in f.message]
    assert stale_warnings
    assert "PROCEEDING ANYWAY" in stale_warnings[0].message
    assert "UNVERIFIED" in stale_warnings[0].message


def test_a_stale_rule_that_does_not_apply_does_not_block():
    """Staleness only matters for rules that would actually be used."""
    _, result = validate(code="US-FL", today=LATER, allow_stale=False,
                         disclosure_facts={"storeys_in_building": 2})
    blocked_titles = [f.location for f in result.blocking]
    assert "rule fl_fire_sprinkler_condo_disclosure" not in blocked_titles


def test_the_stale_message_carries_the_source_url_to_re_verify_against():
    _, result = validate(code="US-CA", today=LATER)
    message = next(f.message for f in result.blocking if "due for review by" in f.message)
    assert "http" in message


# -------------------------------------------------------------- deposit limits


@pytest.mark.parametrize(
    "code,deposit,expect_blocked",
    [
        ("US-CA", 2000.0, False),   # exactly one month — at the cap
        ("US-CA", 2000.01, True),   # a cent over
        ("US-CA", 4000.0, True),    # two months
        ("US-NY", 2000.0, False),
        ("US-NY", 4000.0, True),
        ("US-TX", 4000.0, False),   # no cap in Texas
        ("US-TX", 20000.0, False),
        ("US-FL", 4000.0, False),   # no cap in Florida
    ],
)
def test_deposit_caps_are_arithmetic_and_differ_by_jurisdiction(code, deposit, expect_blocked):
    _, result = validate(code=code, tenancy={"security_deposit": deposit})
    blocked = any(f.location.endswith("security_deposit") for f in result.blocking)
    assert blocked is expect_blocked


def test_a_deposit_at_exactly_the_cap_is_not_defeated_by_float_representation():
    """0.1 + 0.2 arithmetic must not make a lawful deposit look unlawful."""
    _, result = validate(tenancy={"monthly_rent": 1234.56, "security_deposit": 1234.56})
    assert not any(f.location.endswith("security_deposit") for f in result.blocking)


def test_the_cap_message_names_the_authority_and_the_ceiling():
    _, result = validate(tenancy={"security_deposit": 5000.0})
    message = next(f.message for f in result.blocking if f.location.endswith("security_deposit"))
    assert "1950.5" in message and "2,000.00" in message


def test_small_landlord_exception_raises_the_california_ceiling_but_is_flagged():
    _, result = validate(tenancy={"security_deposit": 4000.0}, small_landlord_exception=True)
    assert not any(f.location.endswith("security_deposit") for f in result.blocking)
    warning = next(f for f in result.warnings if f.location.endswith("security_deposit"))
    assert "does not verify that the exception applies" in warning.message


def test_small_landlord_exception_does_not_exist_in_new_york():
    """New York's cap admits no exception, so asserting one must not defeat it."""
    _, result = validate(code="US-NY", tenancy={"security_deposit": 4000.0},
                         small_landlord_exception=True)
    assert any(f.location.endswith("security_deposit") for f in result.blocking)


# ------------------------------------------------------------ record integrity


def test_a_lease_with_no_tenant_is_refused():
    req = make_request()
    req.tenants = []
    result = validate_pack(req, load_ruleset("US-CA"), today=TODAY)
    assert any(f.location == "tenants" for f in result.blocking)


def test_an_end_date_before_the_start_date_is_refused():
    _, result = validate(tenancy={"start_date": "2026-12-31", "end_date": "2026-01-01"})
    assert any(f.location == "tenancy.end_date" for f in result.blocking)


def test_an_unparseable_date_is_refused_rather_than_coerced():
    _, result = validate(tenancy={"start_date": "next Tuesday"})
    assert any("not an ISO date" in f.message for f in result.blocking)


def test_a_negative_deposit_is_refused():
    _, result = validate(tenancy={"security_deposit": -100.0})
    assert any(f.location == "tenancy.security_deposit" for f in result.blocking)


def test_zero_rent_is_refused():
    _, result = validate(tenancy={"monthly_rent": 0.0})
    assert any(f.location == "tenancy.monthly_rent" for f in result.blocking)


def test_a_missing_address_is_refused():
    _, result = validate(property={"street_address": "  "})
    assert any(f.location == "property.street_address" for f in result.blocking)


def test_a_malformed_rule_condition_blocks_rather_than_being_skipped(tmp_path):
    """A typo in a jurisdiction file must never decide that a law does not apply."""
    (tmp_path / "us_zz.yaml").write_text("""
code: US-ZZ
name: Nowhere
rules:
  - id: zz_broken
    kind: disclosure
    title: Broken rule
    body: This body is long enough to be a real disclosure body for testing purposes.
    applies_when:
      all:
        - field: year_built
          op: approximately
          value: 1978
    citation:
      authority: Test Code § 1
      source_url: https://example.invalid/1
      verified_on: 2025-01-01
      review_by: 2030-01-01
""", encoding="utf-8")
    req = make_request()
    from real_estate_pack.rules import load_jurisdiction_file

    result = validate_pack(req, load_jurisdiction_file(tmp_path / "us_zz.yaml"), today=TODAY)
    assert not result.ok_to_draft
    assert any("malformed" in f.message for f in result.blocking)


def test_a_pack_with_no_disclosures_warns_but_does_not_block():
    """A jurisdiction whose disclosures all legitimately fail to apply produces
    an empty packet. Worth a second look, not worth a refusal."""
    from real_estate_pack.rules import load_jurisdiction_file

    (tmp := __import__("pathlib").Path(__file__).parent / "_empty_jurisdiction.yaml").write_text("""
code: US-ZZ
name: Nowhere
rules:
  - id: zz_never
    kind: disclosure
    title: A disclosure that never applies here
    body: This body is long enough to count as a real disclosure body for testing.
    applies_when:
      all:
        - field: year_built
          op: lt
          value: 1800
    citation:
      authority: Test Code § 1
      source_url: https://example.test/1
      verified_on: 2025-01-01
      review_by: 2030-01-01
""", encoding="utf-8")
    try:
        req = make_request(property={"year_built": 2020})
        result = validate_pack(req, load_jurisdiction_file(tmp), today=TODAY)
        assert result.ok_to_draft
        assert any(f.location == "disclosures" for f in result.warnings)
    finally:
        tmp.unlink()


# ------------------------------- mandatory notices that must be ANSWERED
# A notice required in both directions must not become optional just because
# nobody filled it in. These lock in the fix for a real bug: applicability was
# once keyed on `is_set`, so leaving the question blank silently removed the
# disclosure and the lease still looked complete.


def test_an_unanswered_mandatory_texas_flood_notice_blocks_rather_than_vanishing():
    _, result = validate(
        code="US-TX",
        disclosure_facts={"in_100_year_floodplain": None, "flooded_in_last_5_years": None},
    )
    assert not result.ok_to_draft
    message = next(f.message for f in result.blocking if "tx_flooding" in f.location)
    assert "in_100_year_floodplain" in message and "flooded_in_last_5_years" in message
    assert "A 'no' is a disclosure, not an exemption" in message


def test_the_unanswered_mandatory_notice_still_appears_in_the_required_set():
    """It is required; it is merely incomplete. It must not drop out."""
    _, result = validate(code="US-TX", disclosure_facts={"in_100_year_floodplain": None})
    assert "Flooding Disclosure" in [r.title for r in result.applicable()]


def test_an_unanswered_new_york_sprinkler_notice_blocks():
    _, result = validate(code="US-NY", disclosure_facts={"sprinkler_system_present": None})
    assert not result.ok_to_draft
    assert any("sprinkler_system_present" in f.message for f in result.blocking)


def test_answering_no_satisfies_a_both_directions_notice():
    """'No' is a complete answer. Only silence blocks."""
    _, result = validate(code="US-NY", disclosure_facts={"sprinkler_system_present": False})
    assert result.ok_to_draft, [f.message for f in result.blocking]
    assert "Sprinkler System Notice" in [r.title for r in result.applicable()]


def test_decisions_record_every_rule_evaluated_not_just_the_ones_that_fired():
    """The compliance index depends on this: a reviewer asking 'why is there no
    flood disclosure' needs a row saying it was evaluated."""
    _, result = validate()
    jurisdiction = load_ruleset("US-CA")
    assert len(result.decisions) == len(jurisdiction.rules)
    assert any(not d.applies for d in result.decisions)
