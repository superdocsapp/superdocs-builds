"""Writes approved changes back into the original .docx.

The editing service returns replacement content for a passage, and that content
is written into the original package rather than the package being replaced by
an export. Everything the run did not approve a change to is therefore untouched
at the byte level, because nothing wrote to it.

Paragraphs are located by their current text rather than by position or by an
identifier from the editing service. Position drifts as edits land, and an
external identifier cannot be verified against the file in hand. Text can be:
if the passage the service reports having changed is not present exactly once,
nothing is written and the caller is told.

What is preserved inside a rewritten paragraph: comment range markers, comment
references, paragraph properties, and the formatting of the first text run.
What is not: inline formatting that varied across runs within that paragraph.
"""

from __future__ import annotations

import html
import re
import zipfile
from collections.abc import Mapping
from io import BytesIO

from lxml import etree

from thread_resolver.adapters.ooxml import DOCUMENT_PART, XML, qn


class WriteBackError(Exception):
    """Raised when a change cannot be placed with certainty, leaving the file alone."""


_TAG = re.compile(r"<[^>]+>")
_BLOCK_END = re.compile(r"</(p|div|li|h[1-6])\s*>", re.IGNORECASE)
_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_WHITESPACE = re.compile(r"[ \t\r\f\v]+")


def html_to_text(fragment: str) -> str:
    """Reduce an HTML fragment to the text a Word paragraph would hold.

    Block boundaries become newlines so that a multi-paragraph replacement is
    still recognisable as several paragraphs rather than one run-on line.
    """
    text = _BREAK.sub("\n", fragment)
    text = _BLOCK_END.sub("\n", text)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    text = _WHITESPACE.sub(" ", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def normalise(text: str) -> str:
    """Comparison form for matching a passage, ignoring incidental whitespace."""
    return " ".join(text.split())


def apply_changes(data: bytes, changes: Mapping[str, str]) -> bytes:
    """Replace the text of each named passage.

    `changes` maps the passage as it currently reads to its replacement. Both
    are plain text; HTML from an editing service is reduced with `html_to_text`
    before it gets here.

    Every passage must match exactly one paragraph. A passage that matches none,
    or more than one, aborts the whole write so that a partial application never
    reaches the file.
    """
    if not changes:
        return data

    parts = _read_parts(data)
    if DOCUMENT_PART not in parts:
        raise WriteBackError(f"{DOCUMENT_PART} is missing, so there is no body to write into.")

    root = etree.fromstring(parts[DOCUMENT_PART])
    body = root.find(qn("w:body"))
    if body is None:
        raise WriteBackError("The document has no body element.")

    paragraphs = body.findall(qn("w:p"))
    index = _index_by_text(paragraphs)

    targets = []
    for passage, replacement in changes.items():
        key = normalise(passage)
        matches = index.get(key, [])
        if not matches:
            raise WriteBackError(
                f"The passage {_preview(passage)!r} is not in the document, so the change "
                "cannot be placed. Nothing was written."
            )
        if len(matches) > 1:
            raise WriteBackError(
                f"The passage {_preview(passage)!r} appears {len(matches)} times, so the "
                "change cannot be placed unambiguously. Nothing was written."
            )
        targets.append((matches[0], replacement))

    for paragraph, replacement in targets:
        _replace_text(paragraph, replacement)

    rewritten = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    return _replace_part(data, DOCUMENT_PART, rewritten)


def _index_by_text(paragraphs: list[etree._Element]) -> dict[str, list[etree._Element]]:
    index: dict[str, list[etree._Element]] = {}
    for paragraph in paragraphs:
        key = normalise(_text_of(paragraph))
        if key:
            index.setdefault(key, []).append(paragraph)
    return index


def _text_of(paragraph: etree._Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter(qn("w:t")))


def _replace_text(paragraph: etree._Element, replacement: str) -> None:
    """Swap a paragraph's text while keeping everything that is not text.

    Comment range markers and comment references live among the runs. Removing
    them would detach the thread from its passage, so only runs that carry text
    and nothing else are removed.
    """
    text_runs = [run for run in paragraph.findall(qn("w:r")) if _is_plain_text_run(run)]
    if not text_runs:
        raise WriteBackError("The passage has no editable text runs.")

    template = text_runs[0]
    position = list(paragraph).index(template)
    properties = template.find(qn("w:rPr"))

    for run in text_runs:
        paragraph.remove(run)

    for offset, line in enumerate(replacement.split("\n")):
        paragraph.insert(position + offset, _build_run(line, properties))


def _is_plain_text_run(run: etree._Element) -> bool:
    """A run that carries text and no structural markers."""
    if run.find(qn("w:t")) is None:
        return False
    return run.find(qn("w:commentReference")) is None


def _build_run(text: str, properties: etree._Element | None) -> etree._Element:
    run = etree.Element(qn("w:r"))
    if properties is not None:
        # Copied so the same properties element is not shared between runs.
        run.append(etree.fromstring(etree.tostring(properties)))
    node = etree.SubElement(run, qn("w:t"))
    node.text = text
    node.set(f"{{{XML}}}space", "preserve")
    return run


def _read_parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _replace_part(archive_bytes: bytes, part_name: str, data: bytes) -> bytes:
    buffer = BytesIO()
    with (
        zipfile.ZipFile(BytesIO(archive_bytes)) as source,
        zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for info in source.infolist():
            payload = data if info.filename == part_name else source.read(info.filename)
            target.writestr(info, payload)
    return buffer.getvalue()


def _preview(text: str, limit: int = 60) -> str:
    flat = normalise(text)
    return flat[:limit] + ("..." if len(flat) > limit else "")
