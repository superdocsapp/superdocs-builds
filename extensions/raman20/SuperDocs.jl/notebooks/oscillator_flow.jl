### A Pluto.jl notebook ###
# v0.20.13

using Markdown
using InteractiveUtils

# ╔═╡ a1000001-0000-4000-8000-000000000001
begin
    import Pkg
    Pkg.activate(joinpath(@__DIR__, ".."))
    Pkg.instantiate()
    using SuperDocs
    using Random: Xoshiro
end

# ╔═╡ a1000001-0000-4000-8000-000000000002
md"""
# Pluto → SuperDocs: damped oscillator note

A **Julia** notebook computes a synthetic forced oscillator, writes a lab note with display math, plots it with gnuplot, and hands the document to SuperDocs.jl (upload, HITL, figure, export).

All numbers are simulated. Not a physical experiment.

Open this file in Pluto, set `SUPERDOCS_API_KEY`, and run.
"""

# ╔═╡ a1000001-0000-4000-8000-000000000003
begin
    LIVE = haskey(ENV, "SUPERDOCS_API_KEY") && !isempty(ENV["SUPERDOCS_API_KEY"])
    SESSION = "oscillator-" * string(abs(rand(Int32)))
    WORK = mktempdir(prefix="pluto-osc-")
    (LIVE, SESSION, WORK)
end

# ╔═╡ a1000001-0000-4000-8000-000000000004
md"""## 1. Integrate in Julia"""

# ╔═╡ a1000001-0000-4000-8000-000000000005
sim = let
    m, c, k, F, Ω = 1.0, 0.35, 16.0, 2.4, 3.2
    dt, T, σ, x0, v0 = 0.01, 8.0, 0.08, 0.15, 0.0
    ω0 = sqrt(k / m)
    ζ = c / (2 * sqrt(k * m))
    ωd = ω0 * sqrt(1 - ζ^2)
    Xp = (F / m) / sqrt((ω0^2 - Ω^2)^2 + (2 * ζ * ω0 * Ω)^2)
    ϕ = atan(2 * ζ * ω0 * Ω, ω0^2 - Ω^2)
    n = Int(round(T / dt))
    t = range(0, step=dt, length=n) |> collect
    x = zeros(n)
    v = zeros(n)
    x[1] = x0
    v[1] = v0
    for i in 1:(n - 1)
        a = -2 * ζ * ω0 * v[i] - ω0^2 * x[i] + (F / m) * cos(Ω * t[i])
        v[i + 1] = v[i] + dt * a
        x[i + 1] = x[i] + dt * v[i + 1]
    end
    y = x .+ σ .* randn(Xoshiro(11), n)
    xhat = 0.12 .* exp.(-ζ .* ω0 .* t) .* cos.(ωd .* t) .+ Xp .* cos.(Ω .* t .- ϕ)
    rmse = sqrt(sum((y .- xhat) .^ 2) / n)
    (; m, c, k, F, Ω, dt, T, σ, ω0, ζ, ωd, Xp, ϕ, n, t, x, y, xhat, rmse)
end

# ╔═╡ a1000001-0000-4000-8000-000000000006
md"""
ω₀ = $(round(sim.ω0; digits=3)), ζ = $(round(sim.ζ; digits=5)), RMSE = $(round(sim.rmse; digits=4)) m on $(sim.n) samples.
"""

# ╔═╡ a1000001-0000-4000-8000-000000000007
md"""## 2. Figure + markdown document"""

# ╔═╡ a1000001-0000-4000-8000-000000000008
paths = let
    csv = joinpath(WORK, "series.csv")
    png = joinpath(WORK, "fig_timeseries.png")
    gp = joinpath(WORK, "fig.gp")
    mdpath = joinpath(WORK, "oscillator.md")
    open(csv, "w") do io
        println(io, "t x y xhat")
        for i in 1:sim.n
            println(io, sim.t[i], " ", sim.x[i], " ", sim.y[i], " ", sim.xhat[i])
        end
    end
    write(gp, """
set terminal pngcairo size 720,360 font "sans,10"
set output "$(png)"
set xlabel "t (s)"
set ylabel "x (m)"
set key top right
plot "$(csv)" using 1:2 with lines lw 2 title "latent x", \\
     "$(csv)" using 1:3 with points pt 7 ps 0.25 title "y (noisy)", \\
     "$(csv)" using 1:4 with lines lw 1.5 dt 2 title "fit"
""")
    run(`gnuplot $gp`)
    isfile(png) || error("gnuplot did not write $png")
    write(mdpath, """
# Forced damped oscillator (synthetic)

Computed in Julia. Not a physical experiment.

## Abstract

We integrate the forced damped oscillator
\$\$m\\ddot x + c\\dot x + kx = F\\cos(\\Omega t)\$\$
with a first-order split stepper, add i.i.d. Gaussian observation noise, and overlay a transient-plus-particular fit. This paragraph is slightly wordy on purpose so SuperDocs can tighten the prose without touching the equations.

## 1. Model

Newton's law for a linear oscillator is the display equation above. The undamped frequency and damping ratio are
\$\$\\omega_0 = \\sqrt{k/m}, \\qquad \\zeta = c/(2\\sqrt{km}).\$\$
A particular solution of the drive frequency is \$x_p(t)=X_p\\cos(\\Omega t-\\phi)\$.

## 2. Generator numbers

| symbol | value |
|---|---|
| \$m\$ | $(sim.m) kg |
| \$c\$ | $(sim.c) N s / m |
| \$k\$ | $(sim.k) N / m |
| \$\\omega_0\$ | $(round(sim.ω0; digits=4)) rad/s |
| \$\\zeta\$ | $(round(sim.ζ; digits=5)) |
| \$F\$ | $(sim.F) N |
| \$\\Omega\$ | $(sim.Ω) rad/s |
| \$\\Delta t\$ | $(sim.dt) s |
| \$T\$ | $(sim.T) s |
| \$\\sigma\$ | $(sim.σ) m |
| RMSE | $(round(sim.rmse; digits=4)) m |

## 3. Time series

### Figure 1. Displacement

Latent \$x(t)\$, noisy \$y_n\$, and the fit \$\\hat x(t)\$. RMSE is expected a little above \$\\sigma\$ because the homogeneous amplitude is set by hand, not estimated.
""")
    (; png, mdpath)
end

# ╔═╡ a1000001-0000-4000-8000-000000000009
md"""## 3. Math helpers (no API key)"""

# ╔═╡ a1000001-0000-4000-8000-00000000000a
begin
    src_md = read(paths.mdpath, String)
    from_md = SuperDocs.extract_latex(src_md)
    native_preview = SuperDocs.to_native_math("<p>\$\$\\omega_0=$(round(sim.ω0; digits=3))\$\$</p>")
    (; n_latex=length(from_md), preview_native=SuperDocs.has_native_math(native_preview),
     leftover=SuperDocs.has_dollar_math(native_preview), sample=first(from_md, 3))
end

# ╔═╡ a1000001-0000-4000-8000-00000000000b
md"""## 4. Live SuperDocs roundtrip"""

# ╔═╡ a1000001-0000-4000-8000-00000000000c
begin
    client = LIVE ? SuperDocs.Client() : nothing
    if !LIVE
        md"Live SuperDocs cells skipped (no `SUPERDOCS_API_KEY`)."
    else
        up = SuperDocs.upload(client, paths.mdpath; session_id=SESSION)
        html0 = something(up.html, SuperDocs.session_html(client, SESSION))
        expected = SuperDocs.extract_latex(html0)
        job = SuperDocs.chat_async(client,
            "Tighten the abstract. Do not alter any equation, table, or caption.";
            session_id=SESSION, approval_mode="ask_every_time")
        job = SuperDocs.wait(client, job; timeout=600)
        pending = SuperDocs.pending_changes(job)
        if job.status == "awaiting_approval" && !SuperDocs.is_continue_prompt(job)
            job = SuperDocs.approve(client, SESSION, job.job_id; approved=true, changes=pending)
            job = SuperDocs.wait(client, job; timeout=600)
        end
        html = SuperDocs.html_after_job(client, job, SESSION)
        report = SuperDocs.verify_math(html, expected)
        img = SuperDocs.upload_image(client, paths.png; filename="fig_timeseries.png")
        html_fig = SuperDocs.place_image(html, SuperDocs.embed_url(img);
                                         after="Figure 1. Displacement", alt="Figure 1. Displacement")
        SuperDocs.chat(client,
            "Keep the document exactly as provided. Do not rewrite any equation.";
            session_id=SESSION, document_html=html_fig, approval_mode="approve_all")
        html2 = SuperDocs.session_html(client, SESSION)
        dest_docx = joinpath(WORK, "oscillator.docx")
        dest_pdf = joinpath(WORK, "oscillator.pdf")
        b1, w1 = SuperDocs.export_document(client; session_id=SESSION, format=:docx,
            options=SuperDocs.ExportOptions(filename="oscillator"), dest=dest_docx)
        b2, w2 = SuperDocs.export_document(client; session_id=SESSION, format=:pdf,
            options=SuperDocs.ExportOptions(filename="oscillator", paper_size="Letter"), dest=dest_pdf)
        (; session=SESSION, verify=SuperDocs.verify_key(client),
         chunks=up.chunks_count, status=job.status, n_pending=length(pending),
         math_ok=report.ok, missing=report.missing,
         native0=SuperDocs.has_native_math(html0), leftover0=SuperDocs.has_dollar_math(html0),
         native=SuperDocs.has_native_math(html2), leftover=SuperDocs.has_dollar_math(html2),
         img_tags=length(split(html2, "<img")) - 1, embed=SuperDocs.embed_url(img),
         docx_bytes=length(b1), pdf_bytes=length(b2),
         warn_docx=[w.code for w in w1], warn_pdf=[w.code for w in w2],
         dest_docx, dest_pdf)
    end
end

# ╔═╡ Cell order:
# ╠═a1000001-0000-4000-8000-000000000001
# ╠═a1000001-0000-4000-8000-000000000002
# ╠═a1000001-0000-4000-8000-000000000003
# ╠═a1000001-0000-4000-8000-000000000004
# ╠═a1000001-0000-4000-8000-000000000005
# ╠═a1000001-0000-4000-8000-000000000006
# ╠═a1000001-0000-4000-8000-000000000007
# ╠═a1000001-0000-4000-8000-000000000008
# ╠═a1000001-0000-4000-8000-000000000009
# ╠═a1000001-0000-4000-8000-00000000000a
# ╠═a1000001-0000-4000-8000-00000000000b
# ╠═a1000001-0000-4000-8000-00000000000c
