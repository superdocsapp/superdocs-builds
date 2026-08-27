"""Rendering: statutory text is reproduced, never generated, and never injected into.

The governing rule of this module is that the model is handed finished content
and told to restyle it. These tests check the content really is finished, really
is escaped, and really carries the citations and dates that make the pack
auditable.
"""
from __future__ import annotations

import pytest
from _builders import build_pack, build_request

from real_estate_pack.assemble import INDEX, LEASE, PACKET
from real_estate_pack.render import VERBATIM_CLASS, build_instruction, esc

STATES = ["US-CA", "US-TX", "US-NY", "US-FL"]


# ------------------------------------------------------------------- escaping


@pytest.mark.parametrize(
    "hostile",
    [
        "<script>alert(1)</script>",
        "Smith & Sons <Holdings>",
        'O"Brien\'s "Quoted" Trust',
        "</div><h1>injected</h1>",
    ],
)
def test_party_names_are_escaped_before_entering_the_instruction(hostile):
    """A landlord's trading name is user-supplied text that ends up inside a
    prompt. An unescaped angle bracket is a malformed document at best and an
    embedded instruction at worst."""
    _, jurisdiction, _, doc_set = build_pack(landlord_name=hostile)
    for document in doc_set.documents:
        assert hostile not in document.content_html
        assert esc(hostile) in document.content_html or hostile.split("<")[0] in document.content_html


def test_escaping_survives_into_the_instruction_sent_to_the_api():
    req, jurisdiction, _, doc_set = build_pack(landlord_name="<script>x</script>")
    instruction = doc_set.get(LEASE).instruction(req, jurisdiction)
    assert "<script>" not in instruction


def test_esc_handles_none_without_printing_the_word_none():
    assert esc(None) == ""


# --------------------------------------------------------- statutory fidelity


def test_prescribed_text_is_reproduced_exactly():
    """Florida's radon paragraph is prescribed word-for-word by statute."""
    _, _, _, doc_set = build_pack("US-FL")
    packet = doc_set.get(PACKET).content_html
    assert (
        "Radon is a naturally occurring radioactive gas that, when it has accumulated in a building"
        in packet.replace("<br />", " ").replace("&#x27;", "'")
    )


def test_verbatim_blocks_are_marked_so_the_model_can_be_told_to_leave_them():
    _, _, _, doc_set = build_pack("US-CA")
    packet = doc_set.get(PACKET).content_html
    assert VERBATIM_CLASS in packet
    assert 'data-verbatim="true"' in packet


def test_non_prescribed_disclosures_are_not_marked_verbatim():
    """California's bed bug notice requires the substance, not one sentence.
    Over-marking would tell the model it cannot reformat something it can."""
    _, _, _, doc_set = build_pack("US-CA")
    packet = doc_set.get(PACKET).content_html
    bedbug = next(e for e in doc_set.entries if e.rule.id == "ca_bed_bug_notice")
    section = packet.split(f'id="{bedbug.entry_id}"')[1].split('<div class="disclosure"')[0]
    assert 'data-verbatim="true"' not in section


def test_line_structure_of_a_notice_survives_rendering():
    """Checkbox lines and blank fields carry meaning; collapsing them into prose
    would destroy a form."""
    _, _, _, doc_set = build_pack("US-NY")
    packet = doc_set.get(PACKET).content_html
    assert "<br />" in packet
    assert "[ ] Yes" in packet


# ------------------------------------------------------- citations and dates


@pytest.mark.parametrize("code", STATES)
def test_every_disclosure_carries_its_authority_in_the_packet(code):
    _, _, _, doc_set = build_pack(code)
    packet = doc_set.get(PACKET).content_html
    for entry in doc_set.entries:
        if entry.rule.kind != "disclosure":
            continue
        assert esc(entry.rule.citation.authority) in packet
        assert esc(entry.rule.citation.source_url) in packet


@pytest.mark.parametrize("code", STATES)
def test_the_index_carries_both_dates_for_every_rule_evaluated(code):
    """This is what makes the pack 'dated' in the sense the card asks for."""
    _, _, validation, doc_set = build_pack(code)
    index = doc_set.get(INDEX).content_html
    for decision in validation.decisions:
        assert decision.rule.citation.verified_on.isoformat() in index
        assert decision.rule.citation.review_by.isoformat() in index


# ------------------------------------------------------- the shared identity


@pytest.mark.parametrize("kind", [LEASE, PACKET, INDEX])
def test_every_document_carries_the_same_identity_block(kind):
    req, _, _, doc_set = build_pack()
    content = doc_set.get(kind).content_html
    assert esc(req.pack_id) in content
    assert esc(req.property.full_address()) in content
    assert esc(req.landlord.name) in content


def test_money_is_formatted_once_and_identically_everywhere():
    req, _, _, doc_set = build_pack(tenancy={"monthly_rent": 1234.5, "security_deposit": 1234.5})
    for document in doc_set.documents:
        assert "$1,234.50" in document.content_html


def test_recorded_answers_render_as_words_not_python_booleans():
    """'False' in a legal disclosure reads as a rendering artefact; 'No' reads as
    an answer."""
    _, _, _, doc_set = build_pack("US-TX", disclosure_facts={"flooded_in_last_5_years": False})
    packet = doc_set.get(PACKET).content_html
    assert "<td>No</td>" in packet
    assert "<td>False</td>" not in packet


def test_all_tenants_are_named_and_each_gets_a_signature_line():
    _, _, _, doc_set = build_pack(tenant_names=["Ada Lovelace", "Grace Hopper"])
    lease = doc_set.get(LEASE).content_html
    assert "Ada Lovelace" in lease and "Grace Hopper" in lease
    assert lease.count("Date: ____________") >= 3  # landlord + two tenants


# ---------------------------------------------------------------- instruction


def test_the_instruction_forbids_rewording_prescribed_text():
    req, jurisdiction, _, doc_set = build_pack("US-FL")
    instruction = doc_set.get(PACKET).instruction(req, jurisdiction)
    assert VERBATIM_CLASS in instruction
    assert "Do not reword" in instruction


def test_the_instruction_forbids_inventing_new_legal_content():
    """The failure mode that matters most: a model helpfully adding a disclosure
    nobody researched, with no citation and no date."""
    req, jurisdiction, _, doc_set = build_pack()
    instruction = doc_set.get(PACKET).instruction(req, jurisdiction)
    assert "Do not add any disclosure" in instruction
    assert "say so in your response rather than supplying it" in instruction


def test_the_instruction_tells_the_model_to_preserve_the_customers_template():
    """Regression, found by a live run rather than by reasoning.

    The first live parity run produced two documents that were TEXTUALLY
    IDENTICAL despite being drafted onto two completely different customer
    templates — neither template's masthead, strapline or footer survived. The
    branding was present in the uploaded document and was then replaced
    wholesale during the edit turn (37 changes, rather than an insert).

    Adding this rule cut it to a single change and the branding survived. Without
    the rule, "drafted onto the customer's own template" is not true."""
    req, jurisdiction, _, doc_set = build_pack()
    instruction = doc_set.get(LEASE).instruction(req, jurisdiction)
    assert "PRESERVE THE TEMPLATE" in instruction
    for element in ("letterhead", "masthead", "footer"):
        assert element in instruction
    assert "leaving every other existing element exactly where it is" in instruction


def test_the_instruction_protects_the_cross_reference_codes():
    req, jurisdiction, _, doc_set = build_pack()
    instruction = doc_set.get(LEASE).instruction(req, jurisdiction)
    assert "D-1" in instruction
    assert "cross-reference each other by those codes" in instruction


def test_the_instruction_carries_the_finished_content_not_a_description_of_it():
    req, jurisdiction, _, doc_set = build_pack("US-FL")
    instruction = doc_set.get(PACKET).instruction(req, jurisdiction)
    assert doc_set.get(PACKET).content_html in instruction


def test_build_instruction_names_the_jurisdiction_and_property():
    req, jurisdiction, _, doc_set = build_pack("US-NY")
    instruction = build_instruction("Test Doc", "<p>x</p>", req, jurisdiction)
    assert "New York" in instruction
    assert req.property.full_address() in instruction


# ------------------------------------------------------------- empty packets


def test_an_empty_packet_says_why_rather_than_being_blank():
    """A blank page is indistinguishable from a crash."""
    from datetime import date

    from real_estate_pack.assemble import assemble
    from real_estate_pack.rules import load_jurisdiction_file
    from real_estate_pack.validate import validate_pack
    import pathlib

    path = pathlib.Path(__file__).parent / "_empty_render.yaml"
    path.write_text("""
code: US-ZZ
name: Nowhere
rules: []
""", encoding="utf-8")
    try:
        req = build_request()
        jurisdiction = load_jurisdiction_file(path)
        validation = validate_pack(req, jurisdiction, today=date(2025, 9, 1))
        doc_set = assemble(req, jurisdiction, validation, today=date(2025, 9, 1))
        packet = doc_set.get(PACKET).content_html
        assert "No disclosure rule" in packet
        lease = doc_set.get(LEASE).content_html
        assert "No jurisdiction-specific disclosure was triggered" in lease
    finally:
        path.unlink()
