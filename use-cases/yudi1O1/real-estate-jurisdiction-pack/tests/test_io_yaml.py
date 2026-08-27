"""Loading a lease record, and refusing to load a subtly wrong one.

A permissive loader turns `year_build:` into a property with no construction
year, which then blocks with a confusing message about lead paint — or, in a
less careful engine, silently drops a federally required disclosure. Rejecting
the unknown key names the typo where it was made.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from real_estate_pack.io_yaml import InputError, load_request

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

VALID = """
pack_id: T-1
jurisdiction: us-ca
property:
  street_address: 1 Test Street
  city: Testville
  state: CA
  postal_code: "00000"
  year_built: 1970
tenancy:
  start_date: "2026-01-01"
  end_date: "2026-12-31"
  monthly_rent: 2000
  security_deposit: 2000
landlord:
  name: Test Landlord LLC
tenants:
  - name: Test Tenant
"""


def write(tmp_path, body, name="record.yaml"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_a_valid_record_loads(tmp_path):
    req = load_request(write(tmp_path, VALID))
    assert req.pack_id == "T-1"
    assert req.property.year_built == 1970
    assert req.tenancy.monthly_rent == 2000.0


def test_the_jurisdiction_code_is_normalised_to_upper_case(tmp_path):
    """`us-ca` in a hand-written file must resolve the same as `US-CA`."""
    assert load_request(write(tmp_path, VALID)).jurisdiction == "US-CA"


def test_a_tenant_may_be_written_as_a_bare_name(tmp_path):
    req = load_request(write(tmp_path, VALID.replace("  - name: Test Tenant", "  - Test Tenant")))
    assert req.tenants[0].name == "Test Tenant"
    assert req.tenants[0].role == "tenant"


@pytest.mark.parametrize(
    "typo,expected",
    [
        ("year_built", "year_build"),
        ("street_address", "street_adress"),
        ("postal_code", "postcode"),
    ],
)
def test_a_misspelled_property_key_is_named_rather_than_ignored(tmp_path, typo, expected):
    body = VALID.replace(f"  {typo}:", f"  {expected}:")
    with pytest.raises(InputError, match=expected):
        load_request(write(tmp_path, body))


def test_a_misspelled_top_level_key_is_rejected(tmp_path):
    with pytest.raises(InputError, match="tenents"):
        load_request(write(tmp_path, VALID.replace("tenants:", "tenents:")))


def test_a_misspelled_tenancy_key_is_rejected(tmp_path):
    with pytest.raises(InputError, match="monthly_rnet"):
        load_request(write(tmp_path, VALID.replace("monthly_rent:", "monthly_rnet:")))


def test_the_error_lists_the_keys_that_would_have_been_accepted(tmp_path):
    with pytest.raises(InputError, match="Allowed here"):
        load_request(write(tmp_path, VALID.replace("tenants:", "tenents:")))


def test_the_error_suggests_disclosure_facts_for_jurisdiction_answers(tmp_path):
    """The most likely reason someone adds an unexpected key."""
    with pytest.raises(InputError, match="disclosure_facts"):
        load_request(write(tmp_path, VALID + "\nsprinkler_system_present: true\n"))


@pytest.mark.parametrize("missing", ["pack_id", "jurisdiction", "landlord"])
def test_a_missing_required_top_level_key_is_named(tmp_path, missing):
    body = "\n".join(line for line in VALID.splitlines() if not line.startswith(missing))
    if missing == "landlord":
        body = body.replace("  name: Test Landlord LLC\n", "")
    with pytest.raises(InputError, match=missing):
        load_request(write(tmp_path, body))


def test_a_missing_required_property_key_is_named(tmp_path):
    body = VALID.replace('  postal_code: "00000"\n', "")
    with pytest.raises(InputError, match="postal_code"):
        load_request(write(tmp_path, body))


def test_a_missing_required_tenancy_key_is_named(tmp_path):
    body = VALID.replace("  security_deposit: 2000\n", "")
    with pytest.raises(InputError, match="security_deposit"):
        load_request(write(tmp_path, body))


def test_disclosure_facts_keys_are_open_by_design(tmp_path):
    """Their names come from the jurisdiction files, so the loader cannot know
    them. A misspelled fact is caught by the validator instead, which reports
    the fact it needed and did not get."""
    body = VALID + "\ndisclosure_facts:\n  anything_at_all: true\n"
    assert load_request(write(tmp_path, body)).disclosure_facts["anything_at_all"] is True


def test_disclosure_facts_must_be_a_mapping(tmp_path):
    body = VALID + "\ndisclosure_facts:\n  - not\n  - a mapping\n"
    with pytest.raises(InputError, match="must be a mapping"):
        load_request(write(tmp_path, body))


def test_a_null_fact_reads_as_unanswered_not_as_false(tmp_path):
    from real_estate_pack.models import UNSET

    body = VALID + "\ndisclosure_facts:\n  known_mold_health_threat: null\n"
    req = load_request(write(tmp_path, body))
    assert req.lookup_fact("known_mold_health_threat") is UNSET


def test_malformed_yaml_names_the_file(tmp_path):
    with pytest.raises(InputError, match="not valid YAML"):
        load_request(write(tmp_path, "pack_id: [unclosed\n"))


def test_a_missing_file_is_reported_clearly(tmp_path):
    with pytest.raises(InputError, match="No input file"):
        load_request(tmp_path / "does_not_exist.yaml")


def test_a_non_mapping_document_is_rejected(tmp_path):
    with pytest.raises(InputError, match="top level must be a mapping"):
        load_request(write(tmp_path, "- just\n- a list\n"))


def test_non_numeric_money_is_rejected_rather_than_coerced(tmp_path):
    with pytest.raises(InputError, match="could not build the record"):
        load_request(write(tmp_path, VALID.replace("monthly_rent: 2000", "monthly_rent: about two thousand")))


# --------------------------------------------------------- the shipped examples


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.yaml")), ids=lambda p: p.name)
def test_every_shipped_example_loads(path):
    req = load_request(path)
    assert req.pack_id
    assert req.tenants, f"{path.name} has no tenant"


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.yaml")), ids=lambda p: p.name)
def test_every_shipped_example_uses_a_real_jurisdiction(path):
    from real_estate_pack.rules import load_ruleset

    load_ruleset(load_request(path).jurisdiction)
