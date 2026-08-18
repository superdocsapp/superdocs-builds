# Architecture

## Design principle

The application is a translation-control plane around SuperDocs. It is not a document-editor clone.

```text
                 ┌──────────────────────────────┐
                 │ Manuscript upload             │
                 │ TXT / MD / DOCX / HTML        │
                 └──────────────┬───────────────┘
                                │
                                ▼
                 ┌──────────────────────────────┐
                 │ Deterministic ingest          │
                 │ structure + provenance + hash │
                 └──────────────┬───────────────┘
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
          ┌──────────────────┐    ┌──────────────────┐
          │ Term extraction  │    │ Style/format     │
          │ provider         │    │ analysis         │
          └────────┬─────────┘    └────────┬─────────┘
                   │                       │
                   ▼                       ▼
          ┌─────────────────────────────────────────┐
          │ Evidence quality gate + human review    │
          └───────────────────┬─────────────────────┘
                              │
                              ▼
                 ┌──────────────────────────────┐
                 │ Translation packet           │
                 │ source + terms + rules +     │
                 │ style + formatting + guide   │
                 └──────────────┬───────────────┘
                                │
                                ▼
                 ┌──────────────────────────────┐
                 │ SuperDocs server-side adapter │
                 │ HTML → proposal → approval   │
                 │ → export                      │
                 └──────────────┬───────────────┘
                                │
                                ▼
                 ┌──────────────────────────────┐
                 │ Returned translation          │
                 └──────────────┬───────────────┘
                                │
                                ▼
                 ┌──────────────────────────────┐
                 │ Conservative alignment        │
                 │ + protected-term QA           │
                 └──────────────┬───────────────┘
                                │
                                ▼
                 ┌──────────────────────────────┐
                 │ Chapter report + evidence     │
                 │ PASS / ISSUES / REVIEW       │
                 └──────────────────────────────┘
```

## Why the extraction layer is two-stage

The provider is allowed to propose semantic candidates, but the application does not trust provider output as evidence. Quotes are checked against the real manuscript, and a deterministic quality gate rejects ordinary vocabulary such as sentence-initial `There`, `Would`, or `What`.

This protects the human review queue from both model hallucination and naive capitalization heuristics.

## Why QA is chapter-scoped

Translation frequently changes sentence and paragraph boundaries. Protected-term verification therefore compares occurrence counts at chapter scope. The alignment layer remains available for evidence localization, but alignment uncertainty never silently turns into PASS.

Missing chapters are reported once as a structural failure per protected term/chapter combination rather than exploding into one finding for every source paragraph.

## Memory boundary

Approved terms are persisted in a local, scope-keyed translation memory. The scope is derived from manuscript title, author and target language, preventing unrelated books from inheriting one another's rules. Memory entries are suggestions on a new run, never automatic enforcement.

## SuperDocs boundary

Only `src/superdocs/client.ts` knows HTTP paths. `src/superdocs/integration.ts` owns the workflow state machine. The browser only sees safe run state and proposed changes; the API key never leaves the server.

The integration follows the current official SuperDocs guidance around HTML round trips, server-side API keys, async jobs, human approval and `data-chunk-id` preservation.
