import json
import os
from client import SuperDocsClient
from hasher import get_file_hashes

def main():
    print("Starting eCTD Module 2 Assembler Pipeline...")
    
    # 1. Read manifest to find files
    with open("manifest.json", "r") as f:
        manifest = json.load(f)
        
    # Find unique module 5 sources
    sources = set()
    for section, data in manifest.get("sections", {}).items():
        for source in data.get("sources", []):
            sources.add(source)
            
    # 2. Hashing and Dependency Tracking BEFORE uploading
    state_file = "session_state.json"
    old_state = {}
    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            old_state = json.load(f)
            
    old_hashes = old_state.get("hashes", {})
    new_hashes = get_file_hashes(sources)
    
    changed_sources = set()
    for source in sources:
        if new_hashes.get(source) != old_hashes.get(source):
            changed_sources.add(source)
            
    print(f"Changed sources detected: {changed_sources}")
    
    if not changed_sources:
        print("No changes detected in source documents. Exiting early.")
        return

    # 3. Upload main document and attachments for the changed session
    client = SuperDocsClient()
    
    print("Uploading module2_shell.docx...")
    doc_res = client.upload_document("module2_shell.docx")
    session_id = doc_res.get("session_id")
    document_id = doc_res.get("document_id")
    print(f"Session ID: {session_id}, Document ID: {document_id}")
    
    attachment_ids = {}
    for source in sources:
        print(f"Uploading attachment: {source}...")
        att_id = client.upload_attachment(session_id, source)
        attachment_ids[source] = att_id
        print(f"Attachment ID for {source}: {att_id}")
    
    # 4. Draft Sections affected by changed sources
    affected_sections = []
    for section, data in manifest.get("sections", {}).items():
        section_sources = data.get("sources", [])
        if any(src in changed_sources for src in section_sources):
            affected_sections.append((section, data["title"], section_sources))
            
    for section_num, title, section_sources in affected_sections:
        print(f"Drafting section {section_num} - {title}...")
        prompt = (
            f"Please draft section '{section_num} {title}' using the attached source documents. "
            f"You MUST explicitly cite the source document and section for every drafted paragraph. "
            f"Use the sources: {', '.join(section_sources)}."
        )
        job_id = client.chat_async(session_id, prompt)
        print(f"Started drafting job for {section_num}: {job_id}")

    # 5. Save state
    state = {
        "session_id": session_id,
        "document_id": document_id,
        "attachments": attachment_ids,
        "hashes": new_hashes
    }
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)
    print("Pipeline complete. State saved to session_state.json.")

if __name__ == "__main__":
    main()
