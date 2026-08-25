# SuperDocs.jl

A Julia SDK for [SuperDocs](https://superdocs.app): files, LaTeX, plots, and edit instructions go in; typed REST writes come back. SuperDocs stays the document engine. Julia is the client.

Built for the SuperDocs task.

This package is **not** in the Julia General registry yet. Install from this folder:

```julia
using Pkg
Pkg.develop(path="extensions/raman20/SuperDocs.jl")  # from a superdocs-builds clone
# or: Pkg.add(url="https://github.com/raman20/superdocs-builds", subdir="extensions/raman20/SuperDocs.jl")
```

Requires Julia 1.10+. Set `SUPERDOCS_API_KEY=your-key-here` (never commit a real key). Create a key at [use.superdocs.app](https://use.superdocs.app) → Settings → API Keys, or via agent signup in the [docs](https://docs.superdocs.app).

## What it does

A scientific computing client: upload a lab note, ask SuperDocs to edit it, approve the proposed changes item by item, insert a plot via the images API, check that LaTeX survived, export `.docx` / PDF.

SuperDocs features used: chat editing, human-in-the-loop approve, image upload, export, math (LaTeX → native editor/Word math). REST only — not MCP.

```julia
using SuperDocs
client = SuperDocs.Client()                 # reads SUPERDOCS_API_KEY
session = "lab-note-1"
up = SuperDocs.upload(client, "fixtures/lab_note.md"; session_id=session)
expected = SuperDocs.extract_latex(up.html)
job = SuperDocs.chat_async(client,
        "Tighten the abstract. Do not alter any equation.";
        session_id=session, approval_mode="ask_every_time")
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
```

`chat_async` defaults to review mode (`ask_every_time`). Sync `chat` is auto-apply only and rejects HITL.

**Math.** Markdown `$...$` / `$$...$$` is what you write in a `.md` file. SuperDocs' markdown upload leaves those dollars as **visible source** — KaTeX in the web editor only mounts native nodes:

```html
<span data-latex="E=mc^2" data-type="inline-math">E=mc^2</span>
<span data-latex="x^2+y^2=z^2" data-type="block-math">x^2+y^2=z^2</span>
```

`latex_inline` / `latex_block` still emit dollar delimiters for markdown (no extra newlines inside `$$` — those become `<br/>` and KaTeX will not match). `latex_inline_html` / `latex_block_html` emit the native spans. `upload(...; native_math=true)` (the default) converts leftover dollars in the parsed HTML and re-loads the file as HTML. `chat(..., document_html=...)` runs the same conversion. `to_native_math` / `has_dollar_math` / `has_native_math` are the building blocks. Helpers never emit Unicode lookalikes. `verify_math` checks sources; it does not algebraically rewrite.

Image embed URLs prefer SuperDocs `canonical_url` (never an expiring `view_url`). Export warnings such as `math_partial_fidelity` are returned, never swallowed.

## How to run

Keyless tests (no network):

```bash
cd extensions/raman20/SuperDocs.jl
julia --project=. -e 'using Pkg; Pkg.test()'
```

Live roundtrip (uses operations; exports are free):

```bash
export SUPERDOCS_API_KEY=your-key-here
export SUPERDOCS_LIVE=1
julia --project=. examples/live_roundtrip.jl
```

Pluto notebooks (run **inside Pluto**, not as a raw script):

- `notebooks/lab_note.jl` — fixture math always; live HITL lab note when `SUPERDOCS_API_KEY` is set.
- `notebooks/oscillator_flow.jl` — Julia integrates a synthetic oscillator, writes markdown, plots with gnuplot, uploads session `pluto-oscillator-011`.

Headless check (Pluto is not a package dep):

```bash
julia --project=/tmp/pluto-sd notebooks/run_in_pluto.jl notebooks/oscillator_flow.jl
```

The README screenshot (`notebooks/lab_note.png`) is the **live exported lab note** after HITL. SuperDocs chat will not fetch GCS image URLs — `place_image` injects `<img src>` (canonical URL from `upload_image`). PDF/Word export typesets native math nodes; leftover `$` source stays source. The SDK still prints `math_partial_fidelity` when SuperDocs sends it.

## Limits (honest)

- v0.1 wraps the four-call floor (upload → chat → approve → export) plus images and export warnings — not all 77 REST paths.
- Registration-ready (`Project.toml` UUID + compat). A General registry PR is extra, not required for this task.
- Synthetic fixtures only. Do not upload real papers or lab data.
- Image storage is SuperDocs-side; signed view URLs expire — the SDK embeds the canonical URL.

## Credit

Built by Raman (github.com/raman20) for the SuperDocs task.
