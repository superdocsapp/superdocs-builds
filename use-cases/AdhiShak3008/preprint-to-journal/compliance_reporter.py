"""
compliance_reporter.py
Map journal profile requirements to met/unmet/unverifiable statuses
based on the transformed manuscript HTML.

Honest reporting rules:
- Never claim compliance for something that cannot be verified programmatically.
- 'instruction_sent' means the AI was instructed to apply this requirement;
  manual verification is recommended.
- 'unmet' means the requirement was checked and found not to be satisfied.
- 'met' means the requirement was checked and found to be satisfied.
- 'unverifiable' means the requirement cannot be checked from the HTML alone.
"""

import re
from html.parser import HTMLParser


class _HeadingExtractor(HTMLParser):
    """Extract heading text and levels from HTML."""
    def __init__(self):
        super().__init__()
        self._headings = []
        self._current_level = None
        self._current_text = []

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._current_level = int(tag[1])
            self._current_text = []

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if self._current_level is not None:
                self._headings.append({
                    "level": self._current_level,
                    "text": " ".join(self._current_text).strip(),
                })
            self._current_level = None
            self._current_text = []

    def handle_data(self, data):
        if self._current_level is not None:
            self._current_text.append(data)

    def get_headings(self):
        return self._headings


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self):
        return " ".join(self._parts)


def _extract_headings(html):
    p = _HeadingExtractor()
    p.feed(html or "")
    return p.get_headings()


def _extract_text(html):
    p = _TextExtractor()
    p.feed(html or "")
    return p.get_text()


def _count_words(text):
    return len(text.split())


def _heading_texts(html):
    return [h["text"].lower() for h in _extract_headings(html)]


def _section_present(html, section_name):
    """Check if a section heading matching section_name exists in the HTML."""
    headings = _heading_texts(html)
    target = section_name.lower()
    return any(target in h or h in target for h in headings)


def build_report(profile, transformed_html, blinding_result=None):
    """
    Build a compliance report for the transformed manuscript.

    Returns a list of requirement dicts, each with:
        requirement: str (human-readable name)
        status: 'met' | 'unmet' | 'unverifiable' | 'instruction_sent' | 'partial'
        detail: str (explanation)
    """
    report = []
    text = _extract_text(transformed_html)

    # 1. Section order
    section_order = profile.get("section_order", [])
    if section_order:
        headings = _heading_texts(transformed_html)
        missing_sections = [
            s for s in section_order
            if not any(s.lower() in h or h in s.lower() for h in headings)
        ]
        if not missing_sections:
            report.append({
                "requirement": "Section structure",
                "status": "instruction_sent",
                "detail": (
                    f"All {len(section_order)} required sections were found in "
                    f"the transformed manuscript. Section ordering was applied "
                    f"by the AI — verify the order visually."
                ),
            })
        else:
            report.append({
                "requirement": "Section structure",
                "status": "partial",
                "detail": (
                    f"The following required sections were not found in the "
                    f"transformed manuscript: "
                    f"{', '.join(missing_sections)}. "
                    f"These sections may be missing from the original manuscript "
                    f"or may use different heading names."
                ),
            })

    # 2. Reference style
    report.append({
        "requirement": f"Reference style ({profile.get('reference_style', 'unknown')})",
        "status": "instruction_sent",
        "detail": (
            f"The AI was instructed to apply {profile['name']} reference "
            f"formatting ({profile.get('reference_style_description', profile.get('reference_style', ''))}). "
            f"Reference formatting cannot be reliably verified programmatically. "
            f"Manual review of the reference list is required."
        ),
    })

    # 3. Figure placement
    fig_placement = profile.get("figure_placement", "")
    fig_present = bool(re.search(
        r"<\s*figure|fig(?:ure)?\s*\d|fig\s*\.|figure\s*legend",
        transformed_html, re.IGNORECASE
    ))
    if fig_present:
        report.append({
            "requirement": f"Figure placement ({fig_placement})",
            "status": "instruction_sent",
            "detail": (
                f"Figures were detected in the manuscript. The AI was instructed "
                f"to place them: {profile.get('figure_placement_description', fig_placement)}. "
                f"Verify figure placement visually."
            ),
        })
    else:
        report.append({
            "requirement": f"Figure placement ({fig_placement})",
            "status": "unverifiable",
            "detail": "No figures detected in the manuscript HTML.",
        })

    # 4. Table placement
    tbl_placement = profile.get("table_placement", "")
    tbl_present = bool(re.search(r"<\s*table", transformed_html, re.IGNORECASE))
    if tbl_present:
        report.append({
            "requirement": f"Table placement ({tbl_placement})",
            "status": "instruction_sent",
            "detail": (
                f"Tables were detected in the manuscript. The AI was instructed "
                f"to place them: {profile.get('table_placement_description', tbl_placement)}. "
                f"Verify table placement visually."
            ),
        })
    else:
        report.append({
            "requirement": f"Table placement ({tbl_placement})",
            "status": "unverifiable",
            "detail": "No tables detected in the manuscript HTML.",
        })

    # 5. Word limit
    word_limit = profile.get("word_limit")
    if word_limit:
        word_count = _count_words(text)
        if word_count <= word_limit:
            report.append({
                "requirement": f"Word limit ({word_limit} words)",
                "status": "met",
                "detail": (
                    f"Manuscript is approximately {word_count} words "
                    f"(limit: {word_limit}). Note: word count includes all "
                    f"text in the HTML and may differ from the journal's "
                    f"counting method."
                ),
            })
        else:
            report.append({
                "requirement": f"Word limit ({word_limit} words)",
                "status": "unmet",
                "detail": (
                    f"Manuscript is approximately {word_count} words, which "
                    f"exceeds the {word_limit}-word limit by approximately "
                    f"{word_count - word_limit} words. Manual reduction is "
                    f"required. Scientific content must not be deleted to meet "
                    f"the limit."
                ),
            })
    else:
        report.append({
            "requirement": "Word limit",
            "status": "met",
            "detail": f"{profile['name']} does not specify a main-text word limit.",
        })

    # 6. Abstract word limit
    abstract_limit = profile.get("abstract_word_limit")
    if abstract_limit:
        # Try to find abstract section text
        abstract_match = re.search(
            r"(?:abstract|summary)[^<]*</h\d>(.*?)(?=<h\d|$)",
            transformed_html, re.IGNORECASE | re.DOTALL
        )
        if abstract_match:
            abstract_text = _extract_text(abstract_match.group(1))
            abstract_words = _count_words(abstract_text)
            if abstract_words <= abstract_limit:
                report.append({
                    "requirement": f"Abstract word limit ({abstract_limit} words)",
                    "status": "met",
                    "detail": f"Abstract is approximately {abstract_words} words.",
                })
            else:
                report.append({
                    "requirement": f"Abstract word limit ({abstract_limit} words)",
                    "status": "unmet",
                    "detail": (
                        f"Abstract is approximately {abstract_words} words, "
                        f"exceeding the {abstract_limit}-word limit. "
                        f"Manual reduction required."
                    ),
                })
        else:
            report.append({
                "requirement": f"Abstract word limit ({abstract_limit} words)",
                "status": "unverifiable",
                "detail": "Abstract section could not be located for word counting.",
            })

    # 7. Required declarations
    declarations = profile.get("required_declarations", [])
    decl_descriptions = profile.get("declaration_descriptions", {})
    for decl in declarations:
        decl_heading = decl.replace("_", " ").title()
        # Check for placeholder (missing) or actual content
        placeholder_pattern = r"\[DECLARATION REQUIRED"
        if re.search(placeholder_pattern, transformed_html, re.IGNORECASE):
            report.append({
                "requirement": f"Declaration: {decl_heading}",
                "status": "unmet",
                "detail": (
                    f"A placeholder was inserted for the '{decl_heading}' "
                    f"declaration. This must be completed before submission. "
                    f"Required: {decl_descriptions.get(decl, 'See journal guidelines.')}"
                ),
            })
        elif _section_present(transformed_html, decl_heading):
            report.append({
                "requirement": f"Declaration: {decl_heading}",
                "status": "met",
                "detail": f"'{decl_heading}' section found in manuscript.",
            })
        else:
            # Also check for common alternative headings
            alt_names = {
                "competing_interests": ["conflict of interest", "conflicts of interest",
                                        "competing interests"],
                "data_availability": ["data availability", "data access",
                                      "availability of data"],
                "author_contributions": ["author contributions", "contributions"],
                "funding": ["funding", "funding statement", "financial support"],
            }
            alts = alt_names.get(decl, [])
            found_alt = any(_section_present(transformed_html, alt) for alt in alts)
            if found_alt:
                report.append({
                    "requirement": f"Declaration: {decl_heading}",
                    "status": "met",
                    "detail": (
                        f"'{decl_heading}' section found (possibly under an "
                        f"alternative heading)."
                    ),
                })
            else:
                report.append({
                    "requirement": f"Declaration: {decl_heading}",
                    "status": "unmet",
                    "detail": (
                        f"'{decl_heading}' declaration not found in the "
                        f"transformed manuscript. This is required by "
                        f"{profile['name']}. "
                        f"Required content: "
                        f"{decl_descriptions.get(decl, 'See journal guidelines.')}"
                    ),
                })

    # 8. Blinding
    if profile.get("blinded_review"):
        if blinding_result:
            removed = blinding_result.get("items_removed", [])
            remaining = blinding_result.get("potential_remaining", [])
            if removed and not remaining:
                report.append({
                    "requirement": "Blinding (double-blind review)",
                    "status": "met",
                    "detail": (
                        f"Blinding applied: {len(removed)} category(ies) of "
                        f"identifying information removed. No obvious remaining "
                        f"identifiers detected. Manual review is still required."
                    ),
                })
            elif removed and remaining:
                report.append({
                    "requirement": "Blinding (double-blind review)",
                    "status": "partial",
                    "detail": (
                        f"Blinding applied: {len(removed)} category(ies) removed. "
                        f"However, {len(remaining)} potential identifier(s) may "
                        f"remain. Manual review required: "
                        f"{'; '.join(remaining[:3])}"
                        + (" (and more)" if len(remaining) > 3 else "")
                    ),
                })
            else:
                report.append({
                    "requirement": "Blinding (double-blind review)",
                    "status": "unverifiable",
                    "detail": (
                        "Blinding was instructed but no blinding placeholders "
                        "were detected in the output. Manual review required."
                    ),
                })
        else:
            report.append({
                "requirement": "Blinding (double-blind review)",
                "status": "instruction_sent",
                "detail": (
                    "Blinding instructions were sent to the AI. "
                    "Manual review of the manuscript is required to confirm "
                    "all identifying information has been removed."
                ),
            })
    else:
        report.append({
            "requirement": "Blinding",
            "status": "met",
            "detail": f"{profile['name']} does not require blinded review.",
        })

    return report


def summarise_report(report):
    """
    Return counts of each status type and an overall assessment string.
    """
    counts = {"met": 0, "unmet": 0, "partial": 0,
              "instruction_sent": 0, "unverifiable": 0}
    for item in report:
        status = item.get("status", "unverifiable")
        counts[status] = counts.get(status, 0) + 1

    if counts["unmet"] == 0 and counts["partial"] == 0:
        overall = "All verifiable requirements satisfied or instructed."
    elif counts["unmet"] > 0:
        overall = (
            f"{counts['unmet']} requirement(s) unmet — manual action required "
            f"before submission."
        )
    else:
        overall = (
            f"{counts['partial']} requirement(s) partially satisfied — "
            f"review recommended."
        )

    return {"counts": counts, "overall": overall}
