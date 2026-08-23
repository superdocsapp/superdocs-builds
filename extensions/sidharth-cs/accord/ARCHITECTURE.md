# ACCORD — architecture

A Statement of Work that writes itself while the meeting happens, on the
firm's own template, with a human approving every change before the file
leaves.

---

## 1. System topology

Audio never touches a third party except the transcriber. The SuperDocs key
lives only on the server; the panel and the helper never see it.

```mermaid
flowchart TB
    subgraph local["Reviewer's Mac"]
        swift["audio-fetcher (Swift)<br/>ScreenCaptureKit + AVAudioEngine<br/>pause-bounded chunks (12s ceiling)<br/>1.5s overlap"]
        helper["helper.py<br/>outbound WSS only"]
    end

    subgraph zoom["Zoom"]
        panel["ACCORD panel (React)<br/>document · review · export"]
    end

    subgraph railway["Railway — FastAPI"]
        api["REST + SSE"]
        engine["Draft Engine<br/>MeetingSession"]
        gate["Validation gate<br/>deterministic"]
    end

    groq["Groq Whisper<br/>large-v3"]
    sd["SuperDocs API<br/>chat_async · approve · export"]

    panel -- "Listen" --> api
    api -- "START / STOP" --> helper
    helper -- spawn --> swift
    swift -- "PCM chunks" --> api
    api --> groq
    groq -- transcript --> engine
    engine --> gate
    gate -- "approve / deny" --> sd
    sd -- "proposed edit" --> gate
    engine -- SSE --> panel
    panel -- "approve · export" --> api
    api --> sd

    classDef ours fill:#1f6feb22,stroke:#1f6feb
    classDef ext fill:#8b949e22,stroke:#8b949e
    class swift,helper,panel,api,engine,gate ours
    class groq,sd ext
```

**Why the helper exists.** Zoom's RTMS needs a purchased Developer Pack this
account does not have — verified with Zoom, documented in `PROGRESS.md`. The
helper is the honest workaround: it connects **outbound** over WSS, so there
is no inbound port and no tunnel, and it holds no credentials of its own
beyond a rotatable token.

---

## 2. The drafting pipeline

This is the part that matters. SuperDocs proposes; **our code decides**.

```mermaid
flowchart TB
    chunk["pause-bounded audio chunk<br/>1.5s overlap"] --> dedupe["fuzzy overlap dedupe<br/>SequenceMatcher 0.75"]
    dedupe --> batcher["Batcher<br/>7s silence · 15s ceiling · 400 chars<br/>flush dispatched, never awaited"]
    batcher --> resolve["resolve intra-batch repair<br/>'$45,000. Actually, make it $55,000.'<br/>→ 'the budget is $55,000.'"]
    resolve --> classify{"addition<br/>or correction?"}

    classify -- "cue AND value already in draft" --> corr["correction op<br/>FIND old / REPLACE new"]
    classify -- otherwise --> add["addition ops<br/>one per target section"]

    corr --> route
    add --> route["section routing<br/>from the live draft's own headings"]
    route --> chat["SuperDocs chat_async"]
    chat --> propose["proposed edit<br/>awaiting_approval"]

    propose --> gate

    subgraph gate["The gate — deterministic, no model"]
        direction TB
        g1["anchors present<br/>(morphology-tolerant, values exact)"]
        g2["no placeholders · no heading edits<br/>no invented tables"]
        g3["no cross-section contamination"]
        g4["landed in its own target section"]
        g5["earlier committed facts survive"]
    end

    gate -- pass --> approve["approve_changes"]
    gate -- fail --> deny["deny + settle<br/>bounded retry, then roll back"]

    approve --> ledger["fact ledger<br/>only what is VERIFIED present"]
    ledger --> reconcile{"anything committed<br/>earlier now missing?"}
    reconcile -- "yes, and it is a date or amount" --> redrive["re-drive through the same gate"]
    reconcile -- no --> done["publish to panel"]
    redrive --> done

    done --> review["human approves a draft_version"]
    review --> export["export .docx<br/>409 until approved"]

    classDef bad fill:#f8514922,stroke:#f85149
    class deny bad
```

---

## 3. The three ideas worth defending

**The gate never calls a model.** Every check is HTML parsing, anchor
matching and set arithmetic. A model deciding whether a model's output is
acceptable adds a second thing that can be wrong. Failures are then
deterministic and explainable: `missing expected content anchors: ['$55,000']`
names the reason, not a confidence score.

**The ledger records only what was verified present.** It would be easier to
record what each batch *asked* to commit. But then "this is gone now" proves
nothing, and recovery chases content that was never there. The distinction
between requested and observed is what makes the reconciliation pass safe.

**Recovery is more conservative than the gate.** The gate refuses content;
recovery *adds* it on its own initiative, so a false positive duplicates a
paragraph. It therefore acts only on dates and amounts — evidence strong
enough to be sure of — logs everything else, and tries each fact once.

---

## 4. What this architecture does not do

- **No live multiplayer.** One reviewer per meeting.
- **In-memory session state.** A redeploy clears in-progress meetings.
- **One session, one document, strictly serialized.** Concurrent
  `chat_async` on a session returns 409, so every edit is sequential. This is
  the single largest contributor to end-to-end latency, and it is a platform
  constraint rather than a choice.
- **The helper is a local process.** No installer, no login item; it needs
  Screen Recording and Microphone permission granted ahead of time.
- **`demo.py` exists precisely because of that.** A reviewer with no Mac, no
  Zoom account and no API key can drive the identical pipeline in one command.

---

## 5. Verifying it without a meeting

```bash
python3 demo.py --correction        # mid-sentence repair
python3 demo.py --late-correction   # correct a value already written
```

Feeds the same transcript endpoint the live capture feeds, so it exercises
batching, classification, routing, the gate, approval and export. It asserts
export is refused with 409 *before* approval — demonstrating the gate rather
than asserting it.

`383 tests` run with no network and no API key.
