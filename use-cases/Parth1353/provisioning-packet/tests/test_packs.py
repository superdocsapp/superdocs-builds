"""The three claims the assignment card makes, tested.

    "internal and customer packs differ only in what should be hidden"
    "a date change updates every document that carries it"
    "the diagram reflects the ordered configuration"

Everything else in this file supports one of those three.
"""

from __future__ import annotations

import re

import pytest

from packet.diagram import as_designed_diagram, diagram_signature
from packet.order import INTERNAL_PATHS, REDACTION, OrderError
from packet.propagate import diff_orders, instruction_for, plan
from packet.templates import (
    BY_SLUG,
    DOCUMENTS,
    audit_audience,
    documents_carrying,
    render,
    unknown_fields,
)

# ===========================================================================
# "differ only in what should be hidden"
# ===========================================================================


def test_no_internal_field_can_reach_a_customer_render():
    assert audit_audience() == []
    assert unknown_fields() == []


def test_every_internal_value_is_absent_from_every_customer_document(order):
    """The claim checked against the actual rendered text, value by value."""
    secrets = {
        p: str(order.raw(p)) for p in INTERNAL_PATHS if order.raw(p) not in (None, "")
    }
    assert secrets, "the fixture order has no internal values, so this proves nothing"

    for spec in DOCUMENTS:
        text = render(spec, order, audience="customer")
        for path, value in secrets.items():
            if len(value) < 6:
                continue
            assert value not in text, f"{spec.slug} leaks {path}"
        assert "INTERNAL — NOT FOR CUSTOMER RELEASE" not in text


def test_the_internal_pack_does_contain_them(order):
    """Otherwise the previous test would pass on an empty document."""
    sow = render(BY_SLUG["03-installation-scope-of-work"], order, audience="internal")
    assert str(order.raw("internal.wholesale_circuit_ref")) in sow
    assert "INTERNAL — NOT FOR CUSTOMER RELEASE" in sow


def test_the_packs_are_otherwise_the_same(order):
    """Strip the internal blocks from the internal render and the two match.

    This is the exact wording of the card — *differ only in what should be
    hidden* — expressed as an assertion rather than a hope.
    """
    for spec in DOCUMENTS:
        internal = render(spec, order, audience="internal")
        customer = render(spec, order, audience="customer")

        for path in sorted(spec.customer_fields):
            value = order.value(path, audience="customer")
            if value in ("—", "") or len(value) < 4:
                continue
            assert (value in internal) == (value in customer), (
                f"{spec.slug}: {path} renders differently between the packs"
            )


def test_an_internal_field_outside_a_block_fails_safe(order):
    """A template author who forgets the block wrapper must leak nothing.

    The audience check lives in Order.value, not in the template, so the worst
    case is a visible redaction rather than a disclosed figure.
    """
    assert order.value("internal.gross_margin_pct", audience="customer") == REDACTION
    assert order.value("internal.gross_margin_pct", audience="internal") == "50.5%"


def test_an_undeclared_placeholder_is_a_loud_failure(order):
    from packet.templates import DocumentSpec

    rogue = DocumentSpec("x", "X", "both", "p", "<p>{{service.warp_factor}}</p>")
    with pytest.raises(OrderError, match="not a declared field"):
        render(rogue, order, audience="customer")


# ===========================================================================
# "a date change updates every document that carries it"
# ===========================================================================


def test_a_date_change_reaches_every_document_that_carries_the_date():
    carriers = documents_carrying("delivery.rfs_date")
    assert len(carriers) == 6, [d.slug for d in carriers]


def test_a_bandwidth_change_reaches_five_and_not_the_readiness_checklist():
    """Precision cuts both ways: the claim is only worth something if some
    documents are correctly left out."""
    carriers = {d.slug for d in documents_carrying("service.bandwidth_mbps")}
    assert len(carriers) == 5
    assert "04-customer-readiness-checklist" not in carriers


def test_a_margin_change_reaches_the_internal_pack_only():
    assert documents_carrying("internal.gross_margin_pct", audience="customer") == []
    assert documents_carrying("internal.gross_margin_pct", audience="internal")


def test_the_plan_names_exactly_the_documents_that_carry_the_field(order, client, tmp_path):
    from packet.build import Workspace, build_all

    packs = build_all(client, order, workspace=Workspace(tmp_path))
    after = order.copy()
    after.set("delivery.rfs_date", "2026-04-30")

    changes = diff_orders(order, after)
    assert [c.path for c in changes] == ["delivery.rfs_date"]

    planned, untouched = plan(changes, packs, before=order, after=after)
    assert len(planned) == 12, "six documents in each of two packs carry the date"
    assert untouched == []


def test_a_charge_change_leaves_most_of_the_pack_alone(order, client, tmp_path):
    from packet.build import Workspace, build_all

    packs = build_all(client, order, workspace=Workspace(tmp_path))
    after = order.copy()
    after.set("commercial.mrc", 18400.00)

    planned, untouched = plan(diff_orders(order, after), packs, before=order, after=after)
    edited = {e.slug for e in planned}
    assert edited == {
        "01-service-order-form",
        "05-acceptance-test-plan",
        "06-handover-certificate",
    }
    assert len(untouched) == 6, untouched


def test_the_instruction_names_the_old_and_new_value_and_forbids_anything_else(order):
    after = order.copy()
    after.set("delivery.rfs_date", "2026-04-30")
    changes = diff_orders(order, after)

    text = instruction_for(changes, regenerate_diagram=False, after=after)
    assert "16 February 2026" in text
    assert "30 April 2026" in text
    assert "Make only these changes" in text
    assert "Do not reword anything else" in text
    # A vague instruction is the documented cause of over-wide edits.
    assert "update the dates" not in text.lower()


def test_a_formatting_only_difference_is_not_a_change(order):
    """4200 and 4200.0 are the same monthly charge and must not trigger six
    edits that change nothing."""
    after = order.copy()
    after.set("commercial.mrc", 4200.0)
    assert diff_orders(order, after) == []


def test_setting_an_undeclared_field_is_refused(order):
    with pytest.raises(OrderError, match="not a declared field"):
        order.set("delivery.rfs_dat", "2026-04-30")


# ===========================================================================
# "the diagram reflects the ordered configuration"
# ===========================================================================


def test_the_diagram_shows_the_ordered_bandwidth(order):
    assert "1 Gbps" in as_designed_diagram(order)
    faster = order.copy()
    faster.set("service.bandwidth_mbps", 10000)
    diagram = as_designed_diagram(faster)
    assert "10 Gbps" in diagram
    assert "1 Gbps" not in diagram


def test_a_single_path_order_produces_a_single_path_diagram(order):
    diagram = as_designed_diagram(order)
    assert "%% design:diversity=single" in diagram
    assert "single path" in diagram
    assert "Route C" not in diagram


def test_a_diverse_order_produces_a_protected_diagram(order):
    diverse = order.copy()
    diverse.set("service.diversity", "dual")
    diverse.set("service.protection", "1+1 path protection")
    diagram = as_designed_diagram(diverse)
    assert "%% design:diversity=dual" in diagram
    assert "Route C" in diagram
    assert "stroke-dasharray" in diagram


def test_the_diagram_declares_its_own_configuration(order):
    """A caption reading "no protection" contains the substring "protect".
    The declaration exists so a checker never has to guess from prose."""
    single = as_designed_diagram(order)
    assert "%% design:diversity=single" in single
    assert "protect" in single.lower(), "the prose really does contain the trap word"

    diverse = order.copy()
    diverse.set("service.diversity", "dual")
    assert "%% design:diversity=dual" in as_designed_diagram(diverse)


def test_the_diagram_is_regenerated_only_when_the_configuration_moves(order):
    same = order.copy()
    same.set("commercial.mrc", 9999.00)
    assert diagram_signature(order) == diagram_signature(same), (
        "a price change must not redraw the network diagram"
    )

    different = order.copy()
    different.set("service.diversity", "dual")
    assert diagram_signature(order) != diagram_signature(different)


def test_a_bandwidth_change_asks_for_the_diagram_to_be_redrawn(order, client, tmp_path):
    from packet.build import Workspace, build_all

    packs = build_all(client, order, workspace=Workspace(tmp_path))
    after = order.copy()
    after.set("service.bandwidth_mbps", 10000)

    planned, _ = plan(diff_orders(order, after), packs, before=order, after=after)
    sow = [e for e in planned if e.slug == "03-installation-scope-of-work"]
    assert sow and all(e.regenerate_diagram for e in sow)
    assert "mermaid" in sow[0].instruction
    assert "10 Gbps" in sow[0].instruction

    others = [e for e in planned if e.slug != "03-installation-scope-of-work"]
    assert others and not any(e.regenerate_diagram for e in others)


def test_diagram_labels_survive_a_hostile_site_name(order):
    """Node labels live inside quotes; a quote or an angle bracket in a site
    name would otherwise break the Mermaid parse and lose the whole diagram."""
    awkward = order.copy()
    awkward.set("sites.a.label", 'Acme "North" <Works> & Co')
    diagram = as_designed_diagram(awkward)
    body = diagram.split("<pre")[1]
    assert '"Acme ' in body
    assert "<Works>" not in body
    assert re.search(r"flowchart LR", body)


def test_a_field_name_containing_a_digit_renders(order):
    """Regression. `escalation_l1` did not match the field pattern and rendered
    as literal braces inside an internal contract document — silently, because
    nothing looked for leftovers."""
    from packet.templates import BY_SLUG

    text = render(BY_SLUG["03-installation-scope-of-work"], order, audience="internal")
    assert "{{" not in text
    assert str(order.raw("internal.escalation_l1")) in text


def test_an_unsubstituted_placeholder_is_a_hard_failure(order):
    """The backstop for the whole class, not just the one that bit."""
    from packet.templates import DocumentSpec

    malformed = DocumentSpec("x", "X", "both", "p", "<p>{{ service.product }}</p>")
    with pytest.raises(OrderError, match="unsubstituted placeholders"):
        render(malformed, order, audience="internal")


def test_no_rendered_document_in_either_pack_contains_braces(order):
    for spec in DOCUMENTS:
        for audience in ("internal", "customer"):
            assert "{{" not in render(spec, order, audience=audience)


def test_two_fields_sharing_an_old_value_are_disambiguated_by_label(order):
    """Regression from the live run, and the most damaging bug found there.

    On an unprotected circuit, route diversity and protection scheme both read
    "None — single path". Instructing a model to replace that one string with
    two different values is a contradiction, and the live run showed it
    resolving the contradiction differently in different documents — leaving
    the internal and customer packs disagreeing about a contract term.
    """
    after = order.copy()
    after.set("service.diversity", "dual")
    after.set("service.protection", "1+1 path protection")
    changes = diff_orders(order, after)

    colliding = [c for c in changes if c.before_text == "None — single path"]
    assert len(colliding) == 2, "the fixture must actually contain the collision"

    text = instruction_for(changes, regenerate_diagram=False, after=after)

    # Neither item may be phrased as a bare find-and-replace on the shared text.
    assert 'Wherever the document says "None — single path"' not in text
    # Both must name their own labelled row, and warn about the other.
    assert 'labelled "Route diversity"' in text
    assert 'labelled "Protection scheme"' in text
    assert "handled\nseparately below" in text or "handled separately below" in text


def test_a_unique_old_value_still_uses_find_and_replace(order):
    """The disambiguation must not fire when there is nothing to disambiguate —
    a fix that buys correctness by degrading the common case is not a fix."""
    after = order.copy()
    after.set("delivery.rfs_date", "2026-04-30")
    text = instruction_for(diff_orders(order, after), regenerate_diagram=False, after=after)
    assert 'Wherever the document says "16 February 2026"' in text
    assert "labelled" not in text


def test_the_diagram_instruction_uses_an_atomic_section_rewrite(order):
    """Measured live: "replace the diagram" let the model tweak the block in
    place — bandwidth updated, topology left single-path. The agent playbook
    says a section rewrite is atomic, so the instruction asks for that."""
    after = order.copy()
    after.set("service.bandwidth_mbps", 10000)
    text = instruction_for(
        diff_orders(order, after), regenerate_diagram=True, after=after,
        slug="03-installation-scope-of-work",
    )
    assert 'Rewrite the section headed "1. As-designed configuration"' in text
    assert "do not edit the old diagram in\nplace" in text or "do not edit the old diagram in place" in text
    assert "%% design:bandwidth=10 Gbps" in text
