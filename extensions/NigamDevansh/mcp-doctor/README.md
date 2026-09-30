# mcp-doctor

A CLI for the developer whose MCP client says **“server failed to connect”** and
nothing more. It finds SuperDocs configurations, explains the real problem in
plain English, and — with `--fix` — backs them up, repairs what is safe, tests
the resulting configuration, and prints the outcome. Live MCP connection
verification is a later delivery step; the current CLI reports it honestly as
`connection: "not-attempted"` rather than claiming a network check it did not run.

Planned to ship as two native implementations from one shared source of truth:
`npx @superdocs/mcp-doctor` (TypeScript) and
`uvx --from superdocs-mcp-doctor mcp-doctor` (Python). Neither wraps the other.

See [PLAN.md](PLAN.md) for the full design.

---

## Status: delivery step 4 of 6 — native Python diagnosis

Step 1 delivered the shared contract, step 2 the first implementation, step 3
the repair engine: backup, minimal span edits, an unchanged-bytes assertion,
re-parse and re-scan.

Step 4 adds a native Python scanner for `uvx`. It packages the same shared
contract as the Node CLI and covers the same JSON, JSONC and TOML scan corpus.
Both CLIs now have independent source-preserving `--fix` engines and apply the
same evidence gate; neither writes a developer configuration until that
client's live-install evidence permits it.

**`--fix` currently writes nothing, and that is correct.** Every write is gated
on the client's evidence being `captured` from a real installation, and no
client has reached that yet, so the run reports why instead:

```
i Claude Code: config.no-entry not repaired — Claude Code is not write-capable
  on darwin: its configuration knowledge is 'documented', not captured from a
  real installation
```

The engine itself is proven against the shared corpus, whose fix expectations
are literal bytes. On a client with evidence promoted, one pass gives:

```
✓ Claude Code: backed up → .mcp.json.mcp-doctor-20260823-174603.bak
✓ Claude Code: set Accept to application/json
✓ Claude Code: write Bearer once
✓ Claude Code: set the path to /mcp
✓ Claude Code: use https://
✓ Claude Code: set type to http
5 changes written.
```

— with the file's `// comment` and its trailing comma untouched, and the backup
at `-rw-------`.

```bash
cd node && npm install && npm run build
node dist/cli.js                       # scan every supported client
node dist/cli.js --client claude-code  # one client
node dist/cli.js --config path/to.json # one file
node dist/cli.js --json                # machine-readable
node dist/cli.js --report              # redacted Markdown for a support thread

# after publishing
uvx --from superdocs-mcp-doctor mcp-doctor --client claude-code
```

`npm test` needs no build: the contract is read from `shared/` directly, and the
published snapshot is produced at `prepack` only. A snapshot that existed during
development could shadow the real contract, so tests would pass against stale
data — the exact failure the shared contract is meant to prevent.

Four clients, three config formats, all driven from `shared/`:

| Client | Format | Container key | Notes |
| --- | --- | --- | --- |
| Claude Code | JSON | `mcpServers` | `.mcp.json`, `~/.claude.json` |
| VS Code | JSONC | `servers` | comments and trailing commas |
| OpenAI Codex | TOML | `mcp_servers` | `CODEX_HOME`-anchored |
| Antigravity IDE | JSON | `mcpServers` | `serverUrl`; **cannot carry a key** |

```
shared/
  schema/       JSON Schema for every data file, including the --json wire contract
  profile/      the SuperDocs endpoint profile, live-measured and dated
  defects.json  every finding either implementation may emit + the placeholder policy
  path-bases.json  what 'home', 'project_root', 'app_config' mean per platform
  clients/      one registry entry per MCP client — locations, shape, allowed repairs
  fixtures/     *.cases.json — config corpus, exact bytes in and out
                mcp-exchanges.json — recorded HTTP exchanges for the fake server
  VERIFICATION.md  how each claim was obtained, and what is not yet verified
tools/          the contract validator
tests/          proves the validator rejects what it must reject
node/           the TypeScript implementation (npx @superdocs/mcp-doctor)
  src/          contract, paths, parsers, diagnose, render, cli
  test/         the shared fixtures run as the spec, plus span/BOM/CRLF units
```

## Run it

```bash
uv run --with jsonschema python tools/validate_contract.py
```
```bash
uv run --with jsonschema --with pytest pytest tests/ -q
```

---

## What the contract fixes in place

**One pinned destination for the key.** `canonical.url` is the only address that
ever receives a user's credential, so it is pinned to a literal in the schema and
then re-parsed by the validator: no other host, no embedded credentials, no port,
no query, no fragment, and redirects off. The discovery URL is *derived* from it
rather than specified separately. Eight negative tests try to repoint it — a
lookalike host, a downgraded scheme, userinfo — and every one must fail the build.

**The host rule.** `--fix` may repair a URL's scheme, path or trailing slash, but
**never its host**. An entry pointing at a policy gateway, egress proxy,
self-hosted relay or staging endpoint is pointing there on purpose; rewriting it
to the vendor endpoint would silently disable controls the tool cannot see. The
rule is enforced four ways: no host-targeting fix kind may exist, no out-of-scope
defect may be auto-fixable, fixtures assert `--fix` leaves such files
byte-identical, and those fixtures must also assert no probe is sent to the host.

**Credentials cannot reach the output.** A URL can carry a secret in its userinfo
(`https://secret@gateway.example/mcp`), and a finding is rendered into the
terminal, `--json` *and* the Markdown a developer pastes into a support thread.
So message templates interpolate `{host}`, never `{url}` — enforced by a
forbidden-placeholder list the validator checks, rather than by remembering it at
each of 29 defects.

**Evidence before write access, per OS.** Verifying a path on macOS says nothing
about Windows, so path evidence and `write_capable` are both per-platform. The
validator fails the build if any platform is marked write-capable while its path
evidence, the schema evidence, or the repair evidence is not `captured`. Both
shipped clients are `false` everywhere for exactly that reason.

**Repairs are pinned to exact bytes.** Every case asserts a read-only `scan` and
a `--fix` run separately, with literal file content before and after. Asserting
parsed *fields* would let TypeScript and Python reformat differently and both
pass — which is the drift conformance exists to catch. It is also the only way to
prove a span edit preserves comments, trailing commas, CRLF and a BOM, each of
which has its own fixture.

**Protocol versions are never a fault.** Measurement showed SuperDocs
*negotiates* versions rather than rejecting them, so diagnosing one as broken
would send developers to change working configs. The validator refuses to let
that claim come back.

**Determinism, designed in.** The `--json` contract specifies a deterministic
mode — no timestamps, no durations, relative paths, fixed ordering — because the
conformance suite compares the two implementations byte-for-byte, and retrofitting
that onto a shipped format is painful.

---

## What step 2 proved

**The two-implementation design earned its keep before Python existed.** The
registry matched server names with `(?i)^superdocs` — valid Python, and a hard
`SyntaxError` in JavaScript. A single-language build would have shipped it. The
pattern and its flags are now separate fields, and the validator rejects inline
flag groups so it cannot come back.

**Spans are collected in the read-only step**, though nothing writes yet. The
span-edit model only works if the parser can point at the exact bytes of a value,
and discovering in step 3 that it cannot would mean rewriting the parsing layer
underneath a finished diagnosis layer. Unit tests assert a value's span selects
that value and nothing else — through a BOM, through CRLF, and around a block
comment sitting between a key and its value.

**Reading is wide; writing is narrow.** The default scan covers all four
registered clients, because reading a config cannot damage it — and reading all
four is what surfaced `serverUrl`, the headerless client and three container
keys. Writing is gated separately: no client is write-capable, `--fix` is
refused, every client reports its evidence tier, and any client whose knowledge
is not `captured` is named as read-only and experimental in the output. Plan
§13 step 2 records that revision and why.

**Silent failures are reported, not swallowed:**

- A repeated JSON key — the last wins, so a wrong `url` above a right one looks
  like a working config that does not work. Reported, never auto-fixed:
  deleting one of a developer's two lines is a guess about intent.
- A SuperDocs entry under `projects[*].mcpServers` — the registry declares that
  container, so it is read rather than reported as "no entry".
- A flag with no value (`--client` alone) — a usage error, not a silent
  full scan exiting 0 with a confident answer to a different question.

## What step 3 proved

**Two fixes on one field must compose.** A wrong scheme and a wrong path both
live in `url`. Computing each from the original parse meant the second write
discarded the first — the run *reported* repairing the path while the file still
said `/v1/mcp`, and a second run was needed. A successful-looking repair that did
not happen is worse than a refusal. The entry is now re-read after every applied
fix, and a regression test asserts both corrections survive.

**The span assertion is per step, not per run.** Every applied edit shifts the
offsets of the ones after it, so checking an accumulated list at the end would
compare spans against bytes they no longer address. Each fix is verified against
the text its offsets were computed from, and any failure abandons the whole file
rather than writing a change the tool cannot vouch for.

**The runtime re-checks the canonical endpoint.** `validate_contract.py` pins it,
but that runs in CI against the repository and says nothing about the bytes
actually loaded. A vendored or substituted contract would otherwise decide where
an authenticated request goes, so `loadContract` refuses any profile that is not
the exact expected origin with redirects off.

## Next

Step 4 brings Python to parity against the same fixtures, after which the
conformance suite gates every change. Enabling `--fix` for a client is separate
from either: it needs that client's schema captured from a real installation,
per `shared/VERIFICATION.md`.
