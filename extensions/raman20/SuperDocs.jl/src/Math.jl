# Markdown `$` / `$$` is what chat and `.md` files use. SuperDocs' markdown
# upload leaves those dollars as visible text (often with `<br/>` inside).
# The editor KaTeX-renders only native nodes captured from a live .tex upload
# (2026-08-25):
#   <span data-latex="E=mc^2" data-type="inline-math">E=mc^2</span>
#   <span data-latex="\\omega_0=\\sqrt{k/m}" data-type="block-math">...</span>

const _NATIVE_MATH_RE = r"<span\b[^>]*data-type=\"(?:inline-math|block-math)\"[^>]*>.*?</span>"s
const _CODE_RE = r"<code\b[^>]*>.*?</code>"si
const _PRE_RE = r"<pre\b[^>]*>.*?</pre>"si
const _DISPLAY_DOLLAR_RE = r"\$\$(.+?)\$\$"s
const _INLINE_DOLLAR_RE = r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)"s
const _DISPLAY_BRACKET_RE = r"\\\[(.+?)\\\]"s
const _INLINE_PAREN_RE = r"\\\((.+?)\\\)"s

function html_unescape(s::AbstractString)::String
    t = replace(String(s), "&nbsp;" => " ")
    t = replace(t, "&quot;" => "\"")
    t = replace(t, "&#39;" => "'")
    t = replace(t, "&apos;" => "'")
    t = replace(t, "&lt;" => "<")
    t = replace(t, "&gt;" => ">")
    t = replace(t, "&amp;" => "&")
    return t
end

function html_escape(s::AbstractString; attr::Bool=false)::String
    t = replace(String(s), "&" => "&amp;")
    t = replace(t, "<" => "&lt;")
    t = replace(t, ">" => "&gt;")
    attr && (t = replace(t, "\"" => "&quot;"))
    return t
end

"""Wrap `expr` as SuperDocs inline math for markdown. Does not emit Unicode. Does not re-wrap if already delimited."""
function latex_inline(expr::AbstractString)::String
    s = strip(String(expr))
    startswith(s, "\$") && return s
    return "\$" * s * "\$"
end

"""Wrap `expr` as SuperDocs display math for markdown. Single line — newlines inside `\$\$` become `<br/>` on markdown upload and KaTeX will not match."""
function latex_block(expr::AbstractString)::String
    s = strip(String(expr))
    startswith(s, "\$\$") && return s
    return "\$\$" * s * "\$\$"
end

function _math_span(tex::AbstractString, display::Bool)::String
    attr = html_escape(tex; attr=true)
    inner = html_escape(tex)
    kind = display ? "block-math" : "inline-math"
    return "<span data-latex=\"$(attr)\" data-type=\"$(kind)\">$(inner)</span>"
end

"""Native SuperDocs inline equation node. This is what the web editor KaTeX-renders."""
function latex_inline_html(expr::AbstractString)::String
    tex = normalize_latex(expr)
    isempty(tex) && return ""
    return _math_span(tex, false)
end

"""Native SuperDocs display equation node. This is what the web editor KaTeX-renders."""
function latex_block_html(expr::AbstractString)::String
    tex = normalize_latex(expr)
    isempty(tex) && return ""
    return _math_span(tex, true)
end

function normalize_latex(s::AbstractString)::String
    t = strip(String(s))
    t = replace(t, r"<br\s*/?>"i => " ")
    t = replace(t, r"<[^>]+>" => "")
    t = html_unescape(t)
    t = strip(t)
    if startswith(t, "\$\$") && endswith(t, "\$\$") && length(t) >= 4
        t = strip(t[3:end-2])
    elseif startswith(t, "\$") && endswith(t, "\$") && length(t) >= 2
        t = strip(t[2:end-1])
    elseif startswith(t, "\\[") && endswith(t, "\\]") && length(t) >= 4
        t = strip(t[3:end-2])
    elseif startswith(t, "\\(") && endswith(t, "\\)") && length(t) >= 4
        t = strip(t[3:end-2])
    end
    return replace(t, r"\s+" => " ")
end

function _clean_tex(s::AbstractString)::String
    t = replace(String(s), r"<br\s*/?>"i => " ")
    t = replace(t, r"</?(?:em|strong|i|b)[^>]*>"i => "")
    t = replace(t, r"<[^>]+>" => "")
    t = html_unescape(t)
    return replace(strip(t), r"\s+" => " ")
end

function _strip_ends(s::AbstractString, left::Int, right::Int)::String
    i = firstindex(s)
    j = lastindex(s)
    for _ in 1:left
        i = nextind(s, i)
    end
    for _ in 1:right
        j = prevind(s, j)
    end
    i > j && return ""
    return s[i:j]
end

function _protect(html::AbstractString, patterns)::Tuple{String,Vector{String}}
    held = String[]
    out = String(html)
    for re in patterns
        out = replace(out, re => m -> (push!(held, String(m)); "§SDHOLD$(length(held))§"))
    end
    return out, held
end

function _restore(html::AbstractString, held::Vector{String})::String
    out = String(html)
    for i in length(held):-1:1
        out = replace(out, "§SDHOLD$(i)§" => held[i])
    end
    return out
end

function has_native_math(html::AbstractString)::Bool
    return occursin("data-type=\"block-math\"", html) || occursin("data-type=\"inline-math\"", html)
end

"""True when dollar delimiters or `\\(` / `\\[` remain as visible source outside code and native math nodes."""
function has_dollar_math(html::AbstractString)::Bool
    tmp, _ = _protect(html, [_NATIVE_MATH_RE, _CODE_RE, _PRE_RE])
    return occursin(r"\$", tmp) || occursin(r"\\\[", tmp) || occursin(r"\\\(", tmp)
end

function _rewrite_delim(html::AbstractString, re, left::Int, right::Int, display::Bool)::String
    return replace(html, re => m -> begin
        tex = _clean_tex(_strip_ends(m, left, right))
        isempty(tex) ? String(m) : _math_span(tex, display)
    end)
end

"""Turn SuperDocs-uploaded `\$\$...\$\$` / `\$...\$` HTML into native math nodes.

Leaves `<code>` / `<pre>` and existing `data-type=\"*-math\"` spans alone.
Idempotent.
"""
function to_native_math(html::AbstractString)::String
    s = String(html)
    has_dollar_math(s) || return s
    tmp, held = _protect(s, [_NATIVE_MATH_RE, _CODE_RE, _PRE_RE])
    tmp = _rewrite_delim(tmp, _DISPLAY_DOLLAR_RE, 2, 2, true)
    tmp = _rewrite_delim(tmp, _DISPLAY_BRACKET_RE, 2, 2, true)
    tmp = _rewrite_delim(tmp, _INLINE_DOLLAR_RE, 1, 1, false)
    tmp = _rewrite_delim(tmp, _INLINE_PAREN_RE, 2, 2, false)
    return _restore(tmp, held)
end

"""Extract LaTeX sources. Order: MathML annotation, data-latex, \$\$...\$\$, \$...\$ , \\[ \\], \\( \\)."""
function extract_latex(html_or_md::AbstractString)::Vector{String}
    s, _ = _protect(String(html_or_md), [_CODE_RE, _PRE_RE])
    found = String[]
    seen = Set{String}()
    function add(raw)
        n = normalize_latex(raw)
        isempty(n) && return
        if n ∉ seen
            push!(seen, n)
            push!(found, n)
        end
    end
    for m in eachmatch(r"<annotation\b[^>]*encoding\s*=\s*[\"']application/x-tex[\"'][^>]*>(.*?)</annotation>"s, s)
        add(m.captures[1])
    end
    for m in eachmatch(r"data-latex\s*=\s*\"([^\"]*)\"", s)
        add(m.captures[1])
    end
    for m in eachmatch(r"data-latex\s*=\s*'([^']*)'", s)
        add(m.captures[1])
    end
    for m in eachmatch(_DISPLAY_DOLLAR_RE, s)
        add(m.captures[1])
    end
    masked = replace(s, _DISPLAY_DOLLAR_RE => " ")
    for m in eachmatch(_INLINE_DOLLAR_RE, masked)
        add(m.captures[1])
    end
    for m in eachmatch(_DISPLAY_BRACKET_RE, s)
        add(m.captures[1])
    end
    for m in eachmatch(_INLINE_PAREN_RE, s)
        add(m.captures[1])
    end
    return found
end

"""Compare normalized LaTeX sources. `ok` iff `missing` is empty. Does not algebraically rewrite."""
function verify_math(html_or_md::AbstractString, expected::Vector{<:AbstractString};
                     throw_on_fail::Bool=false)::MathReport
    found = extract_latex(html_or_md)
    exp_n = String[]
    seen = Set{String}()
    for e in expected
        n = normalize_latex(e)
        if !isempty(n) && n ∉ seen
            push!(seen, n)
            push!(exp_n, n)
        end
    end
    found_set = Set(found)
    exp_set = Set(exp_n)
    missing = [e for e in exp_n if e ∉ found_set]
    extra = [f for f in found if f ∉ exp_set]
    report = MathReport(exp_n, found, missing, extra, isempty(missing))
    if !report.ok && throw_on_fail
        throw(MathVerifyError(report))
    end
    return report
end
