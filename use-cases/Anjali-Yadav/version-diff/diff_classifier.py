import re
from difflib import SequenceMatcher


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _looks_like_cross_reference(text: str) -> bool:
    lowered = (text or "").lower()
    return (
        "section" in lowered
        or "clause" in lowered
        or "appendix" in lowered
        or "definition" in lowered
        or re.search(r"\b[a-z]+\s+\d+\.\d+\b", lowered) is not None
    )


def classify_diff(before_text: str, after_text: str) -> dict:
    """Classify a before/after text pair as formatting or substantive.

    The classifier deliberately avoids an LLM call. It does a mechanical
    comparison first, then flags cross-reference renumbering as substantive
    even when the visible diff is small.
    """
    before_clean = _normalize_text(before_text)
    after_clean = _normalize_text(after_text)

    if before_clean == after_clean:
        if before_text == after_text:
            return {
                "kind": "no_change",
                "substantive": False,
                "reason": "no_change",
                "before_text": before_clean,
                "after_text": after_clean,
            }
        return {
            "kind": "formatting",
            "substantive": False,
            "reason": "whitespace_or_minor_formatting",
            "before_text": before_clean,
            "after_text": after_clean,
        }

    if before_clean and after_clean:
        ratio = SequenceMatcher(None, before_clean, after_clean).ratio()
    else:
        ratio = 0.0

    if ratio >= 0.97 and before_clean != after_clean:
        # Very small changes such as whitespace or punctuation-only edits are
        # treated as formatting noise, unless they touch a cross-reference.
        if _looks_like_cross_reference(before_text) or _looks_like_cross_reference(after_text):
            return {
                "kind": "substantive",
                "substantive": True,
                "reason": "cross_reference_changed",
                "before_text": before_clean,
                "after_text": after_clean,
            }
        return {
            "kind": "formatting",
            "substantive": False,
            "reason": "whitespace_or_minor_formatting",
            "before_text": before_clean,
            "after_text": after_clean,
        }

    if _looks_like_cross_reference(before_text) or _looks_like_cross_reference(after_text):
        return {
            "kind": "substantive",
            "substantive": True,
            "reason": "cross_reference_changed",
            "before_text": before_clean,
            "after_text": after_clean,
        }

    if before_clean != after_clean:
        return {
            "kind": "substantive",
            "substantive": True,
            "reason": "wording_changed",
            "before_text": before_clean,
            "after_text": after_clean,
        }

    return {
        "kind": "formatting",
        "substantive": False,
        "reason": "no_material_difference",
        "before_text": before_clean,
        "after_text": after_clean,
    }


def summarize_changes(before_text: str, after_text: str) -> dict:
    """Return a small summary that preserves the mechanical/noise split."""
    if not before_text and not after_text:
        return {
            "material_changes": [],
            "formatting_changes": 0,
            "has_material_change": False,
        }

    classification = classify_diff(before_text, after_text)
    material = []
    formatting_changes = 0

    if classification["kind"] == "substantive":
        material.append(
            {
                "before_text": classification["before_text"],
                "after_text": classification["after_text"],
                "reason": classification["reason"],
            }
        )
    elif classification["kind"] == "formatting":
        formatting_changes = 1

    return {
        "material_changes": material,
        "formatting_changes": formatting_changes,
        "has_material_change": bool(material),
    }
