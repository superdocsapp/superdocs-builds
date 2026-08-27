#!/usr/bin/env python3
"""
Test script for SuperDocs Integration Client.
Uploads sample DOCX documents to live SuperDocs API at http://localhost:8000 and creates a test run.
"""
from pathlib import Path
import sys
from app.superdocs_client import SuperDocsClient

def main():
    print("==========================================")
    print(" SuperDocs Live API Integration Test      ")
    print("==========================================")
    
    client = SuperDocsClient()
    
    # 1. Health check
    try:
        health = client.health_check()
        print(f"✅ Live SuperDocs API Health Check: {health}")
    except Exception as e:
        print(f"❌ SuperDocs API health check failed: {e}")
        sys.exit(1)

    # 2. Upload Period 1 sample DOCX documents
    sample_dir = Path(__file__).resolve().parent.parent / "sample_data" / "period_1"
    files_to_upload = [
        "Project_Plan.docx",
        "Risk_Issue_Log.docx",
        "Financial_Report.docx",
        "Workstream_A_Update.docx",
        "Workstream_B_Update.docx",
        "Workstream_C_Update.docx",
        "Previous_Status_Report.docx"
    ]
    
    uploaded_doc_ids = []
    print("\n--- Uploading Synthetic Sample Documents ---")
    for fname in files_to_upload:
        fpath = sample_dir / fname
        try:
            res = client.upload_document(fpath)
            doc_id = res.get("id")
            filename = res.get("filename")
            status = res.get("status")
            uploaded_doc_ids.append(doc_id)
            print(f"✅ Uploaded {filename} -> Doc ID: {doc_id} (Status: {status})")
        except Exception as e:
            print(f"❌ Failed to upload {fname}: {e}")
            sys.exit(1)

    # 3. Create SuperDocs Run
    print("\n--- Creating SuperDocs Run ---")
    try:
        run_res = client.create_run(uploaded_doc_ids)
        run_id = run_res.get("run_id")
        stage = run_res.get("current_stage")
        print(f"✅ Created SuperDocs Run -> Run ID: {run_id} (Current Stage: {stage})")
    except Exception as e:
        print(f"❌ Failed to create SuperDocs run: {e}")
        sys.exit(1)

    # 4. Fetch Run details
    print("\n--- Fetching SuperDocs Run Details ---")
    try:
        details = client.get_run(run_id)
        print(f"✅ Run Details Fetched -> Status: {details.get('status')}, Document IDs: {details.get('document_ids')}")
    except Exception as e:
        print(f"❌ Failed to fetch run details: {e}")
        sys.exit(1)

    print("\n🎉 Step 2 Integration Test PASSED! SuperDocs Client cleanly connected to live API.")

if __name__ == "__main__":
    main()
