import os
import json
import requests
import uuid
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("SUPERDOCS_API_KEY")
BASE_URL = "https://api.superdocs.app/v1"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

def run_pipeline():
    print("--- STARTING PIPELINE ---")
    
    if not API_KEY:
        print("ERROR: API_KEY is missing. Check your .env file.")
        return

    print("1. Preparing data and contacting SuperDocs /chat endpoint...")
    
    try:
        with open("raw_accession.txt", "r") as f:
            raw_text = f.read()
    except FileNotFoundError:
        print("ERROR: raw_accession.txt not found.")
        return

    raw_html = f"<p>{raw_text}</p>"
    
    instruction = (
        "Parse this accession record and generate a structured archival finding aid. "
        "Strictly adhere to the Describing Archives: A Content Standard (DACS). "
        "Extract: 1. Reference Code, 2. Repository, 3. Title, 4. Date, 5. Extent, "
        "6. Name of Creator, 7. Scope and Content, 8. Conditions Governing Access, "
        "9. Languages. If missing, write 'Not specified'. Do not invent data."
    )
    
    current_session_id = str(uuid.uuid4())
    
    chat_payload = {
        "session_id": current_session_id,
        "message": instruction,
        "document_html": raw_html,
        "approval_mode": "ask_every_time"
    }
    
    try:
        print("   -> Sending request (This might take 10-30 seconds)...")
        chat_res = requests.post(f"{BASE_URL}/chat", headers=HEADERS, json=chat_payload, timeout=60)
        chat_res.raise_for_status()
        chat_data = chat_res.json()
        print("   -> Chat response received successfully!")
        
        returned_session_id = chat_data.get("session_id", current_session_id)
        
        print("2. Parsing proposed changes...")
        
        doc_changes = chat_data.get("document_changes")
        if doc_changes is None:
            doc_changes = {}
            
        changes = doc_changes.get("pending_changes")
        if changes is None:
            changes = []
            
        if isinstance(changes, str):
            changes = json.loads(changes)
            
        change_ids = [c.get("id") for c in changes if isinstance(c, dict) and "id" in c]
        
        if change_ids:
            print(f"3. Approving {len(change_ids)} proposed changes...")
            approve_payload = {
                "session_id": returned_session_id,
                "approved_changes": change_ids
            }
            approve_res = requests.post(f"{BASE_URL}/approve", headers=HEADERS, json=approve_payload, timeout=30)
            approve_res.raise_for_status()
            print("   -> Changes approved successfully!")
        else:
            print("3. Document was auto-approved by the API (Full replacement). Skipping manual approval.")
        
        print("4. Exporting finalized document to DOCX...")
        export_payload = {
            "session_id": returned_session_id,
            "format": "docx"
        }
        # UPDATED EXPORT URL HERE
        export_res = requests.post(f"{BASE_URL}/documents/export", headers=HEADERS, json=export_payload, timeout=30)
        export_res.raise_for_status()
        
        with open("finding_aid_DACS.docx", "wb") as f:
            f.write(export_res.content)
        print("\nSUCCESS! File saved locally as finding_aid_DACS.docx")

    except requests.exceptions.HTTPError as e:
        print(f"\nERROR: HTTP Error occurred: {e}")
        print(f"Response text: {e.response.text}")
    except Exception as e:
        print(f"\nERROR: An unexpected error occurred: {e}")

if __name__ == "__main__":
    run_pipeline()