# VoiceRedline — hands-free contract redlining on SuperDocs

Speak an edit. Hear what SuperDocs wants to change. Say "approve" — and only then does it land.

VoiceRedline is a voice-driven front end for SuperDocs' human-in-the-loop editing
loop: you talk to a document, every proposed change comes back as a spoken
summary **plus** the real before/after HTML on screen, and nothing is applied
until you say so. Then you say "export" and walk away with a `.docx`.

I build voice-AI tooling in my day work, and my Task 1 system in this hiring
round analyzed a fictional voice-AI platform's contracts. This build closes the
loop: the contract-review workflow itself, driven by voice, on SuperDocs.

## Why voice + a review gate is a natural pair

A voice interface makes an *editing* API dangerous — you can't proofread what
you dictated into a 40-page contract. SuperDocs' `approval_mode: ask_every_time`
is exactly the missing half: every voice instruction becomes a **reviewable
batch of diffs**, read back to you, decided change-by-change, applied only on
explicit approval. The voice makes it fast; the gate makes it safe.

## What it does

- **Load** the bundled sample MSA, upload your own `.docx`/`.html`/`.txt`, or start blank and draft by voice.
- **Speak an instruction** — "find the sentence about twenty-four month renewal and make it twelve months" — then say **"send it"**.
- **Review by ear and by eye** — each pending change is announced (its `ai_explanation` gloss) and rendered as real before/after HTML. Because the gloss can paraphrase, **"read the text"** speaks the *actual* new text, not the gloss.
- **Decide by voice** — "approve" / "reject" / "next" / "approve all" / "apply". Mixed batches are fine. Buttons mirror every voice command.
- **No-op detection** — if a proposed change's before and after are *identical*, the app flags it on the card and says so out loud (see "Bugs this build found").
- **Iterate** — one document, many voice rounds, one sticky SuperDocs session; the live preview refreshes after each applied round (exports are non-billable).
- **Export** — say "export" for the final `.docx` (PDF/HTML/txt via the API too).

## Run it

```bash
cd voice-redline
pip install -r requirements.txt
export SUPERDOCS_API_KEY=your-key-here        # or ~/.superdocs/agent_credentials.json
uvicorn server:app --port 8765
```

Open `http://127.0.0.1:8765` in **Chrome or Edge** (the Web Speech API lives
there; in other browsers everything works by buttons and typing). Click
**Load sample MSA**, click the mic, and talk.

Offline tests (no network, no key): `pytest tests/ -q`

## Voice grammar

| You say | It does |
|---|---|
| *(any sentence)* | accumulates into the instruction box |
| "send it" / "go ahead" | sends the instruction to SuperDocs |
| "clear" / "scratch that" | clears the box |
| "approve" · "reject" | decides the current change, advances |
| "approve all" · "reject all" | decides everything at once |
| "next" · "back" | navigates changes |
| "repeat" / "read it" | re-reads the AI's explanation |
| **"read the text"** | reads the *actual* new text (gloss can paraphrase) |
| "apply" / "finish" | sends the decision batch to SuperDocs |
| "export" / "download" | downloads the `.docx` |
| "load the sample" · "new blank document" | document lifecycle |

Mic toggle: click or `Ctrl+M`. The mic pauses itself while the app is speaking,
so it never transcribes its own voice.

## Architecture

```
Chrome/Edge (static/index.html)
  Web Speech API: SpeechRecognition (in) + speechSynthesis (out)
  command grammar · diff cards · no-op detector · sandboxed live preview
        │  fetch (localhost only; no key ever reaches the browser)
        ▼
FastAPI bridge (server.py)                      in-memory, single user
  POST /api/documents                → upload_doc        (sticky session)
  POST /api/documents/{id}/edits    → chat_async, ask_every_time   [thread]
  GET  /api/edits/{id}               → status / pending changes
  POST /api/edits/{id}/decisions    → per-change approve/reject     [thread]
  GET  /api/documents/{id}/export   → docx / pdf / html / txt
        │  superdocs_client.py (stdlib-only, reused from my Task 2a extension)
        ▼
SuperDocs REST API  (upload-base64 · chat/async · jobs · approve · export)
```

**SuperDocs features used:** async chat editing (`/v1/chat/async`),
human-in-the-loop approval (`approval_mode: ask_every_time` + per-change
decisions on `/v1/chat/{session}/approve`), job polling, sticky multi-round
sessions, format-preserving export (docx/pdf/html/txt, used for both delivery
and the free live preview).

## Hardened against real API behavior

This build bakes in workarounds for every HITL rough edge I hit this round
(ids reference my round's bug log):

- **B1** — an approve call without an explicit `changes` array is a silent
  no-op. Every decision batch here carries the full per-change array
  (`tests/test_decisions.py` pins it).
- **B3** — `ai_explanation` can paraphrase the real edit, so the spoken gloss
  is never the only evidence: cards always render the true `old_html`/`new_html`,
  and "read the text" speaks the real content on demand.
- **B6** — drafting instructions bypass the server-side approval gate (content
  commits with zero pending changes). The server detects the case and gates
  the draft *locally* as a synthetic change, so voice review still happens.

## Bugs this build found (reported to hello@superdocs.app)

Building the no-op detector wasn't theoretical — the very first live demo edit
("In Section 2, change the automatic renewal period …") came back as the
section **heading replaced by itself**, with an `ai_explanation` claiming
"✅ Renewal period updated", and the document unchanged after approval
(2/2 runs). The same edit phrased as find-and-replace worked first try. A
review gate whose explanations can affirmatively claim a null edit succeeded
is a trust problem — so the app now diffs every pending change client-side and
announces no-ops out loud.

Second find: the approve endpoint accepts decisions for `change_id`s that
don't exist (the job completes anyway), so the server validates every decision
batch against the real pending set before forwarding.

## Honest limits

- Web Speech recognition is Chrome/Edge; elsewhere it degrades to type-and-click.
- Single-user desk tool by design: state lives in memory + SuperDocs sessions.
- Voice commands are English; the grammar is a regex table, not an NLU model.
- Rejecting a locally-gated draft (B6) abandons the session rather than
  reverting server-side content — the export gate is the protection.

## Demo

*(screenshots / video link added with the round's demo materials)*

---

Sample contract (`sample/northvoice-brightline-msa.html`) is fully fictional
synthetic data — a made-up voice-AI vendor and client, styled inline-longhand
so it survives export faithfully. Built with AI assistance (Claude Code),
the way I actually build.
