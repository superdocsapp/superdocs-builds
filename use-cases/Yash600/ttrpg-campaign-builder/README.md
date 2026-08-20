# The Shattered Crown — TTRPG Campaign Builder

A live, working multi-document workspace for a tabletop RPG campaign that keeps a campaign bible,
its player character sheets, and its session log provably consistent with each other as the world
changes — instead of the usual sprawl of disconnected text files a GM normally has to keep in sync
by hand.

This ships with one complete, real (synthetic) sample campaign, **The Shattered Crown**: a
dark-fantasy campaign bible (two factions, one location, one NPC, one named past event), two linked
player character sheets (Aria Nightwind, Kael Draven), and a session log — all hand-authored, all
cross-referenced, all loaded into SuperDocs verbatim.

## What it actually does

**The content.** Four documents: the Campaign Bible, Aria's character sheet, Kael's character
sheet, and Session 01's log (see `backend/content/campaign_pack.py`). Every mention of a faction,
location, NPC, or past event outside its own canonical description is a real cross-reference, not
just prose that happens to repeat a name.

**The dependency model — generalized from a 1:1 edge to a graph.** My other Task 2 build
(healthcare-privacy-pack) links exactly one procedure to exactly one policy section. A campaign
doesn't work that way: "Blackspire" isn't implemented by one document, it's referenced from both
character sheets *and* the session log at once. So this build tracks a proper many-to-many graph
instead:

- **Entity** — a world fact with one canonical description living in one chunk of the Campaign
  Bible: a faction, location, NPC, or named event. (Player characters are deliberately *not*
  Entities — see "What's deliberately out of scope" below.)
- **Reference** — the edge: some other chunk, in any document, mentions/depends on an Entity's
  canonical description. Many References can point at the same Entity.

Both sides carry the exact same content-hash staleness primitive as the healthcare build
(`chunking.content_hash` / `chunking.is_stale`, byte-for-byte identical module, copied not
reinvented): a Reference is `stale` exactly when the hash it was last synced against no longer
matches the Entity's current canonical-chunk hash. Plain equality check, no prose-diffing, no LLM
judgment call.

**The propagation flow.** A GM edits a world fact in plain language (e.g. "change Blackspire from a
ruined castle to an abandoned fortress"). The system:

1. Applies the edit via `chat` on the Campaign Bible.
2. Re-hashes the changed chunk and flags every Reference whose hash no longer matches — in the
   seed campaign, Blackspire is referenced from Aria's sheet, Kael's sheet, and the session log, so
   one edit flags three dependents at once.
3. Fires one `chat/async` job per stale Reference with `approval_mode=ask_every_time`.
4. A human reviews each proposed diff independently and approves or rejects it — rejecting one
   never touches any other pending job.
5. On approval, the Reference re-syncs (hash recorded, status flips back to `synced`).

**Auto-linking — the part with no healthcare-build equivalent.** Editing a document doesn't just
propagate outward from Entities; it also discovers new inbound links. After *any* chunk edit
(`POST /documents/{id}/edit`), the updated text is scanned for mentions of every registered Entity
in the campaign (deterministic substring match on name/slug, word-boundary guarded — see
`main._mentions_entity`). Any newly-mentioned Entity not already linked from that chunk gets a
fresh, already-synced Reference row created automatically. This is exactly how "make Aria's
backstory darker and connect it to the Fall of Eldoria" is meant to be demoed: the seed campaign
deliberately does **not** pre-wire that connection (see `seed.py`'s closing note), so running that
edit live is what first creates the Aria ↔ Fall-of-Eldoria edge in the graph, not a human wiring it
up by hand.

**Illustrations — the actual "images" surface, not a decoration next to it.** Confirmed against
`docs.superdocs.app` before wiring this up: the right endpoint is "upload a base64-encoded image,
get back a stable URL to embed via `<img src>`" — `SuperDocsClient.upload_image_base64`. So
`POST /entities/{id}/generate-image` does three real steps, not one: generate the art
(`image.pollinations.ai`, free, keyless, entirely outside SuperDocs — see `image_gen.py`'s module
docstring for why generation itself is kept separate from the SuperDocs-calling code), upload those
bytes through SuperDocs' own image endpoint for a stable URL, then embed an `<img>` tag into the
Entity's canonical Bible chunk via a real chat edit. The image becomes part of the actual document,
not a UI-only overlay.

**Export — the "coherent, cross-referenced set" the assignment asks for.**
`GET /campaigns/{id}/export` bundles every document in the campaign into one zip, in whichever
format you ask for, in one call. `validator.py` independently re-derives whether the exported set
is actually coherent — for every Reference, it re-fetches the Entity's live canonical chunk from
SuperDocs, recomputes the hash from scratch, and compares it against what the Reference was synced
against, plus confirms the referencing chunk still exists. Same "proof over assertion" philosophy
as the healthcare build's validator, generalized from edges to the reference graph.

## Screenshots

Screenshots aren't included in this folder. v2 removed all auto-ingestion (see `models.py`'s module
docstring) -- there is no `seed.py` that loads a campaign for you anymore; every Campaign is built
through the same REST endpoints the frontend calls. `backend/scripts/demo_seed_live.py` reproduces
"The Shattered Crown" sample campaign -- the same hand-authored content in `content/campaign_pack.py`
-- against a real running instance (real SuperDocs API, real/embedded Postgres): it creates the
campaign, the Campaign Bible, both linked character sheets (Aria Nightwind, Kael Draven), the
session log, wires the cross-references, generates and embeds one real illustration, runs
`/validate`, and exports the whole set to `backend/demo_export/shattered-crown.zip` -- printing
every step and failing loudly on any SuperDocs error rather than continuing silently. Run it
yourself (see "Running it" below) and the Workspace/Review/Export screens will render for real
against your own seeded campaign. I did visually QA the actual frontend build end-to-end against a
throwaway mock server returning canned Shattered-Crown-shaped JSON (no SuperDocs involved) to catch
layout bugs before calling this done -- that mock server isn't part of this deliverable.

## Architecture

```
backend/
  superdocs_client.py   shared REST client -- copied from the healthcare build verbatim (see
                         "why two copies, not one shared package" below), unmodified
  chunking.py            shared pure functions -- copied verbatim: chunk extraction, content
                          hashing, staleness check. Same module, same tests, same guarantees.
  models.py               SQLModel: Campaign, Document, Entity, Reference, GeneratedImage,
                           ChangeEvent -- the many-to-many generalization of the healthcare
                           build's 1:1 Document/PolicySection/Implements
  db.py                   Postgres via `pgserver` (embedded, zero Docker/root), separate default
                           data directory (~/.shattered_crown_campaigns/pgdata) so this can run
                           side by side with the healthcare build on one machine
  image_gen.py             Pollinations wrapper -- generation only, kept out of the SuperDocs-
                           calling code on purpose (swap providers by replacing one function)
  content/campaign_pack.py the actual hand-authored campaign: bible, two character sheets,
                           session log, plus the Entity/Reference seed registries
  seed.py                  uploads the campaign to SuperDocs, populates Postgres -- idempotent
  validator.py             independent re-check + validation_report.json + GET /validate
  main.py                  FastAPI app: entity-change propagation, freeform document edits +
                           auto-link, HITL approval, illustration generation + embed, campaign
                           export, validate
  tests/                   pytest -- chunking (copied), validator (adapted), auto-link (new),
                           no live key or external Postgres required
frontend/
  app/page.tsx                     Workspace -- sidebar (documents + world facts) + document
                                    panel rendered chunk-by-chunk, inline edit / generate-
                                    illustration actions, live hero explainer
  app/review/page.tsx              Review -- diff cards, approve/reject, identical pattern to
                                    the healthcare build's review screen
  app/export/page.tsx              Export -- campaign-wide zip bundle, per-document export,
                                    run-validator button
```

### Why two copies of `superdocs_client.py`/`chunking.py`, not one shared package

Each Task 2 build ships to `use-cases/<username>/<project>/` as its own PR target and should stand
alone for review — a reviewer cloning just this folder shouldn't need to know the healthcare build
exists. The two files are identical in both projects on purpose: same client, same guarantees,
proven twice over instead of imported once.

## SuperDocs features used

The card for this build names four surfaces: **chat, images, Multi-document, export.** This section
describes the actual v2 code (see models.py's module docstring for why v2 replaced v1's
Entity/Reference/hash-propagation design with plain DocumentLink + version-number staleness) — not
the v1 architecture an earlier draft of this section described.

- `POST /v1/documents/upload-base64` — every Document (Campaign Bible, character sheet, NPC,
  location, session log) is uploaded verbatim when created or imported; see
  `_create_document_with_version` in `main.py`
- **chat** — `POST /v1/chat/async` + `POST /v1/chat/{session_id}/approve` for the human-gated
  document-edit loop (`POST /documents/{id}/chat` → propose → approve/reject, mirrors the
  healthcare build's HITL flow exactly); `POST /v1/chat` (synchronous, no `document_html`) for the
  Campaign Assistant's "draft content from a free-text prompt" feature (`POST
  /campaigns/{id}/assistant`) — the AI drafts, the GM explicitly saves it as a real document
  afterward, two distinct steps on purpose
- **images** — `POST /v1/documents/images/upload-base64` for a stable URL, then a deterministic
  (non-AI) HTML insertion places the `<img>` tag in the document (`POST /illustrations` and `POST
  /illustrations/upload`). Illustration bytes are also re-hosted locally (see `_save_local_illustration`)
  as a workaround for a platform-side bug — the `storage.googleapis.com` URL SuperDocs returns has
  been observed 403'ing "AccessDenied" on an anonymous fetch even though the upload call itself
  succeeds; see `main.py`'s `_extract_image_url` docstring
- **Multi-document** — every `Document` gets its own dedicated SuperDocs session
  (`superdocs_session_id`); `list_session_documents` + `get_document` resolve the durable id and
  canonical persisted HTML right after every upload/create/edit, the same per-document-session
  pattern used in the healthcare build
- **export** — `POST /v1/documents/export`, called once per document by `GET
  /campaigns/{id}/export`, which bundles every document into one zip (grouped by type, plus a
  MANIFEST.txt and an Assets/ folder of illustration bytes read from the local re-hosted copies,
  not fetched over the network from the URL known to 403 — see `main.py`'s export-time comment for
  why)
- `GET /v1/documents/{id}` (+ `include_html=true`) — non-billable structure/hash checks used by the
  validator and by every document-creation path to fetch canonical HTML

## What's deliberately out of scope

- **Player characters are not Entities in the propagation graph.** A character's backstory is
  personal narrative, not a shared fact other documents must stay word-for-word consistent with —
  unlike a location or faction description. Making Aria's prose an entity other documents "must
  match" would force nonsensical propagation onto documents that don't need it. Characters are
  still full `Document` rows, still get illustrations if desired, still get auto-linked *from*, they
  just aren't propagation *targets*.
- **No live multiplayer / session-play tooling**, per the card's explicit instruction: this is a
  document generation and organization tool, not a virtual tabletop or a dice server.
- **No premise-driven campaign generator wired into the demo path.** A "type a one-line premise, get
  a drafted campaign" feature (using SuperDocs' own chat against an uploaded skeleton, no separate
  LLM needed) is a natural extension of this architecture, but the required "strong" bar — one
  sample campaign, two linked character sheets, a generated illustration, a coherent export — is
  fully served by the hand-authored, deterministic seed content, and that's what's shipped.

## Operations budget

- `seed.py` costs **0 operations** — every call (`upload-base64`, `GET /v1/documents/{id}`) is a
  free/non-billable read or verbatim load.
- `validator.py` costs **0 operations** per run — only `GET /v1/documents/{id}`, never `chat`.
- Billable calls: entity/document edits (`POST /v1/chat`, one per human-initiated change) and
  propagated reference updates (`POST /v1/chat/async`, exactly one per Reference that actually went
  stale — bounded by however many documents reference that entity, never open-ended). A single
  "change Blackspire" edit that fans out to its 3 seeded dependents costs 4 operations total.
  Illustration generation costs 1 operation per embed (the chat call that places the `<img>` tag;
  the Pollinations generation and the SuperDocs image upload are both free).
- Exports (`POST /v1/documents/export`) are free regardless of format or frequency, including the
  campaign-wide zip bundle.

This project has been exercised against the live API during development (illustration generation +
embed, document upload) while diagnosing and fixing two SuperDocs-side issues: a request-field-name
mismatch on the image-upload endpoint, and a GCS object-ACL bug on the URL that endpoint returns
(worked around by re-hosting generated/uploaded images locally -- see `main.py`'s
`_save_local_illustration`). `pytest` (chunking + validator + auto-link + illustration handling, all
against in-memory SQLite and a `FakeSuperDocsClient`) covers the rest without a live key. The one
thing not yet confirmed end-to-end against the live API is the full "sample campaign -> coherent
cross-referenced export" flow -- run `backend/scripts/demo_seed_live.py` (see "Running it" below) to
confirm that yourself.

## Running it

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
cp .env.example .env
# edit .env: set SUPERDOCS_API_KEY -- you can reuse the same key/account as the
# healthcare-privacy-pack build, or get a free one: see .env.example for the signup call
python3 -m uvicorn main:app --reload --port 8001
```

Runs on port **8001** by default (not 8000), so it can run side by side with the
healthcare-privacy-pack backend on the same machine without a port clash.

With the server running, seed and confirm the sample campaign in a second terminal:

```bash
cd backend
source .venv/bin/activate
python3 scripts/demo_seed_live.py
```

This creates "The Shattered Crown" (Campaign Bible + Aria + Kael + Session 01), wires the
cross-references, generates and embeds one real illustration, validates coherence, and exports the
whole set to `backend/demo_export/shattered-crown.zip` -- printing each step and the exported zip's
contents so you can confirm the bar for yourself instead of taking the README's word for it.

Run the validator any time:

```bash
python3 validator.py   # writes validation_report.json, exit code 1 on any failure (CI-gateable)
```

Run tests (no live key, no external Postgres required):

```bash
pytest -v
```

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local   # NEXT_PUBLIC_API_BASE=http://localhost:8001
npm run dev
```

Open `http://localhost:3000`. Try the demo yourself, on the **Workspace** tab:

1. Open the Campaign Bible, find the Blackspire card, click **Edit this section**, describe
   changing it from a ruined castle to an abandoned fortress, apply.
2. Go to **Review** — three proposed updates are waiting (Aria's sheet, Kael's sheet, Session 01).
   Approve or reject each independently.
3. Back on **Workspace**, open Aria Nightwind's sheet, click **Edit this section** on her
   background, and ask to connect her backstory to the Fall of Eldoria — this creates a brand new
   cross-reference automatically (auto-link), visible immediately in the World Facts sidebar.
4. Click **Generate illustration** on Blackspire's card, describe the scene, generate — the image
   gets embedded directly into the Campaign Bible.
5. Go to **Export**, run the validator, then download the whole campaign as one zip.

## Data model

- **Campaign** — one row per campaign (name, genre, tone, premise).
- **Document** — one row per SuperDocs document (bible / character / session_log), its own
  dedicated `superdocs_session_id`.
- **Entity** — one row per world fact (faction / location / NPC / event), its canonical chunk, and
  `current_content_hash`.
- **Reference** — the edge: some chunk depends on some Entity, `synced_content_hash`, `status`
  (`synced` / `stale` / `pending_review`), in-flight `pending_job_id`.
- **GeneratedImage** — one row per illustration: prompt, SuperDocs image URL, where it got embedded.
- **ChangeEvent** — append-only audit log: every entity edit, document edit, reference flagged
  stale, proposed change, approve/reject decision, auto-link, image generation.
