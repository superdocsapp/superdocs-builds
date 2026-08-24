# Architecture

```mermaid
flowchart TB
  subgraph vault[Obsidian vault]
    T[designated note]
    S[source notes]
  end

  S -->|modify event, debounced| W[bounded watcher]
  W --> F[source fingerprint]
  F --> R[local lexical retrieval]
  T --> O[ownership parse]
  O -->|malformed markers| X1[stop, no network call]
  O --> D[region document:\nowned content only,\nfenced by region headings]

  R --> P{no-spend preview?}
  P -- yes --> PM[preview modal\nzero API calls]
  P -- no --> U[POST documents/upload-base64\nreturn_html]
  T -. read-only .-> A[POST attachments/upload-base64]
  R -. read-only .-> A

  U --> M[chunk id to Markdown block map\ntext must match on both sides]
  U --> C[POST chat/async\napproval_mode ask_every_time]
  A --> C
  C --> J[GET jobs/id\n15 minute deadline]
  J -->|awaiting_kind = continue_prompt| X2[stop, spend nothing more]
  J -->|pending_changes| H[review modal\napprove / reject / feedback,\nmax 3 rounds]
  H --> AP[POST chat/session/approve]
  AP --> J

  J -->|completed| AC[apply approved changes\nby chunk id, into the original note]
  M --> AC
  AC --> V1[check 1: change matches the block it claims]
  V1 --> V2[check 2: no byte changed outside the markers]
  V2 --> V3[check 3: POST documents/export\nagrees region by region]
  V3 -->|disagreement| X3[stop, write nothing]
  V3 --> WR[Vault.process:\nre-read, abort if the note changed, write]
  WR --> T

  ST[(persisted state:\nprocessed + attempted fingerprint)] --- F
  T -. never triggers the watcher .-> W
```

## Invariants

1. The editable document contains owned-region content and nothing else. Human prose reaches SuperDocs only as a read-only attachment, so an edit to it cannot be proposed.
2. The watcher is driven by source changes; the designated note is excluded, so output never becomes input.
3. A source fingerprint is attempted at most once on the automatic path. The attempt is recorded before the first paid call, so a failure cannot bill in a loop.
4. Human approval precedes every write, change by change.
5. An approved change is placed by chunk id, and only after the text SuperDocs claims it is replacing matches the Markdown block that chunk came from.
6. `assertNoUnownedChange` re-derives the candidate from the original and refuses anything that differs outside the markers.
7. The Markdown export is compared against the local result region by region; disagreement writes nothing.
8. The note is re-read inside `Vault.process`; a human edit during the review aborts the write.
9. Malformed, duplicated, nested, unclosed or overlapping markers stop the run before any network call.
10. Preview performs local work only: no request, no operation.
