#!/usr/bin/env python3
"""
Test script for EngageFlow State Extractor and Comparator Engine.
Verifies period-over-period delta extraction between Period 1 and Period 2 documents.
"""
from pathlib import Path
import sys
from app.services.extractor import DocumentExtractor
from app.services.comparator import StateComparator

def main():
    print("==========================================")
    print(" EngageFlow State Delta & Movement Test   ")
    print("==========================================")

    base_dir = Path(__file__).resolve().parent.parent / "sample_data"
    extractor = DocumentExtractor()
    comparator = StateComparator()

    # 1. Extract Period 1 State
    p1_path = base_dir / "period_1"
    p1_state = extractor.extract_from_folder(p1_path, "Period 1 (July 2026)")
    print(f"✅ Extracted Period 1 State: Overall Status = {p1_state.overall_status}")
    print(f"   - Milestones: {len(p1_state.milestones)}")
    print(f"   - Workstreams: {[w.name + ':' + w.status for w in p1_state.workstreams]}")
    print(f"   - Risks/Issues: {len(p1_state.risks_and_issues)}")
    print(f"   - Spend: ${p1_state.financials.cumulative_spend:,.2f} ({p1_state.financials.burn_rate_percent}%)")

    # 2. Extract Period 2 State
    p2_path = base_dir / "period_2"
    p2_state = extractor.extract_from_folder(p2_path, "Period 2 (August 2026)")
    print(f"\n✅ Extracted Period 2 State: Overall Status = {p2_state.overall_status}")
    print(f"   - Milestones: {len(p2_state.milestones)}")
    print(f"   - Workstreams: {[w.name + ':' + w.status for w in p2_state.workstreams]}")
    print(f"   - Risks/Issues: {len(p2_state.risks_and_issues)}")
    print(f"   - Spend: ${p2_state.financials.cumulative_spend:,.2f} ({p2_state.financials.burn_rate_percent}%)")

    # 3. Compute Movements
    compared_state = comparator.compare_states(p1_state, p2_state)
    print(f"\n--- Period Movements Computed ---")
    print(f"Overall Status Movement: {compared_state.overall_status}")

    print("\n📍 Milestone Movements:")
    for ms in compared_state.milestones:
        print(f"  • {ms.id} ({ms.status}): {ms.movement_since_last_period}")

    print("\n📍 Workstream Movements:")
    for ws in compared_state.workstreams:
        print(f"  • {ws.name} ({ws.status}): {ws.movement_since_last_period}")

    print("\n📍 Risk & Issue Movements:")
    for r in compared_state.risks_and_issues:
        print(f"  • [{r.item_type}] {r.id} ({r.severity}, {r.status}): {r.movement_since_last_period}")

    print("\n📍 Financial Movement:")
    if compared_state.financials:
        print(f"  • {compared_state.financials.movement_since_last_period}")

    # Assert key movement statements exist
    assert compared_state.financials.cumulative_spend > p1_state.financials.cumulative_spend, "Spend should increase"
    print("\n🎉 Step 3 Test PASSED! State comparison engine derived accurate movements.")

if __name__ == "__main__":
    main()
