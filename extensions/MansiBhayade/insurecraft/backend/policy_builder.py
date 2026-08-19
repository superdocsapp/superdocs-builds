from typing import List, Dict


def build_policy_document(data: Dict) -> str:

    named_insured = data.get("named_insured", "")
    policy_number = data.get("policy_number", "")
    territory = data.get("territory", "")
    effective_date = data.get("effective_date", "")
    expiry_date = data.get("expiry_date", "")

    liability_limit = data.get(
        "liability_limit",
        ""
    )

    deductible = data.get(
        "deductible",
        ""
    )

    coverage_forms: List[str] = data.get(
        "coverage_forms",
        []
    )

    endorsements: List[str] = data.get(
        "endorsements",
        []
    )

    html = []

    html.append(
        "<h1 data-chunk-id=\"policy-title\">"
        "Insurance Policy"
        "</h1>"
    )

    html.append(
        "<h2 data-chunk-id=\"schedule-title\">"
        "Policy Schedule"
        "</h2>"
    )

    html.append(
        f"<p data-chunk-id=\"named-insured\">"
        f"<strong>Named Insured:</strong> "
        f"{named_insured}</p>"
    )

    html.append(
        f"<p data-chunk-id=\"policy-number\">"
        f"<strong>Policy Number:</strong> "
        f"{policy_number}</p>"
    )

    html.append(
        f"<p data-chunk-id=\"territory\">"
        f"<strong>Territory:</strong> "
        f"{territory}</p>"
    )

    html.append(
        f"<p data-chunk-id=\"effective-date\">"
        f"<strong>Effective Date:</strong> "
        f"{effective_date}</p>"
    )

    html.append(
        f"<p data-chunk-id=\"expiry-date\">"
        f"<strong>Expiry Date:</strong> "
        f"{expiry_date}</p>"
    )

    html.append(
        f"<p data-chunk-id=\"liability-limit\">"
        f"<strong>Liability Limit:</strong> "
        f"{liability_limit}</p>"
    )

    html.append(
        f"<p data-chunk-id=\"deductible\">"
        f"<strong>Deductible:</strong> "
        f"{deductible}</p>"
    )

    html.append(
        "<h2 data-chunk-id=\"coverage-title\">"
        "Coverage Forms"
        "</h2>"
    )

    for index, form in enumerate(coverage_forms):

        html.append(
            f"<p data-chunk-id=\"coverage-{index}\">"
            f"{index + 1}. {form}"
            f"</p>"
        )

    html.append(
        "<h2 data-chunk-id=\"endorsement-title\">"
        "Attached Endorsements"
        "</h2>"
    )

    for index, endorsement in enumerate(endorsements):

        html.append(
            f"<p data-chunk-id=\"endorsement-{index}\">"
            f"{index + 1}. {endorsement}"
            f"</p>"
        )

    return "\n".join(html)


def build_endorsement_instruction(
    endorsement_name: str,
    existing_wording: str,
    amendment_instruction: str
) -> str:

    return f"""
Draft an insurance endorsement titled:

{endorsement_name}

The endorsement amends an existing in-force policy.

EXISTING POLICY WORDING
-----------------------
{existing_wording}

AMENDMENT INSTRUCTION
---------------------
{amendment_instruction}

Requirements:

1. Quote the affected existing policy wording accurately.
2. Clearly identify the wording being amended.
3. Show the replacement wording.
4. Preserve all unaffected policy terms.
5. Keep limits and deductibles numerically identical wherever referenced.
6. Clearly explain the change.
7. Do not invent policy terms.
8. Produce a professional insurance endorsement suitable for underwriter review.

Return the proposed endorsement for review and approval.
""".strip()