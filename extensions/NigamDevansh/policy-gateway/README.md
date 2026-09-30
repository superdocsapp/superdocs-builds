# Policy gateway

An MCP proxy that sits between your agent clients and SuperDocs. It enforces
per-team tool allowlists, scans content before it leaves your network, meters
spend, and writes a tamper-evident record of every call — without any agent
ever holding your `sk_` key.

Clients change a URL and a bearer token. No SDK change, no protocol change.

```
agent ──► gateway ──► api.superdocs.app/mcp
          │
          ├─ identity · envelope · strip authorization · allowlist
          ├─ argument policy · content scan · quota
          └─ audit (hash-chained, append-only)
```

---

## Quick start

```bash
cp .env.example .env                 # add SUPERDOCS_API_KEY
cp policy.yml.example policy.yml     # add your teams
gateway hash-token 'gw_legal_9f2c'   # → paste into policy.yml
docker compose up
```

If something already owns port 8080, set `GATEWAY_HOST_PORT=18080` in `.env` —
only the host side moves.

Point each client at `http://localhost:8080/mcp` using that team's token:

```bash
curl -X POST http://localhost:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json' \
  -H 'Authorization: Bearer gw_legal_9f2c' \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

Without a `policy.yml` the gateway runs as a transparent passthrough. That is
deliberate: put it in the path, confirm nothing breaks, then turn enforcement
on.

---

## The gate chain

| # | Gate | What it does |
| --- | --- | --- |
| ① | Identity | Gateway token → team. Unknown token: `401`, never forwarded. |
| ② | Envelope | Malformed JSON-RPC rejected before any policy runs. |
| ③ | Strip `authorization` | Removed from `arguments` unconditionally, and flagged in the audit entry. |
| ④ | Allowlist | Deny always beats allow. Enforced on `tools/call` *and* by filtering `tools/list`. |
| ⑤ | Argument policy | `force` rewrites, `deny` rejects, `max` caps ordered tiers. |
| ⑥ | Content scan | PII, secrets and injection markers — including text extracted from `.docx`. |
| ⑦ | Quota | Reserve before forwarding, settle on success, **release on failure**. |
| ⑧ | Response | Filter `tools/list`, classify upstream errors, append the audit entry. |

### Why ③ exists

**37 of SuperDocs' 38 tools accept an `authorization` argument.** An agent that
sets it supplies its own credential and routes around every per-team control
here. The gateway strips it on every call and records that it did so — the
presence of that field is itself worth alerting on. Only `health` lacks it.

### Why `request_upload_url` is denied by default

`request_upload_url` returns a pre-signed GCS URL; the agent then PUTs bytes
**directly to storage**, bypassing this gateway completely. `request_download_url`
is the same in reverse.

**A gateway advertising a pre-send scan while leaving those open is lying.**
v1 closes the hole by policy, forcing content through `upload_document_base64`
where the proxy can actually read it. The cost, stated plainly:

- inline uploads are reliable to ~20 MB of file bytes (base64 inflates ~33%)
- teams needing larger documents accept an unscanned path, or wait for v2

v2 sketch, out of scope: rewrite the returned URL to point at the gateway,
stream the bytes through the scanner, then forward to GCS.

---

## Identity: what clients actually change

The brief says the proxy should be transparent — "clients need only a URL
change." With token exchange they also change the bearer value. That is
unavoidable: per-team policy requires per-team identity, and the alternative is
every team sharing one credential, which is the problem this service exists to
solve.

It remains a config-only change. No SDK modification, no protocol modification.

Tokens are stored as `sha256:` hashes; the plaintext exists only in the client's
config. The gateway holds the real `sk_` key and reads it from the environment.

---

## Audit log

Append-only JSONL. Each entry embeds `sha256(prev ‖ canonical(entry))`, so
deleting, editing or reordering an entry breaks the chain at a line `verify` can
name.

```bash
gateway audit verify data/audit.jsonl   # exit 0 clean, 1 broken
gateway audit stats  data/audit.jsonl   # decisions and billed units by team
gateway audit tail   data/audit.jsonl -n 5 --pretty

# or from inside the running container
docker compose exec gateway gateway audit verify data/audit.jsonl
```

Container stdout shows only HTTP status lines. **The decisions are in the audit
log, not in `docker compose logs`** — a denial appears there as a bare `403`
with no reason. `tail -f data/audit.jsonl` is the live view.

```
chain intact — 4 entries, head 846eda5255f281ef...
chain BROKEN at line 2: content was modified — stored hash 852cc16dad0a…, recomputed 27d54f714c57…
```

**This is tamper-evident, not tamper-proof.** Someone with write access can
rewrite every entry from the break onward and produce a clean chain again. What
they cannot do is that *quietly* — the head hash changes, so a hash pinned
anywhere else (a nightly log ship, a monitoring check, a screenshot in a ticket)
stops matching. Pin the head somewhere the gateway cannot reach.

**Content is excluded by design.** Entries record tool, team, decision, reason,
byte counts, the request's SHA-256, argument rewrites, the stripped-`authorization`
flag, scan rule names, billed units and latency — never the document, never the
prompt, never the matched text. An audit log that quotes the documents it guards
is a second copy of the data you are trying to protect.

---

## Failure modes

| Situation | Behaviour | Why |
| --- | --- | --- |
| **Audit log unwritable at startup** | Container exits with `AuditWriteError` naming the path | Better to die at boot than come up healthy and reject everything |
| **Audit log unwritable at request time** | `503`, request **not** forwarded, error names storage and says to contact the platform team | Fails closed. The caller cannot fix it, so the message routes it to whoever can |
| **Disk fills between preflight and write** | `503` stating *"the upstream call may have completed"* | Narrow but real. The message does not claim work did not happen when it might have |
| **Upstream down / transport error** | `502`, quota reservation released | A call that never landed must not bill |
| **Upstream 4xx/5xx** | Status passed through, reservation released, `billed: 0` | Failed operations bill 0 upstream; the audit must agree with the invoice |
| **Quota exhausted** | `429` before forwarding, audited as `quota_exhausted` | Refusing locally costs nothing and cannot bill |
| **Corrupt final log line** | Gateway refuses to append; run `audit verify` | Otherwise a truncating attacker could reset the chain by corrupting one line |
| **Malformed `policy.yml`** | Startup fails | A policy that half-loads is worse than one that does not load |

Failing closed on audit is a deliberate availability trade: a full disk takes the
gateway down rather than silently opening an unrecorded window. If that is wrong
for your deployment, it is one branch in `Proxy._forward_with_policy`.

---

## Latency

Measured against the real SuperDocs API with the free `health` tool, direct vs
proxied, **interleaved** so network drift lands on both arms equally. Gateway
running as a real uvicorn server on loopback, audit `fsync` **on**.

```
n=100 paired samples · tool=health (free) · audit fsync=on

               p50       p95      mean       min       max
direct       334.2     401.7     340.9     314.6     449.1
proxied      343.0     409.8     352.0     322.9     446.5

overhead   p50 +8.8 ms    p95 +8.1 ms
per-pair delta: p50 +10.3 ms, p95 +73.1 ms
```

**Read this honestly.** Wide-area latency to SuperDocs (~335 ms) dominates
completely, so this measures what a user *feels*, not what the gate chain
*costs*. A 40-sample run of the same benchmark reported `p50 +0.5 ms, p95
−5.7 ms` — a negative overhead is obviously noise, not the gateway making
requests faster. The paired delta (`+10.3 ms` p50) is the most robust figure
here because it compares within pairs; treat it as an upper bound that includes
a loopback hop and an `fsync` per request.

The takeaway supported by the data: **the gateway is not perceptible next to
the network.** Anything more precise needs a local stub upstream.

```bash
uv run python bench/benchmark.py -n 100          # costs nothing; health is free
uv run python bench/benchmark.py -n 100 --no-fsync
```

---

## Policy file

See [`policy.yml.example`](policy.yml.example), which is loaded and asserted on
by the test suite so it cannot rot.

```yaml
defaults:
  deny_tools: [request_upload_url, request_download_url]
  arguments:
    cross_session_memory: { force: false }   # tenant bleed between teams
    "archive_document.force": { deny: true }
  scan:
    rules: [pii_email, pii_ssn, secret_api_key, injection_markers]
    on_match: mask                            # block | mask | warn

teams:
  legal:
    token_hash: "sha256:…"                    # gateway hash-token
    allow_tools: [chat_async, get_job, upload_document_base64, export_document]
    arguments:
      "chat_async.model_tier": { max: pro }
    quota: { monthly_edits: 200 }
    scan: { on_match: block }                 # stricter than the default
```

Rules keyed `tool.argument` apply to that tool only; bare keys apply to every
tool. Team rules override defaults for the same key. `"*"` in `allow_tools`
permits everything except `deny_tools`.

---

## Limits

Stated plainly, because each one is a place this would need work before it
carried real traffic:

- **Single process.** Quota counters and the chain head are in-process state.
  Two workers would each keep their own copy — two half-counted quotas, two
  writers racing on one chain. The image pins `--workers 1`; scaling past one
  process needs shared state.
- **Quota is in-memory.** A restart resets the month's usage. Durable
  reconciliation against the real invoice is not built.
- **Masking does not work on binary uploads.** Rewriting text inside a `.docx`
  means rebuilding the ZIP, which v1 does not attempt, so `mask` degrades to
  `block` for base64 fields rather than passing them through unscanned.
- **Egress scanning is off by default** and only wired for the ingress fields.
- **Chunk re-edit billing** is counted as one unit; large creations that bill
  1 per 25 sections are not reconciled.

---

## Tests

```bash
uv run pytest                    # 141 tests, no network, zero SuperDocs quota
uv run ruff check . && uv run ruff format --check .
```

| Suite | Proves |
| --- | --- |
| `test_passthrough` | Proxied responses byte-identical to direct, per method |
| `test_identity` / `test_strip_auth` | Token exchange; `authorization` never reaches upstream |
| `test_allowlist` / `test_arg_policy` | Gate ④ and ⑤ in isolation |
| `test_scanner` | PII, secrets, injection — including a real `.docx` proving ZIP extraction |
| `test_quota` | Reserve / settle / release, including refund on upstream failure |
| `test_audit` | Chain integrity, and **tamper tests that must fail** |
| `test_audit_failure` | Failing closed, and not advancing the chain on a failed write |
| `test_policy_matrix` | Table-driven `(policy, request) → decision`, driven through the YAML loader |
| `test_bootstrap` | How a deployment assembles itself from settings on disk |
| `test_e2e` | Every gate on at once, then `audit verify` over what it produced |

The suite runs against a fake upstream, so it consumes **zero SuperDocs quota**.

### Live tests

Opt-in, and they spend real money:

```bash
RUN_LIVE_GATEWAY=1 uv run pytest -m live -s
```

Six tests against the real API. Four are free (`tools/list` filtering, `health`,
denied tool, bad token). Two bill: one `chat_async` (~1 op) and one quota-ceiling
probe (~2 ops). Both send `approval_mode=ask_every_time`, so jobs park at
approval and are never approved — nothing is applied to any document.

---

## Verified end to end

The container was built, run against the real API, and checked:

- `tools/list` filtered to the team's allowlist; denied tool `403`; bad token `401`
- a real `health` call proxied through with the key swapped
- audit log written to the mounted volume, `verify` clean
- **chain continued across a container restart** (4 → 5 entries, still intact)
- read-only data volume → refuses to boot, naming `/app/data`
