# SuperDocs.jl types + JSON decoders.
# Extra keys ignored. Missing optionals become `nothing` or empty vectors.
# No Dict/Any/JSON3.Object on the public boundary.

const MODEL_TIERS     = ("core", "turbo", "pro", "max")
const THINKING_DEPTHS = ("fast", "balanced", "deep")
const APPROVAL_MODES  = ("approve_all", "ask_every_time")
const RESPONSE_MODES  = ("full", "compact")
const EXPORT_FORMATS  = ("docx", "pdf", "html", "markdown", "txt", "doc")
const OPEN_MODES      = ("replace", "new_focused", "background")
const IMAGE_MIME      = ("image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml")
const SESSION_ID_RE   = r"^[A-Za-z0-9_.-]{1,256}$"

# --- errors ---

abstract type SuperDocsError <: Exception end

struct AuthError <: SuperDocsError
    message::String
end
struct TimeoutError <: SuperDocsError
    message::String
    job_id::Union{Nothing,String}
end
struct RateLimited <: SuperDocsError
    detail::String
    retry_after::Union{Nothing,Int}
    monthly_limit::Union{Nothing,Int}
    monthly_used::Union{Nothing,Int}
    monthly_remaining::Union{Nothing,Int}
end
struct APIError <: SuperDocsError
    status::Int
    detail::String
    error_code::Union{Nothing,String}
    suggested_action::Union{Nothing,String}
end
struct JobFailed <: SuperDocsError
    message::String
    job_id::String
end

Base.showerror(io::IO, e::AuthError) = print(io, "AuthError: ", e.message)
Base.showerror(io::IO, e::TimeoutError) = print(io, "TimeoutError: ", e.message)
Base.showerror(io::IO, e::RateLimited) = print(io, "RateLimited: ", e.detail)
function Base.showerror(io::IO, e::APIError)
    print(io, "APIError($(e.status)): ", e.detail)
    e.error_code !== nothing && print(io, " [", e.error_code, "]")
    e.suggested_action !== nothing && print(io, " suggested=", e.suggested_action)
end
Base.showerror(io::IO, e::JobFailed) = print(io, "JobFailed($(e.job_id)): ", e.message)

# --- usage ---

Base.@kwdef struct UsageInfo
    monthly_used::Union{Nothing,Int} = nothing
    monthly_limit::Union{Nothing,Int} = nothing
    monthly_remaining::Union{Nothing,Int} = nothing
    was_billable::Union{Nothing,Bool} = nothing
    ops_charged::Union{Nothing,Int} = nothing
    quota_exhausted::Union{Nothing,Bool} = nothing
    subscription_tier::Union{Nothing,String} = nothing
    bucket_used::Union{Nothing,String} = nothing
end

# --- HITL ---

Base.@kwdef struct PendingChange
    change_id::String
    operation::String
    chunk_id::Union{Nothing,String} = nothing
    document_id::Union{Nothing,String} = nothing
    old_html::Union{Nothing,String} = nothing
    new_html::Union{Nothing,String} = nothing
    ai_explanation::Union{Nothing,String} = nothing
    insert_after_chunk_id::Union{Nothing,String} = nothing
    batch_id::Union{Nothing,String} = nothing
    batch_total::Union{Nothing,Int} = nothing
end

Base.@kwdef struct ChangeDecision
    change_id::String
    approved::Union{Nothing,Bool} = nothing
    feedback::Union{Nothing,String} = nothing
end

struct BatchDecision
    change_id::String
    approved::Bool
    feedback::Union{Nothing,String}
end

Base.@kwdef struct DocumentChanges
    updated_html::Union{Nothing,String} = nothing
    version_id::Union{Nothing,String} = nothing
    changes_summary::Union{Nothing,String} = nothing
    requires_approval::Union{Nothing,Bool} = nothing
    pending_changes::Vector{PendingChange} = PendingChange[]
    chunk_diffs::Vector{PendingChange} = PendingChange[]
end

Base.@kwdef struct ChatResponse
    response::String
    session_id::String
    document_changes::Union{Nothing,DocumentChanges} = nothing
    usage::Union{Nothing,UsageInfo} = nothing
end

Base.@kwdef struct ContinuePrompt
    message::String = ""
    done::Union{Nothing,Int} = nothing
    total::Union{Nothing,Int} = nothing
    remaining::Union{Nothing,Int} = nothing
end

struct ProposedChangeBatch
    type::Union{Nothing,String}
    batch_id::Union{Nothing,String}
    batch_total::Union{Nothing,Int}
    changes::Vector{PendingChange}
end

const EventContent = Union{String,ProposedChangeBatch,ContinuePrompt}

Base.@kwdef struct IntermediateEvent
    type::Union{Nothing,String} = nothing
    content::Union{Nothing,EventContent} = nothing
    sequence::Union{Nothing,Int} = nothing
    timestamp::Union{Nothing,String} = nothing
end

Base.@kwdef struct JobMetadata
    pending_changes::Vector{PendingChange} = PendingChange[]
    awaiting_kind::Union{Nothing,String} = nothing
    continue_prompt::Union{Nothing,ContinuePrompt} = nothing
    pending_batch_decisions::Vector{BatchDecision} = BatchDecision[]
    intermediate_responses::Vector{IntermediateEvent} = IntermediateEvent[]
    message::Union{Nothing,String} = nothing
    document_html_provided::Union{Nothing,Bool} = nothing
    stopped_unwound::Union{Nothing,Bool} = nothing
end

Base.@kwdef struct JobResult
    response::Union{Nothing,String} = nothing
    session_id::Union{Nothing,String} = nothing
    document_changes::Union{Nothing,DocumentChanges} = nothing
    usage::Union{Nothing,UsageInfo} = nothing
end

Base.@kwdef struct Job
    job_id::String
    session_id::String
    job_type::String = "chat"
    status::String
    created_at::String = ""
    updated_at::String = ""
    progress::Int = 0
    result::Union{Nothing,JobResult} = nothing
    error::Union{Nothing,String} = nothing
    metadata::Union{Nothing,JobMetadata} = nothing
end

Base.@kwdef struct MarginsIn
    top::Union{Nothing,Float64} = nothing
    right::Union{Nothing,Float64} = nothing
    bottom::Union{Nothing,Float64} = nothing
    left::Union{Nothing,Float64} = nothing
end

Base.@kwdef struct PageSetup
    width_in::Union{Nothing,Float64} = nothing
    height_in::Union{Nothing,Float64} = nothing
    margin_in::Union{Nothing,MarginsIn} = nothing
    orientation::Union{Nothing,String} = nothing
    source::Union{Nothing,String} = nothing
end

Base.@kwdef struct UploadResult
    html::Union{Nothing,String} = nothing
    session_id::Union{Nothing,String} = nothing
    filename::Union{Nothing,String} = nothing
    chunks_count::Union{Nothing,Int} = nothing
    version_id::Union{Nothing,String} = nothing
    page_setup::Union{Nothing,PageSetup} = nothing
end

Base.@kwdef struct HistoryDocumentState
    html_content::Union{Nothing,String} = nothing
end
Base.@kwdef struct HistoryResponse
    session_id::String = ""
    document_state::Union{Nothing,HistoryDocumentState} = nothing
end

struct ImageRef
    url::String
    canonical_url::Union{Nothing,String}
    view_url::Union{Nothing,String}
    filename::Union{Nothing,String}
    content_type::Union{Nothing,String}
    size::Union{Nothing,Int}
end

embed_url(img::ImageRef) = img.url  # canonical (multipart) or stable url (base64)

struct ExportWarning
    code::String
    message::Union{Nothing,String}
    detail::Union{Nothing,String}
end

struct ExportResult
    bytes::Vector{UInt8}
    warnings::Vector{ExportWarning}
    content_type::Union{Nothing,String}
    filename::Union{Nothing,String}
end

function Base.iterate(r::ExportResult, state::Int=1)
    state == 1 && return (r.bytes, 2)
    state == 2 && return (r.warnings, 3)
    return nothing
end
Base.length(::ExportResult) = 2
Base.eltype(::Type{ExportResult}) = Any

struct MathReport
    expected::Vector{String}
    found::Vector{String}
    missing::Vector{String}
    extra::Vector{String}
    ok::Bool
end

struct MathVerifyError <: SuperDocsError
    report::MathReport
end
Base.showerror(io::IO, e::MathVerifyError) = print(io, "MathVerifyError: missing=", e.report.missing)

struct ImageAttachment
    id::String
    name::String
    base64Data::String
    mimeType::String
    size::Int
end

Base.@kwdef struct ExportOptions
    paper_size::Union{Nothing,String} = nothing
    orientation::Union{Nothing,String} = nothing
    margins::Union{Nothing,String} = nothing
    filename::Union{Nothing,String} = nothing
    watermark_text::Union{Nothing,String} = nothing
    watermark_opacity::Union{Nothing,Float64} = nothing
    fidelity::Union{Nothing,String} = nothing
    embed_images::Union{Nothing,Bool} = nothing
end

# --- JSON helpers ---

_nothingish(v) = v === nothing || v === missing

function maybe_json(x)
    x isa AbstractString || return x
    s = strip(String(x))
    isempty(s) && return x
    (startswith(s, '{') || startswith(s, '[')) || return x
    try
        return JSON3.read(s)
    catch
        return x
    end
end

function jget(obj, key)
    obj === nothing && return nothing
    if obj isa AbstractDict
        return get(obj, key, get(obj, Symbol(key), nothing))
    end
    return get(obj, Symbol(key), nothing)
end

function jstr(obj, key; default::Union{Nothing,String}=nothing)
    v = jget(obj, key)
    _nothingish(v) && return default
    return String(v)
end

function jint(obj, key; default::Union{Nothing,Int}=nothing)
    v = jget(obj, key)
    _nothingish(v) && return default
    return Int(v)
end

function jbool(obj, key; default::Union{Nothing,Bool}=nothing)
    v = jget(obj, key)
    _nothingish(v) && return default
    return Bool(v)
end

function jfloat(obj, key; default::Union{Nothing,Float64}=nothing)
    v = jget(obj, key)
    _nothingish(v) && return default
    return Float64(v)
end

function decode_usage(obj)::Union{Nothing,UsageInfo}
    obj === nothing && return nothing
    return UsageInfo(
        monthly_used = jint(obj, :monthly_used),
        monthly_limit = jint(obj, :monthly_limit),
        monthly_remaining = jint(obj, :monthly_remaining),
        was_billable = jbool(obj, :was_billable),
        ops_charged = jint(obj, :ops_charged),
        quota_exhausted = jbool(obj, :quota_exhausted),
        subscription_tier = jstr(obj, :subscription_tier),
        bucket_used = jstr(obj, :bucket_used),
    )
end

function decode_pending_change(obj)::PendingChange
    cid = jstr(obj, :change_id)
    cid === nothing && (cid = jstr(obj, :id; default=""))
    op = jstr(obj, :operation; default="edit")
    return PendingChange(
        change_id = cid,
        operation = op,
        chunk_id = jstr(obj, :chunk_id),
        document_id = jstr(obj, :document_id),
        old_html = jstr(obj, :old_html),
        new_html = jstr(obj, :new_html),
        ai_explanation = jstr(obj, :ai_explanation),
        insert_after_chunk_id = jstr(obj, :insert_after_chunk_id),
        batch_id = jstr(obj, :batch_id),
        batch_total = jint(obj, :batch_total),
    )
end

function decode_pending_list(v)::Vector{PendingChange}
    (v === nothing || v === missing) && return PendingChange[]
    v = maybe_json(v)
    out = PendingChange[]
    if v isa AbstractVector
        for item in v
            push!(out, decode_pending_change(item))
        end
    end
    return out
end

function decode_document_changes(obj)::Union{Nothing,DocumentChanges}
    obj === nothing && return nothing
    return DocumentChanges(
        updated_html = jstr(obj, :updated_html),
        version_id = jstr(obj, :version_id),
        changes_summary = jstr(obj, :changes_summary),
        requires_approval = jbool(obj, :requires_approval),
        pending_changes = decode_pending_list(jget(obj, :pending_changes)),
        chunk_diffs = decode_pending_list(jget(obj, :chunk_diffs)),
    )
end

function decode_continue_prompt(obj)::Union{Nothing,ContinuePrompt}
    obj === nothing && return nothing
    obj = maybe_json(obj)
    if obj isa AbstractString
        return ContinuePrompt(message = String(obj))
    end
    return ContinuePrompt(
        message = something(jstr(obj, :message; default=""), ""),
        done = jint(obj, :done),
        total = jint(obj, :total),
        remaining = jint(obj, :remaining),
    )
end

function decode_proposed_batch(obj)::ProposedChangeBatch
    obj = maybe_json(obj)
    return ProposedChangeBatch(
        jstr(obj, :type),
        jstr(obj, :batch_id),
        jint(obj, :batch_total),
        decode_pending_list(jget(obj, :changes)),
    )
end

function decode_event_content(type_str, raw)::Union{Nothing,EventContent}
    raw === nothing && return nothing
    parsed = maybe_json(raw)
    t = type_str === nothing ? "" : String(type_str)
    if parsed isa JSON3.Object || parsed isa AbstractDict
        if t == "proposed_change_batch" || jget(parsed, :changes) !== nothing
            return decode_proposed_batch(parsed)
        end
        if t == "continue_prompt" || jget(parsed, :done) !== nothing || jget(parsed, :remaining) !== nothing
            return decode_continue_prompt(parsed)
        end
        return JSON3.write(parsed)
    end
    if parsed isa AbstractString
        return String(parsed)
    end
    if t == "proposed_change_batch"
        return decode_proposed_batch(parsed)
    end
    return string(parsed)
end

function decode_intermediate(obj)::IntermediateEvent
    t = jstr(obj, :type)
    return IntermediateEvent(
        type = t,
        content = decode_event_content(t, jget(obj, :content)),
        sequence = jint(obj, :sequence),
        timestamp = jstr(obj, :timestamp),
    )
end

function decode_batch_decisions(v)::Vector{BatchDecision}
    (v === nothing || v === missing) && return BatchDecision[]
    v = maybe_json(v)
    out = BatchDecision[]
    if v isa AbstractVector
        for item in v
            push!(out, BatchDecision(
                something(jstr(item, :change_id; default=""), ""),
                something(jbool(item, :approved; default=false), false),
                jstr(item, :feedback),
            ))
        end
        return out
    end
    if v isa JSON3.Object || v isa AbstractDict
        for (k, item) in v
            cid = string(k)
            if item isa JSON3.Object || item isa AbstractDict
                push!(out, BatchDecision(
                    cid,
                    something(jbool(item, :approved; default=false), false),
                    jstr(item, :feedback),
                ))
            end
        end
    end
    return out
end

function decode_metadata(obj)::Union{Nothing,JobMetadata}
    obj === nothing && return nothing
    inter = IntermediateEvent[]
    iv = jget(obj, :intermediate_responses)
    if iv isa AbstractVector
        for item in iv
            push!(inter, decode_intermediate(item))
        end
    end
    return JobMetadata(
        pending_changes = decode_pending_list(jget(obj, :pending_changes)),
        awaiting_kind = jstr(obj, :awaiting_kind),
        continue_prompt = decode_continue_prompt(jget(obj, :continue_prompt)),
        pending_batch_decisions = decode_batch_decisions(jget(obj, :pending_batch_decisions)),
        intermediate_responses = inter,
        message = jstr(obj, :message),
        document_html_provided = jbool(obj, :document_html_provided),
        stopped_unwound = jbool(obj, :stopped_unwound),
    )
end

function decode_job_result(obj)::Union{Nothing,JobResult}
    obj === nothing && return nothing
    return JobResult(
        response = jstr(obj, :response),
        session_id = jstr(obj, :session_id),
        document_changes = decode_document_changes(jget(obj, :document_changes)),
        usage = decode_usage(jget(obj, :usage)),
    )
end

function decode_job(obj)::Job
    inner = jget(obj, :job)
    inner !== nothing && (obj = inner)
    job_id = jstr(obj, :job_id)
    job_id === nothing && (job_id = jstr(obj, :id; default=""))
    return Job(
        job_id = something(job_id, ""),
        session_id = something(jstr(obj, :session_id; default=""), ""),
        job_type = something(jstr(obj, :job_type; default="chat"), "chat"),
        status = something(jstr(obj, :status; default="pending"), "pending"),
        created_at = something(jstr(obj, :created_at; default=""), ""),
        updated_at = something(jstr(obj, :updated_at; default=""), ""),
        progress = something(jint(obj, :progress; default=0), 0),
        result = decode_job_result(jget(obj, :result)),
        error = jstr(obj, :error),
        metadata = decode_metadata(jget(obj, :metadata)),
    )
end

function decode_chat_response(obj)::ChatResponse
    return ChatResponse(
        response = something(jstr(obj, :response; default=""), ""),
        session_id = something(jstr(obj, :session_id; default=""), ""),
        document_changes = decode_document_changes(jget(obj, :document_changes)),
        usage = decode_usage(jget(obj, :usage)),
    )
end

function decode_upload(obj)::UploadResult
    ps = jget(obj, :page_setup)
    page = nothing
    if ps !== nothing
        mi = jget(ps, :margin_in)
        margins = mi === nothing ? nothing : MarginsIn(
            top = jfloat(mi, :top),
            right = jfloat(mi, :right),
            bottom = jfloat(mi, :bottom),
            left = jfloat(mi, :left),
        )
        page = PageSetup(
            width_in = jfloat(ps, :width_in),
            height_in = jfloat(ps, :height_in),
            margin_in = margins,
            orientation = jstr(ps, :orientation),
            source = jstr(ps, :source),
        )
    end
    return UploadResult(
        html = jstr(obj, :html),
        session_id = jstr(obj, :session_id),
        filename = jstr(obj, :filename),
        chunks_count = jint(obj, :chunks_count),
        version_id = jstr(obj, :version_id),
        page_setup = page,
    )
end

function decode_history(obj)::HistoryResponse
    ds = jget(obj, :document_state)
    state = ds === nothing ? nothing : HistoryDocumentState(html_content = jstr(ds, :html_content))
    return HistoryResponse(
        session_id = something(jstr(obj, :session_id; default=""), ""),
        document_state = state,
    )
end

function decode_image_ref(obj)::ImageRef
    canonical = jstr(obj, :canonical_url)
    view = jstr(obj, :view_url)
    url = jstr(obj, :url)
    url === nothing && (url = jstr(obj, :image_url))
    url === nothing && (url = jstr(obj, :src))
    embed = nothing
    stored_view = view
    if canonical !== nothing
        embed = canonical
        stored_view = view !== nothing ? view : url
    elseif url !== nothing
        embed = url
    end
    embed === nothing && throw(APIError(200, "image upload returned no embeddable URL", "missing_url", nothing))
    return ImageRef(
        embed,
        canonical,
        stored_view,
        jstr(obj, :filename),
        jstr(obj, :content_type),
        jint(obj, :size),
    )
end

function decode_export_warning(obj)::ExportWarning
    code = something(jstr(obj, :code; default="unknown"), "unknown")
    msg = jstr(obj, :message)
    d = jget(obj, :detail)
    detail = if d === nothing
        nothing
    elseif d isa AbstractString
        String(d)
    else
        JSON3.write(d)
    end
    return ExportWarning(code, msg, detail)
end

has_math_partial_fidelity(warnings::Vector{ExportWarning}) =
    any(w -> w.code == "math_partial_fidelity", warnings)

function validate_session_id(session_id::AbstractString)
    occursin(SESSION_ID_RE, session_id) ||
        throw(ArgumentError("session_id must match $SESSION_ID_RE (got $(repr(session_id)))"))
    return String(session_id)
end

function validate_enum(name::AbstractString, value, allowed)
    value === nothing && return nothing
    s = value isa Symbol ? String(value) : String(value)
    s in allowed || throw(ArgumentError("$name must be one of $allowed (got $(repr(s)))"))
    return s
end

function compact_payload(d::Dict)
    out = Dict{String,Any}()
    for (k, v) in d
        v === nothing && continue
        out[String(k)] = v
    end
    return out
end
