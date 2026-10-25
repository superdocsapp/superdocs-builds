from html import escape


def _chunk(
    tag: str,
    content: str,
    chunk_id: str,
) -> str:

    if tag in {"hr", "br", "img"}:
        return (
            f'<{tag} '
            f'data-chunk-id="{escape(chunk_id)}">'
        )

    return (
        f'<{tag} '
        f'data-chunk-id="{escape(chunk_id)}">'
        f"{content}"
        f"</{tag}>"
    )


def build_transmittal_content(
    project: dict,
    submittal: dict,
    findings: list[dict],
    reviewer: str,
) -> str:

    parts: list[str] = []

    parts.append(
        "<!DOCTYPE html>"
    )

    parts.append(
        "<html>"
    )

    parts.append(
        "<head>"
        "<meta charset='utf-8'>"
        "<title>Submittal Transmittal</title>"
        "</head>"
    )

    parts.append("<body>")

    # --------------------------------------------------------
    # Cover
    # --------------------------------------------------------

    parts.append(
        _chunk(
            "h1",
            "TRANSMITTAL PACKET",
            "cover-title",
        )
    )

    parts.append(
        _chunk(
            "p",
            (
                f"<strong>Project:</strong> "
                f"{escape(project['name'])}"
            ),
            "project-name",
        )
    )

    parts.append(
        _chunk(
            "p",
            (
                f"<strong>Project Number:</strong> "
                f"{escape(project['project_number'])}"
            ),
            "project-number",
        )
    )

    parts.append(
        _chunk(
            "p",
            (
                f"<strong>Submittal:</strong> "
                f"{escape(submittal['number'])}"
            ),
            "submittal-number",
        )
    )

    parts.append(
        _chunk(
            "p",
            (
                f"<strong>Title:</strong> "
                f"{escape(submittal['title'])}"
            ),
            "submittal-title",
        )
    )

    parts.append(
        _chunk(
            "p",
            (
                f"<strong>Specification:</strong> "
                f"{escape(submittal['specification_section'])}"
            ),
            "specification-section",
        )
    )

    # --------------------------------------------------------
    # Reviewer
    # --------------------------------------------------------

    parts.append(
        _chunk(
            "h2",
            "REVIEW",
            "review-heading",
        )
    )

    parts.append(
        _chunk(
            "p",
            (
                f"<strong>Reviewer:</strong> "
                f"{escape(reviewer)}"
            ),
            "reviewer",
        )
    )

    # --------------------------------------------------------
    # Findings
    # --------------------------------------------------------

    parts.append(
        _chunk(
            "h2",
            "COMPARISON FINDINGS",
            "findings-heading",
        )
    )

    for index, finding in enumerate(
        findings,
        start=1,
    ):

        prefix = (
            f"finding-{index}"
        )

        parts.append(
            _chunk(
                "h3",
                escape(
                    finding["attribute"]
                ),
                f"{prefix}-attribute",
            )
        )

        parts.append(
            _chunk(
                "p",
                (
                    f"<strong>Requirement:</strong> "
                    f"{escape(str(finding['requirement']))}"
                ),
                f"{prefix}-requirement",
            )
        )

        parts.append(
            _chunk(
                "p",
                (
                    f"<strong>Submitted:</strong> "
                    f"{escape(str(finding['submitted_value']))}"
                ),
                f"{prefix}-submitted",
            )
        )

        parts.append(
            _chunk(
                "p",
                (
                    f"<strong>Result:</strong> "
                    f"{escape(finding['result'])}"
                ),
                f"{prefix}-result",
            )
        )

        parts.append(
            _chunk(
                "p",
                (
                    "<strong>"
                    "Specification Evidence:"
                    "</strong> "
                    f"{escape(str(finding.get('specification_evidence', '')))}"
                ),
                f"{prefix}-spec-evidence",
            )
        )

        parts.append(
            _chunk(
                "p",
                (
                    "<strong>"
                    "Submission Evidence:"
                    "</strong> "
                    f"{escape(str(finding.get('submission_evidence', '')))}"
                ),
                f"{prefix}-submission-evidence",
            )
        )

        parts.append(
            _chunk(
                "hr",
                "",
                f"{prefix}-separator",
            )
        )

        parts.append(
            _chunk(
                "p",
                (
                    "<strong>Review status:</strong> "
                    f"{escape(str(finding.get('status', '')))}"
                ),
                f"{prefix}-review-status",
            )
        )

        parts.append(
            _chunk(
                "p",
                (
                    "<strong>Reviewer comment:</strong> "
                    f"{escape(str(finding.get('reviewer_comment', '')))}"
                ),
                f"{prefix}-review-comment",
            )
        )

    parts.append(
        _chunk(
            "h2",
            "REVIEWER COMMENTS",
            "review-comments-heading",
        )
    )

    parts.append(
        _chunk(
            "p",
            (
                "The findings above were reviewed "
                "against the applicable specification "
                "and submitted product information."
            ),
            "review-comments",
        )
    )

    parts.append(
        "</body></html>"
    )

    return "".join(parts)
