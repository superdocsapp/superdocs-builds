"""Observable pairwise compatibility signals derived from DocumentProfile data."""

from __future__ import annotations

from typing import Iterable

from superdocs_template_inference.models import DocumentProfile


def _clamp(value: float) -> float:
    """Clamp a score into the [0.0, 1.0] range."""
    return max(0.0, min(1.0, value))


def _safe_divide(numerator: float, denominator: float) -> float:
    """Divide safely, returning 0.0 if denominator is zero."""
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _jaccard_similarity(left: Iterable[str], right: Iterable[str]) -> float:
    """Return Jaccard similarity for two iterables of terms."""
    left_set = set(left)
    right_set = set(right)

    if not left_set and not right_set:
        return 1.0
    if not left_set or not right_set:
        return 0.0

    union = left_set | right_set
    intersection = left_set & right_set
    return _clamp(_safe_divide(len(intersection), len(union)))


def block_structure_similarity(profile_a: DocumentProfile, profile_b: DocumentProfile) -> float:
    """Compare structural counts using a tolerance-based relative-difference measure."""
    metrics = [
        ("total_blocks", profile_a.structural.total_blocks, profile_b.structural.total_blocks),
        ("paragraph_count", profile_a.structural.paragraph_count, profile_b.structural.paragraph_count),
        ("heading_count", profile_a.structural.heading_count, profile_b.structural.heading_count),
        ("table_count", profile_a.structural.table_count, profile_b.structural.table_count),
        ("list_item_count", profile_a.structural.list_item_count, profile_b.structural.list_item_count),
    ]

    scores: list[float] = []
    for _, left_value, right_value in metrics:
        if left_value == 0 and right_value == 0:
            scores.append(1.0)
            continue
        if left_value == 0 or right_value == 0:
            scores.append(0.5)
            continue

        max_value = max(left_value, right_value)
        if max_value == 0:
            scores.append(1.0)
            continue

        relative_gap = abs(left_value - right_value) / max_value
        if relative_gap <= 0.20:
            scores.append(1.0)
        else:
            scores.append(_clamp(1.0 - relative_gap))

    if not scores:
        return 1.0
    return _clamp(sum(scores) / len(scores))


def block_sequence_similarity(profile_a: DocumentProfile, profile_b: DocumentProfile) -> float:
    """Compare block_type_sequence using normalized Levenshtein similarity."""
    left = profile_a.structural.block_type_sequence
    right = profile_b.structural.block_type_sequence

    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0

    rows = [[0 for _ in range(len(right) + 1)] for _ in range(len(left) + 1)]
    for i in range(len(left) + 1):
        rows[i][0] = i
    for j in range(len(right) + 1):
        rows[0][j] = j

    for i in range(1, len(left) + 1):
        for j in range(1, len(right) + 1):
            cost = 0 if left[i - 1] == right[j - 1] else 1
            rows[i][j] = min(
                rows[i - 1][j] + 1,
                rows[i][j - 1] + 1,
                rows[i - 1][j - 1] + cost,
            )

    max_len = max(len(left), len(right))
    if max_len == 0:
        return 1.0
    similarity = 1.0 - (rows[len(left)][len(right)] / max_len)
    return _clamp(similarity)


def heading_distribution_similarity(profile_a: DocumentProfile, profile_b: DocumentProfile) -> float:
    """Compare heading-level distributions between profiles."""
    left = profile_a.structural.heading_levels
    right = profile_b.structural.heading_levels

    if not left and not right:
        return 1.0

    levels = sorted(set(left) | set(right))
    if not levels:
        return 1.0

    left_total = sum(left.values())
    right_total = sum(right.values())
    if left_total == 0 and right_total == 0:
        return 1.0
    if left_total == 0 or right_total == 0:
        return 0.5

    left_vector = [left.get(level, 0) / left_total for level in levels]
    right_vector = [right.get(level, 0) / right_total for level in levels]

    dot_product = sum(a * b for a, b in zip(left_vector, right_vector))
    left_norm = sum(value * value for value in left_vector) ** 0.5
    right_norm = sum(value * value for value in right_vector) ** 0.5

    if left_norm == 0.0 and right_norm == 0.0:
        return 1.0
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.5

    similarity = dot_product / (left_norm * right_norm)
    return _clamp(similarity)


def section_count_similarity(profile_a: DocumentProfile, profile_b: DocumentProfile) -> float:
    """Compare the number of detected sections using a tolerant difference metric."""
    left_count = len(profile_a.sections)
    right_count = len(profile_b.sections)

    if left_count == 0 and right_count == 0:
        return 1.0
    if left_count == 0 or right_count == 0:
        return 0.5 if left_count + right_count > 0 else 1.0

    deviation = abs(left_count - right_count)
    if deviation <= 1:
        return 1.0

    max_count = max(left_count, right_count)
    if max_count == 0:
        return 1.0
    return _clamp(1.0 - (deviation / max_count))


def section_structure_similarity(profile_a: DocumentProfile, profile_b: DocumentProfile) -> float:
    """Compare section arrangement using heading-level sequence and section-size patterns."""
    left_sections = profile_a.sections
    right_sections = profile_b.sections

    if not left_sections and not right_sections:
        return 1.0
    if not left_sections or not right_sections:
        return 0.5

    left_levels = [section.heading_level if section.heading_level is not None else 0 for section in left_sections]
    right_levels = [section.heading_level if section.heading_level is not None else 0 for section in right_sections]
    left_sizes = [section.block_count for section in left_sections]
    right_sizes = [section.block_count for section in right_sections]

    if not left_levels and not right_levels:
        left_levels = [0] * len(left_sections)
        right_levels = [0] * len(right_sections)

    # 1) Heading-level sequence similarity: captures arrangement, not just count.
    max_len = max(len(left_levels), len(right_levels))
    if max_len == 0:
        level_similarity = 1.0
    else:
        edit_distance = 0
        first = left_levels[:]
        second = right_levels[:]
        if len(first) < len(second):
            first.extend([0] * (len(second) - len(first)))
        elif len(second) < len(first):
            second.extend([0] * (len(first) - len(second)))

        for left_level, right_level in zip(first, second):
            if left_level != right_level:
                edit_distance += 1

        level_similarity = 1.0 - (edit_distance / max_len)

    # 2) Section-size pattern similarity: captures relative size distribution.
    if not left_sizes and not right_sizes:
        size_similarity = 1.0
    elif not left_sizes or not right_sizes:
        size_similarity = 0.5
    else:
        left_avg = sum(left_sizes) / len(left_sizes)
        right_avg = sum(right_sizes) / len(right_sizes)
        if left_avg == 0 and right_avg == 0:
            size_similarity = 1.0
        elif left_avg == 0 or right_avg == 0:
            size_similarity = 0.5
        else:
            relative_gap = abs(left_avg - right_avg) / max(left_avg, right_avg)
            size_similarity = _clamp(1.0 - relative_gap)

    return _clamp((level_similarity + size_similarity) / 2.0)


def vocabulary_overlap(profile_a: DocumentProfile, profile_b: DocumentProfile) -> float:
    """Compare vocabulary overlap using normalized Jaccard similarity."""
    left_vocab = profile_a.content.vocabulary
    right_vocab = profile_b.content.vocabulary

    if not left_vocab and not right_vocab:
        return 1.0
    if not left_vocab or not right_vocab:
        return 0.0

    return _jaccard_similarity(left_vocab.keys(), right_vocab.keys())


def heading_vocabulary_similarity(profile_a: DocumentProfile, profile_b: DocumentProfile) -> float:
    """Compare heading text vocabulary with explicit empty-case behavior."""
    left_headings = profile_a.content.heading_texts
    right_headings = profile_b.content.heading_texts

    if not left_headings and not right_headings:
        return 1.0
    if not left_headings or not right_headings:
        return 0.5

    normalized_left = {token.lower().strip() for heading in left_headings for token in heading.split() if token.strip()}
    normalized_right = {token.lower().strip() for heading in right_headings for token in heading.split() if token.strip()}
    if not normalized_left and not normalized_right:
        return 1.0
    if not normalized_left or not normalized_right:
        return 0.5

    return _jaccard_similarity(normalized_left, normalized_right)


def table_structure_similarity(profile_a: DocumentProfile, profile_b: DocumentProfile) -> float:
    """Compare tables with explicit no-table and one-table behavior."""
    left_has_tables = profile_a.structural.table_count > 0 or bool(profile_a.structural.table_dimensions)
    right_has_tables = profile_b.structural.table_count > 0 or bool(profile_b.structural.table_dimensions)

    if not left_has_tables and not right_has_tables:
        return 1.0
    if left_has_tables and right_has_tables:
        left_dimensions = profile_a.structural.table_dimensions
        right_dimensions = profile_b.structural.table_dimensions

        if not left_dimensions and not right_dimensions:
            return 1.0
        if not left_dimensions or not right_dimensions:
            return 0.5

        left_count = profile_a.structural.table_count
        right_count = profile_b.structural.table_count
        count_similarity = 1.0 if left_count == right_count else _clamp(1.0 - abs(left_count - right_count) / max(left_count, right_count))

        left_avg_rows = profile_a.structural.avg_table_rows or 0.0
        right_avg_rows = profile_b.structural.avg_table_rows or 0.0
        left_avg_cols = profile_a.structural.avg_table_cols or 0.0
        right_avg_cols = profile_b.structural.avg_table_cols or 0.0

        row_similarity = 1.0 if left_avg_rows == 0.0 and right_avg_rows == 0.0 else (
            0.5 if left_avg_rows == 0.0 or right_avg_rows == 0.0 else _clamp(1.0 - abs(left_avg_rows - right_avg_rows) / max(left_avg_rows, right_avg_rows))
        )
        col_similarity = 1.0 if left_avg_cols == 0.0 and right_avg_cols == 0.0 else (
            0.5 if left_avg_cols == 0.0 or right_avg_cols == 0.0 else _clamp(1.0 - abs(left_avg_cols - right_avg_cols) / max(left_avg_cols, right_avg_cols))
        )

        return _clamp((count_similarity + row_similarity + col_similarity) / 3.0)

    return 0.3


def document_length_similarity(profile_a: DocumentProfile, profile_b: DocumentProfile) -> float:
    """Compare document lengths with a deterministic tolerance-based similarity measure."""
    left_length = profile_a.content.total_text_length
    right_length = profile_b.content.total_text_length

    if left_length == 0 and right_length == 0:
        return 1.0
    if left_length == 0 or right_length == 0:
        return 0.2

    max_length = max(left_length, right_length)
    relative_diff = abs(left_length - right_length) / max_length

    tolerance = 0.25
    if relative_diff <= tolerance:
        return 1.0

    similarity = 1.0 - ((relative_diff - tolerance) / (1.0 - tolerance))
    return _clamp(similarity)
