from __future__ import annotations

import re
from pathlib import Path

import yaml

from soc2_index.paths import injection_patterns_path


def load_patterns(path: Path | None = None) -> list[tuple[str, re.Pattern[str]]]:
    data = yaml.safe_load((path or injection_patterns_path()).read_text(encoding="utf-8"))
    out: list[tuple[str, re.Pattern[str]]] = []
    for item in data.get("patterns") or []:
        out.append((item["id"], re.compile(item["regex"])))
    return out


def scan(text: str, patterns: list[tuple[str, re.Pattern[str]]] | None = None) -> list[str]:
    pats = patterns if patterns is not None else load_patterns()
    flags: list[str] = []
    for pid, rx in pats:
        if rx.search(text):
            flags.append(pid)
    return flags
