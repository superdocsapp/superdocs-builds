from __future__ import annotations

import hashlib
import html
import io
import re
import zipfile
from dataclasses import dataclass


INJECTION_PATTERNS = (
    r"ignore\s+(?:all\s+)?previous\s+instructions",
    r"system\s+message",
    r"reveal\s+(?:the\s+)?(?:secret|api\s+key|credentials)",
    r"you\s+are\s+now\s+(?:an|the)\s+assistant",
    r"execute\s+(?:this|the)\s+(?:command|tool)",
)


@dataclass(frozen=True)
class SourcePayload:
    filename: str
    media_type: str
    data: bytes


def _docx_to_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"</w:p>|</w:tr>", "\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    return html.unescape(xml)


def extract_text(payload: SourcePayload) -> str:
    name = payload.filename.lower()
    if name.endswith(".docx"):
        return _docx_to_text(payload.data)
    if name.endswith((".txt", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml")):
        return payload.data.decode("utf-8", errors="replace")
    raise ValueError(f"unsupported source format: {payload.filename}")


def detect_prompt_injection(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            hits.append(pattern)
    return hits


def source_metadata(payload: SourcePayload, text: str) -> dict:
    return {
        "sha256": hashlib.sha256(payload.data).hexdigest(),
        "bytes": len(payload.data),
        "line_count": len(text.splitlines()) or 1,
        "prompt_injection_hits": detect_prompt_injection(text),
        "parser": "deterministic-text-v1",
    }


def chunk_text(text: str, max_chars: int = 1200) -> list[tuple[str, int, int]]:
    lines = text.splitlines() or [""]
    chunks: list[tuple[str, int, int]] = []
    start = 1
    buffer: list[str] = []
    size = 0
    for number, line in enumerate(lines, start=1):
        if buffer and size + len(line) + 1 > max_chars:
            chunks.append(("\n".join(buffer), start, number - 1))
            buffer, size, start = [], 0, number
        buffer.append(line)
        size += len(line) + 1
    if buffer:
        chunks.append(("\n".join(buffer), start, len(lines)))
    return chunks
