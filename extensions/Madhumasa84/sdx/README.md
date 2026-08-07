# sdx

`sdx` is a pipe-friendly Node.js CLI for explicit, reviewed SuperDocs document workflows. Stage 4 adds bounded retry/rate-limit handling, privacy-safe operation journaling, manual restart recovery, inter-process concurrency protection, deterministic record/replay tooling, and an offline 120-page styled-DOCX streaming proof.

## Install

Node.js 20 or newer is required.

```bash
npm ci
npm run build
npm install -g .
sdx --version
```

## Credentials

Store a key with a hidden terminal prompt:

```bash
sdx auth login
sdx auth status
```

`SUPERDOCS_API_KEY` overrides the stored credential for CI and live tests. Keys are never accepted in argv, profiles, or sessions. On systems without an OS secret-store integration, Stage 3 uses `~/.sdx/credentials.json` with mode `0600`; this limitation is deliberate and documented.

## Human edit and interactive approval

Leave review proposals pending (exit 3):

```bash
sdx edit report.docx "tighten the executive summary"
```

The command prints section-level removed/added text, pending IDs, and the exact `sdx approve <job-id>` command shape. Review every proposal interactively and export only approved edits:

```bash
sdx edit report.docx "update risks" --approve --export pdf
```

Every proposal receives an explicit yes/no decision. Rejections may include optional feedback in an interactive terminal. Nothing is silently approved.

## JSON and programmatic approval

JSON mode emits exactly one schema-versioned object on stdout; progress remains on stderr:

```bash
sdx edit report.docx "update risks" --json | jq '.changes'
```

It never prompts. Submit a complete, explicit decision set later:

```bash
sdx approve job_123 --accept ch_1,ch_3 --reject ch_2 --json
```

`--accept-all` exists only as an unmistakable explicit operation and cannot be mixed with item decisions. Unknown, duplicate, conflicting, or incomplete IDs fail before approval. The command re-fetches the job and refuses terminal or continuation states.

## Named sessions

```bash
sdx edit report.docx "first edit" --session q3-review
sdx edit report.docx "now shorten the conclusion" --session q3-review
sdx sessions list
sdx sessions show q3-review
sdx sessions remove q3-review
```

Reusing an alias continues the same server session and does not upload again. A different path or changed source hash fails safely. Removing an alias deletes only local state; it never deletes, closes, or archives the remote SuperDocs File.

Named workflows are protected by per-session inter-process locks. Concurrent work on the same alias fails before duplicate chat submission; different aliases remain independent.

## Resume an interrupted job

```bash
sdx resume job_123
sdx resume job_123 --approve
sdx resume --session q3-review --approve
```

`resume` polls the persisted job ID and never creates a replacement chat job. Without `--approve`, a review or continuation remains pending with exit 3. With it, every newly observed proposal/continuation is decided explicitly. A completed remote job resumes its saved export intent with a fresh signed download URL and atomic finalization. If more than one pending job matches, supply an ID; an expired/unretained job fails without resubmission.

## Create from a file or stdin

```bash
cat notes.md | sdx new --title "Q3 Review" --export pdf
sdx new notes.md --title "Q3 Review" --export docx
```

`new` streams stdin to a restrictive temporary file, refuses empty or terminal stdin, uses the pre-signed document load path, and exports exact supplied content. Defaults are predictable: `Q3 Review` plus PDF becomes `q3-review.pdf`; `report.docx` edited to DOCX becomes `report.sdx.docx`.

Existing outputs and the source itself are protected. Use `--overwrite` only when atomic replacement is intentional.

## Profiles

Profiles are strict JSON in `~/.sdxrc` and contain only non-secret settings:

```json
{
  "version": 1,
  "activeProfile": "work",
  "profiles": {
    "default": { "exportFormat": "docx", "timeoutSeconds": 300 },
    "work": {
      "apiBaseUrl": "https://api.superdocs.app",
      "modelTier": "pro",
      "exportFormat": "pdf",
      "pollIntervalMs": 1000,
      "color": "auto"
    }
  }
}
```

```bash
sdx profiles list
sdx profiles show work
sdx profiles use work
```

Precedence is CLI > environment > selected profile > default profile > built-in. Supported environment settings are `SDX_PROFILE`, `SDX_API_BASE_URL`, `SDX_MODEL_TIER`, `SDX_EXPORT_FORMAT`, `SDX_TIMEOUT`, `SDX_POLL_INTERVAL`, and `SDX_COLOR`. Unknown profile fields are rejected.

## Global and workflow options

Relevant global options are `--profile`, `--session`, `--json`, `--output`, `--export`, `--timeout` (seconds), `--verbose`, and `--no-color`. `NO_COLOR` is also honored. Edit adds `--approve`, `--poll-interval`, `--diff-limit`, and `--overwrite`; approve adds `--accept`, `--reject`, `--accept-all`, `--feedback`, and `--overwrite`; resume adds `--approve`, `--poll-interval`, and `--overwrite`.

Colour is emitted only to an interactive terminal. HTML and terminal control sequences are sanitized. Large individual changes are truncated with exact hidden character/line counts; increase `--diff-limit` to inspect more.

## Completions

```bash
sdx completions bash > ~/.local/share/bash-completion/completions/sdx
sdx completions zsh > ~/.zfunc/_sdx
sdx completions fish > ~/.config/fish/completions/sdx.fish
```

Generated scripts are deterministic and contain no decoration.

## Doctor

```bash
sdx doctor
sdx doctor --json
```

Doctor checks Node, strict profile parsing, credential availability, profile/credential/session/pending-job/ledger/directory permissions, API URL validity, temp/filesystem capabilities, and atomic output primitives. It performs no billable document operation and no network call.

## Local storage

- Profiles: `~/.sdxrc` (non-secret)
- Credential: `~/.sdx/credentials.json` (`0600`)
- Named sessions: `~/.sdx/sessions.json` (`0600`)
- Pending jobs: `~/.sdx/pending-jobs.json` (`0600`)
- Operation ledger: `~/.sdx/operations.json` (`0600`)
- Workflow/state locks: `~/.sdx/locks/` and adjacent `*.lock` directories (`0700`, bounded and stale-recoverable)

State writes use inter-process locks plus atomic replacement; directories are `0700`. The operation ledger stores hashes, safe IDs/paths, lifecycle boundaries, and export intent—not raw instructions, signed URLs, document bytes, or credentials.

## Retry and ambiguous outcomes

Application 429 responses use documented `Retry-After` seconds and fail promptly when the delay exceeds the command budget. Infrastructure 429 responses without that header use bounded exponential backoff with full jitter. Safe polling/download reads retry transient 500/502/503 and transport failures; ambiguous writes and signed uploads do not.

The current OpenAPI documents no idempotency header, so `sdx` sends none. Chat submission is journaled before the request and the job ID is persisted immediately after acknowledgement. If the connection drops while acceptance is unknown, exit 22 reports an unknown remote state and blocks automatic resubmission. This is an at-most-one automatic-submission guarantee, not exactly-once delivery. See [retry and recovery](docs/retry-recovery.md).

## Verification

```bash
npm run build
npm run typecheck
npm run lint
npm run test:unit
npm run test:integration
npm run test:fixture
npm run test:replay
npm run test:stress
npm test
npm pack --dry-run
```

The deterministic fixture and contract-derived replay never need a real credential or external network. Stress construction and measurements are documented in [docs/stress-method.md](docs/stress-method.md); repository-only sanitized observations are stored under `docs/evidence/stage4-stress.json` and excluded from the npm package.

Live cassette recording is deliberately separate:

```bash
SDX_RECORD_FIXTURE=1 npm run record:live
```

It also requires `SUPERDOCS_API_KEY` already in the environment, generates only disposable synthetic input, allows one potentially billable edit, applies explicit approval, omits signed-storage traffic, and rejects unsafe cassette output. No live cassette is checked in: the included replay is explicitly contract-derived. `npm run test:live` remains opt-in and capped.

## Current limitations

The public API offers no documented idempotency mechanism for the used chat endpoint, so an accepted request whose response is lost requires manual reconciliation. Pre-chat ledger checkpoints are diagnosable but cannot recreate the intentionally unpersisted private instruction. Recovery is explicit (`sdx resume`), not automatic. Ctrl+C never cancels remote work. Remote cancellation/deletion/archive, OS keychain integration, rendered 120-page verification (no renderer was installed), live large-file proof, a genuinely live-recorded cassette, and broader cross-platform permission/locking proof remain pending. Release/submission work belongs to Stage 5.
