import re
from dataclasses import dataclass
from enum import Enum


class SensitiveAction(str, Enum):
    BLOCK = "block"
    MASK = "mask"


@dataclass(frozen=True)
class SensitiveMatch:
    category: str
    start: int
    end: int


@dataclass(frozen=True)
class SensitiveScanResult:
    allowed: bool
    content: str
    matches: tuple[SensitiveMatch, ...]


_PATTERNS = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "phone": re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "api_key": re.compile(r"\b(?:sk|pk)_[A-Za-z0-9_-]{16,}\b"),
}


def scan_sensitive_content(content: str, *, action: SensitiveAction = SensitiveAction.BLOCK) -> SensitiveScanResult:
    matches = [
        SensitiveMatch(category, match.start(), match.end())
        for category, pattern in _PATTERNS.items()
        for match in pattern.finditer(content)
    ]
    matches.sort(key=lambda item: item.start)
    if not matches:
        return SensitiveScanResult(True, content, ())
    if action == SensitiveAction.BLOCK:
        return SensitiveScanResult(False, content, tuple(matches))
    masked = content
    for match in reversed(matches):
        masked = masked[:match.start] + f"[REDACTED:{match.category}]" + masked[match.end:]
    return SensitiveScanResult(True, masked, tuple(matches))
