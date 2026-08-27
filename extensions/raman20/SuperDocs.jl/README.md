# SuperDocs.jl

A Julia REST client for [SuperDocs](https://superdocs.app). Files, LaTeX, plots, and edit instructions go in; typed REST writes come back. SuperDocs stays the document engine.

REST only — not MCP.

## What it does

1. **Upload** a markdown lab note into a SuperDocs session.
2. **Chat** an edit (default: review each proposed change before it applies).
3. **Keep math** as KaTeX equations, not leftover `$$` source.
4. **Insert figures** through the images API.
5. **Export** `.docx` / PDF and surface `X-Export-Warnings`.

SuperDocs features used: chat editing, human-in-the-loop approve, image upload, export, math.

## Install

Not in the Julia General registry.

From a [superdocsapp/superdocs-builds](https://github.com/superdocsapp/superdocs-builds) clone:

```julia
using Pkg
Pkg.develop(path="extensions/raman20/SuperDocs.jl")
```

Or without cloning:

```julia
using Pkg
Pkg.add(url="https://github.com/superdocsapp/superdocs-builds",
        subdir="extensions/raman20/SuperDocs.jl")
```

Requires Julia 1.10+. Dependencies: HTTP.jl, JSON3, Base64 (stdlib).

## API key

```bash
export SUPERDOCS_API_KEY=your-key-here
```

Create a key at [use.superdocs.app](https://use.superdocs.app) → Settings → API Keys. Never commit a real key. `Client()` reads the env var; pass `api_key=` to override.

## Four-call flow

```julia
using SuperDocs
client = SuperDocs.Client()
session = "lab-note-1"

up = SuperDocs.upload(client, "fixtures/lab_note.md"; session_id=session)
expected = SuperDocs.extract_latex(something(up.html, ""))

job = SuperDocs.chat_async(client,
        "Tighten the abstract. Do not alter any equation.";
        session_id=session)
job = SuperDocs.wait(client, job)
pending = SuperDocs.pending_changes(job)
job = SuperDocs.approve(client, session, job.job_id; approved=true, changes=pending)
job = SuperDocs.wait(client, job)

html = SuperDocs.html_after_job(client, job, session)
SuperDocs.verify_math(html, expected)

img = SuperDocs.upload_image(client, "plot.png")
html = SuperDocs.place_image(html, SuperDocs.embed_url(img); after="Methods")
SuperDocs.chat(client, "Keep the document exactly as provided. Do not rewrite equations.";
               session_id=session, document_html=html)

bytes, warnings = SuperDocs.export_document(client; session_id=session, format=:docx)
SuperDocs.has_math_partial_fidelity(warnings) && @warn "math_partial_fidelity"
```

`chat_async` defaults to `ask_every_time` (HITL). Sync `chat` is `approve_all` only — the server cannot pause a sync call. `approve` / `continue_job` return `{}`; call `wait` again.

## Math

Write `$x^2$` / `$$E=mc^2$$` in markdown. SuperDocs markdown upload leaves those dollars as visible text (often with `<br/>` inside). The editor only KaTeX-renders:

```html
<span data-latex="E=mc^2" data-type="inline-math">E=mc^2</span>
<span data-latex="x^2+y^2=z^2" data-type="block-math">x^2+y^2=z^2</span>
```

| Helper | Role |
|---|---|
| `latex_inline` / `latex_block` | `$...$` / `$$...$$` for markdown. Display math is a single line — a newline inside `$$` becomes `<br/>` and will not render. |
| `latex_inline_html` / `latex_block_html` | Native `data-latex` spans. |
| `to_native_math` | Convert leftover `$` / `$$` / `\(` / `\[` in HTML. Skips `<code>` / `<pre>`. Idempotent. |
| `upload(...; native_math=true)` | Default: after markdown parse, convert and re-upload as HTML. |
| `chat(..., document_html=...)` | Runs `to_native_math` on HTML you send. |
| `extract_latex` / `verify_math` | Round-trip check. Does not rewrite algebra or emit Unicode (`x²`). |
| `has_native_math` / `has_dollar_math` | Inspect HTML. |

If Word export cannot build native math, SuperDocs may send `math_partial_fidelity`. The SDK returns that warning; it does not drop it.

## Images

Do not ask chat to insert a GCS URL — it will not fetch it. Inject the tag:

```julia
img = SuperDocs.upload_image(client, "fig.png")
html = SuperDocs.place_image(html, SuperDocs.embed_url(img); after="Figure 1. Displacement")
SuperDocs.chat(client, "Keep the document exactly as provided.";
               session_id=session, document_html=html)
```

`embed_url` prefers `canonical_url` over an expiring signed `view_url`. Files over 10 MB and unknown suffixes (png/jpg/jpeg/webp/gif/svg) are rejected. `upload_image_bytes` is the in-memory variant.

## Export

```julia
result = SuperDocs.export_document(client; session_id=session, format=:pdf,
    options=SuperDocs.ExportOptions(filename="lab-note", paper_size="Letter"),
    dest="lab-note.pdf")
bytes, warnings = result
```

Formats: `:docx` (default), `:pdf`, `:html`, `:markdown`, `:txt`. Uploads and exports are not billed; chat turns are. The export body is binary — do not JSON-parse it.

## Public API

| Group | Names |
|---|---|
| Client | `Client`, `verify_key`, `wait`, `get_job`, `cancel_job` |
| Document | `upload`, `session_html`, `html_after_job` |
| Chat / HITL | `chat`, `chat_async`, `approve`, `continue_job`, `pending_changes`, `awaiting_kind`, `is_continue_prompt` |
| Math | `latex_inline`, `latex_block`, `latex_inline_html`, `latex_block_html`, `to_native_math`, `extract_latex`, `verify_math`, `has_native_math`, `has_dollar_math` |
| Images | `upload_image`, `upload_image_bytes`, `embed_url`, `place_image` |
| Export | `export_document`, `parse_export_warnings`, `has_math_partial_fidelity` |

Errors: `AuthError`, `TimeoutError`, `RateLimited`, `APIError`, `JobFailed`, `MathVerifyError`. Extra JSON keys are ignored.

`session_id` is caller-chosen (`[A-Za-z0-9_.-]{1,256}`). The first request on a fresh session retries once on 5xx other than 504. Sync chat allows ~30 minutes (server cap). `wait` defaults to 300s; pass a larger `timeout` for slow jobs.

## How to run

Keyless tests (no network):

```bash
cd extensions/raman20/SuperDocs.jl
julia --project=. -e 'using Pkg; Pkg.test()'
```

Live script (chat turns use operations; exports do not):

```bash
export SUPERDOCS_API_KEY=your-key-here
export SUPERDOCS_LIVE=1
julia --project=. examples/live_roundtrip.jl
```

Pluto notebooks — open them in Pluto; do not `include` them as scripts:

| Notebook | What it does |
|---|---|
| `notebooks/lab_note.jl` | Fixture math with no key. With a key: HITL lab note + figure. |
| `notebooks/oscillator_flow.jl` | Integrates a synthetic oscillator, plots with gnuplot, uploads to SuperDocs. Needs `gnuplot` on `PATH`. |

`notebooks/lab_note.png` is a screenshot of a live export after HITL. With your own key, a notebook creates a session you can open at [use.superdocs.app](https://use.superdocs.app).

Optional headless run (Pluto is not a package dependency):

```bash
julia --project=<pluto-env> notebooks/run_in_pluto.jl notebooks/oscillator_flow.jl
```

## Limits

- Four-call floor plus images, math nodes, and export warnings — not templates, SSE, multi-document tabs, MCP, or agent signup.
- Registration-ready (`Project.toml` UUID + `[compat]`). Not in the General registry.
- Synthetic fixtures only.
- Image bytes are stored by SuperDocs; signed view URLs expire.

## Credit

Raman (github.com/raman20). MIT — see `LICENSE`.
