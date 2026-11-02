# SuperDocs MCP Tool Explorer

A developer tool for inspecting and calling the live [SuperDocs](https://superdocs.app) MCP server from a browser. It discovers tools at runtime, builds a form from each tool's input schema, validates the arguments, executes the tool, and shows the response.

It exists so you can try SuperDocs tools without installing or configuring a local MCP client.

## What it uses

- SuperDocs MCP server at `https://api.superdocs.app/mcp/` ([MCP setup](https://docs.superdocs.app/mcp/setup))
- Streamable HTTP transport
- `Authorization: Bearer sk_…` on every MCP request
- The MCP handshake (`initialize`, `notifications/initialized`) and the `Mcp-Session-Id` header, handled by the official TypeScript MCP SDK
- `tools/list` (including cursor pagination) and `tools/call`

Tool names and input schemas are whatever the server returns. Nothing in the UI is a catalog of SuperDocs tools.

## Architecture

```
Browser
  → Explorer UI (schema-driven form)
  → Explorer HTTP API
  → MCP client session (official SDK, in this process)
  → https://api.superdocs.app/mcp/
```

The API key stays on the server. Either set `SUPERDOCS_API_KEY` in the server environment, or paste a key into the UI. A pasted key is sent once on `POST /api/sessions` and kept in memory for that session. It is not written to the client bundle, returned by the API, or logged.

Sessions are in memory. Restarting the process drops them. Idle sessions close after 30 minutes.

## Local setup

Requirements: Node.js 20 or newer.

```bash
cd extensions/theshloksschauhan/mcp-tool-explorer
npm install
copy .env.example .env
```

On macOS or Linux, use `cp .env.example .env`.

Edit `.env` only on your machine. Do not commit it.

| Variable | Required | Purpose |
|---|---|---|
| `SUPERDOCS_API_KEY` | No | Server-side key. When set, the UI does not ask for a key. |
| `SUPERDOCS_MCP_URL` | No | Defaults to `https://api.superdocs.app/mcp/`. |
| `SUPERDOCS_EXPLORER_HOST` | No | Defaults to `127.0.0.1`. |
| `SUPERDOCS_EXPLORER_PORT` | No | Defaults to `8787`. |
| `SUPERDOCS_MCP_TIMEOUT_MS` | No | Per MCP request. Defaults to `60000`. |
| `SUPERDOCS_SESSION_TTL_MS` | No | Idle session lifetime. Defaults to `1800000`. |

Create a key from SuperDocs Settings, or follow the [API keys](https://docs.superdocs.app/account/api-keys) docs. The server card at `https://api.superdocs.app/.well-known/mcp.json` describes the same endpoint and the required Bearer header.

## Run

Development (API on port 8787, UI on port 5173 with `/api` proxied):

```bash
npm run dev
```

Open `http://127.0.0.1:5173`. Connect, search the discovered tools, fill the generated form, and execute.

Production:

```bash
npm run build
npm start
```

Open `http://127.0.0.1:8787`. The production server serves the built UI and the API on one port.

## Tests, types, and build

```bash
npm test
npm run lint
npm run build
```

`npm test` uses a local Streamable HTTP fixture and does not call SuperDocs. `npm run lint` is `tsc --noEmit`.

To run one real discovery and one real `health` call (the documented connectivity check) after tools are discovered:

```bash
# PowerShell
$env:SUPERDOCS_API_KEY = "sk_your_key_here"
npm run test:live
```

The live test skips when `SUPERDOCS_API_KEY` is unset.

## Deployment

1. `npm ci`
2. `npm run build`
3. Set `SUPERDOCS_API_KEY` only if every visitor should share one account. For more than one person, leave it unset and let each person enter their own key.
4. `npm start` behind HTTPS.
5. Keep the host on loopback unless a reverse proxy is in front of it.

Do not put the API key in any `VITE_` variable or in frontend source. The UI learns the endpoint from `GET /api/config`, which reports whether a server key is configured and never includes the key.

## How a call works

1. `POST /api/sessions` opens an MCP session.
2. `GET /api/sessions/:id/tools` calls `tools/list` until there is no `nextCursor`.
3. The form is generated from that tool's `inputSchema`.
4. Blank optional fields are omitted. Blank required fields are rejected with the field name. The same schema is checked again on the server before `tools/call`.
5. The result panel shows status, timing, the arguments that were sent, and the MCP result. Long strings and nested JSON collapse.

Supported schema shapes: string, number, integer, boolean, enum, array, object, nested object, required, optional, and nullable (`null` in `type`, or `anyOf` / `oneOf` with `null`). Schemas the form cannot represent become a JSON field. Ajv still checks the original schema.

## Limitations

- MCP prompts and resources are not listed. This app is a tool explorer.
- OAuth is not implemented. SuperDocs documents Bearer API keys for this endpoint; a 401 from the server is shown as an authentication failure.
- Sessions live in one process. More than one server instance does not share them.
- Request bodies are limited to 2 MB.
- A server-side `SUPERDOCS_API_KEY` means every visitor of that process calls SuperDocs as that account.
- Image and audio tool content is shown as JSON. Very long strings stay collapsed until you expand them.
- Tool errors (`isError: true`) are shown as results. Transport failures, timeouts, validation errors, and dropped sessions are shown as errors.
