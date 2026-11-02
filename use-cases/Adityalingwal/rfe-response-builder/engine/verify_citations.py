import re


# markdown punctuation a round trip through SuperDocs rewrites without
# touching the words: a backslash escape is dropped, a backtick is dropped,
# an HTML line break inside a table cell came back as a space before
# SuperDocs' 2026-08 update and disappears entirely since — both readings
# are tolerated
MARKDOWN_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|~>])")
LINE_BREAK_TAG = re.compile(r"<br\s*/?>", re.IGNORECASE)


def _normalize(text: str, line_break: str = " ") -> str:
    """Reduce text to its words so formatting cannot masquerade as a change.

    Markdown blockquote markers, code fences and backslash escapes are
    formatting, not content: SuperDocs re-serialises them on export
    (`O*NET` comes back as `O\\*NET`), and a quote taken from inside a
    "> ..." block must still match. Every word, number and punctuation
    mark stays and must match. A `<br>` becomes `line_break` — the export
    turned it into a space before SuperDocs' 2026-08 update and deletes
    it since, so containment is checked under both readings (see
    `contains_verbatim`).
    """
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
    text = MARKDOWN_ESCAPE.sub(r"\1", text)
    text = LINE_BREAK_TAG.sub(line_break, text)
    text = text.replace("`", "")
    return re.sub(r"\s+", " ", text).strip().lower()


def _variants(text: str) -> list[str]:
    """The normalized text under each reading its `<br>` tags may have had."""
    variants = [_normalize(text)]
    if LINE_BREAK_TAG.search(text):
        variants.append(_normalize(text, line_break=""))
    return variants


def contains_verbatim(needle: str, haystack: str) -> bool:
    """Word-for-word containment, tolerant of either `<br>` reading."""
    return any(n in h for n in _variants(needle) for h in _variants(haystack))


def citation_is_verbatim(quote: str, source_text: str) -> bool:
    """A cited quote must appear word-for-word in its named source.

    Comparison is whitespace- and case-insensitive, nothing more: a
    paraphrase is not a citation.
    """
    return contains_verbatim(quote, source_text)


def find_citation_failures(
    cited_sections: list[dict], sources: dict[str, str]
) -> list[str]:
    """Check every drafted section's citations; name each failure.

    `cited_sections`: [{"section": ..., "file": ..., "quote": ...}, ...]
    `sources`: file name -> full text.
    Returns human-readable failure messages, empty when all citations hold.
    """
    failures = []
    for cited in cited_sections:
        section, file, quote = cited["section"], cited["file"], cited["quote"]
        if file not in sources:
            failures.append(
                f"section '{section}' cites '{file}', which is not among the "
                f"petition documents — the citation is invented"
            )
        elif not citation_is_verbatim(quote, sources[file]):
            failures.append(
                f"section '{section}' quotes text that does not appear in "
                f"'{file}' — fix the quote or the citation before export"
            )
    return failures
