# SuperDocs Authenticated Agent Connection Walkthrough

A reference Python client and step-by-step walkthrough demonstrating how an AI agent autonomously discovers SuperDocs, retrieves authorization metadata via **RFC 9728 (OAuth 2.0 Protected Resource Metadata)**, signs up or reuses Bearer credentials, and completes an authenticated **Model Context Protocol (MCP)** Streamable HTTP connection.

---

## Architecture & Protocol Flow

SuperDocs implements standards-based MCP authorization discovery (RFC 9728) paired with instant autonomous agent onboarding (`/v1/agents/signup`). This allows headless AI agents to discover the server, acquire an API key, and begin executing document editing tools with zero human intervention.

```mermaid
sequenceDiagram
    autonumber
    participant Agent as Agent Client
    participant Card as WellKnown Server Card
    participant MCP as SuperDocs MCP Server
    participant Meta as RFC 9728 Resource Metadata
    participant Signup as Agent Signup API

    Agent->>Card: 1. GET /.well-known/mcp.json
    Card-->>Agent: Returns server card & signup endpoint hint
    
    Agent->>MCP: 2. POST /mcp/ (Unauthenticated initialize)
    MCP-->>Agent: 401 Unauthorized + WWW-Authenticate header
    
    Agent->>Meta: 3. GET /mcp/.well-known/oauth-protected-resource
    Meta-->>Agent: Returns RFC 9728 metadata (signup_endpoint, bearer_methods)
    
    alt Credentials Cached (~/.superdocs/agent_credentials.json or SUPERDOCS_API_KEY)
        Agent->>Signup: 4a. GET /v1/agents/whoami (Validate existing Bearer key)
        Signup-->>Agent: 200 OK (Account active & quota status)
    else No Cached Credentials
        Agent->>Signup: 4b. POST /v1/agents/signup (Agent name + terms)
        Signup-->>Agent: 201 Created (One-time api_key sk_...)
    end
    
    Agent->>MCP: 5. POST /mcp/ (initialize with Authorization: Bearer sk_...)
    MCP-->>Agent: 200 OK (Server capabilities & 38 document tools)
    
    Agent->>MCP: 6. POST /mcp/ (tools/call 'health' & 'get_account_status')
    MCP-->>Agent: Structured tool execution output
```

---

## Prerequisites & Setup

This walkthrough is built using Python's standard library (`urllib`), requiring **zero third-party dependencies**.

### Quick Run

```bash
# 1. Clone & navigate to project directory
cd extensions/Shreyaskulkarni56/agent-connection-walkthrough

# 2. (Optional) Install optional dependencies if desired
pip install -r requirements.txt

# 3. Dry-run discovery only (Steps 1–3, no account creation)
python connect.py --discover-only

# 4. Full end-to-end flow (Discovers, signs up new agent, runs MCP tools)
python connect.py --agent-name my-first-agent

# 5. Subsequent runs (Reuses cached key at ~/.superdocs/agent_credentials.json)
python connect.py --skip-signup
```

---

## Step-by-Step Protocol Walkthrough

### Step 1: Server Card Discovery

The agent probes `GET https://api.superdocs.app/.well-known/mcp.json` to inspect the MCP server card specification.

**Request:**
```http
GET /.well-known/mcp.json HTTP/1.1
Host: api.superdocs.app
User-Agent: SuperDocs-AgentConnectionWalkthrough/1.0
```

**Response (HTTP 200 OK):**
```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json",
  "name": "app.superdocs/superdocs",
  "version": "1.0.0",
  "title": "SuperDocs",
  "remotes": [
    {
      "type": "streamable-http",
      "url": "https://api.superdocs.app/mcp",
      "headers": [
        {
          "name": "Authorization",
          "description": "Bearer API key (sk_...). Get one instantly at POST /v1/agents/signup",
          "isRequired": true,
          "isSecret": true
        }
      ]
    }
  ],
  "_meta": {
    "signup_endpoint": "https://api.superdocs.app/v1/agents/signup",
    "documentation": "https://docs.superdocs.app"
  }
}
```

*Why it matters:* Allows standard registries and AI agents to dynamically learn the remote endpoint transport type, required headers, and documentation URLs.

---

### Step 2: Unauthenticated Probe (401 Authorization Challenge)

The agent attempts an unauthenticated MCP `initialize` request to test endpoint security.

**Request:**
```http
POST /mcp/ HTTP/1.1
Host: api.superdocs.app
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": { "name": "walkthrough-probe", "version": "1.0.0" }
  }
}
```

**Response (HTTP 401 Unauthorized):**
```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer realm="OAuth", resource_metadata="https://api.superdocs.app/mcp/.well-known/oauth-protected-resource", error="invalid_token", error_description="Missing or invalid access token"
Content-Type: application/json

{"detail": "Missing or invalid access token"}
```

*Why it matters:* Following RFC 9728, the server advertises its protected resource metadata endpoint in the `WWW-Authenticate` header's `resource_metadata` parameter.

---

### Step 3: RFC 9728 Protected Resource Metadata Retrieval

The agent fetches metadata from `GET https://api.superdocs.app/mcp/.well-known/oauth-protected-resource`.

**Request:**
```http
GET /mcp/.well-known/oauth-protected-resource HTTP/1.1
Host: api.superdocs.app
```

**Response (HTTP 200 OK):**
```json
{
  "resource": "https://api.superdocs.app/mcp",
  "bearer_methods_supported": ["header"],
  "resource_documentation": "https://docs.superdocs.app/account/api-keys",
  "resource_name": "SuperDocs MCP Server",
  "signup_endpoint": "https://api.superdocs.app/v1/agents/signup"
}
```

*SuperDocs Specific Note:* Traditional OAuth flows require an Authorization Server (`.well-known/oauth-authorization-server`), user login, and redirect callbacks. SuperDocs simplifies this for autonomous agents by providing a direct `signup_endpoint` returning a Bearer API key (`sk_...`).

---

### Step 4: Credential Acquisition & Local Cache

If no cached API key is present in environment variable `SUPERDOCS_API_KEY` or `~/.superdocs/agent_credentials.json`, the client calls the signup endpoint.

**Request:**
```http
POST /v1/agents/signup HTTP/1.1
Host: api.superdocs.app
Content-Type: application/json

{
  "terms_accepted": true,
  "agent_name": "connection-walkthrough-demo"
}
```

**Response (HTTP 201 Created):**
```json
{
  "account_id": "27d177fa-ad19-47eb-8aea-285202b8cd27",
  "slug": "connection-walkthrough-demo-5d3300",
  "api_key": "sk_1813828cc628c9a0a93b46518e83ecf5",
  "quota": {
    "tier": "free",
    "monthly_limit": 500,
    "used": 0,
    "remaining": 500,
    "resets_at": "2026-09-01T00:00:00+00:00"
  },
  "endpoints": {
    "mcp": "https://api.superdocs.app/mcp",
    "whoami": "https://api.superdocs.app/v1/agents/whoami"
  }
}
```

The key is cached locally to `~/.superdocs/agent_credentials.json`. Future runs validate the key via `GET /v1/agents/whoami` instead of creating duplicate accounts.

---

### Step 5: Authenticated MCP Handshake & Tool Invocation

With a valid Bearer token, the client initiates the Streamable HTTP MCP session over `https://api.superdocs.app/mcp/`.

#### 1. MCP Initialize
**Request:**
```http
POST /mcp/ HTTP/1.1
Host: api.superdocs.app
Authorization: Bearer sk_1813828cc628c9a0a93b46518e83ecf5
Accept: application/json, text/event-stream
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": { "name": "agent-connection-walkthrough", "version": "1.0.0" }
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2024-11-05",
    "serverInfo": { "name": "SuperDocs", "version": "3.4.0" },
    "capabilities": {
      "tools": { "listChanged": true },
      "resources": { "subscribe": false }
    }
  }
}
```

#### 2. MCP Initialized Notification
```http
POST /mcp/ HTTP/1.1
Authorization: Bearer sk_1813828cc628c9a0a93b46518e83ecf5

{"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
```

#### 3. Tool Calls (`health` & `get_account_status`)
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": { "name": "health", "arguments": {} }
}
```
**Output:** `{"status": "healthy", "service": "superdocs-backend"}`

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": { "name": "get_account_status", "arguments": {} }
}
```
**Output:** `{"account_id": "27d177fa...", "tier": "free", "quota": {"remaining": 500, "monthly_limit": 500}}`

---

## Sample Terminal Output

Below is an actual terminal transcript running `python connect.py`:

```text
======================================================================
 SUPERDOCS AUTHENTICATED AGENT CONNECTION WALKTHROUGH
 Demonstration of RFC 9728 Discovery + Bearer Key MCP Handshake
======================================================================

======================================================================
 STEP 1: DISCOVER SERVER CARD
 GET https://api.superdocs.app/.well-known/mcp.json
======================================================================

--> Request: GET https://api.superdocs.app/.well-known/mcp.json
<-- Response: HTTP 200
[+] Found Server Card: 'app.superdocs/superdocs' v1.0.0
    - Remote MCP Endpoint : https://api.superdocs.app/mcp
    - Required Auth Header: Authorization (Bearer API key (sk_...))
    - Signup Endpoint Hint: https://api.superdocs.app/v1/agents/signup

======================================================================
 STEP 2: UNAUTHENTICATED PROBE
 POST https://api.superdocs.app/mcp/ (Expect HTTP 401)
======================================================================

--> Request: POST https://api.superdocs.app/mcp/
    Body: {"jsonrpc": "2.0", "id": 1, "method": "initialize"...}
<-- Response: HTTP 401
[+] Captured WWW-Authenticate Header:
    Bearer realm="OAuth", resource_metadata="https://api.superdocs.app/mcp/.well-known/oauth-protected-resource"
[+] Discovered Protected Resource Metadata URL:
    https://api.superdocs.app/mcp/.well-known/oauth-protected-resource

======================================================================
 STEP 3: FETCH RFC 9728 METADATA
 GET https://api.superdocs.app/mcp/.well-known/oauth-protected-resource
======================================================================

--> Request: GET https://api.superdocs.app/mcp/.well-known/oauth-protected-resource
<-- Response: HTTP 200
[+] Resource Identified       : https://api.superdocs.app/mcp
[+] Supported Auth Methods    : header
[+] Self-Signup Endpoint      : https://api.superdocs.app/v1/agents/signup

======================================================================
 STEP 4: CREDENTIAL ACQUISITION / REUSE
 Manage Bearer API Key (https://api.superdocs.app/v1/agents/signup)
======================================================================

[+] Found cached credentials file at ~/.superdocs/agent_credentials.json
    Account ID: 27d177fa-ad19-47eb-8aea-285202b8cd27
    API Key   : sk_18...ecf5
[+] Key validated successfully via GET https://api.superdocs.app/v1/agents/whoami

======================================================================
 STEP 5: AUTHENTICATED MCP CONNECTION
 Streamable HTTP Session over https://api.superdocs.app/mcp/
======================================================================

--> [1/4] Sending MCP 'initialize' request...
<-- [1/4] MCP Connected to Server: SuperDocs v3.4.0
--> [2/4] Sending MCP 'notifications/initialized'...
<-- [2/4] Notification acknowledged.
--> [3/4] Requesting available tools ('tools/list')...
<-- [3/4] Server exposes 38 tools.
--> [4/4] Executing tool calls ('health', 'get_account_status')...
    [Tool: health]             -> status: healthy, service: superdocs-backend
    [Tool: get_account_status] -> account: 27d177fa..., tier: free, ops left: 500/500

======================================================================
 WALKTHROUGH EXECUTION SUMMARY
======================================================================
 [x] Step 1: Discovered Server Card (/.well-known/mcp.json)
 [x] Step 2: Probed Unauthenticated Endpoint (Caught HTTP 401)
 [x] Step 3: Parsed RFC 9728 Metadata (oauth-protected-resource)
 [x] Step 4: Acquired/Loaded Bearer Credentials
 [x] Step 5: Completed Authenticated MCP Tool Handshake & Calls
```

---

## Developer Integration Checklist

When implementing SuperDocs agent connection logic in your own framework:

- [ ] **Step 1:** Fetch `GET https://api.superdocs.app/.well-known/mcp.json` to discover server capabilities.
- [ ] **Step 2:** Parse the `WWW-Authenticate` header on `401 Unauthorized` responses to extract `resource_metadata`.
- [ ] **Step 3:** Fetch `GET .../oauth-protected-resource` to extract `signup_endpoint`.
- [ ] **Step 4:** Check local store (`~/.superdocs/agent_credentials.json` or `SUPERDOCS_API_KEY`) and validate with `GET /v1/agents/whoami`.
- [ ] **Step 5:** If missing, auto-signup via `POST /v1/agents/signup` with `{"terms_accepted": true, "agent_name": "..."}`. Store `api_key` securely.
- [ ] **Step 6:** Pass header `Authorization: Bearer <api_key>` on all MCP calls (`/mcp/`) and REST endpoints (`/v1/chat`).

---

## Troubleshooting

| Symptom | Cause | Solution |
|---------|-------|----------|
| **HTTP 401 on `/mcp/`** | Missing or invalid API key | Complete Step 4 signup or verify `SUPERDOCS_API_KEY` format (`sk_...`). |
| **HTTP 404 on OAuth AS endpoints** | SuperDocs does not use standard OAuth AS redirects | SuperDocs uses direct agent signup. Follow RFC 9728 `signup_endpoint` instead of looking for authorization servers. |
| **Quota limit reached** | Free tier monthly cap (500 ops) | Check remaining operations using the `get_account_status` tool or `POST /v1/agents/handoff` to transfer to a human account. |
| **Dry-run without creating accounts** | Testing connection logic safely | Run `python connect.py --discover-only` to stop after discovery steps. |

---

## SuperDocs Features Used

- **MCP Discovery:** Standard Server Card (`/.well-known/mcp.json`)
- **RFC 9728 Metadata:** Protected Resource Metadata (`/mcp/.well-known/oauth-protected-resource`)
- **Autonomous Agent Signup:** Instant Bearer key creation (`POST /v1/agents/signup`)
- **Account Verification:** Identity & quota inspection (`GET /v1/agents/whoami`)
- **MCP Streamable HTTP:** Full JSON-RPC 2.0 tool invocation (`health`, `get_account_status`, and 38 document editor tools)
