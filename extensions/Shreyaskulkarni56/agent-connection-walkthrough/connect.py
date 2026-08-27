#!/usr/bin/env py
"""
SuperDocs Authenticated Agent Connection Walkthrough
=====================================================

This script demonstrates how an MCP agent client connects to SuperDocs using
standards-based discovery (RFC 9728 Protected Resource Metadata) and Bearer API key authentication.

Protocol Flow:
  Step 1: Server Card Discovery   -> GET /.well-known/mcp.json
  Step 2: Unauthenticated Probe   -> POST /mcp/ (receives HTTP 401 + WWW-Authenticate header)
  Step 3: RFC 9728 Metadata       -> GET /mcp/.well-known/oauth-protected-resource
  Step 4: Credential Acquisition   -> POST /v1/agents/signup (or load cached ~/.superdocs/agent_credentials.json)
  Step 5: Authenticated MCP        -> POST /mcp/ (initialize -> initialized -> tools/list -> tools/call)

CLI Usage:
  py -3 connect.py --discover-only
  py -3 connect.py --agent-name my-custom-agent
  py -3 connect.py --skip-signup
  py -3 connect.py --verbose
"""

import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

CREDENTIALS_FILE = os.path.expanduser("~/.superdocs/agent_credentials.json")
DEFAULT_AGENT_NAME = "connection-walkthrough-demo"

# Create SSL context for secure HTTPS calls
SSL_CONTEXT = ssl.create_default_context()


def safe_print(text: str) -> None:
    """Print text safely across operating systems and console encodings."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8"))


def print_banner(step_num: int, title: str, description: str) -> None:
    """Print a styled section banner for the walkthrough."""
    separator = "=" * 70
    safe_print(f"\n{separator}")
    safe_print(f" STEP {step_num}: {title.upper()}")
    safe_print(f" {description}")
    safe_print(f"{separator}\n")


def mask_key(api_key: str) -> str:
    """Return a masked representation of an API key for safe display."""
    if not api_key:
        return "None"
    if len(api_key) <= 8:
        return api_key[:2] + "..." + api_key[-2:]
    return api_key[:5] + "..." + api_key[-4:]


def http_request(url: str, method: str = "GET", headers: dict = None, body: dict = None) -> tuple[int, dict, str]:
    """
    Execute an HTTP request using Python standard library (urllib).
    Returns (status_code, response_headers_dict, response_body_text).
    """
    if headers is None:
        headers = {}
    
    headers.setdefault("User-Agent", "SuperDocs-AgentConnectionWalkthrough/1.0")

    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, context=SSL_CONTEXT) as response:
            resp_headers = {k.lower(): v for k, v in response.headers.items()}
            resp_body = response.read().decode("utf-8")
            return response.status, resp_headers, resp_body
    except urllib.error.HTTPError as err:
        resp_headers = {k.lower(): v for k, v in err.headers.items()}
        resp_body = err.read().decode("utf-8")
        return err.code, resp_headers, resp_body
    except Exception as exc:
        safe_print(f"[ERROR] HTTP Request failed: {exc}")
        sys.exit(1)


# -----------------------------------------------------------------------------
# STEP 1: Discover Server Card
# -----------------------------------------------------------------------------
def discover_server_card(verbose: bool = False) -> dict:
    """
    Step 1: Fetch server card from /.well-known/mcp.json.
    Exposes registry metadata, remote endpoints, and signup location hint.
    """
    print_banner(1, "Discover Server Card", "GET https://api.superdocs.app/.well-known/mcp.json")

    url = "https://api.superdocs.app/.well-known/mcp.json"
    safe_print(f"--> Request: GET {url}")
    
    status, headers, body_text = http_request(url, method="GET")
    safe_print(f"<-- Response: HTTP {status}")

    try:
        card = json.loads(body_text)
    except json.JSONDecodeError:
        safe_print(f"[ERROR] Failed to parse JSON response from {url}")
        sys.exit(1)

    if verbose:
        safe_print(f"Full response:\n{json.dumps(card, indent=2)}")

    name = card.get("name", "Unknown")
    version = card.get("version", "Unknown")
    remotes = card.get("remotes", [])
    meta = card.get("_meta", {})

    safe_print(f"[+] Found Server Card: '{name}' v{version}")
    if remotes:
        mcp_url = remotes[0].get("url")
        auth_hdr = remotes[0].get("headers", [{}])[0]
        safe_print(f"    - Remote MCP Endpoint : {mcp_url}")
        safe_print(f"    - Required Auth Header: {auth_hdr.get('name')} ({auth_hdr.get('description')})")
    
    signup_endpoint = meta.get("signup_endpoint")
    safe_print(f"    - Signup Endpoint Hint: {signup_endpoint}")

    return card


# -----------------------------------------------------------------------------
# STEP 2: Unauthenticated Probe (401 Expected)
# -----------------------------------------------------------------------------
def probe_unauthenticated(verbose: bool = False) -> str:
    """
    Step 2: POST an unauthenticated MCP `initialize` request to /mcp/.
    SuperDocs rejects with 401 Unauthorized and returns the RFC 9728
    resource_metadata URL in the WWW-Authenticate header.
    """
    print_banner(2, "Unauthenticated Probe", "POST https://api.superdocs.app/mcp/ (Expect HTTP 401)")

    url = "https://api.superdocs.app/mcp/"
    init_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "walkthrough-probe", "version": "1.0.0"}
        }
    }

    safe_print(f"--> Request: POST {url}")
    safe_print(f"    Body: {json.dumps(init_payload)}")
    
    status, headers, body_text = http_request(url, method="POST", body=init_payload)
    safe_print(f"<-- Response: HTTP {status}")

    if verbose and body_text:
        safe_print(f"    Body: {body_text}")

    if status != 401:
        safe_print(f"[!] Warning: Expected HTTP 401 but got HTTP {status}")

    www_auth = headers.get("www-authenticate", "")
    safe_print(f"[+] Captured WWW-Authenticate Header:\n    {www_auth}")

    # Extract resource_metadata URL via regex
    match = re.search(r'resource_metadata="([^"]+)"', www_auth)
    if not match:
        safe_print("[ERROR] Could not extract resource_metadata URL from WWW-Authenticate header.")
        sys.exit(1)

    resource_metadata_url = match.group(1)
    safe_print(f"[+] Discovered Protected Resource Metadata URL:\n    {resource_metadata_url}")

    return resource_metadata_url


# -----------------------------------------------------------------------------
# STEP 3: RFC 9728 Protected Resource Metadata
# -----------------------------------------------------------------------------
def fetch_resource_metadata(metadata_url: str, verbose: bool = False) -> dict:
    """
    Step 3: Fetch RFC 9728 Protected Resource Metadata.
    Returns resource identification, supported auth methods, and signup_endpoint.
    """
    print_banner(3, "Fetch RFC 9728 Metadata", f"GET {metadata_url}")

    safe_print(f"--> Request: GET {metadata_url}")
    status, headers, body_text = http_request(metadata_url, method="GET")
    safe_print(f"<-- Response: HTTP {status}")

    try:
        metadata = json.loads(body_text)
    except json.JSONDecodeError:
        safe_print(f"[ERROR] Failed to parse resource metadata JSON from {metadata_url}")
        sys.exit(1)

    if verbose:
        safe_print(f"Full metadata:\n{json.dumps(metadata, indent=2)}")

    resource = metadata.get("resource")
    bearer_methods = metadata.get("bearer_methods_supported", [])
    signup_endpoint = metadata.get("signup_endpoint")
    docs_link = metadata.get("resource_documentation")

    safe_print(f"[+] Resource Identified       : {resource}")
    safe_print(f"[+] Supported Auth Methods    : {', '.join(bearer_methods)}")
    safe_print(f"[+] Self-Signup Endpoint      : {signup_endpoint}")
    safe_print(f"[+] Resource Documentation    : {docs_link}")

    return metadata


# -----------------------------------------------------------------------------
# STEP 4: Credential Acquisition / Reuse
# -----------------------------------------------------------------------------
def load_or_acquire_credentials(signup_endpoint: str, agent_name: str, skip_signup: bool, verbose: bool = False) -> str:
    """
    Step 4: Load existing credentials or sign up for a new Bearer API key.
    Checks environment variable `SUPERDOCS_API_KEY`, then `~/.superdocs/agent_credentials.json`.
    If absent and skip_signup is False, calls `POST /v1/agents/signup`.
    """
    print_banner(4, "Credential Acquisition / Reuse", f"Manage Bearer API Key ({signup_endpoint})")

    # 1. Check environment variable
    env_key = os.environ.get("SUPERDOCS_API_KEY")
    if env_key:
        safe_print(f"[+] Found API key in environment variable SUPERDOCS_API_KEY: {mask_key(env_key)}")
        if validate_key(env_key, verbose):
            return env_key

    # 2. Check cached credentials file
    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                creds = json.load(f)
            cached_key = creds.get("api_key")
            if cached_key:
                safe_print(f"[+] Found cached credentials file at {CREDENTIALS_FILE}")
                safe_print(f"    Account ID: {creds.get('account_id')}")
                safe_print(f"    API Key   : {mask_key(cached_key)}")
                if validate_key(cached_key, verbose):
                    return cached_key
        except Exception as err:
            safe_print(f"[!] Warning reading credentials file: {err}")

    if skip_signup:
        safe_print("[ERROR] --skip-signup specified but no valid credentials found in environment or file.")
        sys.exit(1)

    # 3. Perform autonomous signup
    safe_print(f"--> No existing key found. Signing up new agent '{agent_name}' at {signup_endpoint}...")
    signup_payload = {
        "terms_accepted": True,
        "agent_name": agent_name
    }

    status, headers, body_text = http_request(signup_endpoint, method="POST", body=signup_payload)
    safe_print(f"<-- Response: HTTP {status}")

    try:
        res = json.loads(body_text)
    except json.JSONDecodeError:
        safe_print(f"[ERROR] Failed to parse signup response: {body_text}")
        sys.exit(1)

    if verbose:
        safe_print(f"Full signup response:\n{json.dumps(res, indent=2)}")

    if status != 201 or "api_key" not in res:
        safe_print(f"[ERROR] Signup failed (HTTP {status}): {res.get('detail', body_text)}")
        sys.exit(1)

    api_key = res["api_key"]
    account_id = res.get("account_id")
    slug = res.get("slug")
    quota = res.get("quota", {})

    safe_print(f"[+] Signup successful!")
    safe_print(f"    - Account ID   : {account_id}")
    safe_print(f"    - Slug         : {slug}")
    safe_print(f"    - API Key      : {mask_key(api_key)} (Shown only once at creation!)")
    safe_print(f"    - Quota        : {quota.get('remaining')}/{quota.get('monthly_limit')} ops remaining")

    # Save credentials locally for reuse
    try:
        os.makedirs(os.path.dirname(CREDENTIALS_FILE), exist_ok=True)
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
        safe_print(f"[+] Saved agent credentials locally to {CREDENTIALS_FILE}")
    except Exception as err:
        safe_print(f"[!] Warning: Failed to save credentials file: {err}")

    return api_key


def validate_key(api_key: str, verbose: bool = False) -> bool:
    """Validate key using GET /v1/agents/whoami."""
    whoami_url = "https://api.superdocs.app/v1/agents/whoami"
    headers = {"Authorization": f"Bearer {api_key}"}
    status, _, body_text = http_request(whoami_url, method="GET", headers=headers)
    if status == 200:
        safe_print(f"[+] Key validated successfully via GET {whoami_url}")
        if verbose:
            safe_print(f"    Account Status: {body_text}")
        return True
    safe_print(f"[!] Key validation returned HTTP {status}. Proceeding with fallback.")
    return False


# -----------------------------------------------------------------------------
# STEP 5: Authenticated MCP Handshake & Tool Invocation
# -----------------------------------------------------------------------------
def connect_mcp(api_key: str, verbose: bool = False) -> None:
    """
    Step 5: Execute authenticated Streamable HTTP MCP handshake:
      1. POST /mcp/ method='initialize' with Authorization: Bearer <key>
      2. POST /mcp/ method='notifications/initialized'
      3. POST /mcp/ method='tools/list'
      4. POST /mcp/ method='tools/call' for 'health'
      5. POST /mcp/ method='tools/call' for 'get_account_status'
    """
    print_banner(5, "Authenticated MCP Connection", "Streamable HTTP Session over https://api.superdocs.app/mcp/")

    mcp_url = "https://api.superdocs.app/mcp/"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json"
    }

    # 1. Initialize
    safe_print("--> [1/4] Sending MCP 'initialize' request...")
    init_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "agent-connection-walkthrough", "version": "1.0.0"}
        }
    }
    status, _, body_text = http_request(mcp_url, method="POST", headers=headers, body=init_body)
    if status != 200:
        safe_print(f"[ERROR] MCP initialize failed with HTTP {status}: {body_text}")
        sys.exit(1)

    init_res = json.loads(body_text)
    server_info = init_res.get("result", {}).get("serverInfo", {})
    safe_print(f"<-- [1/4] MCP Connected to Server: {server_info.get('name')} v{server_info.get('version')}")

    # 2. Initialized Notification
    safe_print("--> [2/4] Sending MCP 'notifications/initialized'...")
    notify_body = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {}
    }
    http_request(mcp_url, method="POST", headers=headers, body=notify_body)
    safe_print("<-- [2/4] Notification acknowledged.")

    # 3. List Tools
    safe_print("--> [3/4] Requesting available tools ('tools/list')...")
    list_tools_body = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    }
    status, _, body_text = http_request(mcp_url, method="POST", headers=headers, body=list_tools_body)
    tools_res = json.loads(body_text)
    tools = tools_res.get("result", {}).get("tools", [])
    safe_print(f"<-- [3/4] Server exposes {len(tools)} tools.")
    if verbose:
        tool_names = [t.get("name") for t in tools]
        safe_print(f"    Available tools: {', '.join(tool_names[:10])}... ({len(tools)} total)")

    # 4. Call Tools ('health' and 'get_account_status')
    safe_print("--> [4/4] Executing tool calls ('health', 'get_account_status')...")
    
    # Call health
    health_body = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "health", "arguments": {}}
    }
    _, _, h_text = http_request(mcp_url, method="POST", headers=headers, body=health_body)
    h_json = json.loads(h_text)
    h_content = h_json.get("result", {}).get("structuredContent", {})
    safe_print(f"    [Tool: health]             -> status: {h_content.get('status')}, service: {h_content.get('service')}")

    # Call get_account_status
    acc_body = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "get_account_status", "arguments": {}}
    }
    _, _, a_text = http_request(mcp_url, method="POST", headers=headers, body=acc_body)
    a_json = json.loads(a_text)
    a_content = a_json.get("result", {}).get("structuredContent", {})
    quota = a_content.get("quota", {})
    safe_print(f"    [Tool: get_account_status] -> account: {a_content.get('account_id')}, tier: {a_content.get('tier')}, ops left: {quota.get('remaining')}/{quota.get('monthly_limit')}")


# -----------------------------------------------------------------------------
# SUMMARY & CONFIGURATION SNIPPET
# -----------------------------------------------------------------------------
def print_summary(api_key: str = None) -> None:
    """Print complete summary recap and copy-paste MCP configuration snippet."""
    separator = "=" * 70
    safe_print(f"\n{separator}")
    safe_print(" WALKTHROUGH EXECUTION SUMMARY")
    safe_print(f"{separator}")
    safe_print(" [x] Step 1: Discovered Server Card (/.well-known/mcp.json)")
    safe_print(" [x] Step 2: Probed Unauthenticated Endpoint (Caught HTTP 401)")
    safe_print(" [x] Step 3: Parsed RFC 9728 Metadata (oauth-protected-resource)")
    
    if api_key:
        safe_print(" [x] Step 4: Acquired/Loaded Bearer Credentials")
        safe_print(" [x] Step 5: Completed Authenticated MCP Tool Handshake & Calls")
    else:
        safe_print(" [-] Step 4: Skipped (--discover-only mode active)")
        safe_print(" [-] Step 5: Skipped (--discover-only mode active)")

    safe_print("\n" + "-" * 70)
    safe_print(" Sample MCP Client Configuration:")
    safe_print("-" * 70)
    sample_key = api_key if api_key else "sk_your_api_key_here"
    
    safe_print("1. Native Remote HTTP URL (Cursor / Windsurf / Cline / Continue):")
    native_config = {
        "mcpServers": {
            "superdocs": {
                "url": "https://api.superdocs.app/mcp",
                "headers": {
                    "Authorization": f"Bearer {sample_key}"
                }
            }
        }
    }
    safe_print(json.dumps(native_config, indent=2))

    safe_print("\n2. Claude Desktop (via npx server-http wrapper):")
    claude_config = {
        "mcpServers": {
            "superdocs": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-http", "https://api.superdocs.app/mcp"],
                "headers": {
                    "Authorization": f"Bearer {sample_key}"
                }
            }
        }
    }
    safe_print(json.dumps(claude_config, indent=2))
    safe_print("=" * 70 + "\n")


# -----------------------------------------------------------------------------
# CLI ENTRYPOINT
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="SuperDocs Authenticated Agent Connection Walkthrough Client"
    )
    parser.add_argument(
        "--agent-name",
        default=DEFAULT_AGENT_NAME,
        help=f"Agent name for self-signup (default: {DEFAULT_AGENT_NAME})"
    )
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Run discovery steps 1-3 only; do not sign up or connect to MCP"
    )
    parser.add_argument(
        "--skip-signup",
        action="store_true",
        help="Do not request new key from signup; require existing env key or credentials file"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed JSON payloads and HTTP responses"
    )

    args = parser.parse_args()

    safe_print("\n" + "=" * 70)
    safe_print(" SUPERDOCS AUTHENTICATED AGENT CONNECTION WALKTHROUGH")
    safe_print(" Demonstration of RFC 9728 Discovery + Bearer Key MCP Handshake")
    safe_print("=" * 70)

    # Step 1: Server Card
    card = discover_server_card(verbose=args.verbose)

    # Step 2: 401 Probe
    metadata_url = probe_unauthenticated(verbose=args.verbose)

    # Step 3: RFC 9728 Metadata
    metadata = fetch_resource_metadata(metadata_url, verbose=args.verbose)

    if args.discover_only:
        safe_print("\n[+] --discover-only mode enabled. Stopping after discovery steps.")
        print_summary(api_key=None)
        return

    # Step 4: Credential Acquisition / Reuse
    signup_endpoint = metadata.get("signup_endpoint", "https://api.superdocs.app/v1/agents/signup")
    api_key = load_or_acquire_credentials(
        signup_endpoint=signup_endpoint,
        agent_name=args.agent_name,
        skip_signup=args.skip_signup,
        verbose=args.verbose
    )

    # Step 5: Authenticated MCP Session
    connect_mcp(api_key=api_key, verbose=args.verbose)

    # Summary
    print_summary(api_key=api_key)


if __name__ == "__main__":
    main()
