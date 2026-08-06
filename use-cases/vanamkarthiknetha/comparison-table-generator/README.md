# Comparison-Table Document Generator

When a prospect asks "how are you different?", they deserve a document they can
forward internally — not an answer that evaporates after the call. This generator
produces a **branded, externally shareable feature-comparison document** (real
table, real branding, .docx and PDF) from a small JSON config, using SuperDocs
for the AI table fill, the human-in-the-loop approval, and the styled export.

All competitor names are **fictional**. The generator lays out exactly what the
config says — it is explicitly instructed never to invent or embellish a claim.

## How it works

```
config.json ──> branded HTML template (local, deterministic)
                   │  upload
                   ▼
             SuperDocs session
                   │  one chat operation: "fill the table with EXACTLY these values"
                   ▼
             proposed changes  ──> shown to you, approved/rejected (HITL)
                   │  approve
                   ▼
             verify (free HTML export, diffed cell-by-cell against the config;
                   │  one repair operation only if the AI drifted)
                   ▼
             export .docx / .pdf (free, full styling fidelity)
```

The verify step exists because LLM fills can drift in small ways (in testing, one
run renamed the "Capability" header to "Feature" and swapped check-mark glyphs
between runs). The generator never trusts the fill blindly: every header, row
label, and cell is compared against the config after applying, and a single
targeted repair operation is issued if anything moved. A run only succeeds if the
exported document provably matches the config.

Configuration over code: **adding a competitor column or a capability row is a
config edit + re-run.** No code changes. (`configs/acme-vs-2.json` vs
`configs/acme-vs-3.json` differ by one competitor and one row — the layout holds.)

## Run it

```bash
export SUPERDOCS_API_KEY=your-key-here   # never commit this
python generate.py configs/acme-vs-2.json          # interactive approval
python generate.py configs/acme-vs-3.json --yes    # auto-approve
```

- Python 3.10+, stdlib only — nothing to install.
- Each run costs **one SuperDocs operation** (the table fill; +1 only if a drift
  repair is needed). Exports and verification are free.
- Outputs land in `out/` (samples of both runs are committed under `samples/`).

## Config reference

| Key | What it does |
|-----|--------------|
| `product` | Your product name — first data column |
| `competitors` | List of fictional competitor names — one column each |
| `capabilities[].name` | Row label |
| `capabilities[].values` | Map of column name → `"yes"` / `"no"` / `"partial"` / free text |
| `brand.accent_color` | Header/title color |
| `brand.footer` | Footer disclaimer line |
| `outputs` | Any of `docx`, `pdf`, `html`, `markdown`, `txt` |

## SuperDocs features used

- `POST /v1/documents/upload-base64` — branded template upload
- `POST /v1/chat/async` with `approval_mode: "ask_every_time"` — the table fill as a reviewable job
- `GET /v1/jobs/{id}` → `pending_changes` — human-in-the-loop diff review
- `POST /v1/chat/{session}/approve` — explicit per-change approval
- `POST /v1/documents/export` — free HTML export for verification, then styled .docx / PDF with the table intact

Built by Karthik Vanam for the SuperDocs hiring round, with AI-assisted development.
