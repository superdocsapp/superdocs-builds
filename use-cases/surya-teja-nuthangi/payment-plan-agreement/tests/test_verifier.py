import pytest

from payment_plan_agreement.engine import PaymentPlanService
from payment_plan_agreement.render import render_seed_html
from payment_plan_agreement.verifier import AgreementVerifier


def _codes(report): return {x.code for x in report.findings}


def test_clean_seed_runs_all_checks(request_factory):
    plan = PaymentPlanService().calculate(request_factory()); report = AgreementVerifier().verify(plan, render_seed_html(plan))
    assert report.status == "pass"
    assert len(report.checks_run) == 20


@pytest.mark.parametrize(("mutator", "code"), [
    (lambda h: h.replace("$225.00", "$250.00", 1), "V003"),
    (lambda h: h.replace("monthly installments", "weekly installments"), "V009"),
    (lambda h: h.replace('<tr data-installment="4"><td>4</td><td>2026-12-15</td><td>$225.00</td><td>$0.00</td></tr>', ""), "V001"),
    (lambda h: h.replace("Example Health Services", "Wrong Creditor", 1), "V015"),
    (lambda h: h.replace("No late fee applies.", "A processing fee of $25.00 applies."), "V017"),
    (lambda h: h.replace("INV-100", ""), "V016"),
    (lambda h: h.replace('data-agreement-section="payment-schedule"', 'data-agreement-section="removed"'), "V020"),
])
def test_adversarial_corruptions_are_blocked(request_factory, mutator, code):
    plan = PaymentPlanService().calculate(request_factory()); report = AgreementVerifier().verify(plan, mutator(render_seed_html(plan)))
    assert report.status == "blocked" and code in _codes(report)


def test_unequal_installments_cannot_be_called_equal(request_factory):
    plan = PaymentPlanService().calculate(request_factory(original_balance="100.00", upfront_payment=0, installment_count=3))
    html = render_seed_html(plan).replace("3 monthly installments totaling", "3 equal monthly installments totaling")
    assert "V012" in _codes(AgreementVerifier().verify(plan, html))


def test_parse_failure_is_not_no_findings(request_factory):
    plan = PaymentPlanService().calculate(request_factory())
    report = AgreementVerifier().verify(plan, "<p>not an agreement</p>")
    assert report.status == "blocked" and "SCHEDULE_TABLE_NOT_FOUND" in _codes(report)
