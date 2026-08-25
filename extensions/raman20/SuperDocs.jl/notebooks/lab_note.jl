### A Pluto.jl notebook ###
# v0.20.13

using Markdown
using InteractiveUtils

# ╔═╡ 7c1a0001-0000-4000-8000-000000000001
begin
    import Pkg
    Pkg.activate(joinpath(@__DIR__, ".."))
    Pkg.instantiate()
end

# ╔═╡ 7c1a0001-0000-4000-8000-000000000002
using SuperDocs

# ╔═╡ 7c1a0001-0000-4000-8000-000000000003
md"""
# SuperDocs.jl lab note

Scientific client demo: upload a synthetic note, review an edit, keep the equation, insert a figure, export Word.

Set `SUPERDOCS_API_KEY` in the environment for the live path. Without a key, fixture cells still run `extract_latex` / `verify_math` / `to_native_math`. `upload` converts leftover `\$\$` source into native `data-latex` nodes so the web editor KaTeX-renders.
"""

# ╔═╡ 7c1a0001-0000-4000-8000-000000000004
const PKG = joinpath(@__DIR__, "..")

# ╔═╡ 7c1a0001-0000-4000-8000-000000000005
const LIVE = haskey(ENV, "SUPERDOCS_API_KEY") && !isempty(ENV["SUPERDOCS_API_KEY"])

# ╔═╡ 7c1a0001-0000-4000-8000-000000000006
lab_md = read(joinpath(PKG, "fixtures", "lab_note.md"), String)

# ╔═╡ 7c1a0001-0000-4000-8000-000000000007
md"""Source lab note (synthetic):"""

# ╔═╡ 7c1a0001-0000-4000-8000-000000000008
Text(lab_md)

# ╔═╡ 7c1a0001-0000-4000-8000-000000000009
from_md = SuperDocs.extract_latex(lab_md)

# ╔═╡ 7c1a0001-0000-4000-8000-00000000000a
uploaded_html = read(joinpath(PKG, "test", "fixtures", "lab_note_uploaded.html"), String)

# ╔═╡ 7c1a0001-0000-4000-8000-00000000000b
fixture_report = SuperDocs.verify_math(uploaded_html, SuperDocs.extract_latex(uploaded_html))

# ╔═╡ 7c1a0001-0000-4000-8000-00000000000c
md"""Fixture math report (no key needed): `ok = $(fixture_report.ok)` found $(fixture_report.found)"""

# ╔═╡ 7c1a0001-0000-4000-8000-00000000000d
begin
    native_demo = SuperDocs.to_native_math("<p>\$\$\\bar{x}=1\$\$</p>")
    client = LIVE ? SuperDocs.Client() : nothing
    session = LIVE ? ("lab-note-pluto-" * string(abs(rand(Int32)))) : nothing
    if LIVE
        (; session, native_preview=SuperDocs.has_native_math(native_demo))
    else
        md"Live cells skipped (no `SUPERDOCS_API_KEY`). Native-math demo still ran: `has_native_math = $(SuperDocs.has_native_math(native_demo))`."
    end
end

# ╔═╡ 7c1a0001-0000-4000-8000-00000000000e
begin
    if LIVE
        up = SuperDocs.upload(client, joinpath(PKG, "fixtures", "lab_note.md"); session_id=session)
        expected = SuperDocs.extract_latex(something(up.html, ""))
        job = SuperDocs.chat_async(client,
            "Tighten the abstract. Do not alter any equation.";
            session_id=session, approval_mode="ask_every_time")
        job = SuperDocs.wait(client, job; timeout=600)
        pending = SuperDocs.pending_changes(job)
        if job.status == "awaiting_approval" && !SuperDocs.is_continue_prompt(job)
            job = SuperDocs.approve(client, session, job.job_id; approved=true, changes=pending)
            job = SuperDocs.wait(client, job; timeout=600)
        end
        html = SuperDocs.html_after_job(client, job, session)
        report = SuperDocs.verify_math(html, isempty(expected) ? from_md : expected)
        png = joinpath(tempdir(), "lab-note-plot.png")
        # 1×1 PNG so the notebook does not require Plots.jl as a package dep
        write(png, UInt8[
            0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a,0x00,0x00,0x00,0x0d,0x49,0x48,0x44,0x52,
            0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x01,0x08,0x06,0x00,0x00,0x00,0x1f,0x15,0xc4,
            0x89,0x00,0x00,0x00,0x0d,0x49,0x44,0x41,0x54,0x78,0x9c,0x63,0xf8,0xcf,0xc0,0x00,
            0x00,0x00,0x03,0x00,0x01,0x00,0x05,0xfe,0xd4,0xef,0x00,0x00,0x00,0x00,0x49,0x45,
            0x4e,0x44,0xae,0x42,0x60,0x82])
        img = SuperDocs.upload_image(client, png)
        html = SuperDocs.place_image(html, SuperDocs.embed_url(img); after="Methods", alt="figure")
        SuperDocs.chat(client, "Keep the document exactly as provided. Do not rewrite any equation.";
                       session_id=session, document_html=html, approval_mode="approve_all")
        html2 = SuperDocs.session_html(client, session)
        dest = joinpath(PKG, "notebooks", "lab-note-live.docx")
        bytes, warnings = SuperDocs.export_document(client; session_id=session, format=:docx, dest=dest)
        (; session, pending, report, embed=SuperDocs.embed_url(img), dest, nbytes=length(bytes),
         native=SuperDocs.has_native_math(html2), leftover=SuperDocs.has_dollar_math(html2),
         warning_codes=[w.code for w in warnings], usage=(job.result === nothing ? nothing : job.result.usage))
    else
        md"Live SuperDocs roundtrip skipped (no `SUPERDOCS_API_KEY`)."
    end
end

# ╔═╡ Cell order:
# ╠═7c1a0001-0000-4000-8000-000000000001
# ╠═7c1a0001-0000-4000-8000-000000000002
# ╠═7c1a0001-0000-4000-8000-000000000003
# ╠═7c1a0001-0000-4000-8000-000000000004
# ╠═7c1a0001-0000-4000-8000-000000000005
# ╠═7c1a0001-0000-4000-8000-000000000006
# ╠═7c1a0001-0000-4000-8000-000000000007
# ╠═7c1a0001-0000-4000-8000-000000000008
# ╠═7c1a0001-0000-4000-8000-000000000009
# ╠═7c1a0001-0000-4000-8000-00000000000a
# ╠═7c1a0001-0000-4000-8000-00000000000b
# ╠═7c1a0001-0000-4000-8000-00000000000c
# ╠═7c1a0001-0000-4000-8000-00000000000d
# ╠═7c1a0001-0000-4000-8000-00000000000e
