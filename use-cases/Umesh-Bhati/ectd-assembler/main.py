import json
import os
import sys
import time
from requests.exceptions import RequestException
from client import SuperDocsClient
from hasher import get_file_hashes

class Manifest:
    def __init__(self, filepath: str):
        with open(filepath, "r") as f:
            self.data = json.load(f)
            
    def get_all_sources(self) -> set:
        sources = set()
        for data in self.data.get("sections", {}).values():
            for source in data.get("sources", []):
                sources.add(source)
        return sources
        
    def get_affected_sections(self, changed_sources: set) -> list:
        affected = []
        for section, data in self.data.get("sections", {}).items():
            section_sources = data.get("sources", [])
            if any(src in changed_sources for src in section_sources):
                affected.append((section, data["title"], section_sources))
        return affected

def main():
    print("Starting eCTD Module 2 Assembler Pipeline...")
    client = SuperDocsClient()
    
    try:
        if not client.verify_connection():
            print("Error: Could not verify connection to SuperDocs API.")
            sys.exit(1)
    except RequestException as e:
        print(f"Error: Could not connect to SuperDocs API. ({e})")
        sys.exit(1)
    
    # 1. Read manifest to find files
    manifest = Manifest("manifest.json")
    sources = manifest.get_all_sources()
            
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

    try:
        # 3. Upload main document and attachments for the changed session
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
        affected_sections = manifest.get_affected_sections(changed_sources)
            
        job_ids = {}
        for section_num, title, section_sources in affected_sections:
            print(f"Drafting section {section_num} - {title}...")
            prompt = (
                f"Please draft section '{section_num} {title}' using the attached source documents. "
                f"You MUST explicitly cite the source document and section for every drafted paragraph. "
                f"Use the sources: {', '.join(section_sources)}."
            )
            job_id = client.chat_async(session_id, prompt)
            job_ids[section_num] = job_id
            print(f"Started drafting job for {section_num}: {job_id}")

        # 6. Review and Export
        print("\nWaiting for SuperDocs AI to finish drafting...")
        for section_num, job_id in job_ids.items():
            while True:
                # We mock the sleep out in tests, but this would poll normally
                try:
                    status = client.get_job_status(job_id)
                    if status in ["completed", "approved", "hitl_approval_required"]:
                        break
                except RequestException:
                    # Keep polling if there's a transient network issue
                    pass
                time.sleep(1)
                
        print(f"\nDrafting complete. Please review and approve the changes in the SuperDocs Web UI:")
        print(f"https://app.superdocs.app/sessions/{session_id}")
        
        # HITL Step
        input("Press Enter once you have reviewed and approved the document natively in the browser...")
        
        print("Exporting final document...")
        client.export_document(document_id, "final_module2.docx")
        print("Successfully exported to final_module2.docx.")

        # 7. Save state
        state = {
            "session_id": session_id,
            "document_id": document_id,
            "attachments": attachment_ids,
            "hashes": new_hashes
        }
        with open(state_file, "w") as f:
            json.dump(state, f, indent=2)
        print("Pipeline complete. State saved to session_state.json.")
        
    except RequestException as e:
        print(f"\nPipeline failed due to API Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

