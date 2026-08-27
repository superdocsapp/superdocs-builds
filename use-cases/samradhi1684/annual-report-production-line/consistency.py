import re
from itertools import combinations


NUMBER_PATTERN = re.compile(
    r"""
    (?P<prefix>£|\$|€|₹)?
    \s*
    (?P<value>\d+(?:,\d{3})*(?:\.\d+)?)
    \s*
    (?P<unit>
        million|billion|thousand|trillion|
        m|bn|k|tn|
        %|percent|percentage
    )?
    """,
    re.IGNORECASE | re.VERBOSE,
)


def strip_html(html):
    """Convert HTML into readable plain text."""

    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def normalize_number(value, unit):
    """Normalize scale units to a comparable numeric value."""

    multiplier = {
        "thousand": 1_000,
        "k": 1_000,
        "million": 1_000_000,
        "m": 1_000_000,
        "billion": 1_000_000_000,
        "bn": 1_000_000_000,
        "trillion": 1_000_000_000_000,
        "tn": 1_000_000_000_000,
    }

    return value * multiplier.get(unit.lower(), 1)


def extract_numbers(html, document_name):
    """
    Extract numeric candidates without trying to understand
    what each number means.

    Semantic interpretation is intentionally left to SuperDocs.
    """

    text = strip_html(html)

    figures = []

    for match in NUMBER_PATTERN.finditer(text):

        prefix = (match.group("prefix") or "").strip()
        raw_value = match.group("value").replace(",", "")
        unit = (match.group("unit") or "").strip().lower()

        value = float(raw_value)

        normalized_value = normalize_number(value, unit)

        start = max(0, match.start() - 120)
        end = min(len(text), match.end() + 120)

        figures.append(
            {
                "document": document_name,
                "original": match.group(0).strip(),
                "prefix": prefix,
                "value": value,
                "unit": unit,
                "normalized_value": normalized_value,
                "context": text[start:end],
            }
        )

    return figures


def build_candidate_pairs(documents):
    """
    Build plausible numeric comparisons between documents.

    We only filter obviously incompatible candidates locally.
    Semantic interpretation is left to SuperDocs.
    """

    extracted = {
        name: extract_numbers(html, name)
        for name, html in documents.items()
    }

    pairs = []

    document_names = list(extracted)

    for left_name, right_name in combinations(document_names, 2):

        for left in extracted[left_name]:
            for right in extracted[right_name]:

                # Don't compare percentages with monetary values,
                # years with monetary values, etc.
                if left["prefix"] != right["prefix"]:
                    continue

                left_unit = left["unit"]
                right_unit = right["unit"]

                # If both have explicit units, require compatible
                # unit families.
                if left_unit and right_unit:
                    left_is_percent = left_unit in {
                        "%", "percent", "percentage"
                    }
                    right_is_percent = right_unit in {
                        "%", "percent", "percentage"
                    }

                    if left_is_percent != right_is_percent:
                        continue

                pairs.append({
                    "left": left,
                    "right": right,
                })

    return pairs

def print_candidates(pairs):

    print("\n" + "=" * 70)
    print("NUMBER CONSISTENCY CANDIDATES")
    print("=" * 70)

    for index, pair in enumerate(pairs, start=1):

        left = pair["left"]
        right = pair["right"]

        print(f"\n[{index}]")

        print(
            f"  {left['document']}: "
            f"{left['original']}"
        )

        print(
            f"  Context: {left['context']}"
        )

        print(
            f"  {right['document']}: "
            f"{right['original']}"
        )

        print(
            f"  Context: {right['context']}"
        )

    print("\n" + "=" * 70)