from typing import List


def extract_verbatim_quote(text: str, keywords: List[str], default_quote: str) -> str:
    """
    Finds and extracts the exact sentence in the raw text matching any of the specified keywords.
    Ensures quotes are cleanly trimmed and truncated to reasonable length (250 chars).
    """
    lines = text.split("\n")
    for line in lines:
        cleaned = line.strip()
        if not cleaned:
            continue
        for kw in keywords:
            if kw.lower() in cleaned.lower():
                return cleaned[:250]
    return default_quote
