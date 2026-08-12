import json
from client import SuperDocsClient

def main():
    print("Starting eCTD Module 2 Assembler Pipeline...")
    
    # Initialize API client
    client = SuperDocsClient()
    
    # 1. Read manifest to find files
    with open("manifest.json", "r") as f:
        manifest = json.load(f)
        
    # Find unique module 5 sources
    sources = set()
    for section, data in manifest.get("sections", {}).items():
        for source in data.get("sources", []):
            sources.add(source)
            
    # 2. Upload main document
    print("Uploading module2_shell.docx...")
    doc_res = client.upload_document("module2_shell.docx")
    session_id = doc_res.get("session_id")
    document_id = doc_res.get("document_id")
    print(f"Session ID: {session_id}, Document ID: {document_id}")
    
    # 3. Upload attachments
    attachment_ids = {}
    for source in sources:
        print(f"Uploading attachment: {source}...")
        att_id = client.upload_attachment(session_id, source)
        attachment_ids[source] = att_id
        print(f"Attachment ID for {source}: {att_id}")
        
    # 4. Save state
    state = {
        "session_id": session_id,
        "document_id": document_id,
        "attachments": attachment_ids
    }
    with open("session_state.json", "w") as f:
        json.dump(state, f, indent=2)
    print("Pipeline complete. State saved to session_state.json.")

if __name__ == "__main__":
    main()
