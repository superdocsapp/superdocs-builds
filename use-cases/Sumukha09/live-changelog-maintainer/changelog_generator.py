import os
import re
from typing import List
from models import Release, Changelog

class ChangelogGenerator:
    def __init__(self, changelog: Changelog):
        self.changelog = changelog
        
    def detect_duplicate(self, release: Release) -> bool:
        """Returns True if the release version already exists."""
        for r in self.changelog.releases:
            if r.version == release.version:
                return True
        return False

    def generate_release_markdown(self, release: Release) -> str:
        """Generates markdown for a single release chunk."""
        lines = []
        lines.append(f"## {release.version}")
        
        if release.added:
            lines.append("\n### Added")
            for item in release.added:
                lines.append(f"* {item}")
                
        if release.improved:
            lines.append("\n### Improved")
            for item in release.improved:
                lines.append(f"* {item}")
                
        if release.fixed:
            lines.append("\n### Fixed")
            for item in release.fixed:
                lines.append(f"* {item}")
                
        if release.breaking_changes:
            lines.append("\n### Breaking Changes")
            for item in release.breaking_changes:
                lines.append(f"* {item}")
        
        lines.append("\n") # Blank line between releases
        return "\n".join(lines) + "\n"
        
    def update_markdown(self, existing_md: str, new_release: Release) -> str:
        """Inserts a new release directly into existing markdown, keeping historical bytes identical."""
        if self.detect_duplicate(new_release):
            return existing_md
            
        release_md = self.generate_release_markdown(new_release)
        
        # Insert directly after the main # Product Changelog header and its trailing newlines
        title_pattern = re.compile(r"^(#\s+.*?\n+)", re.MULTILINE)
        match = title_pattern.search(existing_md)
        if match:
            insert_pos = match.end()
            return existing_md[:insert_pos] + release_md + existing_md[insert_pos:]
        
        # Fallback if no header found
        return release_md + existing_md

    def generate_initial_markdown(self) -> str:
        """Generates a complete markdown file from scratch (for first run)."""
        lines = [f"# {self.changelog.title}\n\n"]
        for release in self.changelog.releases:
            lines.append(self.generate_release_markdown(release))
        return "".join(lines)

def process_releases(incoming_releases: List[Release], preview_mode: bool = False):
    """Processes incoming releases. Implements stopping rule by processing exactly one release."""
    if not incoming_releases:
        print("No incoming releases to process.")
        return 0
        
    # Stopping Condition: The maintainer must process one release per invocation and then stop.
    release_to_process = incoming_releases[0]
    
    source_path = os.path.join("source", "changelog.md")
    export_path = os.path.join("export", "changelog.md")
    
    # Ensure source directory exists
    os.makedirs("source", exist_ok=True)
    if not os.path.exists(source_path):
        from mock_data import get_mock_releases
        initial_releases = get_mock_releases()
        initial_releases.sort(key=lambda x: x.version, reverse=True)
        cg = ChangelogGenerator(Changelog(title="Product Changelog", releases=initial_releases))
        with open(source_path, "w", encoding="utf-8") as f:
            f.write(cg.generate_initial_markdown())
            
    with open(source_path, "r", encoding="utf-8") as f:
        existing_md = f.read()
        
    # Extract existing versions for duplicate detection
    existing_versions = re.findall(r"^##\s+(v\d+\.\d+\.\d+)", existing_md, re.MULTILINE)
    changelog = Changelog(title="Product Changelog", releases=[Release(version=v, date="") for v in existing_versions])
    
    generator = ChangelogGenerator(changelog)
    
    if generator.detect_duplicate(release_to_process):
        print(f"Release {release_to_process.version} is a duplicate. Skipping.")
        return 0
        
    updated_md = generator.update_markdown(existing_md, release_to_process)
    
    # PREVIEW MODE (No Spend, No MCP Calls)
    if preview_mode:
        print("--- PREVIEW MODE ---")
        print(f"Proposed Update for {release_to_process.version}:")
        print(generator.generate_release_markdown(release_to_process))
        print("--- END PREVIEW ---")
        return 1
        
    # Export flow - Self trigger protection by exporting to separate directory
    os.makedirs("export", exist_ok=True)
    with open(export_path, "w", encoding="utf-8") as f:
        f.write(updated_md)
        
    print(f"Successfully processed {release_to_process.version} and exported to {export_path}")
    
    # Run the live MCP workflow over the exported file
    execute_live_workflow(export_path)
    
    return 1

def call_mcp_tool(url, headers, tool_name, arguments):
    import requests
    import json
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }
    
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()
    
    content = data.get("result", {}).get("content", [])
    if content:
        return content[0].get("text", "")
    return ""

def execute_live_workflow(markdown_path: str):
    import json
    import base64
    import os
    import time
    
    print("\n[MCP] Connecting to SuperDocs MCP via REST/POST...")
    config_path = os.path.expanduser(r"~\.gemini\config\mcp_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
        
    sd_config = config.get("mcpServers", {}).get("superdocs", {})
    url = sd_config.get("serverUrl", "")
    if url.endswith("sse"):
        url = url[:-3]
    headers = sd_config.get("headers", {})
    headers["Content-Type"] = "application/json"
    headers["Accept"] = "application/json"
    
    with open(markdown_path, "r", encoding="utf-8") as f:
        content = f.read()
    b64_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    
    print("[MCP] Session initialized. Uploading document...")
    call_mcp_tool(url, headers, "upload_document_base64", {
        "filename": "changelog.md",
        "file_base64": b64_content,
        "session_id": "task2b_demo_session"
    })
    
    print("[MCP] Requesting AI insertion via chat_async...")
    res_text = call_mcp_tool(url, headers, "chat_async", {
        "session_id": "task2b_demo_session",
        "message": "Please update the changelog with the latest release.",
        "response_mode": "compact",
        "approval_mode": "ask_every_time"
    })
    
    data = json.loads(res_text)
    job_id = data.get("job_id")
    
    print(f"[MCP] Job created: {job_id}. Polling for awaiting_approval status...")
    
    while True:
        res_text = call_mcp_tool(url, headers, "get_job", {"job_id": job_id})
        data = json.loads(res_text)
        status = data.get("status")
        
        if status == "awaiting_approval":
            print("[MCP] Job is awaiting approval. Extracting batch ID...")
            inter_res = data.get("metadata", {}).get("intermediate_responses", [])
            batch_id = None
            for ir in inter_res:
                if ir.get("type") == "proposed_change_batch":
                    try:
                        batch_data = json.loads(ir.get("content", "{}"))
                        changes = batch_data.get("changes", [])
                        if changes:
                            batch_id = changes[0].get("change_id")
                            break
                    except Exception as e:
                        pass
                        
            if batch_id:
                print(f"[MCP] Found change_id: {batch_id}. Calling approve_change...")
                call_mcp_tool(url, headers, "approve_change", {
                    "session_id": "task2b_demo_session",
                    "job_id": job_id,
                    "approved": True
                })
                print("[MCP] Change approved.")
            else:
                print("[MCP] ERROR: Could not find change_id.")
                break
        
        elif status == "completed":
            print("[MCP] Job completed successfully!")
            break
        elif status in ["error", "failed"]:
            print(f"[MCP] Job failed: {status}")
            break
            
        time.sleep(2)
        
    print("[MCP] Exporting final document...")
    res_text = call_mcp_tool(url, headers, "export_document", {"session_id": "task2b_demo_session"})
    print(res_text)
    print("[MCP] Live workflow complete!")

def main():
    import sys
    from mock_data import get_latest_mock_release
    
    preview = "--preview" in sys.argv
    incoming = [get_latest_mock_release()]
    process_releases(incoming, preview_mode=preview)

if __name__ == "__main__":
    main()
