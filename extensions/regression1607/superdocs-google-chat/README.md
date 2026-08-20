# SuperDocs for Google Chat

Draft, edit, and approve documents **without leaving Google Chat** — powered by the
[SuperDocs](https://superdocs.app) API.

> Built as Task 2 of the SuperDocs engineer assignment. Uses the four SuperDocs
> primitives end-to-end: **upload → chat (edit) → approve → export.**

---

## What it does

@mention the app in a space with a request, and it:

1. **Uploads** a seed document to a SuperDocs session (`POST /v1/documents/upload-base64`).
2. **Sends the edit instruction** under a human gate (`POST /v1/chat/async`,
   `approval_mode: "ask_every_time"`), then **polls** the job to the review point
   (retrying once past the documented fresh-session warmup failure).
3. Posts a **summary card** with a real, short-lived signed link to download the
   current draft, plus an **item-by-item approval card**: every proposed change
   has its own ✅ Approve / ❌ Reject button, with *Apply decisions* / *Approve all*
   / *Reject all* shortcuts.
4. Per-item clicks **update the same card in place** (`actionResponse: UPDATE_MESSAGE`)
   and record the decision — nothing is applied until you press *Apply decisions*.
5. On apply, it approves exactly the changes you accepted
   (`POST /v1/chat/{session_id}/approve`; undecided items default to rejected so
   nothing lands unreviewed), lets the job resume, and posts a **result card** with a
   genuine signed download link (`POST /v1/downloads`).
6. Say **`digest`** and it summarizes what the space produced and what's still
   waiting; a `POST /tasks/daily-digest` endpoint lets a scheduler push the same
   digest daily — so nothing sits silently forever.
7. Ask a follow-up that **edits the same doc** (*"revise it"*, *"update it"*) and it
   reuses that document's SuperDocs session. Ask one that **references a prior doc**
   (*"...using last year's"*, *"based on the previous"*) and it opens that produced
   document as a **reference tab** (`POST /v1/sessions/{id}/documents/open`) and
   drafts a **new** document from it — true multi-document, and non-destructive: the
   referenced doc is never mutated.

```
@app draft the renewal letter for Acme
        │
        ▼
  upload ─▶ chat_edit(ask_every_time) ─▶ poll ─▶ awaiting_approval
        │
        ▼
  ┌─ summary card (Download current draft) ─────────────┐
  └─ approval card (per-item ✅/❌ + Apply / Approve all)┘
        │  ✅ some / ❌ some  →  Apply decisions
        ▼
  approve(decisions) ─▶ downloads ─▶ result card (Download final)
```

## Honesty notes (design calls)

- **The document link is real, never faked.** SuperDocs has no public per-session
  share URL, so instead of inventing one we mint a genuine short-lived (~15 min)
  signed download URL via `POST /v1/downloads` (which never costs an operation). If
  that call ever fails, the card simply omits the button rather than showing a dead link.
- **Item-by-item is real.** Decisions are persisted per change across stateless
  card clicks and sent to the approve endpoint as a per-change array; approving one
  and rejecting another in the same review works (locked in by a unit test).
- **The daily digest** is exposed as a scheduler-hit endpoint. Pushing the card
  into a space requires Chat service-account credentials (a deployment concern);
  without them the endpoint returns the per-space digest payload for pull/preview.
- **New-document creation auto-applies.** When a reference draft creates a brand-new
  document, SuperDocs applies the creation immediately, so there may be nothing to
  review. The app then reports the document as *ready to download* rather than
  claiming "no changes were needed" — the result card never misrepresents what happened.

## Why polling (and the double-parse note)

SuperDocs edits can take 30s–several minutes, and its docs warn that the SSE
`proposed_change_batch.content` field is a **JSON string inside JSON** (needs a
second parse). We drive the flow with the **polling** endpoint (`GET /v1/jobs/{id}`)
where `metadata.pending_changes` is already a parsed array — avoiding that trap.
`parse_pending_changes()` still handles the double-encoded string defensively, and a
unit test locks that behavior in.

## Architecture

```
app/
  superdocs.py   SuperDocsClient — the 4 calls + poll + parse_pending_changes +
                 download_url + multi-document (session roster / documents/open)
  cards.py       Google Chat cardsV2 builders (pure); item-by-item + UPDATE_MESSAGE
  store.py       per-space review state: per-change decisions + durable source ids + digest
  dispatch.py    pure event→response handlers (MESSAGE, CARD_CLICKED, ADDED_TO_SPACE)
  auth.py        verifies Google Chat's signed JWT (opt-in via GOOGLE_CHAT_AUDIENCE)
  main.py        thin FastAPI webhook + /tasks/daily-digest + /health
tests/           39 tests, fully mocked — no network, no API key
deployment/      chat-app-manifest.json for sideloading
```

All business logic lives in pure functions (`dispatch.py`) with the SuperDocs
client injected, so the entire flow is tested with a fake and **no API key**.

## Run the tests

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q          # 39 passed
```

## Run locally

```bash
cp .env.example .env         # add your sk_ key
export $(grep -v '^#' .env | xargs)
uvicorn app.main:app --reload --port 8080
```

`GET /health` reports whether the key is configured and whether request auth is
being enforced.

## Deploy to Google Chat (step by step)

Anyone can go from a fresh clone to a working app in a Chat space in ~10 minutes.
You need a Google account, a Google Cloud project, and the app running somewhere
Google can reach over HTTPS (ngrok is easiest for a demo).

### 1. Run the app and expose it

```bash
# terminal 1 — the app
cp .env.example .env                    # put your SuperDocs sk_ key in .env
export $(grep -v '^#' .env | xargs)
uvicorn app.main:app --reload --port 8080

# terminal 2 — a public HTTPS tunnel to it
ngrok http 8080
```

Copy the HTTPS forwarding URL ngrok prints, e.g. `https://ab12-34-56.ngrok-free.app`.
That is your **App URL** below. Verify it works: `curl https://<your-url>/health`
should return JSON.

### 2. Create the Google Cloud project and enable the Chat API

1. Go to <https://console.cloud.google.com/> and create (or select) a project.
2. Enable the **Google Chat API**:
   APIs & Services → Library → search "Google Chat API" → **Enable**
   (or run `gcloud services enable chat.googleapis.com`).

### 3. Configure the Chat app

Open **Google Chat API → Configuration** in the console and fill it in — the
values mirror `deployment/chat-app-manifest.json`:

| Field | Value |
|---|---|
| **App name** | `SuperDocs` |
| **Avatar URL** | any square PNG (e.g. `https://use.superdocs.app/favicon.png`) |
| **Description** | `Draft and edit documents in chat, with human approval, powered by SuperDocs.` |
| **Functionality** | ✅ Receive 1:1 messages · ✅ Join spaces & group conversations |
| **Connection settings** | **HTTP endpoint URL** = your App URL **with a trailing slash**, e.g. `https://ab12-34-56.ngrok-free.app/` |
| **Authentication Audience** | **App URL** (recommended) — the same URL |
| **Visibility** | Add your own Google email so only you can see it while testing |

Click **Save**. (There is no separate "upload manifest" button in the console —
the manifest in `deployment/` is the reference for these fields and for anyone
scripting the config via the Chat API.)

### 4. (Recommended) turn on request verification

So the webhook only trusts real Google Chat calls, set the audience you entered
above and restart the app:

```bash
# in terminal 1 (.env or export)
GOOGLE_CHAT_AUDIENCE=https://ab12-34-56.ngrok-free.app   # your App URL
```

`GET /health` will then show `"auth_enforced": true`, and any request without a
valid Google-signed JWT gets a `401`. Leave it unset for the very first smoke test
if you want to rule out auth as a variable.

### 5. Test it in a space

1. In Google Chat, start a DM with the app (search its name) or add it to a space:
   **+ New chat / Add people & apps** → your app.
2. Mention it with a request:
   `@SuperDocs draft the renewal letter for Acme`
3. It replies with a **summary card** (Download current draft) and an
   **item-by-item approval card**. Approve/reject changes, then **Apply decisions**;
   the result card links the finished `.docx`.
4. Try `@SuperDocs draft the 2025 renewal based on last year's` to see the
   multi-document reference draft, and `@SuperDocs digest` for the space summary.

> First request in a fresh session can be slow or fail while SuperDocs warms up —
> the app retries once automatically; if you still see an error, send it again.

### 6. Capture the screenshot for the PR

With the approval card visible in a space, take a screenshot and save it to
`docs/approval-card.png` (referenced in this README). Keep secrets out of frame.

### Hardening & scheduling (production)

- **Verify the caller is Google Chat.** Set `GOOGLE_CHAT_AUDIENCE` to the audience
  configured on your Chat app connection (App URL, or the project number). The webhook
  then rejects any request whose Google-signed JWT doesn't verify (`401`). Left
  unset, auth is disabled for local dev. Requires `google-auth` (in requirements).
- **Daily digest.** Point a scheduler (e.g. Cloud Scheduler) at
  `POST /tasks/daily-digest?token=$DIGEST_TOKEN` once a day; it returns one digest
  card per space. Pushing the card into the space itself needs Chat
  service-account credentials — a deployment step, documented here rather than faked.
- **Stable hosting.** For anything beyond a demo, replace the ngrok tunnel with a
  real deployment (Cloud Run, Fly.io, a VM) and use that fixed HTTPS URL as the App
  URL and audience.

## Configuration

| Env var | Purpose | Default |
|---|---|---|
| `SUPERDOCS_API_KEY` | SuperDocs key (`sk_...`) | — (required) |
| `EXPORT_FORMAT` | `docx` \| `pdf` \| `html` \| `markdown` \| `txt` | `docx` |
| `SEED_TEMPLATE` | HTML a fresh draft starts from | a minimal stub |
| `GOOGLE_CHAT_AUDIENCE` | Enables JWT verification of Chat requests when set | — (auth off) |
| `DIGEST_TOKEN` | Shared secret guarding `/tasks/daily-digest` | — |

The key is read server-side only and never sent to Chat.

## Screenshot

_Add a screenshot of the item-by-item approval card in a Chat space here (`docs/approval-card.png`)._

---

Built by Ekansh Kumar for the SuperDocs engineer task — an integration built **on**
SuperDocs (never a clone **of** it).
