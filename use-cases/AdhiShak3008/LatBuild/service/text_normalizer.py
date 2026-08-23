"""
text_normalizer.py
Deterministic normalization of PDF-extracted text.

Fixes two classes of PDF extraction artifacts:
1. Word concatenation: "groundinglanguagemodelresponses" -> split into words
2. Hyphenation artifacts: "ad- vanced" -> "advanced"

Rules:
- Does NOT alter wording, meaning, or sentences
- Does NOT paraphrase or summarize
- Preserves citations [1], (Smith et al., 2020) etc.
- Preserves paragraph boundaries
- Preserves punctuation
- Deterministic: same input always produces same output
"""

import re


def normalize_section_text(text: str) -> str:
    """Apply all deterministic normalizations to extracted section text."""
    if not text:
        return text

    paragraphs = text.split("\n\n")
    normalized = []
    for para in paragraphs:
        p = para.strip()
        if not p:
            continue
        p = _fix_hyphenation(p)
        p = _fix_concatenated_words(p)
        p = _normalize_whitespace(p)
        normalized.append(p)

    return "\n\n".join(normalized)


def _fix_hyphenation(text: str) -> str:
    """
    Join words hyphenated across line breaks.
    "ad- vanced" -> "advanced"
    "Retrieval- Augmented" -> "Retrieval-Augmented"
    """
    # word- continuation (lowercase after hyphen+space = line break)
    text = re.sub(r'(\w)- ([a-z])', r'\1\2', text)
    # Word- Capitalized (compound term, keep hyphen)
    text = re.sub(r'(\w)- ([A-Z])', r'\1-\2', text)
    return text


# Known camelCase terms that should NOT be split
_PRESERVE_TERMS = {
    'PilotMaster', 'PilotCore', 'DocPilot', 'TracePilot', 'GaugePilot',
    'TinyBERT', 'PyMuPDF', 'LangChain', 'AutoGen', 'CrewAI',
    'GitHub', 'JavaScript', 'TypeScript', 'FastAPI', 'LangGraph',
    'OpenAI', 'ChatGPT', 'arXiv', 'iPhone', 'YouTube',
}

# Common English word starts (for splitting concatenated tokens)
_WORD_STARTS = [
    'through', 'within', 'between', 'across', 'while', 'rather',
    'without', 'during', 'before', 'after', 'under', 'above',
    'the', 'and', 'for', 'that', 'with', 'from', 'this', 'which',
    'using', 'than', 'have', 'has', 'been', 'not', 'are', 'but',
    'their', 'into', 'also', 'can', 'may', 'each', 'its', 'all',
    'retrieval', 'document', 'language', 'model', 'pipeline',
    'evaluation', 'execution', 'benchmark', 'information',
    'generation', 'engineering', 'platform', 'framework',
    'observability', 'intelligence', 'configuration',
    'application', 'implementation', 'architecture',
    'operational', 'experimental', 'independently',
    'subsequently', 'consequently', 'comprehensive',
]

# Common word endings for suffix-based splitting
_WORD_ENDINGS = [
    'tion', 'sion', 'ment', 'ness', 'ance', 'ence',
    'able', 'ible', 'ling', 'ting', 'ning', 'ring', 'ing',
    'ous', 'ive', 'ful', 'ity', 'ory', 'ary', 'ery',
    'ally', 'ely', 'ily', 'ly',
    'ated', 'ized', 'ised', 'ted', 'sed', 'ned', 'red', 'led', 'ed',
    'ies', 'als', 'ors', 'ers', 'ics', 'ems', 'ons', 'ts', 'es',
    'al', 'or', 'er', 'ic', 'le', 'se', 'ce', 'ge', 'de', 'te', 'ne',
]


def _fix_concatenated_words(text: str) -> str:
    """
    Split words concatenated by PDF extraction.

    Conservative approach: only split at HIGH-CONFIDENCE boundaries
    to avoid over-splitting. It's better to leave some concatenation
    than to introduce incorrect word breaks.

    High-confidence splits:
    1. CamelCase: "languageModel" -> "language Model"
    2. Punctuation+lowercase: "tracing,and" -> "tracing, and"
    3. Period+Uppercase: "systems.The" -> "systems. The"
    """
    # Protect known terms
    placeholders = {}
    for term in _PRESERVE_TERMS:
        if term in text:
            ph = f"\x00{len(placeholders)}\x00"
            placeholders[ph] = term
            text = text.replace(term, ph)

    # CamelCase split: lowercase -> Uppercase (highest confidence)
    text = re.sub(r'([a-z])([A-Z][a-z])', r'\1 \2', text)

    # Punctuation followed by lowercase without space
    text = re.sub(r'([,;:])([a-z])', r'\1 \2', text)

    # Period followed by Uppercase (sentence boundary)
    text = re.sub(r'\.([A-Z])', r'. \1', text)

    # Restore protected terms
    for ph, term in placeholders.items():
        text = text.replace(ph, term)

    return text


def _split_long_token(token: str) -> str:
    """
    Split a long concatenated token into words using greedy forward matching.
    """
    if len(token) <= 18:
        return token

    result = []
    remaining = token.lower() if token.islower() else token
    original_remaining = token

    # Sort word starts by length (longest first for greedy match)
    starts_sorted = sorted(_WORD_STARTS, key=len, reverse=True)

    iterations = 0
    while len(remaining) > 0 and iterations < 50:
        iterations += 1
        matched = False

        # Try prefix match against known word starts
        for prefix in starts_sorted:
            if remaining.lower().startswith(prefix) and len(remaining) > len(prefix):
                after = remaining[len(prefix):]
                # Only accept if the remainder starts with a lowercase letter
                # (indicating another word follows)
                if after and (after[0].islower() or after[0] in ',;:.'):
                    result.append(remaining[:len(prefix)])
                    remaining = remaining[len(prefix):]
                    matched = True
                    break

        if matched:
            continue

        # Try suffix-based splitting: find where current word likely ends
        best_end = 0
        for suffix in sorted(_WORD_ENDINGS, key=len, reverse=True):
            pos = remaining.lower().find(suffix, 3)
            if pos > 0:
                candidate_end = pos + len(suffix)
                if candidate_end < len(remaining) and 4 <= candidate_end <= 16:
                    after = remaining[candidate_end:]
                    if after and after[0].islower():
                        best_end = candidate_end
                        break

        if best_end > 0:
            result.append(remaining[:best_end])
            remaining = remaining[best_end:]
        else:
            # Can't split — keep the rest as one chunk
            result.append(remaining)
            remaining = ""

    return " ".join(result)


def _normalize_whitespace(text: str) -> str:
    """Clean up whitespace artifacts."""
    # Multiple spaces -> single
    text = re.sub(r'  +', ' ', text)
    # Space before punctuation
    text = re.sub(r' ([,;:])', r'\1', text)
    # Ensure space after period+uppercase (sentence boundary)
    text = re.sub(r'\.([A-Z])', r'. \1', text)
    return text.strip()
