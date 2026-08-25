import pytest
from app.services.aggregation_service import AggregationService


@pytest.mark.asyncio
async def test_aggregate_programme_reconciliation(db_session):
    """Verify aggregate report mathematically reconciles with underlying assessments."""
    service = AggregationService(db=db_session)
    report = await service.get_programme_metrics(cycle_year=2026)

    # 5 suppliers seeded in DB
    assert report.total_suppliers_invited == 5
    # 2 attestations submitted in seed
    assert report.responses_submitted == 2
    assert report.attestation_rate_pct == 40.0  # 2 / 5 * 100

    # Risk tier distribution sum must equal total assessed responses (2)
    risk_sum = sum(item.count for item in report.risk_tier_breakdown)
    assert risk_sum == 2

    # Tier counts must sum to total suppliers (5)
    tier_sum = sum(item.total_suppliers for item in report.tier_distribution)
    assert tier_sum == 5

    # Pillar averages must be valid non-zero percentages
    assert 0.0 <= report.pillar_averages.environmental_avg <= 100.0
    assert 0.0 <= report.pillar_averages.social_avg <= 100.0
    assert 0.0 <= report.pillar_averages.governance_avg <= 100.0
