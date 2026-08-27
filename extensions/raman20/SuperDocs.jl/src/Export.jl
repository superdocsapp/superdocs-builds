function parse_export_warnings(headers)::Vector{ExportWarning}
    h = headers isa Dict ? headers : _lower_headers(headers)
    raw = get(h, "x-export-warnings", nothing)
    raw === nothing && return ExportWarning[]
    txt = String(raw)
    isempty(strip(txt)) && return ExportWarning[]
    decoded = try
        String(Base64.base64decode(txt))
    catch e
        throw(APIError(200, "X-Export-Warnings is not valid base64: $e", "bad_export_warnings", nothing))
    end
    obj = try
        JSON3.read(decoded)
    catch e
        throw(APIError(200, "X-Export-Warnings is not JSON: $e", "bad_export_warnings", nothing))
    end
    obj isa AbstractVector || throw(APIError(200, "X-Export-Warnings JSON is not a list", "bad_export_warnings", nothing))
    return [decode_export_warning(item) for item in obj]
end

function _filename_from_disposition(disp::Union{Nothing,AbstractString})
    disp === nothing && return nothing
    m = match(r"filename\*?=(?:UTF-8''|\"?)([^\";]+)", String(disp))
    m === nothing && return nothing
    return String(m.captures[1])
end

function export_document(client::Client;
                         session_id=nothing,
                         html=nothing,
                         upload_id=nothing,
                         format::Symbol=:docx,
                         options::ExportOptions=ExportOptions(),
                         dest::Union{Nothing,AbstractString}=nothing)
    fmt = validate_enum("format", format, EXPORT_FORMATS)
    if session_id === nothing && html === nothing && upload_id === nothing
        throw(ArgumentError("export_document requires one of session_id, html, upload_id"))
    end
    payload = compact_payload(Dict{String,Any}(
        "session_id" => session_id === nothing ? nothing : validate_session_id(session_id),
        "html" => html,
        "upload_id" => upload_id,
        "format" => fmt,
    ))
    opts = compact_payload(Dict{String,Any}(
        "paper_size" => options.paper_size,
        "orientation" => options.orientation,
        "margins" => options.margins,
        "filename" => options.filename,
        "watermark_text" => options.watermark_text,
        "watermark_opacity" => options.watermark_opacity,
        "fidelity" => options.fidelity,
        "embed_images" => options.embed_images,
    ))
    !isempty(opts) && (payload["options"] = opts)
    url = rstrip(client.base_url, '/') * "/v1/documents/export"
    headers = auth_headers(client; accept="*/*", content_type="application/json")
    raw = request_checked(client, "POST", url, headers, json_body(payload);
                          readtimeout=client.timeout_io_s)
    warnings = parse_export_warnings(raw.headers)
    filename = _filename_from_disposition(get(raw.headers, "content-disposition", nothing))
    content_type = get(raw.headers, "content-type", nothing)
    result = ExportResult(raw.body, warnings, content_type, filename)
    if dest !== nothing
        open(dest, "w") do io
            write(io, result.bytes)
        end
    end
    return result
end
