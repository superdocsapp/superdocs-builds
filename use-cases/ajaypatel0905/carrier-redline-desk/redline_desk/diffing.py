"""Word-level tracked-changes markup, computed deterministically in code.

The AI proposes clause text; this module decides how the change is expressed
as <ins>/<del> markup (which SuperDocs exports as genuine Word w:ins/w:del).
Because the markup is computed, not generated, it carries a proof obligation:

    reject_all(redline(old, new))  == old   (byte-identical)
    accept_all(redline(old, new))  == new   (byte-identical)

verify_roundtrip() checks both for every change; the engine refuses to export
a redline whose proofs fail.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_OUTER = re.compile(r"^<(?P<tag>[a-zA-Z][a-zA-Z0-9]*)(?P<attrs>[^>]*)>(?P<inner>.*)</(?P=tag)>$", re.DOTALL)


def split_outer(outer_html: str) -> tuple[str, str, str]:
    m = _OUTER.match(outer_html.strip())
    if not m:
        raise ValueError(f"not a single-element block: {outer_html[:80]!r}")
    return m.group("tag"), m.group("attrs"), m.group("inner")


def _tokens(s: str) -> list[str]:
    return re.findall(r"\s+|[^\s<]+|<[^>]*>", s)


def _mark(author: str, date: str) -> str:
    return f' data-author="{author}" data-date="{date}"'


def redline_inner(old_inner: str, new_inner: str, author: str, date: str) -> str:
    """Inline word-level diff. Falls back to whole-content replace when either
    side contains element markup (nested tags make word-level splicing unsafe)."""
    if "<" in old_inner or "<" in new_inner:
        return f"<del{_mark(author, date)}>{old_inner}</del><ins{_mark(author, date)}>{new_inner}</ins>"
    out: list[str] = []
    a, b = _tokens(old_inner), _tokens(new_inner)
    for op, i1, i2, j1, j2 in SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append("".join(a[i1:i2]))
        else:
            if i2 > i1:
                out.append(f"<del{_mark(author, date)}>{''.join(a[i1:i2])}</del>")
            if j2 > j1:
                out.append(f"<ins{_mark(author, date)}>{''.join(b[j1:j2])}</ins>")
    return "".join(out)


def redline_block(old_outer: str, new_outer: str, author: str, date: str) -> str:
    tag, attrs, old_inner = split_outer(old_outer)
    _, _, new_inner = split_outer(new_outer)
    return f"<{tag}{attrs}>{redline_inner(old_inner, new_inner, author, date)}</{tag}>"


def insertion_block(new_outer: str, author: str, date: str) -> str:
    tag, attrs, inner = split_outer(new_outer)
    return f"<{tag}{attrs}><ins{_mark(author, date)}>{inner}</ins></{tag}>"


_DEL_RE = re.compile(r"<del\b[^>]*>(.*?)</del>", re.DOTALL)
_INS_RE = re.compile(r"<ins\b[^>]*>(.*?)</ins>", re.DOTALL)


def reject_all(redlined: str) -> str:
    return _INS_RE.sub("", _DEL_RE.sub(lambda m: m.group(1), redlined))


def accept_all(redlined: str) -> str:
    return _DEL_RE.sub("", _INS_RE.sub(lambda m: m.group(1), redlined))


def verify_roundtrip(old_outer: str, new_outer: str, redlined_outer: str) -> dict:
    """Inner-content proofs: the redline keeps the old block's tag and attrs
    (chunk identity), so equality is checked on the content the change governs."""
    _, _, old_inner = split_outer(old_outer)
    _, _, new_inner = split_outer(new_outer)
    _, _, red_inner = split_outer(redlined_outer)
    return {
        "reject_all_equals_old": reject_all(red_inner) == old_inner,
        "accept_all_equals_new": accept_all(red_inner) == new_inner,
    }


def verify_insertion(new_outer: str, redlined_outer: str) -> dict:
    _, _, new_inner = split_outer(new_outer)
    _, _, red_inner = split_outer(redlined_outer)
    return {
        "reject_all_equals_old": reject_all(red_inner) == "",
        "accept_all_equals_new": accept_all(red_inner) == new_inner,
    }
