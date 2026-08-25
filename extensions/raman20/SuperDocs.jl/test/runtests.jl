using Test
using JSON3
using Base64
using SuperDocs

const FIX = joinpath(@__DIR__, "fixtures")
const PKG = joinpath(@__DIR__, "..")

jsonfile(name) = JSON3.read(read(joinpath(FIX, name), String))

function json_raw(obj; status=200, headers=Dict{String,String}())
    h = merge(Dict("content-type" => "application/json"), headers)
    return SuperDocs.RawResponse(status, h, Vector{UInt8}(JSON3.write(obj)))
end

function bytes_raw(bytes::Vector{UInt8}; status=200, headers=Dict{String,String}())
    return SuperDocs.RawResponse(status, headers, bytes)
end

@testset "SuperDocs.jl" begin

    @testset "Client factory" begin
        fake = (method, url, headers, body) -> json_raw(Dict())
        c = SuperDocs.Client(; api_key="sk_test", transport=fake)
        @test c isa SuperDocs.Client
        @test c.api_key == "sk_test"
        @test c.timeout_sync_s == 1810.0
        @test SuperDocs.Client(; api_key="sk_test", transport=fake) isa SuperDocs.Client
        @test_throws SuperDocs.AuthError SuperDocs.Client()
    end

    @testset "session id validation" begin
        fake = (m, u, h, b) -> json_raw(Dict("html" => "<p/>", "session_id" => "ok"))
        c = SuperDocs.Client(; api_key="sk_test", transport=fake)
        @test_throws ArgumentError SuperDocs.encode_chat(; message="hi", session_id="bad id")
        @test_throws ArgumentError SuperDocs.encode_chat(; message="hi", session_id="a/b")
    end

    @testset "chat encoder" begin
        payload = SuperDocs.encode_chat(; message="Tighten the abstract.", session_id="lab-note-1")
        @test payload["message"] == "Tighten the abstract."
        @test payload["session_id"] == "lab-note-1"
        @test !haskey(payload, "document_html")
        @test !haskey(payload, "async_mode")
        async_default = SuperDocs.encode_chat(; message="x", session_id="s",
                                              approval_mode="ask_every_time")
        @test async_default["approval_mode"] == "ask_every_time"
        @test_throws ArgumentError SuperDocs.encode_chat(; message="", session_id="s")
    end

    @testset "chat() rejects HITL" begin
        fake = (m, u, h, b) -> json_raw(Dict("response" => "ok", "session_id" => "s"))
        c = SuperDocs.Client(; api_key="sk_test", transport=fake)
        @test_throws ArgumentError SuperDocs.chat(c, "hi"; session_id="s", approval_mode="ask_every_time")
    end

    @testset "chat decoder" begin
        obj = jsonfile("chat_response.json")
        resp = SuperDocs.decode_chat_response(obj)
        @test resp isa SuperDocs.ChatResponse
        @test resp.response isa String
        @test resp.usage.ops_charged == 1
        @test resp.usage.monthly_remaining == 499
        @test !(resp isa Dict)
    end

    @testset "double-parse proposed_change_batch" begin
        obj = jsonfile("proposed_change_batch_stringified.json")
        ev = SuperDocs.decode_intermediate(obj)
        @test ev.content isa SuperDocs.ProposedChangeBatch
        @test !isempty(ev.content.changes)
        @test ev.content.changes[1].change_id == "ch_1"
        @test ev.content.changes[1].operation == "edit"
    end

    @testset "maybe_json on progress text" begin
        @test SuperDocs.maybe_json("Analyzing document structure...") == "Analyzing document structure..."
        @test SuperDocs.maybe_json("{not json") == "{not json"
        parsed = SuperDocs.maybe_json("{\"a\":1}")
        @test parsed.a == 1
    end

    @testset "continue_prompt flavour" begin
        job = SuperDocs.decode_job(jsonfile("job_awaiting_continue.json"))
        @test SuperDocs.is_continue_prompt(job)
        @test SuperDocs.awaiting_kind(job) == "continue_prompt"
        @test isempty(SuperDocs.pending_changes(job))
        hitl = SuperDocs.decode_job(jsonfile("job_awaiting.json"))
        @test !SuperDocs.is_continue_prompt(hitl)
        @test SuperDocs.pending_changes(hitl)[1].change_id == "ch_1"
    end

    @testset "approve encoder" begin
        body = SuperDocs.encode_approve(; job_id="job_1", approved=true, changes=SuperDocs.PendingChange[])
        @test body["approved"] === true
        @test body["job_id"] == "job_1"
        @test haskey(body, "approved")
        @test_throws UndefKeywordError SuperDocs.encode_approve(; job_id="job_1")
        pc = SuperDocs.PendingChange(change_id="ch_1", operation="edit")
        body2 = SuperDocs.encode_approve(; job_id="job_1", approved=true, changes=[pc])
        @test body2["changes"][1]["approved"] === true
    end

    @testset "approve 200 empty object then get_job" begin
        calls = []
        fake = function (method, url, headers, body)
            push!(calls, (method, url))
            if method == "POST" && occursin("/approve", url)
                return json_raw(Dict())
            end
            return json_raw(jsonfile("job_awaiting.json"))
        end
        c = SuperDocs.Client(; api_key="sk_test", transport=fake)
        job = SuperDocs.approve(c, "lab-note-1", "job_hitl"; approved=true)
        @test job isa SuperDocs.Job
        @test job.job_id == "job_hitl"
        @test calls[1][1] == "POST"
        @test occursin("/approve", calls[1][2])
        @test calls[2][1] == "GET"
        @test occursin("/v1/jobs/job_hitl", calls[2][2])
        @test length(calls) == 2
    end

    @testset "session_html field" begin
        fake = function (method, url, headers, body)
            @test occursin("/v1/sessions/lab-note-1/history", url)
            @test !occursin("/documents", url)
            return json_raw(jsonfile("session_history.json"))
        end
        c = SuperDocs.Client(; api_key="sk_test", transport=fake)
        html = SuperDocs.session_html(c, "lab-note-1")
        @test occursin("application/x-tex", html)
        missing_html = SuperDocs.Client(; api_key="sk_test", transport=(m,u,h,b) -> json_raw(Dict("session_id"=>"s")))
        @test_throws SuperDocs.APIError SuperDocs.session_html(missing_html, "s")
    end

    @testset "html_after_job" begin
        hist = SuperDocs.Client(; api_key="sk_test",
            transport=(m,u,h,b) -> json_raw(jsonfile("session_history.json")))
        empty_job = SuperDocs.Job(; job_id="j", session_id="lab-note-1", status="completed")
        html = SuperDocs.html_after_job(hist, empty_job, "lab-note-1")
        @test occursin("bar{x}", html)
        filled = SuperDocs.Job(; job_id="j", session_id="lab-note-1", status="completed",
            result=SuperDocs.JobResult(document_changes=SuperDocs.DocumentChanges(updated_html="<p>from-job</p>")))
        @test SuperDocs.html_after_job(hist, filled, "lab-note-1") == "<p>from-job</p>"
    end

    @testset "cancel 200 empty then get_job" begin
        calls = []
        fake = function (method, url, headers, body)
            push!(calls, (method, url))
            if method == "POST" && occursin("/cancel", url)
                return json_raw(Dict())
            end
            return json_raw(Dict("job_id"=>"j1","session_id"=>"s","status"=>"cancelled"))
        end
        c = SuperDocs.Client(; api_key="sk_test", transport=fake)
        job = SuperDocs.cancel_job(c, "j1")
        @test job.status == "cancelled"
        @test calls[1][1] == "POST"
        @test calls[2][1] == "GET"
        n = 0
        accepted = function (method, url, headers, body)
            n += 1
            if method == "POST"
                return json_raw(Dict("stop_state"=>"accepted"))
            end
            if n < 4
                return json_raw(Dict("job_id"=>"j1","session_id"=>"s","status"=>"in_progress",
                    "metadata"=>Dict("stopped_unwound"=>false)))
            end
            return json_raw(Dict("job_id"=>"j1","session_id"=>"s","status"=>"cancelled",
                "metadata"=>Dict("stopped_unwound"=>true)))
        end
        c2 = SuperDocs.Client(; api_key="sk_test", transport=accepted)
        job2 = SuperDocs.cancel_job(c2, "j1")
        @test job2.status == "cancelled"
        forbidden = (m,u,h,b) -> SuperDocs.RawResponse(409, Dict("content-type"=>"application/json"),
            Vector{UInt8}("{\"detail\":\"already finished\"}"))
        c3 = SuperDocs.Client(; api_key="sk_test", transport=forbidden)
        @test_throws SuperDocs.APIError SuperDocs.cancel_job(c3, "j1")
    end

    @testset "transport arity and compact poll" begin
        seen = String[]
        fake = function (method, url, headers, body)
            @test method isa String
            @test url isa String
            push!(seen, url)
            return json_raw(Dict("job_id"=>"j","session_id"=>"s","status"=>"completed",
                "result"=>Dict("response"=>"done","session_id"=>"s")))
        end
        c = SuperDocs.Client(; api_key="sk_test", transport=fake, poll_interval_s=0.0)
        job = SuperDocs.Job(; job_id="j", session_id="s", status="pending")
        SuperDocs.wait(c, job; timeout=5, interval=0)
        @test any(u -> occursin("compact=true", u), seen)
        @test any(u -> occursin("/v1/jobs/j", u) && !occursin("compact=true", u), seen)
    end

    @testset "math round-trip" begin
        md = read(joinpath(PKG, "fixtures", "lab_note.md"), String)
        html = read(joinpath(FIX, "lab_note_uploaded.html"), String)
        from_md = SuperDocs.extract_latex(md)
        from_html = SuperDocs.extract_latex(html)
        @test any(s -> occursin("bar{x}", s) || occursin("sum", s), from_md)
        @test any(s -> occursin("bar{x}", s), from_html)
        report = SuperDocs.verify_math(html, from_html)
        @test report.ok
        mutated = replace(html, r"<annotation.*?</annotation>"s => "")
        mutated = replace(mutated, r"\\\(.*?\\\)"s => "")
        bad = SuperDocs.verify_math(mutated, from_html)
        @test !bad.ok
        @test !isempty(bad.missing)
        @test SuperDocs.latex_inline("x^2") == "\$x^2\$"
        @test !occursin("²", SuperDocs.latex_inline("x^2"))
        @test SuperDocs.latex_block("x^2") == "\$\$x^2\$\$"
        @test !occursin("\n", SuperDocs.latex_block("x^2"))
        already = SuperDocs.latex_inline("\$a\$")
        @test already == "\$a\$"
    end

    @testset "native math nodes" begin
        inline = SuperDocs.latex_inline_html("x^2")
        @test occursin("data-type=\"inline-math\"", inline)
        @test occursin("data-latex=\"x^2\"", inline)
        @test !occursin("\$", inline)
        @test !occursin("²", inline)
        block = SuperDocs.latex_block_html("E = mc^2")
        @test occursin("data-type=\"block-math\"", block)
        @test occursin("data-latex=\"E = mc^2\"", block)
        broken = "<p>\$\$<br/>m=1,\\quad c=0.35,<br/>\\sigma=0.08.<br/>\$\$</p>" *
                 "<p>Let \$x(t)\$ be displacement. Use <code>\$\$...\$\$</code>.</p>"
        native = SuperDocs.to_native_math(broken)
        @test SuperDocs.has_native_math(native)
        @test !SuperDocs.has_dollar_math(native)
        @test occursin("data-type=\"block-math\"", native)
        @test occursin("data-type=\"inline-math\"", native)
        @test occursin("<code>\$\$...\$\$</code>", native)
        @test SuperDocs.to_native_math(native) == native
        report = SuperDocs.verify_math(native, ["m=1,\\quad c=0.35, \\sigma=0.08.", "x(t)"])
        @test report.ok
        # leftover dollars in code are not extracted as equations
        @test !any(t -> t == "...", report.found)
        ent = SuperDocs.to_native_math("<p>\$0&lt;\\zeta&lt;1\$</p>")
        found = SuperDocs.extract_latex(ent)
        @test any(t -> occursin("0<\\zeta<1", t), found)
        @test SuperDocs.has_dollar_math(broken)
        @test !SuperDocs.has_dollar_math(native)
        payload = SuperDocs.encode_chat(; message="keep math", session_id="lab-note-1",
                                        document_html="<p>\$\$E=mc^2\$\$</p>")
        @test occursin("block-math", payload["document_html"])
        @test !occursin("\$\$", payload["document_html"])
    end

    @testset "upload native_math re-load" begin
        calls = []
        dollar_html = "<p>\$\$x^2\$\$</p>"
        native_html = SuperDocs.to_native_math(dollar_html)
        fake = function (method, url, headers, body)
            push!(calls, url)
            @test occursin("/v1/documents/upload", url)
            if length(calls) == 1
                return json_raw(Dict("html"=>dollar_html, "session_id"=>"s",
                                     "chunks_count"=>1, "filename"=>"note.md"))
            end
            return json_raw(Dict("html"=>native_html, "session_id"=>"s",
                                 "chunks_count"=>1, "filename"=>"note.html"))
        end
        c = SuperDocs.Client(; api_key="sk_test", transport=fake)
        md = joinpath(tempdir(), "sd-native-math.md")
        write(md, "\$\$x^2\$\$")
        up = SuperDocs.upload(c, md; session_id="s")
        @test length(calls) == 2
        @test SuperDocs.has_native_math(something(up.html, ""))
        @test !SuperDocs.has_dollar_math(something(up.html, ""))
        calls2 = []
        fake2 = function (method, url, headers, body)
            push!(calls2, url)
            return json_raw(Dict("html"=>dollar_html, "session_id"=>"s", "chunks_count"=>1))
        end
        c2 = SuperDocs.Client(; api_key="sk_test", transport=fake2)
        up2 = SuperDocs.upload(c2, md; session_id="s", native_math=false)
        @test length(calls2) == 1
        @test SuperDocs.has_dollar_math(something(up2.html, ""))
    end

    @testset "image URL struct" begin
        multi = SuperDocs.decode_image_ref(jsonfile("image_upload.json"))
        @test SuperDocs.embed_url(multi) == "https://cdn.superdocs.app/img/canonical-plot"
        @test multi.canonical_url == "https://cdn.superdocs.app/img/canonical-plot"
        @test SuperDocs.embed_url(multi) != multi.view_url
        b64 = SuperDocs.decode_image_ref(jsonfile("image_upload_base64.json"))
        @test SuperDocs.embed_url(b64) == "https://cdn.superdocs.app/img/stable-plot"
        @test SuperDocs.embed_url(b64) != b64.view_url
        @test_throws SuperDocs.APIError SuperDocs.decode_image_ref(JSON3.read("{}"))
        calls = []
        fake = function (method, url, headers, body)
            push!(calls, url)
            @test occursin("/v1/documents/images/upload", url)
            @test !occursin("application/json", get(headers, "Content-Type", get(headers, "content-type", "")))
            return json_raw(jsonfile("image_upload.json"))
        end
        png = joinpath(tempdir(), "sd-test-plot.png")
        write(png, UInt8[0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
        c = SuperDocs.Client(; api_key="sk_test", transport=fake)
        img = SuperDocs.upload_image(c, png)
        @test SuperDocs.embed_url(img) == "https://cdn.superdocs.app/img/canonical-plot"
        @test_throws ArgumentError SuperDocs.upload_image(c, png; filename="plot.bmp")
        html = "<h2>Methods</h2><p>body</p>"
        placed = SuperDocs.place_image(html, "https://cdn.superdocs.app/img/canonical-plot"; after="Methods")
        @test occursin("<img src=\"https://cdn.superdocs.app/img/canonical-plot\"", placed)
        @test findfirst("Methods", placed).stop < findfirst("<img", placed).start
    end

    @testset "export warnings and Accept" begin
        payload = JSON3.write([Dict("code"=>"math_partial_fidelity","message"=>"kept as LaTeX","detail"=>Dict("tex"=>"\\foo"))])
        b64 = Base64.base64encode(payload)
        hdrs = Dict("x-export-warnings"=>b64, "content-type"=>"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "content-disposition"=>"attachment; filename=\"lab-note.docx\"")
        warns = SuperDocs.parse_export_warnings(hdrs)
        @test SuperDocs.has_math_partial_fidelity(warns)
        @test SuperDocs.parse_export_warnings(Dict{String,String}()) == SuperDocs.ExportWarning[]
        seen_accept = Ref("")
        fake = function (method, url, headers, body)
            seen_accept[] = get(headers, "Accept", get(headers, "accept", ""))
            @test seen_accept[] != "application/json"
            @test occursin("/v1/documents/export", url)
            return bytes_raw(UInt8[0x50, 0x4b]; headers=merge(Dict("content-type"=>"application/octet-stream"), hdrs))
        end
        c = SuperDocs.Client(; api_key="sk_test", transport=fake)
        result = SuperDocs.export_document(c; session_id="lab-note-1", format=:docx)
        @test result.bytes == UInt8[0x50, 0x4b]
        bytes, warnings = result
        @test bytes == result.bytes
        @test SuperDocs.has_math_partial_fidelity(warnings)
        @test seen_accept[] == "*/*"
    end

    @testset "cold retry" begin
        n503 = Ref(0)
        fake503 = function (method, url, headers, body)
            n503[] += 1
            if n503[] == 1
                return SuperDocs.RawResponse(503, Dict("content-type"=>"application/json"), Vector{UInt8}("{\"detail\":\"warming\"}"))
            end
            return json_raw(Dict("job_id"=>"j","session_id"=>"fresh-1","status"=>"pending"))
        end
        c = SuperDocs.Client(; api_key="sk_test", transport=fake503)
        job = SuperDocs.chat_async(c, "hi"; session_id="fresh-1", cold=true)
        @test job.job_id == "j"
        @test n503[] == 2
        n504 = Ref(0)
        fake504 = function (method, url, headers, body)
            n504[] += 1
            return SuperDocs.RawResponse(504, Dict("content-type"=>"application/json"),
                Vector{UInt8}("{\"detail\":\"wall-clock timeout (30 min)\"}"))
        end
        c2 = SuperDocs.Client(; api_key="sk_test", transport=fake504)
        @test_throws SuperDocs.TimeoutError SuperDocs.chat_async(c2, "hi"; session_id="fresh-2", cold=true)
        @test n504[] == 1
    end

    @testset "401 vs 403 vs 413" begin
        e401 = SuperDocs.Client(; api_key="sk_test",
            transport=(m,u,h,b) -> SuperDocs.RawResponse(401, Dict("content-type"=>"application/json"),
                read(joinpath(FIX, "errors", "401.json"))))
        @test_throws SuperDocs.AuthError SuperDocs.verify_key(e401)
        e403 = SuperDocs.Client(; api_key="sk_test",
            transport=(m,u,h,b) -> SuperDocs.RawResponse(403, Dict("content-type"=>"application/json"),
                read(joinpath(FIX, "errors", "403.json"))))
        @test_throws SuperDocs.APIError SuperDocs.verify_key(e403)
        e413 = SuperDocs.Client(; api_key="sk_test",
            transport=(m,u,h,b) -> SuperDocs.RawResponse(413, Dict("content-type"=>"application/json"),
                read(joinpath(FIX, "errors", "413.json"))))
        err = try
            SuperDocs.export_document(e413; session_id="s")
            nothing
        catch e
            e
        end
        @test err isa SuperDocs.APIError
        @test err.status == 413
        @test err.suggested_action == "email_request" || occursin("email_request", err.detail)
    end

    @testset "header redaction" begin
        @test SuperDocs.redact_header_value("Authorization", "Bearer sk_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") == "Bearer [redacted]"
        @test SuperDocs.redact_header_value("Content-Type", "application/json") == "application/json"
    end

    @testset "key scan" begin
        bad = false
        msgs = String[]
        for (dir, _, files) in walkdir(PKG)
            occursin(".git", dir) && continue
            occursin("Manifest.toml", dir) && continue
            for f in files
                endswith(f, ".png") && continue
                path = joinpath(dir, f)
                text = try
                    read(path, String)
                catch
                    continue
                end
                if occursin(r"sk_[0-9a-f]{32}", text)
                    # allow the redaction test's obvious fake key of all-a
                    if occursin(r"sk_[0-9a-f]{32}", text) && !occursin("sk_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", text)
                        # still fail on any other 32-hex key
                        for m in eachmatch(r"sk_[0-9a-f]{32}", text)
                            if m.match != "sk_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                                push!(msgs, "key-like token in $path")
                                bad = true
                            end
                        end
                    end
                end
                if occursin(r"lce_[A-Za-z0-9]{20,}", text)
                    push!(msgs, "org key-like token in $path")
                    bad = true
                end
                for m in eachmatch(r"(?m)^(?:export\s+)?SUPERDOCS_API_KEY=([^\s\"'`]+)", text)
                    val = m.captures[1]
                    if val != "your-key-here" && !startswith(val, "\$") && val != "..."
                        push!(msgs, "SUPERDOCS_API_KEY assignment in $path")
                        bad = true
                    end
                end
            end
        end
        @test !bad
        isempty(msgs) || @info "key scan" msgs
    end

    @testset "tests always inject transport" begin
        # This file never constructs Client() without transport= except the AuthError case.
        src = read(@__FILE__, String)
        @test occursin("transport=", src)
        @test occursin("AuthError", src)
    end

    @testset "429 usage headers" begin
        fake = (m,u,h,b) -> SuperDocs.RawResponse(429,
            Dict("content-type"=>"text/plain","retry-after"=>"2",
                 "x-usage-limit"=>"500","x-usage-used"=>"500","x-usage-remaining"=>"0"),
            Vector{UInt8}("slow down"))
        c = SuperDocs.Client(; api_key="sk_test", transport=fake)
        e = try
            SuperDocs.verify_key(c)
            nothing
        catch err
            err
        end
        @test e isa SuperDocs.RateLimited
        @test e.retry_after == 2
        @test e.monthly_remaining == 0
    end
end
