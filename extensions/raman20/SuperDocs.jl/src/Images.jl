const IMAGE_EXT_MIME = Dict(
    ".png" => "image/png",
    ".jpg" => "image/jpeg",
    ".jpeg" => "image/jpeg",
    ".webp" => "image/webp",
    ".gif" => "image/gif",
    ".svg" => "image/svg+xml",
)
const MAX_IMAGE_BYTES = 10 * 1024 * 1024

function _image_mime(filename::AbstractString)
    ext = lowercase(splitext(filename)[2])
    mime = get(IMAGE_EXT_MIME, ext, nothing)
    mime === nothing && throw(ArgumentError("unsupported image suffix $ext; expected png/jpg/jpeg/webp/gif/svg"))
    return mime
end

function upload_image(client::Client, path::AbstractString; filename=nothing)::ImageRef
    name = filename === nothing ? basename(path) : String(filename)
    mime = _image_mime(name)
    bytes = read(path)
    length(bytes) > MAX_IMAGE_BYTES && throw(ArgumentError("image exceeds 10 MB"))
    url = rstrip(client.base_url, '/') * "/v1/documents/images/upload"
    form = HTTP.Form(Dict(
        "file" => HTTP.Multipart(name, IOBuffer(bytes), mime),
    ))
    headers = auth_headers(client; accept="*/*", content_type=nothing)
    raw = request_checked(client, "POST", url, headers, form;
                          readtimeout=client.timeout_io_s)
    return decode_image_ref(decode_json(raw))
end

"""Base64 image upload. Embed rule: returned `url` (stable); never `view_url`."""
function upload_image_bytes(client::Client, data::Vector{UInt8};
                            filename::AbstractString,
                            content_type::AbstractString="image/png")::ImageRef
    length(data) > MAX_IMAGE_BYTES && throw(ArgumentError("image exceeds 10 MB"))
    content_type in IMAGE_MIME || throw(ArgumentError("content_type must be one of $IMAGE_MIME"))
    url = rstrip(client.base_url, '/') * "/v1/documents/images/upload-base64"
    payload = Dict{String,Any}(
        "filename" => String(filename),
        "image_base64" => Base64.base64encode(data),
        "content_type" => String(content_type),
    )
    headers = auth_headers(client; content_type="application/json")
    raw = request_checked(client, "POST", url, headers, json_body(payload);
                          readtimeout=client.timeout_io_s)
    return decode_image_ref(decode_json(raw))
end

"""Insert `<img src>` after a heading. SuperDocs chat will not fetch GCS URLs; HTML injection is the write path."""
function place_image(html::AbstractString, image_url::AbstractString;
                     after::AbstractString="Methods", alt::AbstractString="figure")::String
    src = replace(String(image_url), "&" => "&amp;", "\"" => "&quot;")
    img = "<p><img src=\"$(src)\" alt=\"$(alt)\"/></p>"
    r = Regex("(?is)(<h[1-6][^>]*>\\s*" * replace(after, r"([\\^\$\.\|\?\*\+\(\)\[\]\{\}])" => s"\\\1") * "\\s*</h[1-6]>)")
    m = match(r, String(html))
    m === nothing && return String(html) * img
    loc = m.offset + ncodeunits(m.match)
    h = String(html)
    return h[1:prevind(h, loc)] * img * h[loc:end]
end
