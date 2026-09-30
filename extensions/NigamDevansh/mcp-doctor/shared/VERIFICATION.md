# How each claim in `shared/` was obtained

Decision D3 says client knowledge is **dated, evidence-backed data**, and that an
entry becomes write-capable only once its claims are *captured* rather than
*documented*. This file is the audit trail behind those tiers. It is meant to
age visibly: a claim whose date is old is a claim to re-check, not a claim to
trust harder.

Tiers used throughout:

| Tier | Meaning |
| --- | --- |
| `captured` | Read from a real installation, or round-tripped through a real file. |
| `documented` | Taken from the client's or server's official documentation. Not yet observed here. |
| `unverified` | Neither. Reported to the user as low confidence; never write-capable. |

---

## Endpoint profile — `profile/superdocs.json`

**All `captured`, measured 2026-08-22** against `https://api.superdocs.app/mcp`
with read-only requests. No billable tool was called, so re-running the
verification costs nothing.

| Claim | How it was measured | Result |
| --- | --- | --- |
| Unauthenticated `initialize` → 401 | POST `initialize`, no `Authorization` header | `401`, body `{"detail":"Authentication required. Provide an sk_ or lce_ API key as Bearer token."}` |
| Unauthenticated `tools/list` → 401 | POST `tools/list`, no credential | `401`, same body |
| The 401 fingerprint | response headers of the above | `www-authenticate: Bearer realm="OAuth", resource_metadata="https://api.superdocs.app/mcp/.well-known/oauth-protected-resource", error="invalid_token"` |
| Key prefixes | the 401 body names them explicitly | `sk_` **and** `lce_` |
| Discovery document | `GET /mcp/.well-known/oauth-protected-resource`, no credential | `200` with `resource`, `bearer_methods_supported: ["header"]`, `resource_documentation`, `resource_name` |
| `Accept` requirement | authenticated `initialize` with four `Accept` values | `application/json` → 200; `application/json, text/event-stream` → 200; `*/*` → **406**; `text/html` → **406**; header absent → **406** |
| Protocol negotiation | authenticated `initialize` with four `protocolVersion` values, then again via the `MCP-Protocol-Version` header | all → **200**. `2026-07-28` answered `2025-11-25`; `2025-11-25` answered itself; `2025-06-18` and `2024-11-05` answered themselves |
| Inventory | authenticated `tools/list`, `prompts/list`, `resources/list` | 38 tools, 4 prompts, 0 resources |
| Statelessness | response headers on `initialize` | no `Mcp-Session-Id` |

### A correction worth recording

An earlier draft of the plan claimed SuperDocs **rejects** the modern
`2026-07-28` protocol version. Measurement showed the opposite: it negotiates,
answering with `2025-11-25` and `HTTP 200`. Building on the original claim would
have made mcp-doctor tell developers their client's protocol version was broken
and send them to change a working configuration — a false positive of exactly
the kind this tool exists to eliminate.

`tools/validate_contract.py` now fails the build if
`protocol.rejects_unknown_versions` is ever set back to `true`.

---

## Client registry — `clients/claude-code.json`

Path evidence is recorded **per operating system**. An earlier revision carried a
single global `captured` alongside a list of unverified platforms, which reads as
a blanket claim: anything checking `evidence.paths.status` would have trusted
Windows on the strength of a macOS observation. Now each platform carries its own
tier, and `write_capable` is likewise per-OS.

| Claim | Tier | Evidence |
| --- | --- | --- |
| Config path, macOS | `captured` | `~/.claude.json` confirmed present on a real installation, 2026-08-22, while running inside Claude Code. |
| Config path, Linux | `unverified` | Same path expected; no Linux installation available. |
| Config path, Windows | `unverified` | No Windows installation available. |
| Remote-HTTP server schema | `documented` | From Claude Code's published MCP documentation. **No MCP server was configured on this machine to read back**, so the shape has not been observed here. |
| Repairs | `unverified` | No repair round-tripped. `repairs.allowed` is empty and every `write_capable` platform is `false`. |

Expansion is defined in `path-bases.json`, not in registry entries: a location
names a `base` (`home`, `project_root`, `app_config`, `app_data`) and a relative
path. Registry paths may not contain `~`, `%VAR%` or backslashes — enforced by
both the schema and the validator — so neither implementation invents platform
behaviour and then disagrees with the other about which file it is reading.

## Client registry — `clients/vscode.json`

Added so JSONC has a home in the fixture corpus. Every claim is `documented` or
weaker, and no platform is write-capable.

| Claim | Tier | Evidence |
| --- | --- | --- |
| Config path, macOS | `documented` | The containing directory (`~/Library/Application Support/Code/User`) was confirmed present, but **no `mcp.json` existed to capture**. Directory evidence is not file evidence. |
| Config path, Linux / Windows | `unverified` | No installation available. |
| Schema | `documented` | VS Code's top-level key is `servers`, **not** `mcpServers` — the most common cross-client mistake, and why the container key is data rather than a constant. |

### What must happen before `--fix` touches a Claude Code config

1. Configure a real remote-HTTP MCP server in Claude Code.
2. Read back the written entry and compare it against `http_server_schema`.
3. Promote `evidence.schema` to `captured` with that date.
4. Add repair fixtures that round-trip, and promote `evidence.repairs`.
5. Only then set `write_capable: true` and populate `repairs.allowed`.

The validator enforces this order: setting `write_capable: true` while evidence
is merely `documented` fails, and a non-empty `repairs.allowed` without
`write_capable` fails. The sequence cannot be short-circuited by editing one
field.

### Clients checked for but absent on this machine

Recorded so the gap is explicit rather than looking like an oversight:
Cursor (`~/.cursor/mcp.json`), VS Code user-level `mcp.json`, Windsurf, Cline
and Zed were all looked for on 2026-08-22 and are **not installed here**.
Claude Desktop's config exists at the documented macOS path but contains no
`mcpServers` key. None of these can be captured from this machine; each needs an
installation to verify against before it ships as write-capable.

---

## Client registry — `clients/codex.json`

The only TOML client, added because the contract declared TOML as a supported
format with nothing behind it.

| Claim | Tier | Evidence |
| --- | --- | --- |
| Config path, macOS | `captured` | `~/.codex/config.toml` read on a real installation (5.2KB) with live `[mcp_servers.*]` tables. `CODEX_HOME` was observed set inside that file, which is why `codex_home` is a base rather than a hardcoded path. |
| Config path, Linux / Windows | `unverified` | No installation available. `codex_home` has no Windows fallback, so the location is reported unresolvable rather than guessed. |
| Container + stdio shape | `captured` | `[mcp_servers.<name>]` with `command`, `args`, `env`, `cwd`, `enabled`, `startup_timeout_sec` — two real stdio servers read. |
| Remote-HTTP fields | `documented` | **Not observed.** Every server on that machine was stdio, so `url` and the header table name are unconfirmed and must be captured before any repair runs. |

One file holds model settings, plugin toggles, project trust levels *and* MCP
servers — the strongest argument in the whole contract for minimal span edits
over reserialising.

## Client registry — `clients/antigravity.json`

The client that **cannot hold a SuperDocs key**.

| Claim | Tier | Evidence |
| --- | --- | --- |
| Config path, macOS | `captured` | `~/.gemini/config/mcp_config.json` present on a real installation (Antigravity IDE.app). The file was **0 bytes** — a fresh client, not a corrupted one, which is why `config.file-empty` exists as a defect distinct from `config.invalid-syntax`. |
| Schema | `documented` | Read from documentation **shipped with the IDE** (`builtin/skills/agy-customizations/docs/mcp_servers.md`) — stronger than third-party docs, still not an observed config. |

Two findings from that document that changed the contract:

1. **The remote URL field is `serverUrl`, not `url`.** A doctor hunting for a
   field named `url` would report "no entry" with a working server in front of
   it. This is why the URL field is registry data.
2. **There is no headers field for either transport.** Grepping the document for
   *header*, *auth*, *token*, *bearer* and *api-key* returns nothing. SuperDocs
   authenticates with `Authorization: Bearer`, so a SuperDocs entry cannot be
   expressed in this client at all. That produced `scope.client-cannot-authenticate`,
   and a validator rule that a headerless client may not *plan* credential
   repairs — a fix that cannot work if followed is worse than no fix.

Its only documented remote transport is SSE, while SuperDocs answers in plain
JSON. Recorded as `sse_only` rather than assumed compatible; it would need
testing against a real client before any claim is made.

## Recorded exchanges — `fixtures/mcp-exchanges.json`

The evidence behind the profile, and the replay source for the fake server, so
step 2 is not built on prose. Each exchange is tiered:

| Tier | Exchanges |
| --- | --- |
| `captured` | unauthenticated 401 (initialize and tools/list), the `WWW-Authenticate` fingerprint, the discovery document, 406 for `*/*` and for an absent header, the authenticated handshake, both directions of protocol negotiation, tools/list |
| `constructed` | the interceptor 401 (we cannot conjure a real proxy), 403 (no key exists in that state, and provoking one would mean tampering with a real account), 429 (deliberately tripping a rate limit would be rude and would spend quota) |

Sanitisation is recorded per exchange. No request carries a real `Authorization`
value; the validator rejects any that does. Two exchanges are truncated — the
`instructions` prose and 35 of 38 tool objects — because the doctor counts tools
and never reads their schemas; both are marked `truncated` with the real totals.

## Config fixtures — `fixtures/*.cases.json`

Authored from the defect catalogue, not captured. They are the **specification**:
no implementation existed when they were written, so they define what both
implementations must do rather than describing what one happens to do.

Each case asserts **two runs separately** — a read-only `scan` and a `--fix` —
because a corpus that conflates them cannot prove that scanning changes nothing
or that fixing reports what it changed. Inputs are exact bytes (`raw_files`) and
repair expectations are exact bytes, since asserting on parsed *fields* would let
the two implementations reformat differently and both pass. That byte equality is
also the only way to prove the span-edit model preserves comments, CRLF and a BOM.

Every credential-shaped value carries a `fixture` marker, and both the validator
and a test assert that no unmarked credential-shaped string can enter the corpus.
