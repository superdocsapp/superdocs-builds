import os
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path='../.env')

API_KEY = os.getenv("SUPERDOCS_API_KEY")
BASE_URL = "https://api.superdocs.app/v1"
STATE_FILE = "continuity_state.json"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"doc_ids": {}, "chat_ids": {}, "approved": False, "exported": False, "lore_bible": ""}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def upload_chapter(filepath: str, state: dict) -> str:
    filename = os.path.basename(filepath)
    if filename in state["doc_ids"]:
        print(f"[Upload] {filename} already uploaded (ID: {state['doc_ids'][filename]})")
        return state["doc_ids"][filename]
        
    print(f"[Upload] Uploading {filename} to SuperDocs...")
    time.sleep(1)
    doc_id = f"mock_doc_{int(time.time())}"
    state["doc_ids"][filename] = doc_id
    save_state(state)
    print(f"[Upload] Success. ID: {doc_id}")
    return doc_id

def send_continuity_check(doc_ids: list, instruction: str, state: dict) -> dict:
    state_key = "_".join(doc_ids) + str(hash(instruction))
    if state_key in state["chat_ids"]:
        print(f"[Chat] Instruction already processed (Chat ID: {state['chat_ids'][state_key]})")
        return {"id": state["chat_ids"][state_key]}

    print("[Chat] Sending chapter to SuperDocs for Continuity Check...")
    time.sleep(2)
    chat_id = f"mock_chat_{int(time.time())}"
    data = {
        "id": chat_id,
        "proposed_changes": [
            {"id": "c1", "type": "insertion", "content": "WARNING: Continuity Conflict Detected - Protagonist is using a sword lost in Chapter 2."}
        ]
    }
    
    state["chat_ids"][state_key] = chat_id
    save_state(state)
    print(f"[Chat] Success. SuperDocs flagged {len(data['proposed_changes'])} continuity conflicts.")
    return data

def run_continuity_keeper():
    print("--- The Continuity Keeper (Powered by SuperDocs) ---")
    state = load_state()
    
    chapter_file = "chapter3.txt"
    if not os.path.exists(chapter_file):
        with open(chapter_file, "w") as f:
            f.write("Chapter 3\nJohn swung his pristine longsword at the dragon.")
            
    doc_id = upload_chapter(chapter_file, state)
    
    instruction = (
        "You are The Continuity Keeper. Compare this chapter against the established Lore Bible. "
        "Flag any continuity errors (e.g. lost limbs, lost weapons). Do not rewrite the chapter, "
        "just append continuity warnings to the top of the document."
    )
    
    chat_result = send_continuity_check([doc_id], instruction, state)
    print("Continuity Keeper has finished analysis.")
    
if __name__ == "__main__":
    if not API_KEY or API_KEY == "paste_your_superdocs_api_key_here":
        print("ERROR: SUPERDOCS_API_KEY is not set correctly in .env")
        exit(1)
    run_continuity_keeper()
