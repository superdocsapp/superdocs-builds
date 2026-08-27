# SuperDocs Builds

Community builds, extensions, integrations, and vertical AI agent workflows built on the [SuperDocs](https://superdocs.app) platform.

SuperDocs is an AI-native document editor operating directly inside documents rather than alongside them. It provides a web application, REST API, and a Model Context Protocol (MCP) server that enables AI agents to read, write, edit, and format documents programmatically.

---

## 📁 Repository Structure

This monorepo organizes community contributions into two primary categories:

```text
superdocs-builds/
├── README.md                                   # Monorepo documentation & system running guide
├── CONTRIBUTING.md                             # Guidelines for submitting new builds
├── LICENSE                                     # MIT License
├── use-cases/                                  # Full end-to-end applications & vertical workflows
│   └── README.md
└── extensions/                                 # Editor extensions, agent scripts, CLIs & integrations
    ├── README.md
    └── Shreyaskulkarni56/
        └── agent-connection-walkthrough/       # Reference RFC 9728 + MCP connection client
            ├── README.md                       # In-depth protocol walkthrough & specs
            ├── connect.py                      # Runnable Python client (pure stdlib HTTP)
            ├── requirements.txt                # Optional dependencies
            └── .env.example                    # Environment variable configuration template
```

| Folder | Description |
|---|---|
| [`use-cases/`](use-cases/) | Full vertical applications, document automation workflows, and end-to-end production demos. |
| [`extensions/`](extensions/) | Integrations, CLI tools, SDK wrappers, and agent connection protocols extending SuperDocs. |

---

## 🚀 Featured Extension: Authenticated Agent Connection Walkthrough

Located at [`extensions/Shreyaskulkarni56/agent-connection-walkthrough/`](extensions/Shreyaskulkarni56/agent-connection-walkthrough/), this extension provides a zero-dependency Python implementation and step-by-step documentation of how an autonomous AI agent connects to SuperDocs.

### Protocol Architecture & Discovery Flow

SuperDocs implements standards-based MCP authorization discovery (**RFC 9728 Protected Resource Metadata**) combined with autonomous agent self-signup (`/v1/agents/signup`), enabling headless AI agents to register and acquire Bearer API keys without human intervention.

```mermaid
sequenceDiagram
    autonumber
    participant Agent as Agent Client
    participant Card as Server Card (/.well-known/mcp.json)
    participant MCP as SuperDocs MCP Server (/mcp/)
    participant Meta as RFC 9728 Metadata
    participant Signup as Agent Signup API

    Agent->>Card: 1. GET /.well-known/mcp.json
    Card-->>Agent: Returns Server Card & signup hint
    
    Agent->>MCP: 2. POST /mcp/ (Unauthenticated initialize)
    MCP-->>Agent: 401 Unauthorized + WWW-Authenticate header
    
    Agent->>Meta: 3. GET /mcp/.well-known/oauth-protected-resource
    Meta-->>Agent: Returns RFC 9728 metadata (signup_endpoint, bearer_methods)
    
    alt Cached Credentials Found
        Agent->>Signup: 4a. GET /v1/agents/whoami (Validate Bearer key)
        Signup-->>Agent: 200 OK (Account active & quota status)
    else No Credentials Found
        Agent->>Signup: 4b. POST /v1/agents/signup (Agent name & terms)
        Signup-->>Agent: 201 Created (Bearer API Key sk_...)
    end
    
    Agent->>MCP: 5. POST /mcp/ (initialize with Authorization: Bearer sk_...)
    MCP-->>Agent: 200 OK (Server capabilities & 38 document tools)
    
    Agent->>MCP: 6. POST /mcp/ (tools/call 'health' & 'get_account_status')
    MCP-->>Agent: Tool execution response
```

---

## 🛠️ System Running Procedure

Follow these step-by-step instructions to run and test the SuperDocs Agent Connection Walkthrough locally.

### Step 1: Prerequisites

- **Python 3.10+** (uses standard library `urllib`, `json`, `ssl`; no external pip packages strictly required).
- Internet connectivity to access `https://api.superdocs.app`.

### Step 2: Navigate to Project Directory

Open your shell and change directory into the walkthrough folder:

```bash
cd extensions/Shreyaskulkarni56/agent-connection-walkthrough
```

### Step 3: Run System Execution Modes

#### Mode 1: Dry-Run / Discovery-Only (Safe Probing)
Executes protocol Steps 1–3 only. Probes the server card, catches the 401 challenge, and fetches RFC 9728 metadata without creating an account or using API quota.

```bash
# Windows
py connect.py --discover-only

# Linux / macOS
python3 connect.py --discover-only
```

#### Mode 2: Full End-to-End Autonomous Flow
Executes all 5 steps: discovers endpoints, creates a new agent account via self-signup, saves credentials to `~/.superdocs/agent_credentials.json`, performs the MCP HTTP handshake (`initialize` & `notifications/initialized`), lists all 38 available document tools, and executes the `health` and `get_account_status` tools.

```bash
py connect.py --agent-name my-first-agent
```

#### Mode 3: Skip Signup & Reuse Credentials
Reuses previously cached credentials stored at `~/.superdocs/agent_credentials.json` or provided via the `SUPERDOCS_API_KEY` environment variable. Validates the key via `GET /v1/agents/whoami` before initiating the MCP session.

```bash
# Option A: Using cached file
py connect.py --skip-signup

# Option B: Passing environment variable
set SUPERDOCS_API_KEY=sk_your_existing_api_key
py connect.py --skip-signup
```

#### Mode 4: Verbose Debug Mode
Prints full HTTP request headers, raw JSON bodies, and full server payloads:

```bash
py connect.py --verbose
```

---

## 💻 Integration Snippets for MCP Clients

Once your agent obtains an API key (`sk_...`), configure your editor or agent framework to connect to SuperDocs MCP:

### 1. Cursor / Windsurf / Cline / Continue (Native Remote HTTP)

Add to `.cursor/mcp.json` or your extension settings:

```json
{
  "mcpServers": {
    "superdocs": {
      "url": "https://api.superdocs.app/mcp",
      "headers": {
        "Authorization": "Bearer sk_your_api_key_here"
      }
    }
  }
}
```

### 2. Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "superdocs": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-http",
        "https://api.superdocs.app/mcp"
      ],
      "headers": {
        "Authorization": "Bearer sk_your_api_key_here"
      }
    }
  }
}
```

---

## 🤝 Contributing

Contributions are welcome! To add your own application or extension:

1. Fork this repository.
2. Create your project folder following the naming convention:
   - `use-cases/<github-username>/<project-name>/`
   - `extensions/<github-username>/<project-name>/`
3. Include a detailed `README.md` with setup instructions and features used.
4. Submit a Pull Request. Details are available in [CONTRIBUTING.md](CONTRIBUTING.md).

---

## 🔗 Useful Links

- **Product Web App**: [use.superdocs.app](https://use.superdocs.app)
- **Developer Documentation**: [docs.superdocs.app](https://docs.superdocs.app)
- **Agent Signup API Docs**: [docs.superdocs.app/introduction/agent-signup](https://docs.superdocs.app/introduction/agent-signup)
- **Contact**: hello@superdocs.app

---

## 📜 License

This project is licensed under the [MIT License](LICENSE).

