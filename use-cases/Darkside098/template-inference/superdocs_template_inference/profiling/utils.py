"""Profiling utilities."""

import re
from typing import Set


# Basic English stopwords (small, deterministic list)
STOPWORDS: Set[str] = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "is",
    "are",
    "am",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "should",
    "could",
    "can",
    "may",
    "might",
    "must",
    "of",
    "to",
    "in",
    "at",
    "by",
    "for",
    "from",
    "with",
    "as",
    "on",
    "was",
    "it",
    "that",
    "this",
    "which",
    "who",
    "when",
    "where",
    "why",
    "how",
}


def tokenize_text(text: str) -> list[str]:
    """Tokenize text into words.

    Args:
        text: Input text to tokenize.

    Returns:
        List of tokens (lowercase, punctuation removed).
    """
    # Convert to lowercase
    text = text.lower()

    # Remove punctuation and split on whitespace
    tokens = re.findall(r"\b[a-z0-9]+\b", text)

    return tokens


def filter_stopwords(tokens: list[str]) -> list[str]:
    """Filter out common stopwords.

    Args:
        tokens: List of tokens.

    Returns:
        Filtered list of tokens.
    """
    return [t for t in tokens if t not in STOPWORDS]


def extract_vocabulary(text: str, top_n: int = 20) -> tuple[dict[str, int], list[tuple[str, int]]]:
    """Extract vocabulary and frequencies from text.

    Args:
        text: Input text.
        top_n: Number of top terms to return.

    Returns:
        Tuple of (full vocabulary dict, top N terms list).
    """
    tokens = tokenize_text(text)
    filtered = filter_stopwords(tokens)

    # Count frequencies
    vocab: dict[str, int] = {}
    for token in filtered:
        vocab[token] = vocab.get(token, 0) + 1

    # Get top N
    top = sorted(vocab.items(), key=lambda x: x[1], reverse=True)[:top_n]

    return vocab, top


def calculate_avg_word_length(text: str) -> float:
    """Calculate average word length.

    Args:
        text: Input text.

    Returns:
        Average word length.
    """
    tokens = tokenize_text(text)
    if not tokens:
        return 0.0
    return sum(len(t) for t in tokens) / len(tokens)


def calculate_word_count(text: str) -> int:
    """Calculate total word count (including stopwords).

    Args:
        text: Input text.

    Returns:
        Word count.
    """
    tokens = tokenize_text(text)
    return len(tokens)
