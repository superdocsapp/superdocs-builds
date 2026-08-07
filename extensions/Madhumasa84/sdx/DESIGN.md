# sdx design

## 1. Product and boundaries

`sdx` is a predictable, pipe-friendly CLI for creating and explicitly reviewing SuperDocs document changes. It prioritizes streaming I/O, deny-by-default approval, stable JSON, safe local persistence, restart safety, and verifiable output. Direct DOCX XML mutation, a full-screen TUI, remote deletion/archive/cancellation, invented API idempotency, and release automation remain out of scope through Stage 4.

## 2. Layered architecture

- `src/cli.ts` and `src/program.ts`: process entry, Commander parsing, options, terminal wiring, and exit selection.
- `src/commands/`: use-case services; no Commander parsing.
- `src/core/`: job state, change normalization, envelopes, and exit contracts.
- `src/api/`: authenticated REST, runtime validation, signed streaming transfers.
- `src/config/`: strict non-secret profile parsing and precedence.
- `src/sessions/`: atomic named-session and pending-job persistence.
- `src/operations/`: privacy-safe write-ahead operation ledger.
- `src/storage/`: inter-process locking and stale-owner recovery.
- `src/security/`: credential storage and mandatory redaction.
- `src/presentation/`: human/JSON output and safe section diffs.

Commander handlers construct dependencies; network details remain inside `SuperDocsClient`.

## 3. Command surface

Implemented through Stage 4:

- `sdx edit <file> <instruction>` with interactive `--approve` or pending review.
- `sdx new [file] --title <title>` with streamed stdin.
- `sdx approve <job-id>` with explicit complete decisions.
- `sdx auth login|status`.
- `sdx profiles list|show|use`.
- `sdx sessions list|show|remove`.
- `sdx completions <bash|zsh|fish>`.
- `sdx doctor`.
- `sdx resume [job-id]` with explicit repeated approval/continuation handling.

Global settings include profile/session, JSON, output/export, timeout, verbose, and colour control. No API-key option exists.

## 4. Edit lifecycle

A fresh edit validates/hashes the source and creates a write-ahead record before remote work. Upload prepared/completed and document processed are separate durable boundaries; only opaque upload/document IDs are stored, never signed URLs. `submission-started` is durable before `/v1/chat/async`; `acknowledged` plus `job_id` is durable before polling. Pending changes are normalized and persisted before output. Without interactive approval the command exits 3; with approval every item gets an explicit decision and optional rejection feedback. Only a genuinely completed job can export.

A named session records its server session ID and source identity. A later edit reuses the server session and sends only the instruction, matching the documented server-persisted document/conversation model. Different or changed local sources fail; Stage 3 provides no implicit remote replacement.

## 5. Programmatic approval

`approve` fetches current job state, refuses non-review and continuation states, validates that supplied IDs are known, unique, non-conflicting, and complete, then submits the documented top-level `approved` field and per-item decisions. `--accept-all` is explicit and mutually exclusive with item lists. Polling after submission remains the completion authority. Export occurs only from explicit options or saved pending-job intent.

## 6. Human presentation and terminal safety

Diffs show ordinal, section/heading, change ID, operation, explanation, document ID when present, and old/new blocks. HTML tags/scripts/styles are stripped; paragraph/list/heading boundaries remain readable. ANSI CSI/OSC and control characters from source/model content are removed. Colour is emitted only for a TTY and is disabled by `NO_COLOR` or `--no-color`. Truncation always reports hidden character and line counts and is configurable with `--diff-limit`.

## 7. JSON and streams

`schemas/output-v1.schema.json` remains version `1.0`. Optional `data`, `diagnostics`, and `documentId` are backward-compatible additions; the top-level stays closed. JSON mode writes exactly one object to stdout and never prompts. Progress/diagnostics remain on stderr. Human final results use stdout.

Uploads/downloads and stdin use native streams with backpressure. Document bytes are never whole-file-read or Base64 encoded. Exports land in a same-directory temporary file and use exclusive hard-link finalization by default; explicit overwrite uses atomic rename.

## 8. Profiles and precedence

`~/.sdxrc` is strict versioned JSON. Allowed profile fields are API base URL, model tier, export format, timeout seconds, poll interval milliseconds, and colour preference. Keys are never allowed. Resolution is CLI > environment > selected profile > default profile > built-in. Unknown fields, malformed JSON, unknown profiles, bad URLs, and invalid enumerations fail explicitly.

## 9. Credentials and local state

When no OS secret-store integration is available, `~/.sdx/credentials.json` is an honest 0600 fallback written atomically through a hidden prompt. `SUPERDOCS_API_KEY` takes precedence. `~/.sdx/sessions.json` stores safe aliases/server IDs/source hash/timestamps; `~/.sdx/pending-jobs.json` stores safe pending decisions/export intent. Directories use 0700 and files 0600. Corruption is actionable, not silently reset. Session removal is local only.

## 10. New-document decision

For user-supplied Markdown/TXT/HTML, the current docs say exact held content should be loaded verbatim rather than re-authored from a message. Stage 3 therefore streams the supplied file/stdin through the verified pre-signed `purpose=document` path, uses a sanitized title-derived upload filename, and exports from the loaded session. This consumes no AI editing operation and preserves supplied text. Future from-scratch AI drafting would require a separately specified instruction/review surface.

## 11. Interrupts

SIGINT aborts local streams/polling, removes controllable temporary input/output, preserves recovery state, and exits 130. If an edit job was started, the CLI reports its safe job ID and says it may still run; it never claims cancellation. `resume` selects persisted acknowledged work and polls the same ID. It acquires a new signed export URL after completion and never creates a replacement chat job. A server-expired job fails actionably without resubmission.

## 12. Testing

Unit tests cover contracts, normalization, profiles, redaction, diff sanitization, credentials, permissions, naming, state corruption, deterministic retry timing, and locks. Integration tests spawn the compiled CLI against a strict random-port fixture for Stage 2–4 vertical slices, kill/restart, concurrency, and the resilience fault matrix. A five-run stress suite exercises generated styled OOXML. Optional live tests/recording are isolated and capped. The checked-in cassette and fixture payloads are explicitly contract-derived, not recorded production responses.

## 13. Retry and ambiguous writes

One injected policy handles rate limits and transient reads. Application 429 uses `Retry-After` seconds; infrastructure 429 without that header uses bounded exponential full jitter. Ambiguous transport/5xx failures retry only reads and atomic signed downloads. Conclusively rejected 429s may retry any operation inside the command budget. The API documents no idempotency header, so none is sent. An ambiguous chat submission becomes an `unknown` ledger record and blocks automatic resubmission; the guarantee is at-most-one automatic submission, not exactly-once delivery.

## 14. Persistence and concurrency

Profiles, credentials, sessions, jobs, and operation-ledger mutations use atomic same-directory replacement while holding an atomic lock-directory lease. Files are 0600, state/lock directories 0700, lock wait is bounded, dead owner PIDs recover immediately, and malformed owner state recovers only after a stale threshold. Named workflows additionally hold per-alias SHA-256-derived locks, preventing duplicate same-session work without serializing different aliases.

## 15. Large-document and cassette proof

The test-only DOCX generator creates deterministic 120-page logical OOXML with explicit page breaks, structure, styling, media, and a unique final-page target. The stress fixture hashes upload bytes while streaming without retaining the whole body, streams an edited valid DOCX back, and records five sanitized Linux/WSL time/RSS observations. No renderer was installed, so rendered page count is not claimed.

The recorder is opt-in behind both a flag and environment credential, excludes signed storage/raw bytes, permits one chat edit, sanitizes unstable values, validates secrets, and writes 0600. Normal CI replays a clearly labeled contract-derived cassette with no credential/network. A genuinely live cassette remains pending.

## 16. Deferred Stage 5 work

Release/version/changelog/submission work, authorized live large-file proof and live cassette capture, rendered page-count/environment-matrix verification, OS keychain integration, and broader cross-platform locking/permissions remain Stage 5 or external verification work. Remote cancellation and destructive remote document operations remain unsupported.
