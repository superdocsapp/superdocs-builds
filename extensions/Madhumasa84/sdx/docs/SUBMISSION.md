# SuperDocs `sdx` CLI — Submission Materials

## Project Status

The `sdx` CLI implements the documented Stage 1–5 command and resilience scope that is testable offline, with release publication intentionally outside this private package. It securely manages asynchronous SuperDocs workflows (upload, processing, interactive HITL review, continuation, atomic export) while enforcing strong durability, concurrency protection, and rate limit reliability.

## Final Test Results

- **Unit Tests**: 48/48 Passed
- **Integration Tests**: 84 passed, 0 failed, 1 skipped (the conditional `jq` check is unavailable on this host)
- **Live Smoke & Verification Tests**:
  - Historical sanitized live Stage 4 large-file evidence is recorded in `PROGRESS.md`; no live operation was run during this audit.
  - All offline HTTP deterministic replay and recording fixtures (5/5 tests) pass with mocked responses.
- **Combined Target**: `npm test` completed with 132 passed, 0 failed, and 1 conditional skip (133 tests total).
- **Tooling Checks**: ESLint strict linting and `tsc` type checking all cleanly complete without warnings.

## Release Metadata (v0.1.0)
- **Package size**: 96.7 kB packed / 574.4 kB unpacked.
- **Exclusions Verified**: The local `npm pack` `sdx-superdocs-cli-0.1.0.tgz` archive deliberately excludes live test data (`docs/evidence/`), `live-stage4-output.docx`, secret credentials, and any test-specific fixtures, shipping only `dist`, `schemas`, and runtime `docs`.
- **Export verification**: Offline PDF and DOCX exports are structurally validated before atomic finalization; invalid or truncated downloads leave no final output.
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
- **Rendered PDF Verification**: The offline fixture proves PDF structure and atomic finalization, but no Poppler/pdfinfo renderer is installed here for visual page inspection.
- **Missing API Idempotency**: The SuperDocs async API does not currently offer an Idempotency-Key. `sdx` blocks ambiguous writes and relies on local atomic ledgers (`operations.json`) and explicit `--session` labels to mitigate duplicate billable work instead.
