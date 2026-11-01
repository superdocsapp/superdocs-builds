from __future__ import annotations

import re
from pathlib import Path

import yaml

_DATE_IN_NAME = re.compile(r"(20\d{2}-\d{2}-\d{2})")
_DATE_HEADER = re.compile(r"(?im)^Date:\s*(.+)$")
_OWNER_HEADER = re.compile(r"(?im)^(?:Owner|Prepared by):\s*(.+)$")
_H1_MD = re.compile(r"(?m)^#\s+(.+)$")
_H1_HTML = re.compile(r"(?is)<h1[^>]*>(.*?)</h1>")


def parse_front_matter(text: str) -> tuple[dict, str, bool]:
    """Return (yaml dict, body, has_controls_key). Empty dict if no front-matter."""
    if not text.startswith("---"):
        return {}, text, False
    rest = text[3:]
    if rest.startswith("\n"):
        rest = rest[1:]
    end = rest.find("\n---")
    if end < 0:
        return {}, text, False
    raw = rest[:end]
    body = rest[end + 4 :]
    if body.startswith("\n"):
        body = body[1:]
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        return {}, text, False
    return data, body, "controls" in data


def _first_nonempty_line(text: str) -> str | None:
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s
    return None


def extract_metadata(path: Path, text: str | None) -> dict:
    """Local metadata. Body is never used to guess a control."""
    title = path.name
    date = None
    owner = None
    controls: list[str] = []
    has_controls = False
    evidence_type = None
    status = "ok"
    body = text or ""

    if text is None:
        return {
            "title": title,
            "date": date,
            "owner": owner,
            "front_matter_controls": [],
            "front_matter_has_controls_key": False,
            "evidence_type": None,
            "extract_status": "hash_only",
        }

    fm, body, has_controls = parse_front_matter(text)
    if fm.get("title"):
        title = str(fm["title"])
    if fm.get("date"):
        date = str(fm["date"])
    if fm.get("owner"):
        owner = str(fm["owner"])
    if has_controls:
        raw = fm.get("controls") or []
        if isinstance(raw, str):
            controls = [raw]
        else:
            controls = [str(x) for x in raw]
    if fm.get("evidence_type"):
        evidence_type = str(fm["evidence_type"])

    if title == path.name:
        m = _H1_MD.search(body)
        if m:
            title = m.group(1).strip()
        else:
            hm = _H1_HTML.search(body)
            if hm:
                title = re.sub(r"<[^>]+>", "", hm.group(1)).strip() or title
            else:
                first = _first_nonempty_line(body)
                if first:
                    title = first.lstrip("# ").strip()

    if date is None:
        m = _DATE_IN_NAME.search(path.name)
        if m:
            date = m.group(1)
        else:
            m = _DATE_HEADER.search(body)
            if m:
                date = m.group(1).strip()

    if owner is None:
        m = _OWNER_HEADER.search(body)
        if m:
            owner = m.group(1).strip()

    return {
        "title": title,
        "date": date,
        "owner": owner,
        "front_matter_controls": controls,
        "front_matter_has_controls_key": has_controls,
        "evidence_type": evidence_type,
        "extract_status": status,
    }
