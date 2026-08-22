from src.crm import FakeCRM
from src.esign_client import FakeEsignProvider
from src.fake_client import FakeSuperDocsClient
from src.pipeline import run_pipeline, send_approved_proposal


def _well_behaved_transform(deal):
    def _transform(html):
        replacements = {
            "[CLIENT COMPANY]": deal.client_company,
            "[CLIENT CONTACT NAME]": deal.client_contact_name,
            "[CLIENT CONTACT EMAIL]": deal.client_contact_email,
            "[PRODUCT NAME]": deal.product_name,
            "[DEAL VALUE]": f"${deal.deal_value_usd:,.2f}",
            "[CONTRACT LENGTH]": str(deal.contract_length_months),
            "[PAYMENT TERMS]": deal.payment_terms,
            "[SALES REP NAME]": deal.sales_rep_name,
            "[SALES REP EMAIL]": deal.sales_rep_email,
            "[DATE]": "August 22, 2026",
        }
        for k, v in replacements.items():
            html = html.replace(k, v)
        return html
    return _transform


def test_run_pipeline_never_sends_anything_it_only_drafts():
    crm = FakeCRM()
    client = FakeSuperDocsClient()
    deal = crm.get_deal("deal-001")
    client.script_edit("Replace EVERY placeholder", _well_behaved_transform(deal))

    result = run_pipeline(client, crm, "deal-001")

    assert result.ready_for_approval is True
    assert result.unfilled_placeholders == []
    # run_pipeline has no reference to any esign provider at all -- structurally cannot send anything.


def test_rejecting_a_proposal_sends_nothing():
    crm = FakeCRM()
    client = FakeSuperDocsClient()
    deal = crm.get_deal("deal-001")
    client.script_edit("Replace EVERY placeholder", _well_behaved_transform(deal))

    result = run_pipeline(client, crm, "deal-001")
    esign = FakeEsignProvider()

    outcome = send_approved_proposal(client, esign, result.draft, deal, approved=False)

    assert outcome is None
    assert esign.sent_envelopes == [], "a rejected proposal must never reach the e-sign provider"


def test_approving_a_proposal_sends_exactly_one_envelope_with_correct_recipient():
    crm = FakeCRM()
    client = FakeSuperDocsClient()
    deal = crm.get_deal("deal-002")
    client.script_edit("Replace EVERY placeholder", _well_behaved_transform(deal))

    result = run_pipeline(client, crm, "deal-002")
    esign = FakeEsignProvider()

    outcome = send_approved_proposal(client, esign, result.draft, deal, approved=True)

    assert outcome is not None
    assert outcome.provider == "docusign-fake"
    assert len(esign.sent_envelopes) == 1
    sent = esign.sent_envelopes[0]
    assert sent["signer_email"] == deal.client_contact_email
    assert sent["signer_name"] == deal.client_contact_name
    assert deal.client_company in sent["subject"]


def test_unknown_deal_id_raises_rather_than_silently_producing_an_empty_proposal():
    crm = FakeCRM()
    client = FakeSuperDocsClient()
    try:
        run_pipeline(client, crm, "deal-does-not-exist")
        assert False, "expected a ValueError for an unknown deal id"
    except ValueError as e:
        assert "deal-does-not-exist" in str(e)
