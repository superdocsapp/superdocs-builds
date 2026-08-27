# HTTP belt. Keyword Client() calls the positional constructor — does not recurse.
# Injected transport is 4-arg (method, url, headers, body). Timeouts only on HTTP.jl.

const Transport = Function

struct RawResponse
    status::Int
    headers::Dict{String,String}
    body::Vector{UInt8}
end

struct Client
    api_key::String
    base_url::String
    timeout_sync_s::Float64
    timeout_async_s::Float64
    timeout_poll_s::Float64
    timeout_io_s::Float64
    poll_interval_s::Float64
    user_agent::String
    transport::Union{Nothing,Transport}
    seen_sessions::Set{String}
end

"""Keyword factory. Calls the positional constructor — does not recurse."""
function Client(; api_key::Union{Nothing,AbstractString}=nothing,
                base_url::AbstractString="https://api.superdocs.app",
                timeout_sync_s::Float64=1810.0,
                timeout_async_s::Float64=30.0,
                timeout_poll_s::Float64=30.0,
                timeout_io_s::Float64=120.0,
                poll_interval_s::Float64=2.0,
                user_agent::AbstractString="SuperDocs.jl/0.1.1",
                transport::Union{Nothing,Transport}=nothing)
    key = api_key === nothing ? get(ENV, "SUPERDOCS_API_KEY", "") : String(api_key)
    if isempty(key) && transport === nothing
        throw(AuthError("SUPERDOCS_API_KEY is missing. Set the env var or pass api_key=..."))
    end
    return Client(key, String(base_url), timeout_sync_s, timeout_async_s,
                  timeout_poll_s, timeout_io_s, poll_interval_s,
                  String(user_agent), transport, Set{String}())
end

function _lower_headers(h)::Dict{String,String}
    out = Dict{String,String}()
    for (k, v) in h
        out[lowercase(String(k))] = String(v)
    end
    return out
end

function redact_header_value(name::AbstractString, value::AbstractString)
    lowercase(String(name)) == "authorization" && return "Bearer [redacted]"
    occursin(r"sk_[0-9a-f]{32}", value) && return "[redacted]"
    occursin(r"lce_[A-Za-z0-9]{16,}", value) && return "[redacted]"
    return String(value)
end

function auth_headers(client::Client; accept::Union{Nothing,String}="application/json",
                      content_type::Union{Nothing,String}=nothing)
    h = Dict{String,String}(
        "Authorization" => "Bearer $(client.api_key)",
        "User-Agent" => client.user_agent,
    )
    accept !== nothing && (h["Accept"] = accept)
    content_type !== nothing && (h["Content-Type"] = content_type)
    return h
end

function request!(client::Client, method::String, url::String, headers, body;
                  readtimeout::Float64)
    @debug "SuperDocs.jl request" method=method path=_path_only(url) status_pending=true
    if client.transport !== nothing
        return client.transport(method, url, headers, body)
    end
    try
        resp = HTTP.request(method, url, headers, body;
                            readtimeout=round(Int, readtimeout), connecttimeout=30,
                            status_exception=false)
        return RawResponse(Int(resp.status), _lower_headers(resp.headers), Vector{UInt8}(resp.body))
    catch e
        msg = sprint(showerror, e)
        if occursin(r"timeout"i, msg) || occursin("Timeout", string(typeof(e)))
            throw(TimeoutError("HTTP read/connect timeout on $method $(_path_only(url)): $msg", nothing))
        end
        rethrow()
    end
end

_path_only(url::AbstractString) = begin
    u = String(url)
    i = findfirst("://", u)
    rest = i === nothing ? u : u[(last(i) + 1):end]
    slash = findfirst('/', rest)
    slash === nothing && return rest
    pathq = rest[slash:end]
    q = findfirst('?', pathq)
    return q === nothing ? pathq : pathq[1:q-1]
end

function _parse_error_body(raw::RawResponse)
    txt = String(raw.body)
    isempty(strip(txt)) && return (txt, nothing, nothing)
    obj = try
        JSON3.read(txt)
    catch
        return (txt, nothing, nothing)
    end
    detail = jget(obj, :detail)
    error_code = jstr(obj, :error_code)
    suggested = jstr(obj, :suggested_action)
    if detail === nothing
        detail = jget(obj, :error)
    end
    if detail === nothing
        detail = jget(obj, :message)
    end
    if detail isa JSON3.Object || detail isa AbstractDict
        error_code === nothing && (error_code = jstr(detail, :error_code))
        suggested === nothing && (suggested = jstr(detail, :suggested_action))
        return (JSON3.write(detail), error_code, suggested)
    elseif detail isa AbstractVector
        return (JSON3.write(detail), error_code, suggested)
    elseif detail isa AbstractString
        return (String(detail), error_code, suggested)
    else
        return (txt, error_code, suggested)
    end
end

function raise_http!(raw::RawResponse)
    s = raw.status
    s < 400 && return raw
    detail, error_code, suggested = _parse_error_body(raw)
    if s == 401
        throw(AuthError(isempty(detail) ? "unauthorized" : detail))
    elseif s == 429
        ra = tryparse(Int, get(raw.headers, "retry-after", ""))
        throw(RateLimited(
            isempty(detail) ? "rate limited" : detail,
            ra,
            tryparse(Int, get(raw.headers, "x-usage-limit", "")),
            tryparse(Int, get(raw.headers, "x-usage-used", "")),
            tryparse(Int, get(raw.headers, "x-usage-remaining", "")),
        ))
    elseif s == 504
        throw(TimeoutError(isempty(detail) ? "gateway/wall-clock timeout (30 min)" : detail, nothing))
    else
        throw(APIError(s, isempty(detail) ? "HTTP $s" : detail, error_code, suggested))
    end
end

function request_checked(client::Client, method::String, url::String, headers, body;
                         readtimeout::Float64, cold::Bool=false)
    raw = request!(client, method, url, headers, body; readtimeout=readtimeout)
    if cold && raw.status >= 500 && raw.status != 504
        sleep(1)
        raw = request!(client, method, url, headers, body; readtimeout=readtimeout)
    elseif cold && raw.status == 0
        sleep(1)
        raw = request!(client, method, url, headers, body; readtimeout=readtimeout)
    end
    return raise_http!(raw)
end

function json_body(payload)::Vector{UInt8}
    Vector{UInt8}(JSON3.write(payload))
end

function decode_json(raw::RawResponse)
    isempty(raw.body) && return JSON3.read("{}")
    txt = strip(String(raw.body))
    isempty(txt) && return JSON3.read("{}")
    return JSON3.read(txt)
end

function is_cold(client::Client, session_id::AbstractString, cold::Union{Nothing,Bool})
    cold === nothing && return !(String(session_id) in client.seen_sessions)
    return cold
end

function mark_seen!(client::Client, session_id::AbstractString)
    push!(client.seen_sessions, String(session_id))
    return nothing
end

"""GET /v1/sessions (0 operations). 200 → true. 401 → AuthError."""
function verify_key(client::Client)::Bool
    url = rstrip(client.base_url, '/') * "/v1/sessions"
    headers = auth_headers(client)
    raw = request_checked(client, "GET", url, headers, UInt8[];
                          readtimeout=client.timeout_poll_s)
    return raw.status < 400
end

function get_job(client::Client, job_id::AbstractString; compact::Bool=false)::Job
    url = rstrip(client.base_url, '/') * "/v1/jobs/" * String(job_id)
    compact && (url *= "?compact=true")
    headers = auth_headers(client)
    raw = request_checked(client, "GET", url, headers, UInt8[];
                          readtimeout=client.timeout_poll_s)
    return decode_job(decode_json(raw))
end

function pending_changes(job::Job)::Vector{PendingChange}
    if is_continue_prompt(job)
        @warn "job is a continue_prompt; pending_changes is empty — use continue_job, not approve"
        return PendingChange[]
    end
    m = job.metadata
    m === nothing && return PendingChange[]
    return m.pending_changes
end

awaiting_kind(job::Job)::Union{Nothing,String} =
    job.metadata === nothing ? nothing : job.metadata.awaiting_kind

is_continue_prompt(job::Job)::Bool = awaiting_kind(job) == "continue_prompt"

"""Poll until completed | failed | cancelled | awaiting_approval.

300s is the lab-note default, NOT a server limit (wall clock 30 minutes).
While pending/in_progress, poll `?compact=true`. Then one full GET.
Never auto-approves HITL. Never polls inside approve().
"""
function wait(client::Client, job::Job;
              timeout::Real=300,
              interval::Real=client.poll_interval_s,
              on_continue::Symbol=:return,
              on_progress=nothing)::Job
    t0 = time()
    last_info = t0
    current = job
    while true
        elapsed = time() - t0
        elapsed > timeout && throw(TimeoutError(
            "wait timed out after $(timeout)s (lab default; pass a larger timeout for deep/max)",
            current.job_id))
        st = current.status
        compact = st in ("pending", "in_progress")
        current = get_job(client, current.job_id; compact=compact)
        if compact && current.status in ("completed", "failed", "cancelled", "awaiting_approval")
            current = get_job(client, current.job_id; compact=false)
        end
        on_progress !== nothing && on_progress(current)
        if elapsed > 60 && (time() - last_info) >= 30
            @info "still processing" job_id=current.job_id status=current.status elapsed_s=round(Int, elapsed)
            last_info = time()
        end
        st = current.status
        if st == "completed"
            return current
        elseif st == "failed"
            throw(JobFailed(something(current.error, "job failed"), current.job_id))
        elseif st == "cancelled"
            throw(JobFailed("cancelled", current.job_id))
        elseif st == "awaiting_approval"
            if is_continue_prompt(current)
                if on_continue === :return
                    return current
                elseif on_continue === :resume
                    current = continue_job(client, current.session_id, current.job_id; resume=true)
                    continue
                elseif on_continue === :stop
                    current = continue_job(client, current.session_id, current.job_id; resume=false)
                    continue
                else
                    throw(ArgumentError("on_continue must be :return, :resume, or :stop"))
                end
            else
                return current
            end
        end
        sleep(interval)
    end
end

function cancel_job(client::Client, job_id::AbstractString)::Job
    url = rstrip(client.base_url, '/') * "/v1/jobs/" * String(job_id) * "/cancel"
    headers = auth_headers(client; content_type="application/json")
    raw = request_checked(client, "POST", url, headers, json_body(Dict{String,Any}());
                          readtimeout=client.timeout_poll_s)
    stop_state = nothing
    try
        obj = decode_json(raw)
        stop_state = jstr(obj, :stop_state)
    catch
        stop_state = nothing
    end
    if stop_state == "accepted"
        t0 = time()
        while time() - t0 < 60
            job = get_job(client, job_id)
            st = job.status
            unwound = job.metadata !== nothing && job.metadata.stopped_unwound === true
            if st in ("cancelled", "completed", "failed") || unwound
                return job
            end
            sleep(client.poll_interval_s)
        end
        return get_job(client, job_id)
    end
    return get_job(client, job_id)
end
