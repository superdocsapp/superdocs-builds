import os
import requests
import json
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPERDOCS_API_BASE = "https://api.superdocs.app/v1"

class SuperDocsClient:
    def __init__(self, agent_name="OpenEnrolmentAgent"):
        self.agent_name = agent_name
        self.api_key = os.getenv("SUPERDOCS_API_KEY")
        if not self.api_key:
            self._signup()

    def _signup(self):
        logger.info(f"Signing up agent {self.agent_name} to get a new API key...")
        res = requests.post(f"{SUPERDOCS_API_BASE}/agent/signup", json={"name": self.agent_name}, timeout=5)
        res.raise_for_status()
        self.api_key = res.json().get("api_key")
        logger.info("Successfully fetched API key via agent signup flow.")

    def get_headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def upload_document(self, file_path):
        logger.info(f"Uploading document: {file_path}")
        with open(file_path, 'rb') as f:
            # For file uploads, we generally don't set Content-Type: application/json
            headers = {"Authorization": f"Bearer {self.api_key}"}
            res = requests.post(
                f"{SUPERDOCS_API_BASE}/documents", 
                headers=headers, 
                files={"file": (os.path.basename(file_path), f)}
            )
        res.raise_for_status()
        return res.json()

    def request_edit(self, document_id, instruction):
        logger.info(f"Requesting edit for {document_id}: {instruction}")
        payload = {"instruction": instruction}
        res = requests.post(f"{SUPERDOCS_API_BASE}/documents/{document_id}/edit", headers=self.get_headers(), json=payload)
        res.raise_for_status()
        return res.json()
    
    def approve_edit(self, job_id):
        logger.info(f"Approving edit {job_id}")
        res = requests.post(f"{SUPERDOCS_API_BASE}/jobs/{job_id}/approve", headers=self.get_headers())
        res.raise_for_status()
        return res.json()
        
    def export_document(self, document_id):
        logger.info(f"Exporting document {document_id}")
        res = requests.post(f"{SUPERDOCS_API_BASE}/documents/{document_id}/export", headers=self.get_headers())
        res.raise_for_status()
        return res.json()

client = SuperDocsClient()
