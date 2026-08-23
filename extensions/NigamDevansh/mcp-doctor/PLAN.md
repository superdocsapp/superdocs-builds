# mcp-doctor — fix SuperDocs MCP setup

> Open-task-list card · BAND S2 · surfaces `MCP, API` · destination:
> a pull request into the public repository, `extensions/` folder.

A small CLI for the developer whose MCP client says **“server failed to
connect.”** It finds SuperDocs configurations, explains the real problem in
plain English, and—with `--fix`—backs them up, repairs every safe issue, checks
the connection, and prints the outcome.

Shipped as **two native implementations from one shared source of truth**: a
Python distribution for `uvx` and a TypeScript package for `npx`. Neither wraps
the other.

This is deliberately a **SuperDocs-only** tool. It supports clients configuring
`https://api.superdocs.app/mcp`; it is not a generic MCP doctor.

---

## 1. Decisions (locked)

| # | Decision | Choice |
| --- | --- | --- |
| D1 | Connection path | **Remote HTTP(S) only.** SuperDocs is a URL-addressed, Bearer-authenticated server. |
| D2 | Read vs write | **Read-only by default.** `--fix` is the consent — no prompt, no `--yes`. A timestamped backup is the recovery path. |
| D3 | Client knowledge | **Data, not conditionals.** A registry entry per client, dated and evidence-backed. Write-capable only after its version, OS path, shape and fixture are verified. |
| D4 | Key safety | **Never printed, never sent anywhere but the canonical endpoint.** Credential-free probes come first. |
| D5 | Distribution | **Two native implementations, one shared contract.** Pure Python on PyPI, pure TypeScript on npm. No frozen binaries, no cross-language shelling. |
| D6 | Edit model | **Span-based minimal source edits.** A fix is a list of `{span, replacement}` text splices computed from a parse tree — never a parse-and-reserialise. |

**Why D5 and D6 are the spine.** D5 is what makes the tool reachable: MCP client
users live in both ecosystems, and a Node developer should not need Python to
debug their editor. Publishing natively to each registry is `npm publish` and a
wheel — no per-platform executables, no signing, no notarisation. D6 is what
makes `--fix` safe *and* what makes two implementations verifiable: if a fix is
a list of text splices, then “every byte outside the edit is unchanged” is an
assertion, and “both languages produce the same splices” is a test.

---

## 2. Non-goals (v1, stated so the boundary is visible)

- **stdio servers.** A `command`/`args` local-process server is a different
  failure family. Detected and reported as “out of scope,” never silently
  ignored.
- **OAuth-configured clients.** SuperDocs advertises an OAuth flow at its
  protected-resource document (§5). A client using it rather than a static
  Bearer key is reported as unsupported, not misdiagnosed against Bearer rules.
- **Generic MCP diagnosis.** The canonical endpoint is the only one tested.
- **Anything behind a non-canonical host.** A policy gateway, egress proxy,
  self-hosted relay, staging endpoint or mock server is detected, named and
  **left completely alone** — not diagnosed, not repaired, and above all not
  rewritten to the vendor endpoint. See the host rule in §6. mcp-doctor carries
  no logic for these deployments in either direction: it neither supports them
  nor interferes with them.
- **Recursively searching the home directory.** Known locations only.

---

## 3. The simple user experience

```text
npx  --yes @superdocs/mcp-doctor
uvx  --from superdocs-mcp-doctor mcp-doctor
```

Scans supported client configuration locations and reports the state without
changing anything.

```text
npx  --yes @superdocs/mcp-doctor --fix
uvx  --from superdocs-mcp-doctor mcp-doctor --fix
```

Does the work without asking the developer to make repair decisions:

1. Finds every supported SuperDocs configuration.
2. Makes a timestamped backup beside every file it will change.
3. Repairs every unambiguous SuperDocs setup issue.
4. Re-parses the saved file and tests the real SuperDocs connection.
5. Prints a compact result: fixed, already healthy, or needs manual attention.

Both commands run the tool on demand; the developer installs nothing. Both are
native — the npm package is TypeScript, the PyPI distribution is Python — and
both expose identical arguments, output and exit codes.

`--fix` never changes a file when the client format is unknown, the file is
invalid, or two entries make the correct action ambiguous. Those cases get a
one-line manual instruction instead of a risky rewrite.

```text
✓ Cursor: backed up mcp.json → mcp.json.mcp-doctor-20260822-153012.bak
✓ Cursor: corrected SuperDocs URL and authorization header
✓ Cursor: connected to SuperDocs (38 tools, 4 prompts)
! Claude Desktop: two SuperDocs entries found; left unchanged
```

---

## 4. Scope and safety

- The only endpoint tested with a key is exactly
  `https://api.superdocs.app/mcp`.
- Keys are never printed, included in diffs/reports/errors, or placed on a
  command line. Authenticated requests do not follow redirects.
- Reachability checks use no credential.
- No telemetry: the only network destination is SuperDocs.
- `mcp-doctor` is read-only. `--fix` writes only safe, supported SuperDocs
  configuration edits and always creates a backup first.

**Backups contain the key.** A `.bak` of a config file is a plaintext copy of a
credential, and project-scoped configs (`.cursor/mcp.json`, `.vscode/mcp.json`,
`.mcp.json`) sit **inside a git working tree**. Therefore: backups are written
`0600` before content is added; when the target is inside a git repository and
not already ignored, the tool says so and prints the one-line `.gitignore`
addition. On Windows, POSIX modes do not apply — the backup inherits the
directory ACL and the tool states that limitation rather than implying a
protection it did not apply.

Supported clients are registry entries, not hard-coded conditionals. Unknown
clients can still be parsed and reported, but are never auto-edited.

---

## 5. What SuperDocs currently requires

Live-verified **2026-08-22** against the canonical endpoint with read-only
requests. These are dated observations; drift is expected and handled (§6).

| SuperDocs behaviour | Evidence | Doctor behaviour |
| --- | --- | --- |
| Unauthenticated `initialize` **and** `tools/list` → `401` | measured | This is the credential-free control: reachable and auth-gated, with no key sent. |
| The `401` carries `WWW-Authenticate: Bearer realm="OAuth", resource_metadata="…/.well-known/oauth-protected-resource", error="invalid_token"` | measured | **A SuperDocs fingerprint.** Distinguishes a genuine endpoint `401` from a corporate proxy or captive portal returning `401`/`407` — without which a proxy fault is misdiagnosed as a bad key. |
| `GET /mcp/.well-known/oauth-protected-resource` → `200`, **no credential** | measured | An unambiguous, machine-readable liveness probe. Also yields `resource_documentation` → the authoritative "where to get a key" URL to cite. |
| Keys are **`sk_` or `lce_`** | `401` body | Key-shape validation must accept both. A doctor that demands `sk_` rejects valid keys. |
| `Accept` must include `application/json`. **Absent, `*/*`, and `text/html` all → `406`** | measured | A first-class defect; the raw `406` explains nothing. `application/json, text/event-stream` is accepted. |
| **Protocol version is negotiated, not rejected.** `2026-07-28`, `2025-11-25`, `2025-06-18`, `2024-11-05` all → `200`; the server answers with the version it will use (`2026-07-28` negotiates down to `2025-11-25`). Same via the `MCP-Protocol-Version` header. | measured | **Never diagnose a version as a fault.** Send `initialize`, read `result.protocolVersion` back, report it as an observation. Treating a version as broken would send users to change a working config. |
| No `Mcp-Session-Id` returned | measured | Treat the sequence as stateless; tolerate a session header if one appears later. |
| `initialize` → `notifications/initialized` → lists succeeds | measured | The canonical authenticated sequence. |
| Current lists: 38 tools, 4 prompts, 0 resources | measured | Dated observation; warn on drift, never fail on it. |

The endpoint profile is stored as sanitised fixtures with an opt-in live test.
If SuperDocs changes, the doctor says **“connected with profile drift”** rather
than misdiagnosing a valid key.

---

## 6. Diagnosis and repair rules

| Result | How it is determined | `--fix` behaviour |
| --- | --- | --- |
| **Config** | Invalid/unsupported config, missing SuperDocs entry, wrong canonical URL, unresolved environment variable, malformed known header/transport, or duplicate entries | Repairs only exact, registry-approved cases; otherwise one manual step. |
| **Network** | DNS, TCP, TLS, proxy, certificate or timeout failure before auth — **or** a `401` lacking the SuperDocs fingerprint (§5), which indicates an interceptor, not the endpoint | Explains the underlying connection error; does not rewrite configuration. |
| **Auth** | Credential missing, or a fingerprinted `401`/`403` after the canonical authenticated sequence | Names the credential source, or says to rotate/check account access. Never changes a key. |
| **Profile drift** | Valid MCP response that differs from the dated profile | Reports the difference and the connection status; changes nothing. |

Safe automatic repairs, when the registry says the exact client/version form is
supported:

- normalising a URL that is **already on the canonical SuperDocs host** — scheme,
  trailing slash, or path near-miss (see the host rule below);
- adding or correcting the one SuperDocs entry in a known unambiguous location;
- repairing a known client-specific HTTP transport field;
- repairing a malformed known authorization-header shape without exposing the
  credential;
- repairing a client-specific header override that prevents accepting JSON;
- resolving a duplicate only when the registry has an explicit precedence rule.

The repair engine never guesses which entry to delete, invents a key, changes an
unknown URL, or rewrites syntactically broken configuration.

### The host rule

**`--fix` never changes the host of an entry.** URL repair is limited to entries
already pointing at `api.superdocs.app`; scheme, trailing slash and path are
repairable, the host never is.

An entry pointing somewhere else is pointing there **on purpose** — a policy
gateway or egress proxy, a self-hosted relay, a staging endpoint, a mock server
in a test suite. Rewriting it to the vendor endpoint would not fix a fault; it
would silently route a developer around whatever their organisation put in front
of SuperDocs, disabling controls the tool cannot even see. A diagnostic that
does that is more dangerous than the error it set out to explain.

So a non-canonical host is reported and left alone:

```text
i Cursor: SuperDocs entry points at http://localhost:8080/mcp, not the canonical
  endpoint. Left unchanged — mcp-doctor only diagnoses direct connections to
  api.superdocs.app.
```

Exit `0`: this is information, not a fault. mcp-doctor has no opinion about what
lives at that address and offers no diagnosis of it.

---

## 7. Configuration coverage

Every verified client registry entry defines:

- all supported user, workspace and project config paths per OS, plus
  precedence order;
- the exact format (`JSON`, `JSONC`, `TOML`), encoding and parser;
- the client schema for a remote HTTP SuperDocs server — transport, URL,
  headers, environment-variable interpolation;
- how a SuperDocs entry is identified even when named something other than
  `superdocs`;
- whether the client owns default headers itself or allows an override;
- the exact changes `--fix` may make for that client/version.

The scan handles absent files, unreadable files, symlinks, multiple project
roots and duplicate entries predictably, and reports every matching entry in
precedence order.

Validation covers: syntax (comments/trailing commas where supported), encoding,
duplicate keys where detectable; a canonical HTTPS URL with no embedded
credentials, unsupported path or fragment — a **non-canonical host is recorded
as an out-of-scope observation, never a defect** (§6 host rule); the correct
client-specific transport shape; case-insensitive header names, duplicate
authorization values, missing or doubled `Bearer`, an `Accept` override
incompatible with SuperDocs; environment placeholders and unset variables; and
entry collisions across scopes.

---

## 8. JSONC, TOML and the span-edit model

VS Code and some Cursor files are **JSONC** — JSON with comments and trailing
commas. Reading with a standard JSON parser fails; parse-then-reserialise
destroys comments, ordering and formatting. Neither is acceptable for `--fix`.

So no implementation ever reserialises a config. A fix is computed as **text
splices against the original bytes** (D6):

1. Parse to a tree that records a **source span** for every node.
2. Locate the target SuperDocs node.
3. Emit `{span, replacement}` edits.
4. Apply them to the original text, back to front.
5. Re-parse the result and assert every byte outside the edited spans is
   unchanged.

Step 5 is the safety property, and it is the same assertion in both languages.

| | TypeScript | Python |
| --- | --- | --- |
| JSON / JSONC | `jsonc-parser` (`parseTree`, `modify`, `applyEdits`) — Microsoft’s, purpose-built for exactly this | a small tolerant span-recording scanner (≈200 lines), conformance-tested against the TS output on every fixture |
| TOML | a span-capable TOML reader | `tomllib` for reading; the same span-splice writer |

If a safe source-preserving edit cannot be produced for a given file, that file
is **read-only**: reported, never reformatted, never comment-stripped.

---

## 9. One contract, two implementations

The real risk of shipping two native tools is that they drift into two different
answers. The control is that **almost nothing that decides an answer lives in
either language.**

```text
extensions/mcp-doctor/
  shared/                    ← the single source of truth (language-neutral)
    clients/*.json           ← registry: paths, precedence, schema, allowed repairs
    profile/superdocs.json   ← the dated endpoint profile from §5
    defects.json             ← defect ids, class, severity, message templates
    schema/*.json            ← JSON Schema for the above; both implementations validate
    fixtures/                ← config corpus + golden findings + golden fixed output
  node/                      ← npx @superdocs/mcp-doctor   (TypeScript)
  python/                    ← uvx --from superdocs-mcp-doctor mcp-doctor
  conformance/               ← runs BOTH over shared/fixtures, asserts identical --json
```

Client paths, defect definitions, repair permissions, message text and the
endpoint profile are **data**. Each implementation contributes only: file I/O,
a span-recording parser, an HTTP client, and rendering.

**The conformance suite is the gate.** It runs both binaries across every shared
fixture and asserts their `--json` output is identical, and that their `--fix`
output is byte-identical. A behaviour difference is a build failure, not a
discovery made by a user. This is the same principle the policy gateway used —
rules are data, code is thin — applied across a language boundary.

---

## 10. Commands, output and exit codes

```text
mcp-doctor                  scan and report
mcp-doctor --fix            backup, repair what is safe, re-check
mcp-doctor --client cursor  restrict to one client
mcp-doctor --config PATH    a specific file
mcp-doctor --key-env NAME   credential source (default SUPERDOCS_API_KEY)
mcp-doctor --report         redacted Markdown for a support thread
mcp-doctor --json           machine-readable findings
```

| Exit | Meaning |
| --- | --- |
| `0` | Healthy, fixed, or nothing to do |
| `1` | Manual action remains |
| `2` | Tool or usage error |

**“Nothing found” resolved.** Not using SuperDocs is not a failure, but asking
about something absent is:

- No supported client detected, or clients present with no SuperDocs entry →
  **exit 0**, informational, with a hint that `--fix` can add one.
- `--client X` named explicitly and X has no SuperDocs entry → **exit 1**; a
  direct question deserves a direct answer.
- `--fix` asked to add an entry with **no resolvable key** → **exit 1** naming
  the variable to set. It never writes a placeholder or invents a credential.
- `--fix` with a resolvable key and exactly one unambiguous location → adds the
  entry, verifies the connection, **exit 0**.

Normal terminal output stays short; `--report` and `--json` carry the detail,
fully redacted.

---

## 11. Implementation shape

```text
discover configs
      ↓
parse with the client’s format handler (span-recording)
      ↓
find SuperDocs entry + apply client registry rules
      ↓
credential-free probe: protected-resource document, then expected fingerprinted 401
      ↓
optional authenticated sequence: initialize → notifications/initialized → lists
      ↓
render  ── or ──  backup → span edits → re-parse → unchanged-bytes assert → re-check
```

Modules, mirrored in both languages: `discovery`, `config` (parsers + span
writers), `registry` (loads `shared/clients`), `superdocs` (URL validation +
MCP adapter), `diagnosis` (findings, classes, redaction), `fix` (backup, splice,
validate, atomic replace), `render` (text, JSON, Markdown).

Dependencies stay minimal: Node 20+ uses native `fetch` plus `jsonc-parser`;
Python uses `httpx` plus its own span scanner. Reuse `httpx`, the fake HTTP
transport, CLI/packaging conventions and redaction discipline from
`extensions/policy-gateway` — but **not as an MCP client**, since it is a
reverse proxy that forwards opaque bodies and never performs a handshake.

---

## 12. Tests

- client fixtures for every supported client/version/OS and repair rule;
- discovery fixtures: user/workspace/project precedence, multi-root workspaces,
  symlinks, missing and unreadable files, duplicate entries;
- syntax fixtures: JSON, JSONC, TOML; malformed source, duplicate keys,
  CRLF/BOM/encoding, header casing, environment substitution, credential-bearing
  URLs;
- **host-rule fixtures**: entries pointing at a policy gateway, an egress proxy,
  a self-hosted relay and a staging host, each asserting `--fix` leaves the file
  **byte-identical** and exits `0` with an out-of-scope note — the guarantee that
  no repair ever routes a developer around their own controls;
- SuperDocs fixtures: initialize, initialized notification, lists, 401 **with
  and without the fingerprint**, 403, 406, 404, 429, 5xx, and version
  negotiation (a newer proposal answered with an older version — asserted as
  healthy, never as a fault);
- a fake server asserting request order, headers and JSON-RPC bodies;
- network failures: DNS, timeout, proxy, certificate, redirect;
- redaction: no secret in terminal, diff, exception, JSON, Markdown or log —
  property-tested against every fixture key, in both languages;
- span edits: comments, block comments, trailing commas, CRLF, BOM, and the
  unchanged-bytes assertion outside every edit;
- fix safety: backup exists with the right mode, re-parse, atomic replace,
  idempotence, multi-file partial failure;
- **conformance: both implementations, same fixtures, identical output** (§9);
- opt-in live profile test using read-only calls only.

The default suites use fixtures and a fake server, so they need no key and
spend no SuperDocs quota.

---

## 13. Delivery order

Ordered so that the hardest problem is solved where the best tool for it exists,
and so either implementation can ship alone if the other slips.

1. **Shared contract.** `shared/` schemas, the §5 endpoint profile as fixtures,
   the defect catalogue, and the first client’s registry entry and fixtures.
   No executable yet — this is the artifact both implementations are judged
   against.
2. **TypeScript, read-only.** Discovery, parse, diagnose, render across **every
   registered client**, each surfaced with its evidence tier. Ships as
   `npx @superdocs/mcp-doctor`. **JSONC is proven here first**, where
   `jsonc-parser` already solves it.

   > **Revised during step 2.** This originally said "for one verified client",
   > written when the registry held one entry. It now holds four, spanning JSON,
   > JSONC and TOML — and reading them is what surfaced `serverUrl`, the
   > headerless client, and three different container keys. Restricting the
   > default scan to one client would discard that coverage without making
   > anything safer, because **reading is not the risk; writing is.**
   >
   > So the scope widens and the honesty tightens instead: no client is
   > write-capable, `--fix` is refused outright, every client reports its
   > evidence tier, and the CLI names any client whose knowledge is not
   > `captured` as read-only and experimental. Confidence is surfaced per
   > client rather than approximated by scanning fewer of them.
3. **TypeScript `--fix`.** Backup, span edits, unchanged-bytes assertion,
   re-check. Enabled per client only as evidence is promoted to `captured`,
   so the write surface stays narrower than the read surface.
4. **Python to parity.** Same shared data, same fixtures; the span scanner
   ported against a known-good target. The conformance suite becomes the gate
   from this point on.
5. **More clients, and promoting evidence.** Each client added as data plus
   fixtures — automatically covered in both languages — and each existing entry
   promoted from `documented` to `captured` against a real installation.
6. **Publish both.** `npm publish` and a PyPI wheel; verify `npx` and `uvx` from
   clean macOS, Linux and Windows environments, plus the opt-in live test.

Step 2 is already a useful artifact on its own: offline config diagnosis for
real clients. That matters, because the rubric rewards a simple build finished
immaculately over an ambitious one left half-done.

---

## 14. Risks

| Risk | Control |
| --- | --- |
| **Two implementations drift** | Everything decisive is shared data; conformance suite fails the build on any output difference (§9). |
| Two languages is more work than one | Shared data keeps per-language code thin; delivery order makes each independently shippable (§13). |
| Python has no `jsonc-parser` equivalent | Span-splice model needs only a span-recording scanner, not a writer; proven in TS first, then conformance-tested (§8). |
| Client schemas drift | Registry is dated, tiered data; the tool states its confidence rather than asserting stale certainty. |
| A confidently wrong `--fix` | Registry-approved cases only; backup first; ambiguity reported, never guessed. |
| Leaking a key to a wrong host | Authenticated request only to the canonical endpoint; no redirects; credential-free probes first (§4). |
| A backup leaking a key into git | `0600`, git-tree detection, `.gitignore` line printed; Windows limitation stated honestly (§4). |
| Misreading a proxy `401` as a bad key | The `WWW-Authenticate` fingerprint separates endpoint from interceptor (§5). |
| **`--fix` routing a developer around their own gateway** | The host rule: `--fix` never changes a host. A non-canonical endpoint is reported and left untouched, so no organisational control is ever disabled by a repair (§2, §6). Fixture-tested. |
| SuperDocs changes its MCP surface | Profile drift is a reported state, not a failure (§6). |
| Scope creep into stdio or OAuth | Explicit non-goals, detected and named in output (§2). |

---

## 15. Reuse from this repo

| Needed | Existing |
| --- | --- |
| Fake HTTP server for deterministic tests | `extensions/policy-gateway/tests/conftest.py` (`FakeUpstream`) |
| Recorded real SuperDocs responses to seed fixtures | `fixtures/superdocs_responses/` |
| CLI shape, console script, packaging | `extensions/policy-gateway/gateway/cli.py`, `pyproject.toml` |
| Redaction / never-log-a-credential discipline | the gateway’s audit-log content exclusion |
| “Rules are data, not code” | the gateway’s `policy.yml` and tiered defaults |
| uv, hatchling, ruff (line-length 100), pytest + `live` marker | the gateway extension throughout |

---

## 16. Success standard

A developer runs one zero-install command in the ecosystem they already have,
gets a backup automatically, and ends with either **connected** or a single
sentence naming the one thing a human must do — and the Node user and the Python
user get the identical answer, because a test proves they must.
