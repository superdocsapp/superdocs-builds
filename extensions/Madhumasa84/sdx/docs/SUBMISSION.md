# SuperDocs `sdx` CLI — Submission Materials

## Project Status

The `sdx` CLI successfully implements all required functionality up through Stage 5. It securely manages asynchronous SuperDocs workflows (upload, processing, interactive HITL review, continuation, atomic export) while enforcing strong durability, concurrency protection, and rate limit reliability.

## Final Test Results

- **Unit Tests**: 45/45 Passed
- **Integration Tests**: 82 Passed, 0 Failed, 1 Skipped (due to missing `jq` dependency on host system)
- **Live Smoke & Verification Tests**:
  - 100% of the live Stage 4 proof passed (with exactly 2 billable edit operations verified under real API keys).
  - All offline HTTP deterministic replay and recording fixtures (5/5 tests) pass with mocked responses.
- **Combined Target**: 128 tests total executed via `npm test` resulting in 0 regressions.
- **Tooling Checks**: ESLint strict linting and `tsc` type checking all cleanly complete without warnings.

## Release Metadata (v0.1.0)
- **Package size**: 93.7 kB packed / 561.0 kB unpacked.
- **Exclusions Verified**: The published `sdx-superdocs-cli-0.1.0.tgz` archive deliberately excludes live test data (`docs/evidence/`), `live-stage4-output.docx`, secret credentials, and any test-specific fixtures, shipping only `dist`, `schemas`, and runtime `docs`.
- **Secret Scan**: No credentials, bearer tokens, AWS signed URLs, or private keys were leaked into the final commits.

## Usage Demonstration

The CLI helps safely script workflow operations like so:

```bash
# Safely propose an edit and await approval (returns exit code 3)
sdx edit report.docx "Make the tone more professional" --session q3-review

# Accept the pending job interactively
sdx resume --session q3-review --approve
```

## Known Limitations

- **Rendered DOCX Verification**: While the structural OOXML integrity of the 120-page generated test document is validated successfully (`[Content_Types].xml`, markers, explicit breaks), physical rendering tests could not be performed due to the lack of an installed rendering tool (`soffice`/LibreOffice) on the CI test environment.
- **Cross-Platform OS Native Secret Managers**: The CLI uses `~/.sdx/credentials.json` with mode `0600` because the OS keychain integration was out-of-scope for the early stage deliverables.
- **Missing API Idempotency**: The SuperDocs async API does not currently offer an Idempotency-Key. `sdx` blocks ambiguous writes and relies on local atomic ledgers (`operations.json`) and explicit `--session` labels to mitigate duplicate billable work instead.
