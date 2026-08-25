# Headless Pluto runner for SuperDocs.jl notebooks.
# Not a package dependency: run from a throwaway env that has Pluto.
#
#   SUPERDOCS_API_KEY=... SUPERDOCS_LIVE=1 julia --project=/tmp/pluto-sd \
#     notebooks/run_in_pluto.jl notebooks/oscillator_flow.jl

using Pluto

isempty(ARGS) && error("usage: julia run_in_pluto.jl <notebook.jl>")
path = abspath(ARGS[1])
isfile(path) || error("missing notebook $path")

session = Pluto.ServerSession()
session.options.server.launch_browser = false
session.options.server.disable_writing_notebook_files = true
session.options.evaluation.workspace_use_distributed = false
session.options.evaluation.run_notebook_on_load = true

println("pluto=", pkgversion(Pluto))
println("notebook=", path)
println("live_key=", haskey(ENV, "SUPERDOCS_API_KEY") && !isempty(ENV["SUPERDOCS_API_KEY"]))

nb = Pluto.SessionActions.open(session, path; run_async=false)

function redact(s::AbstractString)
    t = replace(s, r"sk_[0-9a-f]{32}" => "sk_[redacted]")
    return replace(t, r"lce_[A-Za-z0-9]{16,}" => "lce_[redacted]")
end

function report_cells(nb)
    nerr = 0
    for (i, cell) in enumerate(nb.cells)
        body = cell.output.body
        preview = body isa AbstractString ? String(body) : string(body)
        preview = redact(preview)
        if cell.errored
            nerr += 1
            println("CELL_ERROR index=", i, " id=", cell.cell_id)
            println(first(preview, 2000))
            println("---")
        else
            isempty(strip(preview)) && continue
            println("CELL_OK index=", i, " ", first(replace(preview, r"\s+" => " "), 180))
        end
    end
    return nerr
end

nerr = report_cells(nb)
println("cells=", length(nb.cells), " errors=", nerr)
nerr == 0 || error("Pluto notebook had $nerr errored cell(s)")
println("PLUTO_OK")
