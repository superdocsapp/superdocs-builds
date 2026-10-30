# Pinned specification sources

The mock and the contract suite are built against pinned copies of SuperDocs' published
surface. Nothing in this project retypes a shape from memory: if it is not in one of the
files below, it is not asserted.

## REST — `openapi.json`

| | |
|---|---|
| Source | `https://github.com/superdocsapp/docs` → `openapi.json` (repository root) |
| Pinned commit | `ac0d44c3d031fd0e338e7e78839162904ee69e79` |
| Commit date | 2026-07-24 |
| Fetched | 2026-08-10 |
| SHA-256 of the vendored file | `cc836ec7f7ca3b88c83d0d6b135b371b244229e58f96962cc2a2c62d74c439dd` |
| Contents | OpenAPI 3.1.0 · "Universal Document AI API" v2.0.0 · 77 paths · 66 schemas |

Refresh:

```bash
curl -fsSL https://raw.githubusercontent.com/superdocsapp/docs/main/openapi.json \
  -o spec/openapi.json
shasum -a 256 spec/openapi.json          # record the new digest here
```

A refresh is never silent — `scripts/watch_surface.py` (Phase 6) diffs the published file
against this pin on a schedule and opens an issue when they differ.

## MCP — `mcp-tools.json`

Captured in Phase 1 from an authenticated handshake against `https://api.superdocs.app/mcp/`
(`initialize`, `tools/list`, `prompts/list`). It is pinned separately because **the MCP tool
surface is served live from the SuperDocs backend** — the Claude Code plugin carries only a
manifest, so tools and prompts can change with no release anywhere. That makes this pin the
single most drift-prone artifact in the project, and the one the watcher checks most closely.

| | |
|---|---|
| Endpoint | `https://api.superdocs.app/mcp/` |
| Transport | Streamable HTTP |
| Auth | `Authorization: Bearer sk_…` — the same key as REST |
| Expected surface | 38 tools, 4 workflow prompts (per `docs.superdocs.app/mcp/available-tools`) |
| Status | **pending Phase 1** |
