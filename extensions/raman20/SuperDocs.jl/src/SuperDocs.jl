module SuperDocs

using HTTP
using JSON3
using Base64

export Client, verify_key, wait, get_job, cancel_job,
       upload, session_html, html_after_job,
       chat, chat_async, approve, continue_job,
       pending_changes, awaiting_kind, is_continue_prompt,
       latex_inline, latex_block, latex_inline_html, latex_block_html,
       extract_latex, verify_math, to_native_math, has_dollar_math, has_native_math,
       upload_image, upload_image_bytes, embed_url, place_image,
       export_document, parse_export_warnings, has_math_partial_fidelity,
       ImageRef, Job, ChatResponse, PendingChange, ChangeDecision, UsageInfo,
       ExportWarning, ExportResult, ExportOptions, MathReport, UploadResult,
       SuperDocsError, AuthError, TimeoutError, RateLimited, APIError, JobFailed, MathVerifyError

include("Types.jl")
include("Client.jl")
include("Math.jl")
include("Upload.jl")
include("Chat.jl")
include("Images.jl")
include("Export.jl")

end # module
