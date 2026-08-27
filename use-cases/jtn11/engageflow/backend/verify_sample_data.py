#!/usr/bin/env python3
"""
EngageFlow Sample Data Verification Script
Verifies that all synthetic project documents for Period 1 and Period 2 are present and non-empty.
"""
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent / "sample_data"

REQUIRED_DOCUMENTS = [
    "Project_Plan.md",
    "Risk_Issue_Log.md",
    "Financial_Report.md",
    "Workstream_A_Update.md",
    "Workstream_B_Update.md",
    "Workstream_C_Update.md",
    "Previous_Status_Report.md"
]

def verify_period(period_name: str) -> bool:
    period_dir = BASE_DIR / period_name
    print(f"--- Verifying {period_name} in {period_dir} ---")
    if not period_dir.exists():
        print(f"❌ Error: Directory {period_dir} does not exist.")
        return False

    all_ok = True
    for doc in REQUIRED_DOCUMENTS:
        doc_path = period_dir / doc
        if not doc_path.exists():
            print(f"❌ Missing: {doc}")
            all_ok = False
        else:
            content = doc_path.read_text(encoding="utf-8").strip()
            if len(content) == 0:
                print(f"⚠️ Empty file: {doc}")
                all_ok = False
            else:
                print(f"✅ Found {doc} ({len(content.splitlines())} lines, {len(content)} chars)")

    return all_ok

def main():
    print("==========================================")
    print(" EngageFlow Sample Data Integrity Check   ")
    print("==========================================")
    
    p1_ok = verify_period("period_1")
    p2_ok = verify_period("period_2")
    
    if p1_ok and p2_ok:
        print("\n🎉 SUCCESS: All synthetic test documents for Period 1 and Period 2 are present and valid!")
        sys.exit(0)
    else:
        print("\n❌ FAILURE: Missing or invalid sample documents detected.")
        sys.exit(1)

if __name__ == "__main__":
    main()
