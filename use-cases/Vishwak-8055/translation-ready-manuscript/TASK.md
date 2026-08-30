# Task 2 implementation status

## PASS / PARTIAL matrix

| Area | Status | Evidence |
|---|---|---|
| Prepare → review → packet → QA workflow | PASS | `src/workflow/workflow.ts`, browser API routes |
| Automatic term extraction | PASS | provider abstraction + deterministic heuristic + evidence gate |
| Ordinary capitalization false-positive control | PASS | heuristic quality tests + runtime Alice smoke test |
| Human approve/reject | PASS | `/api/review/:runId`, lifecycle in `rules/protectedTerms.ts` |
| Translation packet | PASS | `src/packet/buildPacket.ts`, `src/packet/artifacts.ts` |
| TXT / Markdown | PASS | parser + UI |
| DOCX | PASS | pure Node ZIP/XML adapter + fixture |
| PDF | PASS (text-based) | best-effort PDF text adapter + fixture; scanned PDFs rejected honestly |
| HTML | PASS | heading/paragraph/list extraction |
| Chapter QA | PASS | chapter-scoped protected-term verification |
| Evidence | PASS | source/returned evidence + provenance fields |
| SuperDocs API boundary | PASS (code) | server-side client + workflow adapter |
| SuperDocs upload → edit → approve → export | PASS (code) | upload compatibility + HTML-first fallback + approval + DOCX export |
| Live SuperDocs credentialed round trip | PARTIAL | requires a real `SUPERDOCS_API_KEY`; local environment did not have one |
| `data-chunk-id` preservation check | PASS | server integrity check + existing diff engine |
| Translation memory | PASS | scoped persistent `TermMemory`; suggestions remain human-reviewed |
| Idempotent SuperDocs prepare | PASS | duplicate prepare on an active/completed state returns existing state |
| Prompt-injection boundary | PASS (design/tests) | document is explicitly untrusted in provider prompts; no secret exposure |
| Observability | PASS | per-stage duration metrics on runs |
| Security | PASS | server-only key, ignored `.env`, request size limit, escaped UI text |
| Fresh npm install + full Vitest suite on this build | NOT VERIFIED HERE | dependency registry/cache unavailable in the execution environment |

## Deliberate limitations

- PDF support is for text-based PDFs. Scanned/image-only PDFs are rejected instead of pretending OCR succeeded.
- DOCX support extracts manuscript text plus basic emphasis; it is not a promise of lossless Word layout reproduction.
- The local server uses in-memory workflow state; the persisted term memory is the durable cross-run component. A production multi-instance deployment would need shared durable run state.
- Live SuperDocs verification must be performed with the candidate's own credential.
