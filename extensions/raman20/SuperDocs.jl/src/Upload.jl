function _mime_for_document(name::AbstractString)
    ext = lowercase(splitext(name)[2])
    ext == ".md" && return "text/markdown"
    ext == ".html" && return "text/html"
    ext == ".htm" && return "text/html"
    ext == ".txt" && return "text/plain"
    ext == ".pdf" && return "application/pdf"
    ext == ".docx" && return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ext == ".rtf" && return "application/rtf"
    ext == ".tex" && return "application/x-tex"
    return "application/octet-stream"
end

"""POST /v1/documents/upload multipart. Uploads are not billable.

Always request HTML so `verify_math` has a baseline (`UploadResult.html`).
When `native_math=true` (default) and the parsed HTML still has dollar-delimited source,
the SDK converts those to native `data-latex` nodes and re-uploads as HTML so the
web editor KaTeX-renders. `.tex` uploads already arrive as native nodes (no second call).
"""
function upload(client::Client, path::AbstractString;
                session_id::AbstractString,
                open_mode::AbstractString="replace",
                index::Bool=false,
                native_math::Bool=true)::UploadResult
    bytes = read(path)
    return upload(client, IOBuffer(bytes), basename(path); session_id, open_mode, index, native_math)
end

function upload(client::Client, io::IO, filename::AbstractString;
                session_id::AbstractString,
                open_mode::AbstractString="replace",
                index::Bool=false,
                native_math::Bool=true)::UploadResult
    session_id = validate_session_id(session_id)
    validate_enum("open_mode", open_mode, OPEN_MODES)
    url = rstrip(client.base_url, '/') * "/v1/documents/upload"
    index && (url *= "?index=true")
    form = HTTP.Form(Dict(
        "file" => HTTP.Multipart(filename, io, _mime_for_document(filename)),
        "session_id" => session_id,
        "open_mode" => open_mode,
    ))
    headers = auth_headers(client; accept="*/*", content_type=nothing)
    raw = request_checked(client, "POST", url, headers, form;
                          readtimeout=client.timeout_io_s)
    result = decode_upload(decode_json(raw))
    native_math || return result
    html = result.html
    html === nothing && return result
    has_dollar_math(html) || return result
    converted = to_native_math(html)
    converted == html && return result
    html_name = splitext(filename)[1] * ".html"
    return upload(client, IOBuffer(converted), html_name;
                  session_id, open_mode, index, native_math=false)
end

"""GET /v1/sessions/{id}/history → document_state.html_content. Not billable."""
function session_html(client::Client, session_id::AbstractString)::String
    session_id = validate_session_id(session_id)
    url = rstrip(client.base_url, '/') * "/v1/sessions/" * session_id * "/history"
    headers = auth_headers(client)
    raw = request_checked(client, "GET", url, headers, UInt8[];
                          readtimeout=client.timeout_poll_s)
    hist = decode_history(decode_json(raw))
    ds = hist.document_state
    if ds === nothing || ds.html_content === nothing
        throw(APIError(200, "session history missing document_state.html_content",
                       "missing_html_content", "retry after the document is loaded"))
    end
    return ds.html_content
end

"""Null-safe HTML after a job. Does not throw if result or document_changes is nothing."""
function html_after_job(client::Client, job::Job, session_id::AbstractString)::String
    r = job.result
    if r !== nothing
        dc = r.document_changes
        if dc !== nothing && dc.updated_html !== nothing
            return dc.updated_html
        end
    end
    return session_html(client, session_id)
end
