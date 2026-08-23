"""
blinding.py
Build blinding instructions and analyse blinding coverage.

Blinding is applied when a journal profile has blinded_review=True.
The instruction tells SuperDocs what to redact; this module also provides
a post-transformation analysis that flags items that may still identify
the authors.

LIMITATION NOTICE (shown to users):
Automated blinding is not infallible. The system attempts to identify and
remove author-identifying information, but it cannot guarantee complete
anonymisation. Users must review the blinding result before submission.
"""

import re

BLINDING_LIMITATION = (
    "IMPORTANT: Automated blinding is not infallible. This tool has attempted "
    "to remove identifying information, but it cannot guarantee complete "
    "anonymisation. You must review the blinded manuscript carefully before "
    "submission. Pay particular attention to: self-citations, institutional "
    "acknowledgements, funding body names, and any language that implicitly "
    "identifies the authors or their institution."
)


def build_blinding_instruction(author_info=None):
    """
    Build the blinding section of the transformation instruction.

    author_info: optional dict with:
        'names': list of author name strings
        'affiliations': list of affiliation strings

    Returns a string to be appended to the main transformation instruction.
    """
    parts = [
        "**BLINDING FOR DOUBLE-BLIND PEER REVIEW**",
        "This journal uses double-blind peer review. Apply the following "
        "blinding transformations:",
        "",
        "1. **Author names**: Remove all author names from the title page, "
        "author list, and any other location in the manuscript. Replace with "
        "'[AUTHOR REMOVED]'.",
        "",
        "2. **Affiliations**: Remove all institutional affiliations. Replace "
        "with '[AFFILIATION REMOVED]'.",
        "",
        "3. **Acknowledgements section**: Remove the entire content of the "
        "Acknowledgements section and replace it with: "
        "'[ACKNOWLEDGEMENTS REMOVED FOR BLIND REVIEW — to be restored before "
        "final submission]'.",
        "",
        "4. **Funding information**: Remove all specific funding body names, "
        "grant numbers, and award identifiers from the Acknowledgements, "
        "Funding, and Declarations sections. Replace with "
        "'[FUNDING DETAILS REMOVED FOR BLIND REVIEW]'.",
        "",
        "5. **Self-citations**: Identify references in the reference list that "
        "appear to be authored by the same authors as this manuscript "
        "(look for matching author surnames in the reference list). Replace "
        "the full reference entry with '[SELF-CITATION REMOVED FOR BLIND "
        "REVIEW]' and replace the corresponding in-text citation with "
        "'[CITATION REMOVED]'. Flag each removed self-citation with a comment "
        "noting the original reference number or key.",
        "",
        "6. **Self-identifying language**: Identify and neutralise phrases that "
        "implicitly identify the authors, such as: 'in our previous work', "
        "'as we showed', 'our group', 'our lab', 'our earlier study', "
        "'we previously reported', 'our institution', 'in our laboratory'. "
        "Replace with neutral third-person alternatives such as 'in previous "
        "work [CITATION REMOVED]', 'as shown previously', 'prior research'. "
        "Flag each change with a comment '[SELF-IDENTIFYING LANGUAGE REMOVED]'.",
        "",
        "7. **Corresponding author contact details**: Remove email addresses, "
        "phone numbers, and postal addresses of authors. Replace with "
        "'[CONTACT DETAILS REMOVED FOR BLIND REVIEW]'.",
    ]

    if author_info:
        names = author_info.get("names", [])
        affiliations = author_info.get("affiliations", [])
        if names:
            name_list = ", ".join(f"'{n}'" for n in names)
            parts.append(
                f"\nKnown author names to remove: {name_list}. "
                "Search for these names throughout the document including "
                "in the reference list."
            )
        if affiliations:
            affil_list = ", ".join(f"'{a}'" for a in affiliations)
            parts.append(
                f"Known affiliations to remove: {affil_list}."
            )

    return "\n".join(parts)


def analyse_blinding(html_content, author_info=None):
    """
    Analyse the transformed HTML for remaining identifying information.

    Returns a dict:
        items_removed: list of strings describing what was removed/replaced
        potential_remaining: list of strings describing items that may still
                             identify the authors
        limitation_notice: str
    """
    items_removed = []
    potential_remaining = []

    # Check for blinding placeholders that were inserted
    placeholder_patterns = [
        (r"\[AUTHOR REMOVED\]", "Author name placeholder found"),
        (r"\[AFFILIATION REMOVED\]", "Affiliation placeholder found"),
        (r"\[ACKNOWLEDGEMENTS REMOVED FOR BLIND REVIEW", "Acknowledgements removed"),
        (r"\[FUNDING DETAILS REMOVED FOR BLIND REVIEW\]", "Funding details removed"),
        (r"\[SELF-CITATION REMOVED FOR BLIND REVIEW\]", "Self-citation(s) removed"),
        (r"\[CITATION REMOVED\]", "In-text self-citation(s) removed"),
        (r"\[SELF-IDENTIFYING LANGUAGE REMOVED\]", "Self-identifying language removed"),
        (r"\[CONTACT DETAILS REMOVED FOR BLIND REVIEW\]", "Contact details removed"),
    ]
    for pattern, description in placeholder_patterns:
        matches = re.findall(pattern, html_content, re.IGNORECASE)
        if matches:
            items_removed.append(f"{description} ({len(matches)} instance(s))")

    # Check for potentially remaining identifying information
    risk_patterns = [
        (r"our\s+(lab|group|institution|university|department|laboratory)",
         "Possible self-identifying language: 'our group/lab/institution'"),
        (r"\bin our (previous|prior|earlier|recent) (work|study|paper|publication|research)\b",
         "Possible self-identifying language: 'in our previous work'"),
        (r"\bwe (previously|earlier|recently) (reported|showed|demonstrated|found|published)\b",
         "Possible self-identifying language: 'we previously reported/showed'"),
        (r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
         "Possible email address remaining"),
    ]
    for pattern, description in risk_patterns:
        matches = re.findall(pattern, html_content, re.IGNORECASE)
        if matches:
            potential_remaining.append(
                f"{description} ({len(matches)} instance(s))"
            )

    # Check for known author names if provided
    if author_info:
        for name in author_info.get("names", []):
            # Check surname only (first word of name or last word)
            parts = name.strip().split()
            for part in parts:
                if len(part) > 2:
                    count = len(re.findall(
                        rf"\b{re.escape(part)}\b", html_content, re.IGNORECASE
                    ))
                    if count > 0:
                        potential_remaining.append(
                            f"Author name fragment '{part}' may still appear "
                            f"({count} instance(s)) — check reference list and body"
                        )

    return {
        "items_removed": items_removed,
        "potential_remaining": potential_remaining,
        "limitation_notice": BLINDING_LIMITATION,
    }
