class MockSuperDocsServer:
    """
    A tracking mock server context to intercept SuperDocs API interactions.
    Records operations to verify that steps (e.g. upload -> edit -> approve -> export)
    run sequentially, idempotently, and without state corruption.
    """
    def __init__(self):
        self.uploaded_files = []
        self.instructions_sent = []
        self.approved_change_ids = []
        self.exported_docs = []

    def reset(self):
        self.uploaded_files.clear()
        self.instructions_sent.clear()
        self.approved_change_ids.clear()
        self.exported_docs.clear()

    def simulate_upload(self, filename: str, content: bytes) -> str:
        doc_id = f"test_doc_{len(self.uploaded_files) + 1}"
        self.uploaded_files.append({"document_id": doc_id, "filename": filename, "content": content})
        return doc_id

    def simulate_chat(self, document_id: str, instruction: str) -> dict:
        self.instructions_sent.append({"document_id": document_id, "instruction": instruction})
        # Simulate proposed changes
        proposed = {
            "changes": [
                {
                    "id": f"change_{len(self.instructions_sent)}",
                    "target_section": "Flight Details",
                    "original_text": "Flight AA123 departs at 10:00 AM",
                    "proposed_text": "Flight AA456 departs at 2:30 PM",
                    "reason": f"Interpreted instruction: {instruction}"
                }
            ]
        }
        import json
        return {
            "document_id": document_id,
            "status": "awaiting_approval",
            "proposed_changes": json.dumps(proposed)
        }

    def simulate_approve(self, document_id: str, approved_ids: list) -> dict:
        self.approved_change_ids.append({"document_id": document_id, "approved_ids": approved_ids})
        return {
            "document_id": document_id,
            "status": "committed",
            "committed_changes": approved_ids
        }

    def simulate_export(self, document_id: str, format_type: str) -> bytes:
        self.exported_docs.append({"document_id": document_id, "format": format_type})
        return f"finalized_content_for_{document_id}_as_{format_type}".encode("utf-8")
