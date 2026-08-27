"""Shared test builders.

One place that knows how to construct a complete, valid lease record, so that a
test asserting something about rendering does not accidentally also be a test of
whether the author remembered every California fact.
"""
from __future__ import annotations

from datetime import date

from real_estate_pack.assemble import assemble
from real_estate_pack.models import LeasePackRequest, Party, Property, Tenancy
from real_estate_pack.rules import load_ruleset
from real_estate_pack.validate import validate_pack

#: Before every review date shipped, so nothing is stale unless a test wants it.
TODAY = date(2025, 9, 1)

COMPLETE_FACTS = {
    # California
    "death_on_premises_last_3_years": False,
    "known_mold_health_threat": False,
    "in_special_flood_hazard_area": False,
    "in_area_of_potential_flooding": False,
    "demolition_permit_applied_for": False,
    "utility_meter_serves_other_areas": False,
    # Texas
    "in_100_year_floodplain": False,
    "flooded_in_last_5_years": False,
    # New York
    "sprinkler_system_present": True,
    # Florida
    "storeys_in_building": 4,
}


def build_request(**overrides) -> LeasePackRequest:
    facts = dict(COMPLETE_FACTS)
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
        landlord=Party(name=overrides.pop("landlord_name", "Test Landlord LLC"), role="landlord"),
        tenants=[Party(name=n, role="tenant") for n in overrides.pop("tenant_names", ["Test Tenant"])],
        disclosure_facts=facts,
    )


def build_pack(code="US-CA", today=TODAY, allow_stale=True, **overrides):
    """Return (request, jurisdiction, validation, document_set) for one pack."""
    req = build_request(jurisdiction=code, **overrides)
    jurisdiction = load_ruleset(code)
    validation = validate_pack(req, jurisdiction, today=today, allow_stale=allow_stale)
    doc_set = assemble(req, jurisdiction, validation, today=today)
    return req, jurisdiction, validation, doc_set
