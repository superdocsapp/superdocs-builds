#!/usr/bin/env python3
"""
Test script for EngageFlow Steering Committee Report Generator.
Runs extraction, state comparison, and generates the final engagement status report markdown.
"""
from pathlib import Path
import sys
from app.services.extractor import DocumentExtractor
from app.services.comparator import StateComparator
from app.services.generator import ReportGenerator

def main():
    print("==========================================")
    print(" EngageFlow Report Generation Test        ")
    print("==========================================")

    base_dir = Path(__file__).resolve().parent.parent / "sample_data"
    extractor = DocumentExtractor()
    comparator = StateComparator()
    generator = ReportGenerator()

    # 1. Extract Period 1 & Period 2 states
    p1_state = extractor.extract_from_folder(base_dir / "period_1", "Period 1 (July 2026)")
    p2_state = extractor.extract_from_folder(base_dir / "period_2", "Period 2 (August 2026)")

    # 2. Derive delta state
    compared_state = comparator.compare_states(p1_state, p2_state)

    # 3. Generate Steering Committee Report
    report_md = generator.generate_report(compared_state)

    print("\n--- Generated Steering Committee Report ---\n")
    print(report_md)
    print("\n-------------------------------------------")

    # Assert essential sections exist in report
    required_sections = [
        "Executive Summary",
        "Milestone Progress & Timeline Movement",
        "Workstream Status & Normalized Updates",
        "Risks & Issues Movement (Period-over-Period)",
        "Financial Spend & Budget Burn",
        "Steering Committee Decisions Needed"
    ]

    for sec in required_sections:
        assert sec in report_md, f"Missing section: {sec}"
        print(f"✅ Verified report contains section: {sec}")

    print("\n🎉 Step 4 Test PASSED! Steering Committee report generated cleanly.")

if __name__ == "__main__":
    main()
