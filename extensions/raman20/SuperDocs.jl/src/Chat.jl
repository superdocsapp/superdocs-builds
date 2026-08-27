function encode_chat(; message::AbstractString,
                     session_id::AbstractString,
                     document_html=nothing,
                     image_attachments=nothing,
                     model_tier=nothing,
                     thinking_depth=nothing,
                     approval_mode=nothing,
                     response_mode=nothing,
                     document_id=nothing)
    session_id = validate_session_id(session_id)
    msg = String(message)
    isempty(strip(msg)) && throw(ArgumentError("message must be nonempty"))
    length(msg) > 100_000 && throw(ArgumentError("message exceeds 100_000 characters"))
    html_out = document_html === nothing ? nothing : to_native_math(String(document_html))
    payload = compact_payload(Dict{String,Any}(
        "message" => msg,
        "session_id" => session_id,
        "document_html" => html_out,
        "model_tier" => validate_enum("model_tier", model_tier, MODEL_TIERS),
        "thinking_depth" => validate_enum("thinking_depth", thinking_depth, THINKING_DEPTHS),
        "approval_mode" => validate_enum("approval_mode", approval_mode, APPROVAL_MODES),
        "response_mode" => validate_enum("response_mode", response_mode, RESPONSE_MODES),
        "document_id" => document_id,
    ))
    if image_attachments !== nothing
        atts = Any[]
        for a in image_attachments
            a isa ImageAttachment || throw(ArgumentError("image_attachments must be Vector{ImageAttachment} (vision), not ImageRef"))
            push!(atts, Dict(
                "id" => a.id,
                "name" => a.name,
                "base64Data" => a.base64Data,
                "mimeType" => a.mimeType,
                "size" => a.size,
            ))
        end
        payload["image_attachments"] = atts
    end
    return payload
end

function encode_approve(; job_id::AbstractString,
                        approved::Bool,
                        change_id=nothing,
                        feedback=nothing,
                        changes=nothing)
    body = Dict{String,Any}("job_id" => String(job_id), "approved" => approved)
    change_id !== nothing && (body["change_id"] = String(change_id))
    feedback !== nothing && (body["feedback"] = String(feedback))
    if changes !== nothing
        entries = Any[]
        for c in changes
            if c isa PendingChange
                push!(entries, Dict{String,Any}("change_id" => c.change_id, "approved" => approved))
            elseif c isa ChangeDecision
                d = Dict{String,Any}("change_id" => c.change_id)
                d["approved"] = c.approved === nothing ? approved : c.approved
                c.feedback !== nothing && (d["feedback"] = c.feedback)
                push!(entries, d)
            else
                throw(ArgumentError("changes must be PendingChange or ChangeDecision"))
            end
        end
        body["changes"] = entries
    end
    return body
end

function _post_json(client::Client, path::AbstractString, payload; readtimeout::Float64, cold::Bool=false)
    url = rstrip(client.base_url, '/') * path
    headers = auth_headers(client; content_type="application/json")
    return request_checked(client, "POST", url, headers, json_body(payload);
                           readtimeout=readtimeout, cold=cold)
end

function chat_async(client::Client, message::AbstractString;
                    session_id::AbstractString,
                    document_html=nothing,
                    approval_mode::AbstractString="ask_every_time",
                    model_tier=nothing,
                    thinking_depth=nothing,
                    response_mode::AbstractString="full",
                    document_id=nothing,
                    image_attachments=nothing,
                    cold::Union{Nothing,Bool}=nothing)::Job
    payload = encode_chat(; message, session_id, document_html, image_attachments,
                          model_tier, thinking_depth, approval_mode, response_mode, document_id)
    # never send async_mode (server default true)
    cold_flag = is_cold(client, session_id, cold)
    raw = try
        _post_json(client, "/v1/chat/async", payload;
                   readtimeout=client.timeout_async_s, cold=cold_flag)
    catch e
        # Retry transport / 5xx on a cold session. Never retry a 30-minute 504.
        gateway = e isa TimeoutError && occursin("wall-clock", e.message)
        if cold_flag && !gateway && (e isa TimeoutError || (e isa APIError && e.status >= 500 && e.status != 504))
            sleep(1)
            _post_json(client, "/v1/chat/async", payload;
                       readtimeout=client.timeout_async_s, cold=false)
        else
            rethrow()
        end
    end
    mark_seen!(client, session_id)
    obj = decode_json(raw)
    job_id = something(jstr(obj, :job_id), "")
    sid = something(jstr(obj, :session_id; default=String(session_id)), String(session_id))
    status = something(jstr(obj, :status; default="pending"), "pending")
    return Job(; job_id=job_id, session_id=sid, status=status)
end

function chat(client::Client, message::AbstractString;
              session_id::AbstractString,
              approval_mode::AbstractString="approve_all",
              cold::Union{Nothing,Bool}=nothing,
              kwargs...)::ChatResponse
    if String(approval_mode) == "ask_every_time"
        throw(ArgumentError("HITL requires chat_async (sync /v1/chat cannot pause for approval)"))
    end
    payload = encode_chat(; message, session_id, approval_mode, kwargs...)
    cold_flag = is_cold(client, session_id, cold)
    raw = try
        _post_json(client, "/v1/chat", payload;
                   readtimeout=client.timeout_sync_s, cold=cold_flag)
    catch e
        gateway = e isa TimeoutError && occursin("wall-clock", e.message)
        if cold_flag && !gateway && (e isa TimeoutError || (e isa APIError && e.status >= 500 && e.status != 504))
            sleep(1)
            _post_json(client, "/v1/chat", payload;
                       readtimeout=client.timeout_sync_s, cold=false)
        else
            rethrow()
        end
    end
    mark_seen!(client, session_id)
    return decode_chat_response(decode_json(raw))
end

function approve(client::Client, session_id::AbstractString, job_id::AbstractString;
                 approved::Bool,
                 change_id=nothing,
                 feedback=nothing,
                 changes=nothing)::Job
    session_id = validate_session_id(session_id)
    body = encode_approve(; job_id, approved, change_id, feedback, changes)
    # 200 body is {} — do not parse as Job
    _post_json(client, "/v1/chat/" * session_id * "/approve", body;
               readtimeout=client.timeout_poll_s)
    return get_job(client, job_id)
end

function continue_job(client::Client, session_id::AbstractString, job_id::AbstractString;
                      resume::Bool=true)::Job
    session_id = validate_session_id(session_id)
    body = Dict{String,Any}("job_id" => String(job_id), "continue" => resume)
    _post_json(client, "/v1/chat/" * session_id * "/continue", body;
               readtimeout=client.timeout_poll_s)
    return get_job(client, job_id)
end
