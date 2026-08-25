from __future__ import annotations


def issue(type_: str, message: str, **details: str) -> dict[str, str]:
    """Create the shared issue shape returned by analysis and review validation."""
    return {"type": type_, "message": message, **{key: value for key, value in details.items() if value is not None}}
