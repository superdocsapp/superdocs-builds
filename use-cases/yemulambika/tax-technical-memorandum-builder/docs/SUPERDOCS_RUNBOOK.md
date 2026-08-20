# SuperDocs live runbook

1. Set `SUPERDOCS_BASE_URL=https://api.superdocs.app`, `SUPERDOCS_MODE=real`, and `SUPERDOCS_API_KEY` in the BFF process. Never use a `VITE_*` name. Add `RUN_SUPERDOCS_LIVE_TESTS=1` only for an explicitly authorized live test.
2. Run offline checks first: `npm test`, `npm run lint`, `npm run format:check`, `npm run build`, and `npm run test:ui`.
3. Run `npm run test:live`. It must stop on any non-2xx response, malformed proposal, failed/cancelled job, timeout, invalid quotation, unmatched number, or undecided mandatory proposal. Never substitute the fake adapter.
4. Inspect each downloaded HTML file structurally and by rendering it. This build does not claim DOCX or PDF export.
5. Live harness output belongs under ignored `local-output/`. Before sharing evidence, create a sanitized summary containing only endpoint templates, status codes, truncated IDs, durations, decisions, counts, filenames, and SHA-256 hashes. Never include credentials, authorization headers, source text, traces, recordings, or browser profiles.

The approval action approves proposed memorandum content only. It does not make a tax decision.
