import html
import re

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_EM_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_CODE_RE = re.compile(r"`([^`\n]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_LI_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_HR_RE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_QUOTE_RE = re.compile(r"^>\s?(.*)$")


def _inline(text: str) -> str:
    text = html.escape(text, quote=False)

    def link(m: re.Match) -> str:
        return f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>'

    text = _LINK_RE.sub(link, text)
    text = _CODE_RE.sub(r"<code>\1</code>", text)
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _EM_RE.sub(r"<em>\1</em>", text)
    return text


def _is_table_sep(line: str) -> bool:
    if not line.strip().startswith("|"):
        return False
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells)


def _parse_table(rows: list[str]) -> str:
    header = [c.strip() for c in rows[0].strip().strip("|").split("|")]
    body = []
    for row in rows[2:]:
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        body.append(cells)
    out = ["<table><thead><tr>"]
    for cell in header:
        out.append(f"<th>{_inline(cell)}</th>")
    out.append("</tr></thead><tbody>")
    for cells in body:
        out.append("<tr>")
        for cell in cells:
            out.append(f"<td>{_inline(cell)}</td>")
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def _parse_list(lines: list[str], start_idx: int) -> tuple[str, int]:
    stack = []  # (indent, tag)
    out = []
    i = start_idx
    while i < len(lines):
        m = _LI_RE.match(lines[i])
        if not m:
            break
        indent = len(m.group(1).replace("\t", "  "))
        ordered = m.group(2)[0].isdigit()
        tag = "ol" if ordered else "ul"
        while stack and indent <= stack[-1][0]:
            t, _ = stack.pop()
            out.append(f"</{t}>")
        if not stack or (indent == stack[-1][0] and tag != stack[-1][1]):
            if not stack:
                stack.append((indent, tag))
            else:
                t, _ = stack.pop()
                out.append(f"</{t}>")
                stack.append((indent, tag))
            out.append(f"<{tag}>")
        elif indent > stack[-1][0]:
            stack.append((indent, tag))
            out.append(f"<{tag}>")
        out.append(f"<li>{_inline(m.group(3))}</li>")
        i += 1
    while stack:
        t, _ = stack.pop()
        out.append(f"</{t}>")
    return "".join(out), i


def md_to_html(text: str) -> str:
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("```"):
            fence = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                fence.append(lines[i])
                i += 1
            i += 1
            out.append("<pre>" + html.escape("\n".join(fence), quote=False) + "</pre>")
            continue
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue
        if _HR_RE.match(line):
            out.append("<hr>")
            i += 1
            continue
        if _QUOTE_RE.match(line):
            quote = []
            while i < len(lines) and _QUOTE_RE.match(lines[i]):
                quote.append(_QUOTE_RE.match(lines[i]).group(1))
                i += 1
            out.append("<blockquote>" + "<br>".join(_inline(q) for q in quote) + "</blockquote>")
            continue
        if line.strip().startswith("|") and i + 1 < len(lines) and _is_table_sep(lines[i + 1]):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_parse_table(rows))
            continue
        if _LI_RE.match(line):
            block, i = _parse_list(lines, i)
            out.append(block)
            continue
        para = [line]
        i += 1
        while i < len(lines) and lines[i].strip():
            para.append(lines[i])
            i += 1
        out.append("<p>" + _inline(" ".join(p.strip() for p in para)) + "</p>")
    return "".join(out)
