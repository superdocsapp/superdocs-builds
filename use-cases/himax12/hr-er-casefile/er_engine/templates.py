from __future__ import annotations

from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def load_template(name: str) -> str:
    path = TEMPLATES / f"{name}.md"
    return path.read_text(encoding="utf-8")


def fill(template: str, **fields: str) -> str:
    out = template
    for key, value in fields.items():
        out = out.replace("{{" + key + "}}", value)
    return out
