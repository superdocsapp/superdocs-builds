# SuperDocs.jl

A Julia REST client for [SuperDocs](https://superdocs.app). You send files, LaTeX, plots, and edit instructions; SuperDocs stays the document engine.

Built by Raman (github.com/raman20) for the SuperDocs task. REST only — not MCP.

## What it does

A scientific computing notebook (Pluto, a script, a package test) can:

1. **Upload** a markdown lab note into a SuperDocs session.
2. **Chat** an edit (default: human-in-the-loop — review each proposed change).
3. **Keep math** as real KaTeX equations, not visible `$$` source.
4. **Insert figures** through the images API (chat will not fetch a GCS URL).
5. **Export** `.docx` / PDF and print `X-Export-Warnings` instead of swallowing them.

SuperDocs features used: chat editing, HITL approve, image upload, export, math (LaTeX → native editor nodes / Word math).

## Install

Not in the Julia General registry. From a `superdocs-builds` clone:

```julia
using Pkg
Pkg.develop(path="extensions/raman20/SuperDocs.jl")
```

Or:

```julia
Pkg.add(url="https://github.com/raman20/superdocs-builds", subdir="extensions/raman20/SuperDocs.jl")
```

Requires Julia 1.10+. Dependencies: HTTP.jl, JSON3, Base64 (stdlib).

## API key

```bash
export SUPERDOCS_API_KEY=your-key-here
```

Create a key at [use.superdocs.app](https://use.superdocs.app) → Settings → API Keys. Never commit a real key. `Client()` reads the env var; `Client(; api_key="...")` overrides it.

## Four-call flow

```julia
using SuperDocs
client = SuperDocs.Client()
session = "lab-note-1"

up = SuperDocs.upload(client, "fixtures/lab_note.md"; session_id=session)
expected = SuperDocs.extract_latex(something(up.html, ""))

job = SuperDocs.chat_async(client,
        "Tighten the abstract. Do not alter any equation.";
        session_id=session)                    # default approval_mode = ask_every_time
job = SuperDocs.wait(client, job)
pending = SuperDocs.pending_changes(job)
job = SuperDocs.approve(client, session, job.job_id; approved=true, changes=pending)
job = SuperDocs.wait(client, job)

html = SuperDocs.html_after_job(client, job, session)
SuperDocs.verify_math(html, expected)

img = SuperDocs.upload_image(client, "plot.png")
html = SuperDocs.place_image(html, SuperDocs.embed_url(img); after="Methods")
SuperDocs.chat(client, "Keep the document exactly as provided. Do not rewrite equations.";
               session_id=session, document_html=html)   # sync chat is approve_all only

bytes, warnings = SuperDocs.export_document(client; session_id=session, format=:docx)
SuperDocs.has_math_partial_fidelity(warnings) && @warn "math_partial_fidelity"
```

`chat_async` is the HITL path. Sync `chat` rejects `ask_every_time` (the server cannot pause a sync call). After `approve` / `continue_job`, call `wait` again — those POSTs return `{}`, not a finished job.

## Math

Markdown `$x^2$` / `$$E=mc^2$$` is what you write in a `.md` file. SuperDocs’ **markdown upload leaves those dollars as visible text** (often with `<br/>` inside the delimiters). The web editor only KaTeX-renders native nodes:

```html
<span data-latex="E=mc^2" data-type="inline-math">E=mc^2</span>
<span data-latex="x^2+y^2=z^2" data-type="block-math">x^2+y^2=z^2</span>
```

What the SDK does:

| Helper | Role |
|---|---|
| `latex_inline` / `latex_block` | Emit `$...$` / `$$...$$` for markdown. `latex_block` is a **single line** — newlines inside `$$` become `<br/>` and KaTeX will not match. |
| `latex_inline_html` / `latex_block_html` | Emit the native `data-latex` spans. |
| `to_native_math` | Convert leftover `$` / `$$` / `\(` / `\[` in HTML into native spans. Leaves `<code>` / `<pre>` alone. Idempotent. |
| `upload(...; native_math=true)` | Default: after markdown parse, convert and re-upload as HTML. `.tex` uploads already arrive as native nodes (no second call). |
| `chat(..., document_html=...)` | Runs `to_native_math` on the HTML you send. |
| `extract_latex` / `verify_math` | Round-trip check. Does not algebraically rewrite. Never emits Unicode lookalikes (`x²`). |
| `has_native_math` / `has_dollar_math` | Inspect HTML. |

W3C `<math>` MathML is **not** a write path: SuperDocs’ HTML upload strips it. Word export uses Office math (OMML), not MathML. If a construct cannot become native Word math, SuperDocs keeps LaTeX inside the equation and may send `math_partial_fidelity` — the SDK prints that warning; it does not hide it.

## Images

Chat will **not** fetch a `storage.googleapis.com` URL you paste in the prompt. Inject the tag:

```julia
img = SuperDocs.upload_image(client, "fig.png")
html = SuperDocs.place_image(html, SuperDocs.embed_url(img); after="Figure 1. Displacement")
SuperDocs.chat(client, "Keep the document exactly as provided.";
               session_id=session, document_html=html)
```

`embed_url` uses SuperDocs `canonical_url` (stable id), never the expiring signed `view_url`. After SuperDocs saves the document, the editor HTML `src` is typically a short-lived signed URL that the app re-mints when you open the file. `upload_image_bytes` is the same contract for in-memory PNGs.

Rejects files over 10 MB and unknown suffixes (png/jpg/jpeg/webp/gif/svg).

## Export

```julia
result = SuperDocs.export_document(client; session_id=session, format=:pdf,
    options=SuperDocs.ExportOptions(filename="lab-note", paper_size="Letter"),
    dest="lab-note.pdf")
bytes, warnings = result   # also iterable as a 2-tuple
```

Formats: `:docx` (default), `:pdf`, `:html`, `:markdown`, `:txt`. Uploads and exports are not billed; chat turns are. Never JSON-parse the export body — it is binary.

## Public API

| Group | Names |
|---|---|
| Client | `Client`, `verify_key`, `wait`, `get_job`, `cancel_job` |
| Document | `upload`, `session_html`, `html_after_job` |
| Chat / HITL | `chat`, `chat_async`, `approve`, `continue_job`, `pending_changes`, `awaiting_kind`, `is_continue_prompt` |
| Math | `latex_inline`, `latex_block`, `latex_inline_html`, `latex_block_html`, `to_native_math`, `extract_latex`, `verify_math`, `has_native_math`, `has_dollar_math` |
| Images | `upload_image`, `upload_image_bytes`, `embed_url`, `place_image` |
| Export | `export_document`, `parse_export_warnings`, `has_math_partial_fidelity` |

Errors are typed: `AuthError`, `TimeoutError`, `RateLimited`, `APIError`, `JobFailed`, `MathVerifyError`. Extra JSON keys from SuperDocs are ignored.

`session_id` is caller-chosen (`[A-Za-z0-9_.-]{1,256}`). First request on a fresh session retries once on 5xx other than 504 (cold start). Sync chat `readtimeout` is ~30 minutes (server wall-clock cap); `wait` defaults to 300s because that is enough for the lab note — pass a larger `timeout` for deep/max.

## How to run

Keyless tests (no network, transport injected):

```bash
cd extensions/raman20/SuperDocs.jl
julia --project=. -e 'using Pkg; Pkg.test()'
```

Live script (uses operations; exports are free):

```bash
export SUPERDOCS_API_KEY=your-key-here
export SUPERDOCS_LIVE=1
julia --project=. examples/live_roundtrip.jl
```

Pluto notebooks — open them **in Pluto**, do not `include` them as scripts:

| Notebook | What it does |
|---|---|
| `notebooks/lab_note.jl` | Fixture math always. With a key: HITL lab note + figure. |
| `notebooks/oscillator_flow.jl` | Julia integrates a synthetic forced oscillator, writes markdown, plots with gnuplot, uploads to SuperDocs. Needs `gnuplot` on PATH for the figure cell. |

Headless Pluto check (Pluto is **not** a package dependency):

```bash
julia --project=/tmp/pluto-sd -e 'using Pkg; Pkg.add("Pluto")'
export SUPERDOCS_API_KEY=your-key-here
julia --project=/tmp/pluto-sd notebooks/run_in_pluto.jl notebooks/oscillator_flow.jl
```

`notebooks/lab_note.png` is a screenshot of a live exported lab note after HITL. With your own API key, the notebooks write a new SuperDocs session you can open at [use.superdocs.app](https://use.superdocs.app).

## Limits

- v0.1.1 is the four-call floor plus images, math nodes, and export warnings — not all ~77 REST paths (no templates, SSE, multi-doc tabs, MCP, agent signup).
- Registration-ready (`Project.toml` UUID + `[compat]`). A General registry PR is extra.
- Synthetic fixtures only. Do not upload real papers or lab data.
- Image bytes live on SuperDocs; signed `view_url`s expire.

## License

MIT. See `LICENSE`.
