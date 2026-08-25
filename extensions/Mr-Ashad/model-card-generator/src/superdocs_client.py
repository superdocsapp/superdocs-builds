"""SuperDocs 4-Call API Adapter Client.

Implements the four core operations:
1. Upload (upload base template / document structure)
2. Edit / Chat (send targeted instructions to update evaluation tables)
3. Approve (apply proposed diffs with CRITICAL double JSON deserialization)
4. Export (output synchronized Markdown and PDF files with exponential backoff polling)
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from .updater import SectionBoundaryUpdater
from .pdf_renderer import PDFCardRenderer

logger = logging.getLogger("superdocs_client")


class SuperDocsAPIError(Exception):
    """Base exception for SuperDocs API errors."""
    pass


class DiffParsingError(SuperDocsAPIError):
    """Raised when diff deserialization fails."""
    pass


class ExportPollingTimeoutError(SuperDocsAPIError):
    """Raised when document transformation polling exceeds allowed budget."""
    pass


def extract_and_parse_diff(response_payload: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Perform robust double JSON deserialization on proposed diff payloads.
    
    CRITICAL GOTCHA:
    The SuperDocs API returns proposed diff payloads as a JSON-encoded string
    inside the outer JSON response (e.g. response['diff'] = '{\"changes\": [...]}').
    A secondary JSON parse must be executed on this field before passing the approved
    object to avoid 'undefined' empty diff errors.
    """
    if response_payload is None:
        raise DiffParsingError("Cannot parse empty/None diff payload.")

    # If the payload is already an outer string, parse the outer layer first
    if isinstance(response_payload, str):
        try:
            parsed_outer = json.loads(response_payload)
        except json.JSONDecodeError as e:
            raise DiffParsingError(f"Failed to parse outer JSON payload: {e}")
    elif isinstance(response_payload, dict):
        parsed_outer = response_payload
    else:
        raise DiffParsingError(f"Unsupported payload type: {type(response_payload)}")

    # Check for inner stringified fields containing the actual diff
    inner_diff_raw = None
    if isinstance(parsed_outer, dict):
        if "diff" in parsed_outer:
            inner_diff_raw = parsed_outer["diff"]
        elif "proposed_diff" in parsed_outer:
            inner_diff_raw = parsed_outer["proposed_diff"]
        elif "data" in parsed_outer and isinstance(parsed_outer["data"], dict):
            inner_diff_raw = parsed_outer["data"].get("diff") or parsed_outer["data"].get("proposed_diff")
        else:
            inner_diff_raw = parsed_outer

    # If the extracted inner diff is a JSON-encoded string, perform the SECOND parse
    if isinstance(inner_diff_raw, str):
        try:
            parsed_inner = json.loads(inner_diff_raw)
            # Handle potential tertiary escaping in edge-case proxies
            if isinstance(parsed_inner, str):
                parsed_inner = json.loads(parsed_inner)
            return parsed_inner
        except json.JSONDecodeError as e:
            raise DiffParsingError(f"Failed second JSON parse on inner diff string: {e}")

    if isinstance(inner_diff_raw, dict):
        return inner_diff_raw

    raise DiffParsingError(f"Resolved diff is not a valid JSON object: {type(inner_diff_raw)}")


class SuperDocsClient:
    """Adapter for SuperDocs 4-call document lifecycle management."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        mock_mode: Optional[bool] = None,
        timeout: int = 60,
    ) -> None:
        """Initialize SuperDocs client.
        
        Args:
            api_key: SuperDocs API Key (or env SUPERDOCS_API_KEY)
            base_url: REST API endpoint (default: https://docs.superdocs.app)
            mock_mode: If True, uses local simulation; if None, auto-detected from key presence.
            timeout: HTTP request timeout in seconds.
        """
        self.api_key = api_key or os.environ.get("SUPERDOCS_API_KEY", "")
        self.base_url = (base_url or os.environ.get("SUPERDOCS_API_BASE_URL", "https://api.superdocs.app")).rstrip("/")
        self.timeout = timeout

        if mock_mode is not None:
            self.mock_mode = mock_mode
        else:
            # Auto-enable mock mode if no API key is configured or offline mode is requested
            self.mock_mode = not bool(self.api_key) or os.environ.get("SUPERDOCS_OFFLINE", "0") in ("1", "true")

        self.session_store: Dict[str, Dict[str, Any]] = {}

    def _headers(self) -> Dict[str, str]:
        """Generate HTTP authentication headers."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "SuperDocs-ModelCardGenerator/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["X-API-Key"] = self.api_key
        return headers

    # -------------------------------------------------------------------------
    # 1. Upload Base Template / Document Structure
    # -------------------------------------------------------------------------
    def upload(
        self,
        content: str,
        title: str = "Model and System Card",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Upload base template/document structure and retrieve session/document ID.
        
        Returns:
            {
                "document_id": str,
                "session_id": str,
                "version": int,
                "status": "created"
            }
        """
        metadata = metadata or {}

        if self.mock_mode:
            doc_id = f"doc_{int(time.time() * 1000)}_{random.randint(100, 999)}"
            session_id = f"sess_{random.randint(1000, 9999)}"
            self.session_store[doc_id] = {
                "document_id": doc_id,
                "session_id": session_id,
                "title": title,
                "content": content,
                "metadata": metadata,
                "version": 1,
                "status": "created",
                "created_at": time.time(),
            }
            logger.info(f"[Mock Mode] Document uploaded successfully: {doc_id}")
            return {
                "document_id": doc_id,
                "session_id": session_id,
                "version": 1,
                "status": "created",
            }

        if not HAS_REQUESTS:
            raise RuntimeError("Python requests library is required for live API calls.")

        url = f"{self.base_url}/api/v1/documents"
        payload = {
            "title": title,
            "content": content,
            "metadata": metadata,
        }

        try:
            resp = requests.post(url, headers=self._headers(), json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return {
                "document_id": data.get("document_id") or data.get("id"),
                "session_id": data.get("session_id", ""),
                "version": data.get("version", 1),
                "status": data.get("status", "created"),
            }
        except Exception as e:
            logger.error(f"Failed to upload document to SuperDocs: {e}")
            raise SuperDocsAPIError(f"Upload failed: {e}")

    # -------------------------------------------------------------------------
    # 2. Edit / Chat Instruction for Targeted Updates
    # -------------------------------------------------------------------------
    def chat(
        self,
        document_id: str,
        instruction: str,
        evaluation_markdown: str,
        timestamp: Optional[str] = None,
        run_id: Optional[str] = None,
        baseline_model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send targeted instructions to update evaluation tables and timestamps.
        
        Returns response containing proposed diff (outer JSON with double-encoded diff string).
        """
        if self.mock_mode:
            doc = self.session_store.get(document_id)
            if not doc:
                raise SuperDocsAPIError(f"Document ID not found in session store: {document_id}")

            # Compute proposed changes using the section updater
            original_content = doc["content"]
            updated_content = SectionBoundaryUpdater.update_evaluation(
                document_content=original_content,
                new_eval_markdown=evaluation_markdown,
                timestamp=timestamp,
                run_id=run_id,
                baseline_model=baseline_model,
            )

            # Construct inner diff object
            inner_diff_obj = {
                "target": "evaluation_section",
                "action": "replace_boundaries",
                "timestamp_updated": True,
                "original_checksum": hash(original_content),
                "proposed_content": updated_content,
                "changes": [
                    {"type": "section_replace", "section": "evaluation_tables"},
                    {"type": "timestamp_update", "timestamp": timestamp},
                ],
            }

            # Double-encode inner diff into JSON string to emulate SuperDocs API contract
            inner_diff_json_str = json.dumps(inner_diff_obj)

            response = {
                "document_id": document_id,
                "session_id": doc["session_id"],
                "status": "diff_proposed",
                "instruction": instruction,
                # Outer field containing stringified JSON
                "diff": inner_diff_json_str,
            }
            return response

        if not HAS_REQUESTS:
            raise RuntimeError("Python requests library is required for live API calls.")

        url = f"{self.base_url}/api/v1/documents/{document_id}/chat"
        payload = {
            "instruction": instruction,
            "target_section": "evaluation",
            "context": {
                "evaluation_markdown": evaluation_markdown,
                "timestamp": timestamp,
                "run_id": run_id,
                "baseline_model": baseline_model,
            },
        }

        try:
            resp = requests.post(url, headers=self._headers(), json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed chat edit request for document {document_id}: {e}")
            raise SuperDocsAPIError(f"Chat edit failed: {e}")

    # -------------------------------------------------------------------------
    # 3. Approve Proposed Diffs (With 2x JSON Parse)
    # -------------------------------------------------------------------------
    def approve(
        self,
        document_id: str,
        chat_response_or_diff: Union[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Apply proposed diffs after performing required double JSON deserialization.
        
        Args:
            document_id: Target document ID
            chat_response_or_diff: Chat response object or raw diff string
            
        Returns:
            Approval confirmation and updated document version.
        """
        # Execute the required double JSON deserialization
        parsed_diff = extract_and_parse_diff(chat_response_or_diff)

        if self.mock_mode:
            doc = self.session_store.get(document_id)
            if not doc:
                raise SuperDocsAPIError(f"Document ID not found in session store: {document_id}")

            if "proposed_content" in parsed_diff:
                doc["content"] = parsed_diff["proposed_content"]
            doc["version"] += 1
            doc["status"] = "approved"

            logger.info(f"[Mock Mode] Diff approved for {document_id}, new version: {doc['version']}")
            return {
                "document_id": document_id,
                "version": doc["version"],
                "status": "approved",
                "applied_changes": len(parsed_diff.get("changes", [1])),
            }

        if not HAS_REQUESTS:
            raise RuntimeError("Python requests library is required for live API calls.")

        url = f"{self.base_url}/api/v1/documents/{document_id}/approve"
        payload = {
            "approved_diff": parsed_diff,
        }

        try:
            resp = requests.post(url, headers=self._headers(), json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to approve diff for document {document_id}: {e}")
            raise SuperDocsAPIError(f"Approve failed: {e}")

    # -------------------------------------------------------------------------
    # 4. Export Synchronized Markdown and PDF with Async Polling
    # -------------------------------------------------------------------------
    def export(
        self,
        document_id: str,
        output_dir: Optional[Union[str, Path]] = None,
        base_filename: str = "model_card",
        formats: Optional[List[str]] = None,
    ) -> Dict[str, Union[str, bytes]]:
        """Export synchronized publication-ready Markdown and PDF files with polling.
        
        Args:
            document_id: Document ID
            output_dir: Destination folder to write .md and .pdf files
            base_filename: Base file name without extension
            formats: List of formats (e.g. ['markdown', 'pdf'])
            
        Returns:
            Dict containing {'markdown': content_str, 'pdf': bytes_or_path}
        """
        formats = formats or ["markdown", "pdf", "html"]

        if self.mock_mode:
            doc = self.session_store.get(document_id)
            if not doc:
                raise SuperDocsAPIError(f"Document ID not found: {document_id}")

            content_md = doc["content"]
            pdf_bytes = self._generate_simulated_pdf(content_md, doc.get("title", "Model Card"))

            results: Dict[str, Any] = {
                "markdown": content_md,
                "pdf": pdf_bytes,
                "status": "completed",
            }

            if output_dir:
                out_path = Path(output_dir)
                out_path.mkdir(parents=True, exist_ok=True)
                md_file = out_path / f"{base_filename}.md"
                pdf_file = out_path / f"{base_filename}.pdf"

                with open(md_file, "w", encoding="utf-8") as f:
                    f.write(content_md)
                with open(pdf_file, "wb") as f:
                    f.write(pdf_bytes)

                results["markdown_path"] = str(md_file)
                results["pdf_path"] = str(pdf_file)

            return results

        if not HAS_REQUESTS:
            raise RuntimeError("Python requests library is required for live API calls.")

        # 1. Initiate export task
        initiate_url = f"{self.base_url}/api/v1/documents/{document_id}/export"
        init_resp = requests.post(initiate_url, headers=self._headers(), json={"formats": formats}, timeout=self.timeout)
        init_resp.raise_for_status()
        task_data = init_resp.json()
        task_id = task_data.get("task_id") or task_data.get("export_id") or document_id

        # 2. Poll for completion with exponential backoff
        export_result = self._poll_export_task(task_id=task_id)

        # 3. Save files if output_dir provided
        if output_dir:
            out_path = Path(output_dir)
            out_path.mkdir(parents=True, exist_ok=True)
            if "markdown" in export_result and "markdown_path" not in export_result:
                md_file = out_path / f"{base_filename}.md"
                with open(md_file, "w", encoding="utf-8") as f:
                    f.write(export_result["markdown"])
                export_result["markdown_path"] = str(md_file)

            if "pdf" in export_result and "pdf_path" not in export_result:
                pdf_file = out_path / f"{base_filename}.pdf"
                with open(pdf_file, "wb") as f:
                    if isinstance(export_result["pdf"], str):
                        f.write(export_result["pdf"].encode("utf-8"))
                    else:
                        f.write(export_result["pdf"])
                export_result["pdf_path"] = str(pdf_file)

        return export_result

    def _poll_export_task(
        self,
        task_id: str,
        initial_delay: float = 1.0,
        backoff_factor: float = 1.5,
        max_delay: float = 30.0,
        max_retries: int = 15,
        total_timeout_sec: float = 300.0,
    ) -> Dict[str, Any]:
        """Poll export task status using exponential backoff.
        
        Handles multi-minute processing gracefully without dropping connections.
        """
        delay = initial_delay
        start_time = time.time()
        attempt = 0

        while attempt < max_retries:
            elapsed = time.time() - start_time
            if elapsed > total_timeout_sec:
                raise ExportPollingTimeoutError(
                    f"Export task {task_id} timed out after {elapsed:.1f}s ({attempt} retries)."
                )

            url = f"{self.base_url}/api/v1/export/tasks/{task_id}"
            try:
                resp = requests.get(url, headers=self._headers(), timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", "").lower()

                if status in ("completed", "done", "success"):
                    return {
                        "task_id": task_id,
                        "status": "completed",
                        "markdown": data.get("markdown_content") or data.get("content", ""),
                        "pdf": data.get("pdf_url") or data.get("pdf_bytes", b""),
                    }
                elif status in ("failed", "error"):
                    raise SuperDocsAPIError(f"Export task {task_id} failed: {data.get('error', 'Unknown error')}")

                logger.info(f"Export task {task_id} status: {status}. Waiting {delay:.2f}s...")
            except requests.RequestException as req_err:
                logger.warning(f"Transient error polling export task {task_id}: {req_err}")

            time.sleep(delay)
            delay = min(delay * backoff_factor + random.uniform(0.1, 0.5), max_delay)
            attempt += 1

        raise ExportPollingTimeoutError(
            f"Export task {task_id} exceeded maximum retry attempts ({max_retries})."
        )

    @staticmethod
    def _generate_simulated_pdf(markdown_content: str, title: str) -> bytes:
        """Create publication-grade, beautifully styled PDF binary from card content."""
        return PDFCardRenderer.render_from_markdown(markdown_content, title=title)
