# Canva → Long-Form Document

Built for the SuperDocs Round 2 engineering task, assigned build: "Canva app: design to long-form document."

## What it does

Turns a Canva design (a flyer, poster, or similar) into a full long-form document — a leave-behind report, a brochure, or a long-form article — that carries the design's actual copy, brand colors, and imagery, exported as a real `.docx` or `.pdf`.

Pulls the design's text and visual identity directly from Canva via the Connect API, sends it to SuperDocs to be expanded into the chosen document type, checks the result against a quality gate (brand-color consistency, duplicate-section detection), and lets you re-check for updates if the source Canva design changes later.

## Who it's for

A marketer, small-business owner, or educator who already designs in Canva and needs the "long version" of that design without starting from scratch or losing the brand's visual identity.

## How to run it

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env`:
SUPERDOCS_API_KEY=your-superdocs-key-here
CANVA_CLIENT_ID=your-canva-client-id-here
CANVA_CLIENT_SECRET=your-canva-client-secret-here
CANVA_ACCESS_TOKEN=obtained-via-oauth_canva.py
CANVA_REFRESH_TOKEN=obtained-via-oauth_canva.py


One-time Canva authorization (opens a browser, requires a Canva Developer Portal integration with scopes `asset:read`, `design:content:read`, `design:meta:read`, `profile:read`):
```powershell
python oauth_canva.py
```

Run the app:
```powershell
streamlit run streamlit_app.py
```

That's the only command needed day to day. If your Canva token expires (~4 hours), refresh it without repeating the browser flow:
```powershell
python refresh_canva_token.py
```

## What SuperDocs features it uses

- **Chat** (`/v1/chat`) — the primary, reliable generation path, seeding real content and expanding it into the target document type
- **Chat async + human review** (`/v1/chat/async`, `approval_mode='ask_every_time'`) — an optional, experimental review-gated generation path (see Known Limitations)
- **Images** (`/v1/documents/images/upload-base64`) — embeds the design's own artwork into the generated document
- **Templates** (`/v1/templates/upload-base64`) — saves the design's visual system as a reusable brand template
- **Export** (`/v1/documents/export`) — produces the final `.docx`/`.pdf`

## Architecture

Canva Connect API (OAuth 2.0 + PKCE) → export design as PDF (text/layout) + print-resolution PNG (visual palette) → extract copy and colors locally → seed + expand via SuperDocs chat → quality gate → export.

A lightweight local JSON registry (`design_links.json`) tracks each design's last-known content hash, enabling the Sync feature: re-checking a design costs zero SuperDocs operations if nothing changed, and pushes a targeted update (not a full regeneration) if it did.

## What strong looks like, and how this build gets there

- **Looks like it belongs to the design, not a generic template**: brand colors are extracted from the design itself and applied as real inline CSS to every generated heading — verified programmatically via a quality gate, not just eyeballed.
- **Images at print resolution**: the app auto-detects the design's orientation and requests correctly-dimensioned exports (2480×3508 or 3508×2480, ~300 DPI) — verified by checking the actual downloaded file's pixel dimensions, not assumed.
- **Consistent from page 1 to page 40**: tested via a 6-turn proxy (stating the brand palette once, then adding five more sections with zero restatement) — 100% color consistency held across all six turns on a clean, isolated run.
- **Designs stay linked**: a real Canva edit is detected via content hashing, diffed, and pushed as a targeted update to every already-generated document — tested with a genuine before/after edit in Canva.

## Known limitations (logged honestly, not hidden)

- SuperDocs' `approval_mode='ask_every_time'` activates inconsistently and can propose lower-quality placeholder content when it does activate — see `BUGS.md` for full detail. The default generation path (plain `/v1/chat`) is unaffected and was reliable across every test in this build.
- Cost tracking is not implemented in this build (unlike the Task 1 system) — a reasonable next addition.
- Sync currently re-checks on demand (a button click), not via a live watcher.

## Bugs found

See `BUGS.md` in this folder for the full, detailed list — 12 real issues found and documented during this build, several with root-cause investigation and working fixes.

---
## Screenshots
<img width="500" alt="image" src="https://github.com/user-attachments/assets/259c858d-d596-4612-834b-ca2d5b0707e9" src="URL_1" />
<img width="500" alt="image" src="https://github.com/user-attachments/assets/088abcff-d5be-4cc5-9311-60e9973d8ce9" src="URL_2" />
<img width="500" alt="image" src="https://github.com/user-attachments/assets/6cf63c2e-90eb-45f6-acfa-593313442cc1" src="URL_3" />
<img width="500" alt="image" src="https://github.com/user-attachments/assets/142ad1f5-1bbf-4540-984a-22cadc96d5e3" src="URL_4" />
<img width="500" alt="image" src="https://github.com/user-attachments/assets/bbdee804-35b9-4a87-abd7-4de364a7a69f" src="URL_5" />
<img width="500" alt="image" src="https://github.com/user-attachments/assets/0c37046d-ec36-471b-a9e0-89a9c7f97420" src="URL_6" />
<img width="500" alt="image" src="https://github.com/user-attachments/assets/aed4da09-614b-4c47-a028-9d91ed791543" src="URL_7" />
<img width="500" alt="image" src="https://github.com/user-attachments/assets/d44fdc04-9723-46b5-a81b-b966d53ce226" src="URL_8" />
<img width="500" alt="image" src="https://github.com/user-attachments/assets/c20a9779-b535-42d9-9e67-739ead71fc87" src="URL_9" />
<img width="500" alt="image" src="https://github.com/user-attachments/assets/824e34ba-186d-4791-bd10-56fae5be2c3a" src="URL_10" />







---

Built for the SuperDocs task by Aditya Singh.
