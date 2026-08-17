import re
from decimal import Decimal, InvalidOperation


STREET_SUFFIXES = {
    "drive": "dr",
    "dr.": "dr",
    "dr": "dr",
    "street": "st",
    "st.": "st",
    "st": "st",
    "road": "rd",
    "rd.": "rd",
    "rd": "rd",
    "avenue": "ave",
    "ave.": "ave",
    "ave": "ave",
    "boulevard": "blvd",
    "blvd.": "blvd",
    "blvd": "blvd",
}

STATE_NAMES = {
    "texas": "tx",
}


def normalize_money(value: str | float | int | None) -> float | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    cleaned = value.strip()

    if not cleaned:
        return None

    cleaned = cleaned.replace("$", "").replace(",", "")

    try:
        return float(Decimal(cleaned))
    except InvalidOperation:
        return None


def normalize_percentage(value: str | float | int | None) -> float | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    cleaned = value.strip().replace("%", "")

    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)

    if not match:
        return None

    return float(match.group())


def normalize_term_months(value: str | int | float | None) -> int | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return int(value)

    text = value.lower().strip()

    month_match = re.search(r"(\d+)\s*(?:month|months|monthly)", text)
    if month_match:
        return int(month_match.group(1))

    year_match = re.search(r"(\d+)\s*(?:year|years|yr|yrs)", text)
    if year_match:
        return int(year_match.group(1)) * 12

    return None


def normalize_boolean(value: str | bool | None) -> bool | None:
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    text = value.strip().lower()

    truthy = {
        "yes",
        "true",
        "required",
        "enabled",
        "included",
        "escrowed",
    }

    falsy = {
        "no",
        "false",
        "not required",
        "disabled",
        "waived",
    }

    if text in truthy:
        return True

    if text in falsy:
        return False

    return None


def normalize_person_name(name: str) -> str:
    """
    Basic textual normalization only.

    This deliberately does NOT decide whether omission of a middle
    initial is legally acceptable. That decision belongs to the
    file-rule layer.
    """
    name = name.lower().strip()

    name = re.sub(r"[.,]", "", name)
    name = re.sub(r"\s+", " ", name)

    return name


def name_without_middle_initial(name: str) -> str:
    normalized = normalize_person_name(name)

    parts = normalized.split()

    if len(parts) == 3 and len(parts[1]) == 1:
        return f"{parts[0]} {parts[2]}"

    return normalized


def names_compatible_under_middle_initial_rule(
    left: str,
    right: str,
) -> bool:
    return (
        name_without_middle_initial(left)
        == name_without_middle_initial(right)
    )


def normalize_address(value: str | None) -> str | None:
    if value is None:
        return None

    text = value.lower().strip()

    # Remove punctuation while preserving alphanumeric tokens.
    text = re.sub(r"[,.]", "", text)

    words = text.split()
    normalized_words = []

    for word in words:
        word = STREET_SUFFIXES.get(word, word)
        word = STATE_NAMES.get(word, word)
        normalized_words.append(word)

    return " ".join(normalized_words)


def addresses_match(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False

    return normalize_address(left) == normalize_address(right)


def split_borrower_names(value: str | None) -> list[str]:
    """
    Split common multi-borrower formats used in our declared input set.

    Examples:
    "John A. Carter and Emily Carter"
    "John A. Carter; Emily Carter"
    "John Carter & Emily Carter"
    "John A. Carter / Emily Carter"
    """
    if not value:
        return []

    text = value.strip()

    parts = re.split(
        r"\s+(?:and|&)\s+|\s*;\s*|\s*/\s*",
        text,
        flags=re.IGNORECASE,
    )

    return [
        part.strip()
        for part in parts
        if part.strip()
    ]


def borrower_sets_match_under_middle_initial_rule(
    left: str | None,
    right: str | None,
) -> bool:
    if not left or not right:
        return False

    left_names = split_borrower_names(left)
    right_names = split_borrower_names(right)

    if len(left_names) != len(right_names):
        return False

    left_normalized = sorted(
        name_without_middle_initial(name)
        for name in left_names
    )

    right_normalized = sorted(
        name_without_middle_initial(name)
        for name in right_names
    )

    return left_normalized == right_normalized