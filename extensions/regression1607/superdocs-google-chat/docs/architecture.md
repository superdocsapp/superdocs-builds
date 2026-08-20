# SuperDocs for Google Chat — Architecture

One page. Render to PNG for Drive with any Mermaid tool (e.g. `mmdc -i
architecture.md -o architecture.png`) or the mermaid.live editor.

## Components & data flow

```mermaid
flowchart LR
  subgraph Chat["Google Chat space (desktop + mobile)"]
    U["Reviewer / requester"]
  end

  subgraph App["Our app  (FastAPI, stateless per request)"]
    MAIN["main.py<br/>webhook + /tasks/daily-digest + /health"]
    AUTH["auth.py<br/>verify Google-signed JWT<br/>(opt-in: GOOGLE_CHAT_AUDIENCE)"]
    DISP["dispatch.py<br/>pure event → response handlers"]
    CARDS["cards.py<br/>cardsV2 builders + UPDATE_MESSAGE"]
    STORE["store.py<br/>per-space reviews + durable source ids + digest<br/>(in-memory, lock-guarded)"]
    SDC["superdocs.py<br/>SuperDocsClient"]
  end

  subgraph SD["SuperDocs REST API"]
    UP["POST /v1/documents/upload-base64"]
    CH["POST /v1/chat/async  (ask_every_time)"]
    JOB["GET /v1/jobs/{id}  (poll)"]
    AP["POST /v1/chat/{sid}/approve"]
    DL["POST /v1/downloads  (signed URL)"]
    MD["POST /v1/sessions/{sid}/documents/open  (multi-doc)"]
  end

  SCHED["Cloud Scheduler (daily)"]

  U -- "@mention / button click" --> MAIN
  MAIN --> AUTH --> DISP
  DISP --> CARDS
  DISP <--> STORE
  DISP --> SDC
  SDC --> UP & CH & JOB & AP & DL & MD
  CARDS -- "cardsV2 JSON" --> MAIN --> U
  SCHED -- "POST ?token=..." --> MAIN
```

## Approval sequence (item-by-item → apply → download)

```mermaid
sequenceDiagram
  participant U as Reviewer (Chat)
  participant A as App (dispatch)
  participant S as SuperDocs

  U->>A: @mention "draft the renewal for Acme"
  A->>S: upload-base64 (seed / open prior doc as reference)
  A->>S: chat/async (approval_mode = ask_every_time)
  A->>S: poll job → awaiting_approval + pending_changes
  Note over A,S: warmup: first call may fail → retried once
  A->>S: downloads → real signed draft link
  A-->>U: summary card + item-by-item approval card

  U->>A: ✅ approve change 1  (CARD_CLICKED)
  A->>A: record decision in store
  A-->>U: UPDATE_MESSAGE (same card, ticked)
  U->>A: ❌ reject change 2
  A-->>U: UPDATE_MESSAGE (same card)

  U->>A: Apply decisions
  A->>S: approve (per-change array; undecided → rejected)
  A->>S: poll to completed → downloads
  A-->>U: result card + signed .docx link
```

## UI — what the reviewer sees in the Chat space

The app replies with Google Chat `cardsV2`. The mockups below map 1:1 to the
builders in `cards.py`; item clicks re-render the *same* message in place
(`actionResponse: UPDATE_MESSAGE`).

```
① Summary card (posted in-thread after drafting)      ② Item-by-item approval card
┌───────────────────────────────────────┐            ┌───────────────────────────────────────┐
│ 🦉 SuperDocs                           │            │ Review proposed changes               │
│    Acme Renewal Letter                 │            │ Acme Renewal Letter — 2 change(s)     │
├───────────────────────────────────────┤            ├───────────────────────────────────────┤
│ Request                               │            │ ⬜️ EDIT · 07dcd4d7                     │
│ draft the renewal letter for Acme     │            │ Insert a formal closing paragraph…    │
│                                       │            │   [ ✅ Approve ]   [ ❌ Reject ]        │
│ Referenced   (only on "last year's")  │            │                                       │
│ Acme 2024 Renewal                     │            │ ⬜️ EDIT · 5f21ab90                     │
│                                       │            │ Update the fee to $11,000             │
│ Produced                              │            │   [ ✅ Approve ]   [ ❌ Reject ]        │
│ 2 proposed change(s) awaiting review. │            ├───────────────────────────────────────┤
│                                       │            │ [ Apply decisions ] [Approve all] [Reject all]│
│      [ ⬇ Download current draft ]      │            └───────────────────────────────────────┘
└───────────────────────────────────────┘             (a click updates THIS card: ⬜️→✅/❌)

③ Result card (after Apply decisions)                 ④ Daily digest (say "digest" / scheduler)
┌───────────────────────────────────────┐            ┌───────────────────────────────────────┐
│ 🦉 SuperDocs                           │            │ SuperDocs — daily digest              │
│    Acme Renewal Letter                 │            │ what this space produced              │
├───────────────────────────────────────┤            ├───────────────────────────────────────┤
│ ✅ Applied 1, rejected 1.              │            │ Produced (1)                          │
│                                       │            │  Acme Renewal Letter                  │
│   [ ⬇ Download Acme-Renewal.docx ]     │            │  1 applied, 1 rejected                │
└───────────────────────────────────────┘            │                                       │
   (real ~15-min signed storage URL)                 │ Waiting on someone (0)                │
                                                      │  Nothing pending — nice.              │
                                                      └───────────────────────────────────────┘
```

### Card lifecycle (which card the reviewer sees, and when)

```mermaid
stateDiagram-v2
  [*] --> Summary_Approval: @mention request
  Summary_Approval --> Summary_Approval: ✅/❌ per item<br/>(UPDATE_MESSAGE, no API write)
  Summary_Approval --> Result: Apply / Approve all / Reject all<br/>(approve + export)
  Summary_Approval --> ReadyToDownload: no changes to review<br/>(auto-applied creation)
  Result --> [*]
  ReadyToDownload --> [*]
  Digest --> [*]
  note right of Digest
    "digest" command or the
    daily scheduler endpoint —
    independent of a review
  end note
```

## Legend / decisions
- **Human gate:** nothing applies until *Apply decisions*; each change carries its own
  Approve/Reject; undecided changes default to **rejected** (never apply unreviewed work).
- **Polling, not SSE:** avoids the `proposed_change_batch.content` double-parse trap;
  `parse_pending_changes()` still handles the double-encoded shape defensively.
- **Honest links:** `/v1/downloads` gives a genuine ~15-min signed URL (no fabricated
  share links; button omitted if the call fails).
- **Multi-document:** "using last year's" opens the prior doc as a reference tab and
  drafts a **new** document — the referenced doc is untouched.
- **Auth:** opt-in JWT verification via `GOOGLE_CHAT_AUDIENCE` (off for local dev).
- **State:** in-memory, per-space isolated, lock-guarded (concurrent-safe); a database
  is the documented production swap.
- **Tested:** 39 keyless tests exercise dispatch/cards/store/auth/main through a fake
  client — no network, no API key.
