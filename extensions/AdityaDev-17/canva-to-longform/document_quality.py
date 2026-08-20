"""
document_quality.py — reusable safety checks for any generated
document, meant to run before committing/exporting, not just in test
scripts. Two real bugs found earlier in this build motivated this:
(1) brand colors not surviving into headings, (2) sections silently
duplicated across turns. Both are checked here, programmatically -
"never bluffs" applied to our own pipeline output, not just SuperDocs'.
"""
import re
from collections import Counter


def extract_headings(html: str) -> list[dict]:
    """Returns every h1/h2 heading with its text and any color found
    in its inline style."""
    pattern = re.compile(r'<h[12][^>]*style="([^"]*)"[^>]*>(.*?)</h[12]>', re.DOTALL)
    headings = []
    for match in pattern.finditer(html):
        style, raw_text = match.group(1), match.group(2)
        text = re.sub(r"<[^>]+>", "", raw_text).strip()
        text = re.sub(r"\s+", " ", text)
        color_match = re.search(r"color:\s*(#[0-9a-fA-F]{6})", style)
        headings.append({"text": text, "color": color_match.group(1) if color_match else None})
    return headings


def detect_duplicate_headings(html: str) -> list[dict]:
    """Flags any heading text that appears more than once - the exact
    shape of the real bug found in test_long_document_consistency.py
    (same title, different body text, two separate turns)."""
    pattern = re.compile(r"<h[12][^>]*>(.*?)</h[12]>", re.DOTALL)
    texts = []
    for match in pattern.finditer(html):
        clean = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        clean = re.sub(r"\s+", " ", clean)
        texts.append(clean)

    counts = Counter(t.lower() for t in texts)
    seen_originals = {}
    for t in texts:
        key = t.lower()
        seen_originals.setdefault(key, t)

    return [
        {"text": seen_originals[key], "count": count}
        for key, count in counts.items()
        if count > 1
    ]


def check_color_consistency(html: str, expected_primary: str) -> dict:
    headings = extract_headings(html)
    on_brand = [h for h in headings if h["color"] and h["color"].lower() == expected_primary.lower()]
    off_brand = [h for h in headings if h not in on_brand]
    return {
        "total": len(headings),
        "on_brand_count": len(on_brand),
        "off_brand": off_brand,
    }


def run_quality_report(html: str, expected_primary: str) -> bool:
    """Prints a full report and returns True only if the document
    passes BOTH checks cleanly - the gate a real pipeline would use
    before allowing export/commit."""
    print("=== Document Quality Report ===\n")

    consistency = check_color_consistency(html, expected_primary)
    print(f"Color consistency: {consistency['on_brand_count']}/{consistency['total']} headings on-brand")
    for h in consistency["off_brand"]:
        print(f"  ❌ OFF-BRAND: color={h['color']}  \"{h['text']}\"")

    duplicates = detect_duplicate_headings(html)
    print(f"\nDuplicate sections: {len(duplicates)} found")
    for d in duplicates:
        print(f"  ⚠️  \"{d['text']}\" appears {d['count']} times")

    passed = consistency["off_brand"] == [] and duplicates == []
    print(f"\n{'✅ PASSED' if passed else '❌ FAILED'} quality gate")
    return passed