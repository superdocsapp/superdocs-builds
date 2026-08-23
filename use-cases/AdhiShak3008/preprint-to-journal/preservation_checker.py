"""
preservation_checker.py
Practical scientific-content preservation check.

Compares the original manuscript HTML against the transformed version to
identify content that may have been unintentionally changed.

WHAT THIS CHECKS:
- Numerical values (integers, decimals, percentages, scientific notation)
- Statistical markers (p-values, confidence intervals, effect sizes, n=)
- Equation content (LaTeX delimiters and <math> elements)
- Citation keys / reference numbers
- Substantive sentence-level content changes (via text fingerprinting)

WHAT THIS DOES NOT PROVE:
This checker provides a practical signal, not a guarantee. It can detect
many classes of unintended change but cannot verify that the meaning of
every sentence is preserved. Structural and formatting changes (section
reordering, reference reformatting, figure/table relocation) will appear
as differences and are expected — the checker attempts to filter these out,
but some false positives are possible.

Users must review flagged items and use their own scientific judgement.
"""

import re
from html.parser import HTMLParser


CHECKER_LIMITATION = (
    "This check compares numerical values, statistical markers, equations, "
    "and citation references between the original and transformed manuscript. "
    "It cannot verify that the meaning of every sentence is preserved. "
    "Structural changes (section reordering, reference reformatting) may "
    "produce false positives. Flagged items require human review. "
    "A clean report does not guarantee that scientific content is unchanged."
)


class _TextExtractor(HTMLParser):
    """Extract plain text from HTML, stripping all tags."""
    def __init__(self):
        super().__init__()
        self._parts = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self):
        return " ".join(self._parts)


def _extract_text(html):
    parser = _TextExtractor()
    parser.feed(html or "")
    return parser.get_text()


def _extract_numbers(text):
    """
    Extract all numeric values: integers, decimals, percentages,
    scientific notation (e.g. 1.5×10^-3, 1.5e-3).
    Returns a sorted list of strings.
    """
    pattern = r"""
        (?:
            \d+\.?\d*[eE][+\-]?\d+   # scientific notation: 1.5e-3
          | \d+\.?\d*\s*[×x]\s*10\s*[\^]?\s*[+\-]?\d+  # 1.5×10^-3
          | \d+\.\d+                  # decimal: 3.14
          | \d+%                      # percentage: 95%
          | \d+                       # integer: 42
        )
    """
    return sorted(set(re.findall(pattern, text, re.VERBOSE)))


def _extract_statistical_markers(text):
    """
    Extract statistical values: p-values, confidence intervals,
    effect sizes, sample sizes.
    """
    patterns = [
        r"p\s*[=<>≤≥]\s*[\d\.]+(?:[eE][+\-]?\d+)?",   # p=0.05, p<0.001
        r"95\s*%\s*CI\s*[\[\(][\d\.\s,\-–]+[\]\)]",     # 95% CI [x, y]
        r"n\s*=\s*\d+",                                   # n=42
        r"r\s*=\s*[\-]?\d+\.\d+",                        # r=0.85
        r"OR\s*=\s*[\d\.]+",                              # OR=1.5
        r"HR\s*=\s*[\d\.]+",                              # HR=2.1
        r"β\s*=\s*[\-]?\d+\.\d+",                        # β=0.32
        r"Cohen'?s?\s*d\s*=\s*[\-]?\d+\.\d+",            # Cohen's d=0.5
        r"F\s*\(\s*\d+\s*,\s*\d+\s*\)\s*=\s*[\d\.]+",   # F(1,48)=3.2
        r"t\s*\(\s*\d+\s*\)\s*=\s*[\-]?\d+\.\d+",       # t(48)=2.1
        r"χ²?\s*\(\s*\d+\s*\)\s*=\s*[\d\.]+",            # χ²(1)=4.5
    ]
    found = []
    for p in patterns:
        found.extend(re.findall(p, text, re.IGNORECASE))
    return sorted(set(found))


def _extract_equations(html):
    """Extract LaTeX equation content and <math> element content."""
    equations = []
    # LaTeX display math: $$...$$
    equations.extend(re.findall(r"\$\$(.+?)\$\$", html, re.DOTALL))
    # LaTeX inline math: $...$
    equations.extend(re.findall(r"\$([^$\n]+?)\$", html))
    # LaTeX \[...\] and \(...\)
    equations.extend(re.findall(r"\\\[(.+?)\\\]", html, re.DOTALL))
    equations.extend(re.findall(r"\\\((.+?)\\\)", html, re.DOTALL))
    # <math> elements
    equations.extend(re.findall(r"<math[^>]*>(.+?)</math>", html, re.DOTALL | re.IGNORECASE))
    return sorted(set(e.strip() for e in equations))


def _extract_citation_refs(text):
    """
    Extract citation reference markers.
    Handles: [1], [1,2], [1-3], (Smith et al., 2020), superscript numbers.
    """
    patterns = [
        r"\[\d+(?:[,\-]\d+)*\]",                          # [1], [1,2], [1-3]
        r"\([A-Z][a-z]+(?:\s+et\s+al\.?)?,?\s*\d{4}\)",  # (Smith et al., 2020)
        r"\([A-Z][a-z]+\s+and\s+[A-Z][a-z]+,?\s*\d{4}\)", # (Smith and Jones, 2020)
    ]
    found = []
    for p in patterns:
        found.extend(re.findall(p, text))
    return sorted(set(found))


def _extract_text_fingerprints(text, min_words=6):
    """
    Extract short n-gram fingerprints of substantive sentences.
    Used to detect sentences that were paraphrased or removed.
    Returns a set of normalised sentence fragments.
    """
    # Split on sentence boundaries
    sentences = re.split(r"(?<=[.!?])\s+", text)
    fingerprints = set()
    for sentence in sentences:
        words = sentence.strip().split()
        if len(words) >= min_words:
            # Use first 6 words as fingerprint (normalised to lowercase)
            fp = " ".join(w.lower().strip(".,;:()[]") for w in words[:6])
            fingerprints.add(fp)
    return fingerprints


def check_preservation(original_html, transformed_html):
    """
    Compare original and transformed HTML for scientific content changes.

    Returns a dict:
        numbers_original: list
        numbers_missing: list (in original but not in transformed)
        numbers_added: list (in transformed but not in original)
        stats_original: list
        stats_missing: list
        equations_original: list
        equations_missing: list
        citations_original: list
        citations_missing: list
        sentences_potentially_changed: list of fingerprints
        summary: str
        limitation_notice: str
        has_concerns: bool
    """
    orig_text = _extract_text(original_html)
    trans_text = _extract_text(transformed_html)

    orig_numbers = set(_extract_numbers(orig_text))
    trans_numbers = set(_extract_numbers(trans_text))
    numbers_missing = sorted(orig_numbers - trans_numbers)
    numbers_added = sorted(trans_numbers - orig_numbers)

    orig_stats = set(_extract_statistical_markers(orig_text))
    trans_stats = set(_extract_statistical_markers(trans_text))
    stats_missing = sorted(orig_stats - trans_stats)

    orig_eqs = set(_extract_equations(original_html))
    trans_eqs = set(_extract_equations(transformed_html))
    equations_missing = sorted(orig_eqs - trans_eqs)

    orig_cites = set(_extract_citation_refs(orig_text))
    trans_cites = set(_extract_citation_refs(trans_text))
    citations_missing = sorted(orig_cites - trans_cites)

    orig_fps = _extract_text_fingerprints(orig_text)
    trans_fps = _extract_text_fingerprints(trans_text)
    # Sentences in original that don't appear in transformed
    # (may be due to restructuring — flagged for review, not asserted as errors)
    sentences_potentially_changed = sorted(orig_fps - trans_fps)

    has_concerns = bool(
        numbers_missing
        or stats_missing
        or equations_missing
        or citations_missing
    )

    # Build summary
    lines = []
    total_checked = (
        len(orig_numbers) + len(orig_stats) +
        len(orig_eqs) + len(orig_cites)
    )
    lines.append(
        f"Checked {total_checked} scientific content markers "
        f"({len(orig_numbers)} numbers, {len(orig_stats)} statistical values, "
        f"{len(orig_eqs)} equations, {len(orig_cites)} citation references)."
    )

    if not has_concerns:
        lines.append(
            "No missing numerical values, statistical markers, equations, or "
            "citation references detected."
        )
    else:
        if numbers_missing:
            lines.append(
                f"WARNING: {len(numbers_missing)} numerical value(s) present in "
                f"the original were not found in the transformed manuscript: "
                f"{', '.join(numbers_missing[:10])}"
                + (" (and more)" if len(numbers_missing) > 10 else "")
            )
        if stats_missing:
            lines.append(
                f"WARNING: {len(stats_missing)} statistical marker(s) not found "
                f"in transformed manuscript: {', '.join(stats_missing[:5])}"
            )
        if equations_missing:
            lines.append(
                f"WARNING: {len(equations_missing)} equation(s) not found in "
                f"transformed manuscript."
            )
        if citations_missing:
            lines.append(
                f"NOTE: {len(citations_missing)} citation reference(s) changed "
                f"format or were removed — this may be expected if reference "
                f"style was reformatted."
            )

    if sentences_potentially_changed:
        lines.append(
            f"NOTE: {len(sentences_potentially_changed)} sentence-level "
            f"fingerprint(s) from the original were not found in the transformed "
            f"manuscript. This is expected for restructured sections but should "
            f"be reviewed if scientific claims may have been paraphrased."
        )

    return {
        "numbers_original": sorted(orig_numbers),
        "numbers_missing": numbers_missing,
        "numbers_added": numbers_added,
        "stats_original": sorted(orig_stats),
        "stats_missing": stats_missing,
        "equations_original": sorted(orig_eqs),
        "equations_missing": equations_missing,
        "citations_original": sorted(orig_cites),
        "citations_missing": citations_missing,
        "sentences_potentially_changed": sentences_potentially_changed[:20],
        "summary": " ".join(lines),
        "limitation_notice": CHECKER_LIMITATION,
        "has_concerns": has_concerns,
    }
