# Opt-in live roundtrip. Requires SUPERDOCS_API_KEY and SUPERDOCS_LIVE=1.
# Does not run during Pkg.test().

using SuperDocs

if !haskey(ENV, "SUPERDOCS_API_KEY") || get(ENV, "SUPERDOCS_LIVE", "0") != "1"
    println("Skipping live roundtrip (set SUPERDOCS_API_KEY and SUPERDOCS_LIVE=1).")
    exit(0)
end

pkg = dirname(@__DIR__)
lab = joinpath(pkg, "fixtures", "lab_note.md")
session = "lab-note-" * string(abs(rand(Int32)))
client = SuperDocs.Client()
outdir = mktempdir()
plot_path = joinpath(outdir, "plot.png")

println("session_id=", session)
println("verify_key=", SuperDocs.verify_key(client))

up = SuperDocs.upload(client, lab; session_id=session)
println("uploaded chunks=", up.chunks_count, " html_bytes=", up.html === nothing ? 0 : ncodeunits(up.html))
html0 = something(up.html, SuperDocs.session_html(client, session))
expected = SuperDocs.extract_latex(html0)
println("baseline latex: ", expected)
println("native_math=", SuperDocs.has_native_math(html0),
        " leftover_dollars=", SuperDocs.has_dollar_math(html0))

job = SuperDocs.chat_async(client,
    "Tighten the abstract. Do not alter any equation.";
    session_id=session, approval_mode="ask_every_time")
job = SuperDocs.wait(client, job; timeout=600)
println("after wait status=", job.status, " kind=", SuperDocs.awaiting_kind(job))
if SuperDocs.is_continue_prompt(job)
    job = SuperDocs.continue_job(client, session, job.job_id; resume=true)
    job = SuperDocs.wait(client, job; timeout=600)
end
pending = SuperDocs.pending_changes(job)
println("pending_changes=", length(pending))
for p in pending
    println("  ", p.change_id, " ", p.operation, " ", something(p.ai_explanation, ""))
end
if job.status == "awaiting_approval" && !SuperDocs.is_continue_prompt(job)
    job = SuperDocs.approve(client, session, job.job_id; approved=true, changes=pending)
    job = SuperDocs.wait(client, job; timeout=600)
end
println("post-approve status=", job.status)

html = SuperDocs.html_after_job(client, job, session)
report = SuperDocs.verify_math(html, expected)
println("math ok=", report.ok, " missing=", report.missing)

# Tiny valid-ish PNG (1x1) so we do not depend on Plots.jl in this script.
png = UInt8[
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,
    0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00, 0x00, 0x1f, 0x15, 0xc4,
    0x89, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9c, 0x63, 0xf8, 0xcf, 0xc0, 0x00,
    0x00, 0x00, 0x03, 0x00, 0x01, 0x00, 0x05, 0xfe, 0xd4, 0xef, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45,
    0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
]
write(plot_path, png)
img = SuperDocs.upload_image(client, plot_path)
println("embed_url=", SuperDocs.embed_url(img))
# SuperDocs chat will not fetch GCS URLs; drop <img src> into HTML and sync.
html_with_fig = SuperDocs.place_image(html, SuperDocs.embed_url(img); after="Methods")
chat_resp = SuperDocs.chat(client,
    "Keep the document exactly as provided. Do not rewrite any equation.";
    session_id=session, document_html=html_with_fig)
println("sync html: ", chat_resp.response)
if chat_resp.usage !== nothing
    u = chat_resp.usage
    println("usage billed=", u.was_billable, " remaining=", u.monthly_remaining, " charged=", u.ops_charged)
end

dest = joinpath(outdir, "lab-note.docx")
bytes, warnings = SuperDocs.export_document(client; session_id=session, format=:docx,
    options=SuperDocs.ExportOptions(filename="lab-note"), dest=dest)
# keep a copy for the README screenshot pipeline
cp(dest, joinpath(pkg, "notebooks", "lab-note-live.docx"); force=true)
println("exported ", dest, " bytes=", length(bytes), " warnings=", [w.code for w in warnings])
if SuperDocs.has_math_partial_fidelity(warnings)
    println("math_partial_fidelity surfaced (export still succeeded)")
end
println("math report extra=", report.extra)
println("DONE")
