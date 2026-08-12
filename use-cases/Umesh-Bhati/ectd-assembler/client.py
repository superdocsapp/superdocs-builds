import os
import requests
from requests.exceptions import RequestException

class SuperDocsClient:
    def __init__(self, base_url="https://api.superdocs.app/v1"):
        self.api_key = os.environ.get("SUPERDOCS_API_KEY")
        self.base_url = base_url

    @property
    def auth_headers(self) -> dict:
        if not self.api_key:
            raise ValueError("SUPERDOCS_API_KEY environment variable is missing")
        return {"Authorization": f"Bearer {self.api_key}"}

    def _post_file(self, endpoint: str, filepath: str) -> dict:
        headers = self.auth_headers
        
        with open(filepath, 'rb') as f:
            files = {'file': (os.path.basename(filepath), f)}
            response = requests.post(f"{self.base_url}{endpoint}", headers=headers, files=files)
            response.raise_for_status()
            
        return response.json()

    def verify_connection(self) -> bool:
        headers = self.auth_headers
        
        try:
            response = requests.get(f"{self.base_url}/sessions", headers=headers)
            return response.status_code == 200
        except RequestException:
            return False

    def upload_document(self, filepath: str) -> dict:
        return self._post_file("/upload_document_to_editor", filepath)

    def upload_attachment(self, session_id: str, filepath: str) -> str:
        res = self._post_file(f"/sessions/{session_id}/attachments", filepath)
        return res.get("attachment_id")

    def chat_async(self, session_id: str, prompt: str) -> str:
        headers = self.auth_headers
        headers["Content-Type"] = "application/json"
        payload = {"prompt": prompt}
        
        response = requests.post(
            f"{self.base_url}/sessions/{session_id}/chat_async", 
            headers=headers, 
            json=payload
        )
        response.raise_for_status()
        
        return response.json().get("job_id")

    def get_job_status(self, job_id: str) -> str:
        headers = self.auth_headers
        response = requests.get(
            f"{self.base_url}/jobs/{job_id}",
            headers=headers
        )
        response.raise_for_status()
        return response.json().get("status")

    def export_document(self, document_id: str, output_path: str) -> str:
        headers = self.auth_headers
        response = requests.get(
            f"{self.base_url}/export",
            headers=headers,
            params={"document_id": document_id}
        )
        response.raise_for_status()
        
        with open(output_path, 'wb') as f:
            f.write(response.content)
            
        return output_path
