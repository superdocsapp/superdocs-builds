# Test matrix

| Area | Evidence | Stage | Live API/key |
|---|---|---:|---|
| Help/version and parsing | Spawn compiled CLI; stable help/version and invalid-input behavior | 1/3 | No |
| JSON envelope | AJV + runtime validation; closed v1 top-level with additive Stage 3 fields | 1/3 | No |
| Signed upload/download | Fixture validates exact body, streamed bytes, and absent auth on signed URLs | 2 | No |
| Async/HITL states | Pending, progress, review, continuation, completed, failed, cancelled, timeout, abort | 2 | No |
| Approval safety | Interactive mixed decisions; programmatic complete/duplicate/conflict/unknown/state rejection | 2/3 | No |
| Session reuse | Same alias skips upload; path/hash mismatch blocks remote replacement | 3 | No |
| Pending state | Job/export metadata saved before exit 3; corrupt state fails actionably | 3/4 | No |
| Diff safety | Headings/paragraphs/lists, ANSI/OSC removal, TTY colour flag, explicit truncation | 3 | No |
| Profiles | Strict parsing, unknown fields/profile errors, deterministic precedence | 3 | No |
| Credentials | Hidden/piped input does not echo; env precedence; redacted status; 0600 file | 3 | No |
| Session removal | Compiled test proves no remote DELETE/archive call | 3 | No |
| New stdin/file | Streamed temp input, empty/TTY rejection, cleanup, safe title/output, overwrite guard | 3 | No |
| Completions | Non-empty deterministic bash/zsh/fish scripts with commands/options | 3 | No |
| Doctor | Human/JSON local diagnostics including ledger/state permissions; no fixture API request | 3/4 | No |
| JSON pipeline | Compiled JSON parsed through `jq` when installed | 3 | No |
| Interrupt | New temp cleanup; edit reports possibly-running job ID; exit 130 | 3 | No |
| Live Stage 2 review | Separate capped review-mode smoke | 2 | Optional; pending |
| Live Stage 3 edit/new | At most two synthetic operations after Stage 2 live prerequisite | 3 | Optional; pending |
| Application 429 | Short documented `Retry-After` exact attempts; over-budget prompt failure; usage/error metadata | 4 | No |
| Infrastructure 429 | Plain-text/no-header bounded full-jitter attempts with deterministic fake time | 4 | No |
| Safe transient retry | 500/502/503 polling GET attempts; malformed/partial/HTML/transport classification; exact calls | 4 | No |
| Ambiguous chat outcome | Drop before/after acceptance; one chat at most; `unknown` ledger; second invocation blocked | 4 | No |
| Write-ahead boundaries | Prepared/upload prepared/upload complete/document processed/submission/acknowledged/review/completion/export/download states; no signed URL/raw instruction | 4 | No |
| Restart | Child killed while polling resumes same job; completed-before-export recovery; expired job no resubmit | 4 | No |
| Repeated decisions | Two HITL rounds and two continuation rounds remain explicit; endpoint call counts asserted | 4 | No |
| Concurrency/locking | Bounded contention, dead/stale recovery, 12 no-loss writes, same alias one chat, different aliases concurrent | 4 | No |
| Transfer faults | Interrupted upload one PUT/no chat; truncated/expired download no final/temp; orphan dead-PID temp cleanup | 4 | No |
| 120-page stress | Deterministic styled OOXML, 119 page breaks/120 markers/media, five compiled signed-stream workflows, hashes/time/RSS | 4 | No |
| Record/replay | Dual opt-in guard, one-edit cap, sanitizer/validator/0600 write, contract-derived local replay | 4 | No |
| Live Stage 4 large file | Generated disposable 120-page edit and export | 4 | Optional; pending (0 operations) |
| Live cassette | Sanitized opt-in one-edit recording | 4 | Optional; pending; checked-in replay is contract-derived |

The fixture is deterministic, strict about API versus signed-storage authentication, and never contains real credentials or live responses. Every retry/recovery test asserts remote call counts. The stress method and raw sanitized observations are in `docs/stress-method.md` and `docs/evidence/stage4-stress.json`. Rendered page count is pending because no trustworthy renderer was installed; structural OOXML validation passed. A skipped optional tool/live check is recorded as pending, never as passed.
