# Task 2 — Requirement / Evidence Matrix

This matrix distinguishes local evidence from live API evidence. It must stay honest.

| Requirement | Implementation | Status |
|---|---|---|
| Manuscript is source of truth | deterministic parser + raw content hash | DONE |
| Declared document formats | TXT, Markdown, DOCX, HTML adapters | DONE |
| Automatic term extraction | provider abstraction + conservative lexical quality gate | DONE |
| Evidence verification | provider quotes checked against actual source | DONE |
| Human confirmation before enforcement | `confirmTerm()` lifecycle | DONE |
| DNT / preserve-consistently rules | confirmed-only rule builder | DONE |
| Pronunciation notes | evidence-backed, null when uncertain | DONE |
| Meaning/context notes | evidence-backed term candidates | DONE |
| Style/voice note | provider-generated manuscript-specific note | DONE |
| Formatting-carried meaning | italic, bold, verse, dialogue guidance | DONE |
| Clean source | chunk-anchored HTML | DONE |
| Translation instructions | exported packet artifact | DONE |
| Source metadata | filename, format, author, language, hash | DONE |
| Returned translation alignment | conservative chapter/block alignment | DONE |
| Protected-term QA | chapter-scope protected-term verification | DONE |
| Chapter-by-chapter report | explicit chapter summaries + evidence | DONE |
| Deliberate protected-term failure | main/second demos | DONE |
| Clean no-findings case | second manuscript good translation | DONE |
| Different manuscript support | second manuscript + general parser | DONE |
| SuperDocs request/response adapter | server-side client | DONE (MOCK + CODE) |
| Double-JSON proposed-change parsing | explicit parser + test | DONE |
| Async job polling | `pollJobUntilSettled()` | DONE |
| Human approval boundary | UI per-change approval | DONE LOCALLY |
| Live SuperDocs round trip | credentialed runtime | LIVE PENDING until executed |
| Live API key never reaches browser | server-only env boundary | DONE |
| Chunk-id round-trip verification | returned HTML integrity check | DONE |
| Fresh-clone verification | npm install + verify commands | RUN IN SUBMISSION ENV |

## Definition of done

The local build is complete when:

```text
npm run verify:all
```

passes, the UI supports the full prepare/review/QA workflow, and a second manuscript produces a meaningful result.

The **live SuperDocs** row becomes verified only after a real credentialed run. A mock test or a screenshot of the UI is not sufficient evidence.
