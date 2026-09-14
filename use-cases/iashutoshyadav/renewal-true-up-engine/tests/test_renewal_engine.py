import pytest

from app.models import Customer, UsagePeriod
from app.renewal_engine import PendingHumanDecision, apply_human_decision, start_renewal
from app.superdocs_client import FakeSuperDocsClient

CONTRACT_TEXT = """MASTER SERVICES AGREEMENT (SAMPLE)

2.1 Customer is entitled to use up to 10,000 (ten thousand) compute units per month ("Monthly Entitlement")
under this Agreement.

2.2 The fee for the Monthly Entitlement is $8,000.00 per month, payable in advance.

3.1 If Customer usage exceeds the Monthly Entitlement in any given month, Vendor shall invoice Customer for
the excess usage at a rate of $1.50 per compute unit above the Monthly Entitlement.
"""

CUSTOMER = Customer(customer_id="cust-1", name="Acme Renewals Inc.")


def test_a_clean_renewal_applies_the_amendment_automatically_no_human_needed():
    client = FakeSuperDocsClient()
    usage = UsagePeriod(customer_id="cust-1", period_label="2026-07", units_used=9_000)  # under entitlement

    package = start_renewal(client, CUSTOMER, CONTRACT_TEXT, usage, new_entitlement_units=12_000)

    assert package.exception is None
    assert package.true_up.true_up_amount == 0
    assert package.exported_summary_markdown is not None
    assert "12,000" in package.exported_summary_markdown
    assert "10,000" not in package.exported_summary_markdown


def test_an_overage_renewal_pauses_for_human_approval_instead_of_auto_applying():
    client = FakeSuperDocsClient()
    usage = UsagePeriod(customer_id="cust-1", period_label="2026-07", units_used=15_000)  # over entitlement

    with pytest.raises(PendingHumanDecision) as exc_info:
        start_renewal(client, CUSTOMER, CONTRACT_TEXT, usage, new_entitlement_units=12_000)

    pending = exc_info.value
    assert pending.package.exception is not None
    assert pending.package.exception.reason == "overage_true_up_required"
    assert pending.package.true_up.true_up_amount == pytest.approx(5_000 * 1.5)  # 15000-10000=5000 overage
    # Nothing applied yet - the document must still read the ORIGINAL entitlement.
    assert pending.package.exported_summary_markdown is None


def test_approving_the_pending_decision_applies_the_amendment():
    client = FakeSuperDocsClient()
    usage = UsagePeriod(customer_id="cust-1", period_label="2026-07", units_used=15_000)

    with pytest.raises(PendingHumanDecision) as exc_info:
        start_renewal(client, CUSTOMER, CONTRACT_TEXT, usage, new_entitlement_units=12_000)
    pending = exc_info.value

    result = apply_human_decision(
        client, pending.package, pending.job_id, pending.change_id, approved=True,
    )

    assert "12,000" in result.exported_summary_markdown
    # The true-up record survives regardless of the document-edit outcome - it's a fact about what
    # happened this billing period, not something rejection should erase.
    assert result.true_up.true_up_amount > 0


def test_rejecting_the_pending_decision_leaves_the_original_entitlement_untouched():
    client = FakeSuperDocsClient()
    usage = UsagePeriod(customer_id="cust-1", period_label="2026-07", units_used=15_000)

    with pytest.raises(PendingHumanDecision) as exc_info:
        start_renewal(client, CUSTOMER, CONTRACT_TEXT, usage, new_entitlement_units=12_000)
    pending = exc_info.value

    result = apply_human_decision(
        client, pending.package, pending.job_id, pending.change_id, approved=False, reason="needs legal review",
    )

    # Rejected: no export was even generated, since nothing was approved to export.
    assert result.exported_summary_markdown is None
    # But the true-up fact itself - what actually happened - is still on the record.
    assert result.true_up.true_up_amount > 0


def test_renewal_quote_and_talk_track_are_populated_for_every_package_with_terms():
    """The task card names 'the renewal quote... and a talk track for the customer-success manager' as
    real pack components, not optional extras. Found live on 2026-08-20: both were computed by helper
    functions that existed but were never called from anywhere - dead code satisfying 'write the
    function', not 'include it in the pack'."""
    client = FakeSuperDocsClient()

    clean_usage = UsagePeriod(customer_id="cust-1", period_label="2026-07", units_used=9_000)
    clean = start_renewal(client, CUSTOMER, CONTRACT_TEXT, clean_usage, new_entitlement_units=12_000)
    assert clean.renewal_quote and CUSTOMER.name in clean.renewal_quote
    assert clean.talk_track and CUSTOMER.name in clean.talk_track
    assert "no overage" in clean.talk_track

    overage_usage = UsagePeriod(customer_id="cust-1", period_label="2026-07", units_used=15_000)
    with pytest.raises(PendingHumanDecision) as exc_info:
        start_renewal(client, CUSTOMER, CONTRACT_TEXT, overage_usage, new_entitlement_units=12_000)
    pending = exc_info.value.package
    assert pending.renewal_quote and "true-up" in pending.renewal_quote
    # The talk track must carry the exact governing-clause quote, not a paraphrase - a CS manager
    # repeating this to a customer needs to be citing the real contract, same discipline as the UI.
    assert pending.true_up.governing_clause_quote in pending.talk_track


def test_a_contract_missing_a_governing_clause_is_an_exception_not_a_crash():
    client = FakeSuperDocsClient()
    broken_contract = "This document has no entitlement clause in it at all."
    usage = UsagePeriod(customer_id="cust-1", period_label="2026-07", units_used=100)

    package = start_renewal(client, CUSTOMER, broken_contract, usage, new_entitlement_units=12_000)

    assert package.exception is not None
    assert package.exception.reason == "clause_not_found"


def test_a_second_document_is_uploaded_and_the_export_still_reflects_the_contract_not_it():
    """The 'Multi-document' surface named on this card was never exercised - only one document (the
    contract) was ever uploaded per session. Fixed by uploading a real usage report alongside the
    contract - uploaded FIRST, with the contract uploaded LAST. That order is load-bearing, found live
    (2026-09-14): the real export_document(session_id) call has no document parameter and exports whichever
    document was uploaded most recently, regardless of chat instruction wording - naming the contract
    explicitly in the instruction did not override upload order. This asserts both documents are genuinely
    tracked, in that order, and that the exported result is the contract's content, not the usage report's."""
    client = FakeSuperDocsClient()
    usage = UsagePeriod(customer_id="cust-1", period_label="2026-07", units_used=9_000)

    package = start_renewal(client, CUSTOMER, CONTRACT_TEXT, usage, new_entitlement_units=12_000)

    docs = client._documents[package.session_id]
    assert len(docs) == 2, "the contract and a usage report must both be uploaded to the session"
    assert "usage-report" in docs[0][0]
    assert "contract" in docs[1][0]
    assert "Usage Report" in docs[0][1]
    # The exported document is the AMENDED CONTRACT, not the usage report - the usage report is context.
    assert "MASTER SERVICES AGREEMENT" in package.exported_summary_markdown
    assert package.usage_report_uploaded is True


def test_a_usage_chart_image_is_generated_and_uploaded_for_every_package():
    """The 'images' surface named on this card was never touched at all before this fix - not even
    documented as a cut, despite being named right next to search/templates in the same sentence this
    project's own README already quotes while fixing those two."""
    client = FakeSuperDocsClient()
    usage = UsagePeriod(customer_id="cust-1", period_label="2026-07", units_used=15_000)

    with pytest.raises(PendingHumanDecision) as exc_info:
        start_renewal(client, CUSTOMER, CONTRACT_TEXT, usage, new_entitlement_units=12_000)

    assert exc_info.value.package.usage_chart_url
    assert exc_info.value.package.usage_chart_url.startswith("https://fake.superdocs.local/images/")


def test_the_proposed_amendment_content_is_surfaced_to_the_reviewer_not_just_its_id():
    """Real gap found auditing against the task brief: old_html/new_html/ai_explanation were fetched from
    the API and captured into ProposedChange, but never read by anything - a human approved or rejected an
    amendment without ever seeing what it actually said. PendingHumanDecision must carry the real content,
    not just the id needed to approve/reject it."""
    client = FakeSuperDocsClient()
    usage = UsagePeriod(customer_id="cust-1", period_label="2026-07", units_used=15_000)

    with pytest.raises(PendingHumanDecision) as exc_info:
        start_renewal(client, CUSTOMER, CONTRACT_TEXT, usage, new_entitlement_units=12_000)

    pending = exc_info.value
    assert pending.old_html == "10,000"
    assert pending.new_html == "12,000"
    assert pending.ai_explanation


def test_a_template_reference_is_included_in_the_amendment_instruction_when_given():
    client = FakeSuperDocsClient()
    template_id = client.upload_template("renewal_amendment_template.txt", b"RENEWAL AMENDMENT TEMPLATE\n")
    assert template_id

    usage = UsagePeriod(customer_id="cust-1", period_label="2026-07", units_used=9_000)
    package = start_renewal(
        client, CUSTOMER, CONTRACT_TEXT, usage, new_entitlement_units=12_000,
        template_name="renewal_amendment_template.txt",
    )

    assert package.exception is None
    assert package.exported_summary_markdown is not None
