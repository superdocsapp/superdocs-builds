# Changelog

All notable changes to the `sdx-superdocs-cli` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-07

### Added
- **API Contracts**: Full implementation of SuperDocs async REST/OpenAPI requirements.
- **Pre-signed Streaming**: Secure streamed upload and parsing for local documents (PDF, DOCX, HTML, RTF, MD, TXT).
- **Asynchronous Editing**: Human-in-the-loop (HITL) document editing with programmatic `approve` and `resume`.
- **Review Diffs**: Section-level localized diffs to safely review edits in interactive terminals before acceptance.
- **Named Sessions**: Local durable `session` aliases (`--session name`) to reuse SuperDocs files and skip re-uploading.
- **Workflow Protection**: Atomic, bounded inter-process locks (`0700` directories) to prevent race conditions on shared sessions.
- **Safe State Journaling**: Write-ahead operation ledger storing non-secret state transitions (`0600` files).
- **Interruption Resilience**: Controlled recovery via `sdx resume` to resolve pending jobs when operations are cancelled or dropped.
- **CLI Profiles**: Strict configuration via `~/.sdxrc` mapped to CLI and environment variables.
- **Safe Output Atomic Rename**: Final downloaded exports are strictly verified and atomically moved into place to avoid partial files.
- **Shell Completions**: Native auto-completions for `bash`, `zsh`, and `fish`.
- **Diagnostic Tooling**: Non-billable `sdx doctor` command providing JSON and human-readable environment health checks.
- **Offline Reliability**: Advanced bounded exponential backoff with full jitter for rate limits and robust retry policies for transient errors.
- **Recording & Replay**: Opt-in deterministic HTTP cassette recording with credential and sensitive field redaction.

### Security
- Credentials are read exclusively from environment variables or a secure `0600` stored configuration file.
- Strict isolation of API tokens from signed blob storage queries.
- Pre-upload and post-download local artifact cleanup mechanisms to ensure sensitive temporary fragments are never orphaned.
- All secrets, tokens, and PII are systematically scrubbed from diagnostic outputs and the operation ledger.
