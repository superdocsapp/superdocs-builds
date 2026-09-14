from app.batch import CohortItem, run_cohort_batch
from app.models import Customer, UsagePeriod
from app.superdocs_client import FakeSuperDocsClient

CONTRACT_TEXT = """MASTER SERVICES AGREEMENT (SAMPLE)

2.1 Customer is entitled to use up to 10,000 (ten thousand) compute units per month ("Monthly Entitlement")
under this Agreement.

2.2 The fee for the Monthly Entitlement is $8,000.00 per month, payable in advance.

3.1 If Customer usage exceeds the Monthly Entitlement in any given month, Vendor shall invoice Customer for
the excess usage at a rate of $1.50 per compute unit above the Monthly Entitlement.
"""


def _item(customer_id: str, units_used: float) -> CohortItem:
    return CohortItem(
        customer=Customer(customer_id=customer_id, name=f"Customer {customer_id}"),
        contract_text=CONTRACT_TEXT,
        usage=UsagePeriod(customer_id=customer_id, period_label="2026-07", units_used=units_used),
        new_entitlement_units=12_000,
    )


def test_a_cohort_of_clean_renewals_needs_no_human_review():
    client = FakeSuperDocsClient()
    items = [_item("c1", 5_000), _item("c2", 8_000), _item("c3", 9_999)]

    result = run_cohort_batch(client, items)

    assert len(result.clean) == 3
    assert result.pending_review == []
    assert result.failed == []


def test_only_genuine_overage_exceptions_reach_the_review_queue():
    client = FakeSuperDocsClient()
    items = [_item("clean-1", 5_000), _item("over-1", 15_000), _item("clean-2", 3_000), _item("over-2", 20_000)]

    result = run_cohort_batch(client, items)

    assert len(result.clean) == 2
    assert {p.package.customer.customer_id for p in result.pending_review} == {"over-1", "over-2"}
    assert result.total_processed == 4


BROKEN_CONTRACT_NO_OVERAGE_CLAUSE = """MASTER SERVICES AGREEMENT (SAMPLE)

2.1 Customer is entitled to use up to 8,000 (eight thousand) compute units per month ("Monthly Entitlement")
under this Agreement.

2.2 The fee for the Monthly Entitlement is $6,000.00 per month, payable in advance.
"""


def test_a_clause_not_found_exception_never_lands_in_clean_even_though_start_renewal_does_not_raise():
    """Regression test for a real bug: start_renewal() returns NORMALLY (doesn't raise) for both a truly
    clean renewal and a clause_not_found exception - only PendingHumanDecision is raised, and only for the
    overage case. The first version of run_cohort_batch treated 'didn't raise' as 'clean', which silently
    routed a clause-not-found customer into the clean bucket. Caught by actually running the web app
    against a cohort containing this exact mix, not by any test that existed before this one - none of
    them exercised both exception types together in the same batch."""
    client = FakeSuperDocsClient()
    items = [
        _item("clean-1", 5_000),
        CohortItem(
            customer=Customer("no-clause", "No Clause Inc."),
            contract_text=BROKEN_CONTRACT_NO_OVERAGE_CLAUSE,
            usage=UsagePeriod("no-clause", "2026-07", units_used=100),
            new_entitlement_units=10_000,
        ),
        _item("over-1", 15_000),
    ]

    result = run_cohort_batch(client, items)

    clean_ids = {p.customer.customer_id for p in result.clean}
    review_ids = {p.package.customer.customer_id for p in result.pending_review}

    assert clean_ids == {"clean-1"}
    assert review_ids == {"no-clause", "over-1"}
    assert result.failed == []

    no_clause_item = next(p for p in result.pending_review if p.package.customer.customer_id == "no-clause")
    assert no_clause_item.package.exception.reason == "clause_not_found"
    assert no_clause_item.job_id is None
    assert no_clause_item.change_id is None


def test_one_customers_failure_never_aborts_the_rest_of_the_batch():
    """Simulates a real crash (not a business exception) for one customer mid-batch - the other customers
    must still be processed, not silently dropped."""

    class FlakyClient(FakeSuperDocsClient):
        def upload_document(self, filename, content, session_id):
            if "boom" in session_id:
                raise RuntimeError("simulated SuperDocs outage for this customer")
            return super().upload_document(filename, content, session_id)

    client = FlakyClient()
    items = [_item("ok-1", 5_000), _item("boom-1", 5_000), _item("ok-2", 5_000)]

    result = run_cohort_batch(client, items)

    assert len(result.clean) == 2
    assert [p.customer.customer_id for p in result.clean] == ["ok-1", "ok-2"]
    assert len(result.failed) == 1
    assert result.failed[0].customer_id == "boom-1"
    assert "simulated SuperDocs outage" in result.failed[0].error


def test_max_customers_is_a_real_stopping_rule_not_a_suggestion():
    client = FakeSuperDocsClient()
    items = [_item(f"c{i}", 1_000) for i in range(10)]

    result = run_cohort_batch(client, items, max_customers=3)

    assert result.total_processed == 3
    assert len(result.skipped_over_limit) == 7
    assert result.skipped_over_limit == [f"c{i}" for i in range(3, 10)]


def test_pending_review_items_carry_the_actual_proposed_content_not_just_ids():
    """Real gap found auditing against the task brief: a human reviewing an exception in the web UI saw a
    static placeholder instead of the actual proposed amendment - the content was fetched from the API but
    dropped between PendingHumanDecision and the batch's PendingReviewItem. This is the layer that must
    carry it through to the template."""
    client = FakeSuperDocsClient()
    items = [_item("over-1", 15_000)]

    result = run_cohort_batch(client, items)

    item = result.pending_review[0]
    assert item.old_html == "10,000"
    assert item.new_html == "12,000"
    assert item.ai_explanation


def test_progress_callback_fires_once_per_processed_customer_in_order():
    client = FakeSuperDocsClient()
    items = [_item("c1", 1_000), _item("c2", 1_000)]
    calls: list[tuple[int, int, str, str]] = []

    run_cohort_batch(client, items, on_progress=lambda *args: calls.append(args))

    assert calls == [(1, 2, "c1", "clean"), (2, 2, "c2", "clean")]
