import os
import requests
from requests.exceptions import RequestException

class SuperDocsClient:
    def __init__(self, base_url="https://api.superdocs.app/v1"):
        self.api_key = os.environ.get("SUPERDOCS_API_KEY")
        self.base_url = base_url

    def _post_file(self, endpoint: str, filepath: str) -> dict:
        if not self.api_key:
            raise ValueError("SUPERDOCS_API_KEY environment variable is missing")
        
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        with open(filepath, 'rb') as f:
            files = {'file': (os.path.basename(filepath), f)}
            response = requests.post(f"{self.base_url}{endpoint}", headers=headers, files=files)
            response.raise_for_status()
            
        return response.json()

    def verify_connection(self) -> bool:
        if not self.api_key:
            raise ValueError("SUPERDOCS_API_KEY environment variable is missing")
            
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
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
        if not self.api_key:
            raise ValueError("SUPERDOCS_API_KEY environment variable is missing")
            
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"prompt": prompt}
        
        response = requests.post(
            f"{self.base_url}/sessions/{session_id}/chat_async", 
            headers=headers, 
            json=payload
        )
        response.raise_for_status()
        
        return response.json().get("job_id")
