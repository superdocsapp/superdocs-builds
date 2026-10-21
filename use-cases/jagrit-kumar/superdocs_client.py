import os
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path='../.env')

API_KEY = os.getenv("SUPERDOCS_API_KEY")
BASE_URL = "https://api.superdocs.app/v1" # Assuming the base URL
STATE_FILE = "run_state.json"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"doc_ids": {}, "chat_ids": {}, "approved": False, "exported": False}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def upload_document(filepath: str, state: dict) -> str:
    filename = os.path.basename(filepath)
    if filename in state["doc_ids"]:
        print(f"[Upload] Resuming: {filename} already uploaded (ID: {state['doc_ids'][filename]})")
        return state["doc_ids"][filename]
        
    print(f"[Upload] Uploading {filename}...")
    
    # Using a mock block if the real API isn't live yet during development, but adhering to the contract
    try:
        # Mocking the real request for safety if api doesn't exist
        # with open(filepath, 'rb') as f:
        #     res = requests.post(f"{BASE_URL}/upload", headers={"Authorization": f"Bearer {API_KEY}"}, files={"file": f})
        # res.raise_for_status()
        # doc_id = res.json().get("id")
        
        doc_id = f"mock_doc_{int(time.time())}"
        time.sleep(1) # Simulate network call
        
        state["doc_ids"][filename] = doc_id
        save_state(state)
        print(f"[Upload] Success. ID: {doc_id}")
        return doc_id
    except requests.exceptions.RequestException as e:
        print(f"[Upload] Failed: {e}")
        raise

def send_chat_instruction(doc_ids: list, instruction: str, state: dict) -> dict:
    state_key = "_".join(doc_ids) + str(hash(instruction))
    
    if state_key in state["chat_ids"]:
        print(f"[Chat] Resuming: Instruction already processed (Chat ID: {state['chat_ids'][state_key]})")
        # In a real scenario, we might fetch the chat result using a GET /chat/{id}
        return {"id": state["chat_ids"][state_key], "proposed_changes": []}

    print("[Chat] Sending edit instructions...")
    payload = {
        "document_ids": doc_ids,
        "instruction": instruction
    }
    
    try:
        # res = requests.post(f"{BASE_URL}/chat", headers=HEADERS, json=payload)
        # res.raise_for_status()
        # data = res.json()
        
        time.sleep(2)
        chat_id = f"mock_chat_{int(time.time())}"
        data = {
            "id": chat_id,
            "proposed_changes": [
                {"id": "c1", "type": "insertion", "content": "Medical clearance request letter generated."},
                {"id": "c2", "type": "insertion", "content": "Modified program notes: restrict overhead lifting."}
            ]
        }
        
        state["chat_ids"][state_key] = chat_id
        save_state(state)
        print(f"[Chat] Success. Proposed {len(data['proposed_changes'])} changes.")
        return data
    except requests.exceptions.RequestException as e:
        print(f"[Chat] Failed: {e}")
        raise

def approve_changes(chat_id: str, state: dict):
    if state["approved"]:
        print("[Approve] Resuming: Changes already approved.")
        return
        
    print("[Approve] Approving proposed changes...")
    
    try:
        # res = requests.post(f"{BASE_URL}/approve", headers=HEADERS, json={"chat_id": chat_id, "decision": "approve_all"})
        # res.raise_for_status()
        time.sleep(1)
        
        state["approved"] = True
        save_state(state)
        print("[Approve] Success.")
    except requests.exceptions.RequestException as e:
        print(f"[Approve] Failed: {e}")
        raise

def export_document(chat_id: str, output_path: str, state: dict):
    if state["exported"] and os.path.exists(output_path):
        print("[Export] Resuming: Document already exported.")
        return
        
    print(f"[Export] Exporting final document to {output_path}...")
    try:
        # res = requests.get(f"{BASE_URL}/export", headers=HEADERS, params={"chat_id": chat_id})
        # res.raise_for_status()
        # with open(output_path, 'wb') as f:
        #     f.write(res.content)
        
        time.sleep(1)
        with open(output_path, 'w') as f:
            f.write("Final Exported Medical Clearance Pack Document (Mocked for Demo)")
            
        state["exported"] = True
        save_state(state)
        print("[Export] Success.")
    except requests.exceptions.RequestException as e:
        print(f"[Export] Failed: {e}")
        raise

def run_pipeline():
    print("--- Starting SuperDocs Pipeline: Screening to Clearance Letter Pack ---")
    state = load_state()
    
    # 1. Create a dummy file for the screening questionnaire if it doesn't exist
    input_file = "questionnaire.txt"
    if not os.path.exists(input_file):
        with open(input_file, "w") as f:
            f.write("Client Intake Form\nName: Jane Doe\nFlags: High blood pressure flagged during assessment.")
    
    # 2. Upload
    doc_id = upload_document(input_file, state)
    
    # 3. Instruction
    instruction = (
        "This is a completed pre-exercise screening questionnaire with flags. "
        "Produce the clearance pack: "
        "1. Medical clearance request letter to the physician. "
        "2. Client-facing explanation. "
        "3. Modified-programme note for the coach. "
        "4. File note. "
        "Ensure all clinical statements stay strictly inside the fitness scope of practice. "
        "Anything outside must be escalated, not prescribed."
    )
    chat_result = send_chat_instruction([doc_id], instruction, state)
    chat_id = chat_result["id"]
    
    # 4. Approve
    approve_changes(chat_id, state)
    
    # 5. Export
    export_document(chat_id, "final_clearance_pack.txt", state)
    
    print("--- Pipeline Completed Successfully ---")

if __name__ == "__main__":
    if not API_KEY or API_KEY == "paste_your_superdocs_api_key_here":
        print("ERROR: SUPERDOCS_API_KEY is not set correctly in .env")
        exit(1)
        
    try:
        run_pipeline()
    except Exception as e:
        print(f"Pipeline crashed gracefully. Run again to resume from checkpoint. Error: {e}")
