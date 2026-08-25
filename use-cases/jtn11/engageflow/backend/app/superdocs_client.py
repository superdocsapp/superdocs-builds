"""
SuperDocs Client Module
Isolates all HTTP requests and API integrations with the SuperDocs Agent REST API.
Default endpoint: http://localhost:8000
"""
import os
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
import urllib.request
import urllib.parse
import uuid

DEFAULT_SUPERDOCS_URL = os.environ.get("SUPERDOCS_API_URL", "http://localhost:8000")

class SuperDocsClient:
    def __init__(self, base_url: str = DEFAULT_SUPERDOCS_URL):
        self.base_url = base_url.rstrip("/")

    def health_check(self) -> Dict[str, Any]:
        """Check connection to SuperDocs REST API."""
        url = f"{self.base_url}/health"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def upload_document(self, file_path: Path) -> Dict[str, Any]:
        """
        Uploads a project document to SuperDocs API via multipart form-data.
        Endpoint: POST /api/documents/upload
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Document file not found at {file_path}")

        url = f"{self.base_url}/api/documents/upload"
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
        filename = file_path.name
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document" if file_path.suffix == ".docx" else "application/octet-stream"

        with open(file_path, "rb") as f:
            file_bytes = f.read()

        body = bytearray()
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8"))
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        body.extend(file_bytes)
        body.extend("\r\n".encode("utf-8"))
        body.extend(f"--{boundary}--\r\n".encode("utf-8"))

        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            "Accept": "application/json"
        }

        req = urllib.request.Request(url, data=bytes(body), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def list_documents(self) -> List[Dict[str, Any]]:
        """List all documents stored in SuperDocs."""
        url = f"{self.base_url}/api/documents/"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def create_run(self, document_ids: List[int]) -> Dict[str, Any]:
        """
        Create a new analysis/report run in SuperDocs.
        Endpoint: POST /api/runs/
        """
        url = f"{self.base_url}/api/runs/"
        payload = json.dumps({"document_ids": document_ids}).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_run(self, run_id: str) -> Dict[str, Any]:
        """
        Get run status and findings from SuperDocs.
        Endpoint: GET /api/runs/{run_id}
        """
        url = f"{self.base_url}/api/runs/{run_id}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def approve_finding(self, run_id: str, finding_id: str) -> Dict[str, Any]:
        """
        Approve a specific finding in a SuperDocs run.
        Endpoint: POST /api/runs/{run_id}/findings/{finding_id}/approve
        """
        url = f"{self.base_url}/api/runs/{run_id}/findings/{finding_id}/approve"
        req = urllib.request.Request(url, data=b"", headers={"Accept": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def finalize_run(self, run_id: str) -> Dict[str, Any]:
        """
        Finalize run and export report in SuperDocs.
        Endpoint: POST /api/runs/{run_id}/finalize
        """
        url = f"{self.base_url}/api/runs/{run_id}/finalize"
        req = urllib.request.Request(url, data=b"", headers={"Accept": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
