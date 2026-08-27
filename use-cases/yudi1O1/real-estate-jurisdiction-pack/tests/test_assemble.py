"""Multi-document assembly and cross-document consistency.

The interesting part of multi-document work is not producing three files, it is
producing three that agree. Most of these tests deliberately BREAK a rendered
document and assert the consistency checker notices — a checker that only ever
sees correct input has not been tested.
"""
from __future__ import annotations

import pytest
from _builders import TODAY, build_pack, build_request

from real_estate_pack.assemble import (
    DOCUMENT_ORDER,
    INDEX,
    LEASE,
    PACKET,
    assemble,
    check_consistency,
)
from real_estate_pack.entries import number_entries
from real_estate_pack.rules import load_ruleset
from real_estate_pack.validate import validate_pack

STATES = ["US-CA", "US-TX", "US-NY", "US-FL"]


# ------------------------------------------------------------------ numbering


def test_disclosures_and_clauses_are_numbered_in_separate_sequences():
    _, _, _, doc_set = build_pack()
    assert doc_set.disclosure_ids() == [f"D-{i}" for i in range(1, len(doc_set.disclosure_ids()) + 1)]
    assert doc_set.clause_ids() == [f"L-{i}" for i in range(1, len(doc_set.clause_ids()) + 1)]


def test_limit_rules_produce_no_entry_because_a_cap_is_not_a_document():
    jurisdiction = load_ruleset("US-CA")
    entries = number_entries(jurisdiction.rules)
    assert not any(e.rule.kind == "limit" for e in entries)


def test_numbering_is_stable_across_identical_runs():
    """A coordinator regenerating a pack must not see the references move."""
    first = build_pack()[3]
    second = build_pack()[3]
    assert [e.entry_id for e in first.entries] == [e.entry_id for e in second.entries]
    assert [e.rule.id for e in first.entries] == [e.rule.id for e in second.entries]


def test_federal_disclosures_are_numbered_before_state_ones():
    _, _, _, doc_set = build_pack("US-CA")
    first = doc_set.entries[0]
    assert first.rule.jurisdiction_code == "US-FED"
    assert first.entry_id == "D-1"


# ------------------------------------------------------------- the three docs


def test_a_pack_always_contains_exactly_the_three_documents():
    _, _, _, doc_set = build_pack()
    assert [d.kind for d in doc_set.documents] == list(DOCUMENT_ORDER)


@pytest.mark.parametrize("code", STATES)
def test_every_shipped_jurisdiction_assembles_consistently(code):
    """The consistency guarantee holds for all four, not just the one developed
    against."""
    _, _, _, doc_set = build_pack(code)
    assert check_consistency(doc_set) == []


def test_get_names_the_available_kinds_when_asked_for_a_missing_one():
    _, _, _, doc_set = build_pack()
    with pytest.raises(KeyError, match="compliance_index"):
        doc_set.get("nonexistent")


# --------------------------------------------- the checker actually catches things


def test_a_disclosure_dropped_from_the_packet_is_caught():
    _, _, _, doc_set = build_pack()
    packet = doc_set.get(PACKET)
    dropped = doc_set.disclosure_ids()[0]
    packet.content_html = packet.content_html.replace(f'id="{dropped}"', 'id="X"').replace(
        f">{dropped}.", ">X."
    )
    problems = check_consistency(doc_set)
    assert any(dropped in p and "missing" in p for p in problems)


def test_a_lease_schedule_that_disagrees_with_the_packet_is_caught():
    _, _, _, doc_set = build_pack()
    lease = doc_set.get(LEASE)
    missing = doc_set.disclosure_ids()[-1]
    lease.content_html = lease.content_html.replace(f"<strong>{missing}</strong>", "<strong>D-99</strong>")
    problems = check_consistency(doc_set)
    assert any("attachment schedule disagrees" in p for p in problems)


def test_an_index_that_omits_an_item_is_caught():
    _, _, _, doc_set = build_pack()
    index = doc_set.get(INDEX)
    omitted = doc_set.disclosure_ids()[0]
    index.content_html = index.content_html.replace(f"<td>{omitted}</td>", "<td>—</td>")
    problems = check_consistency(doc_set)
    assert any("does not account for" in p and omitted in p for p in problems)


def test_a_document_carrying_the_wrong_property_address_is_caught():
    """The failure that makes a pack look complete while belonging to two
    different properties."""
    _, _, _, doc_set = build_pack()
    packet = doc_set.get(PACKET)
    packet.content_html = packet.content_html.replace("1 Test Street", "2 Other Street")
    problems = check_consistency(doc_set)
    assert any("property address" in p and PACKET in p for p in problems)


def test_a_document_carrying_the_wrong_pack_reference_is_caught():
    _, _, _, doc_set = build_pack()
    index = doc_set.get(INDEX)
    index.content_html = index.content_html.replace("TEST-1", "TEST-2")
    problems = check_consistency(doc_set)
    assert any("pack reference" in p for p in problems)


def test_mangled_statutory_text_is_caught():
    """The defect this whole build is most afraid of: a prescribed notice that
    has been reworded and still reads perfectly well."""
    _, _, _, doc_set = build_pack("US-FL")
    packet = doc_set.get(PACKET)
    assert "RADON GAS: Radon is a naturally occurring radioactive gas" in packet.content_html
    packet.content_html = packet.content_html.replace(
        "RADON GAS: Radon is a naturally occurring radioactive gas",
        "RADON GAS: Radon is a natural radioactive gas",
    )
    problems = check_consistency(doc_set)
    assert any("statutorily prescribed" in p for p in problems)


def test_statutory_text_containing_an_apostrophe_does_not_trip_a_false_mismatch(tmp_path):
    """Regression. Rendering escapes `'` to `&#x27;`, so before the checker
    unescaped entities, any prescribed passage containing "Tenant's" compared
    unequal to itself and correct output was reported as mangled. A checker that
    cries wolf gets switched off, which is as bad as one that misses a fault."""
    (tmp_path / "us_zz.yaml").write_text("""
code: US-ZZ
name: Nowhere
rules:
  - id: zz_apostrophe
    kind: disclosure
    title: A prescribed notice with punctuation
    verbatim_statutory: true
    body: |
      LANDLORD'S NOTICE: Tenant's rights & obligations under this "agreement"
      are described below, and <this> text must survive rendering intact.
    citation:
      authority: Test Code § 1
      source_url: https://example.test/1
      verified_on: 2025-01-01
      review_by: 2030-01-01
""", encoding="utf-8")
    from real_estate_pack.rules import load_jurisdiction_file

    req = build_request()
    jurisdiction = load_jurisdiction_file(tmp_path / "us_zz.yaml")
    validation = validate_pack(req, jurisdiction, today=TODAY)
    doc_set = assemble(req, jurisdiction, validation, today=TODAY)
    assert check_consistency(doc_set) == []


def test_a_preamble_is_rendered_but_not_marked_untouchable():
    """Florida's deposit notice prescribes two paragraphs word-for-word and
    surrounds them with ordinary blanks. Only the prescribed half may claim to
    be verbatim."""
    _, _, _, doc_set = build_pack("US-FL")
    packet = doc_set.get(PACKET).content_html
    assert "Name of depository" in packet, "the preamble must still be rendered"

    entry = next(e for e in doc_set.entries if e.rule.id == "fl_security_deposit_disclosure")
    section = packet.split(f'id="{entry.entry_id}"')[1].split('<div class="disclosure"')[0]
    verbatim_block = section.split('data-verbatim="true"')[1].split("</div>")[0]

    assert "YOUR LEASE REQUIRES PAYMENT" in verbatim_block, "the prescribed text must be marked verbatim"
    assert "Name of depository" not in verbatim_block, "the fill-in blanks must NOT claim to be statutory"
    assert "Name of depository" in section, "but they must still appear in the notice"


def test_a_stray_reference_in_the_packet_is_caught():
    _, _, _, doc_set = build_pack()
    packet = doc_set.get(PACKET)
    packet.content_html += "<p>See also D-99.</p>"
    problems = check_consistency(doc_set)
    assert any("D-99" in p for p in problems)


# ------------------------------------------------------------------- staleness


def test_stale_entries_are_flagged_on_the_entry_itself():
    from datetime import date

    _, _, _, doc_set = build_pack("US-CA", today=date(2099, 1, 1), allow_stale=True)
    assert any(e.stale for e in doc_set.entries)


def test_nothing_is_flagged_stale_when_everything_is_current():
    _, _, _, doc_set = build_pack("US-CA", today=TODAY)
    assert not any(e.stale for e in doc_set.entries)


def test_a_rule_that_does_not_apply_is_never_marked_stale():
    from datetime import date

    req = build_request(jurisdiction="US-FL", disclosure_facts={"storeys_in_building": 2})
    jurisdiction = load_ruleset("US-FL")
    validation = validate_pack(req, jurisdiction, today=date(2099, 1, 1), allow_stale=True)
    doc_set = assemble(req, jurisdiction, validation, today=date(2099, 1, 1))
    assert not any(e.rule.id == "fl_fire_sprinkler_condo_disclosure" for e in doc_set.entries)


# -------------------------------------------------------------- empty packs


def test_a_pack_with_no_disclosures_still_produces_three_coherent_documents():
    req = build_request(jurisdiction="US-TX", property={"year_built": 2020, "units_in_building": 1})
    jurisdiction = load_ruleset("US-TX")
    validation = validate_pack(req, jurisdiction, today=TODAY)
    doc_set = assemble(req, jurisdiction, validation, today=TODAY)
    assert len(doc_set.documents) == 3
    assert check_consistency(doc_set) == []


def test_the_index_lists_rules_that_did_not_apply():
    """A reviewer asking 'why is there no flood disclosure' needs an answer."""
    _, _, _, doc_set = build_pack("US-CA")
    index = doc_set.get(INDEX).content_html
    assert "Evaluated — does not apply" in index
    assert "Death on the Premises" in index
