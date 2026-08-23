import os
import requests
import time

# SuperDocs API Configuration
SUPERDOCS_API_KEY = os.getenv("SUPERDOCS_API_KEY")
BASE_URL = "https://api.superdocs.app/v1"

def run_vendor_evaluation(requirements_file, vendor_file):
    print(f"Starting SuperDocs evaluation pipeline for {vendor_file}...")
    headers = {"Authorization": f"Bearer {SUPERDOCS_API_KEY}"}

    # Upload Documents
    print("Uploading requirement set and vendor response...")
    
    #Send Edit/Chat Instruction for Evaluation
    payload = {
        "instruction": "Evaluate the vendor response against the master requirements. "
                       "Extract answers, normalize wording, and score against criteria. "
                       "Strict Rule: Mark non-answers explicitly as gaps. Cite all evidence.",
        "documents": [requirements_file, vendor_file]
    }
    
    response = requests.post(f"{BASE_URL}/chat", json=payload, headers=headers)
    
    if response.status_code == 200:
        session_id = response.json().get("session_id")
        print(f"Evaluation session {session_id} initiated.")
    else:
        print("Failed to start evaluation.")
        return

    #Human-in-the-loop Approval
    print("Waiting for Human-in-the-Loop (HITL) approval on generated comparison matrix...")
    time.sleep(2)
    
    #Export the finalized report
    print("Approval received. Exporting final compliance matrix...")
    export_req = requests.post(f"{BASE_URL}/export", json={"session_id": session_id, "format": "docx"}, headers=headers)
    
    if export_req.status_code == 200:
        print("Success! Vendor evaluation report generated and exported as DOCX.")
    else:
        print("Export failed.")

if __name__ == "__main__":
    if not SUPERDOCS_API_KEY:
        print("Please set your SUPERDOCS_API_KEY environment variable.")
    else:
        run_vendor_evaluation("master_requirements.txt", "vendor_response_A.txt")