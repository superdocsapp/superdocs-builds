import re


def extract_section_number(section: str) -> str | None:
    """
    Extract the numeric section identifier.

    Examples:
        Section 7.1 — AgreementTerm -> 7.1
        Section 9.3— Territory       -> 9.3
        Section 12.1 — Termination  -> 12.1
    """
    match = re.search(
        r"section\s+(\d+(?:\.\d+)*)",
        section,
        re.IGNORECASE,
    )

    if not match:
        return None

    return match.group(1)


def classify_deviation(
    deviation: dict,
) -> dict:

    section = deviation["section"]
    dealer_text = (
        deviation.get("dealer_text") or ""
    ).lower()

    section_number = extract_section_number(section)

    classification = "ESCALATE"
    reason = "The change requires human review."
    counter_position = (
        "Maintain the approved master agreement language."
    )

    # --------------------------------------------------
    # Section 4.2 — Payment Terms
    # --------------------------------------------------

    if section_number == "4.2":

        match = re.search(
            r"(\d+)\s*days",
            dealer_text,
        )

        if match:
            days = int(match.group(1))

            if days <= 45:
                classification = "PRE-APPROVED"
                reason = (
                    "The playbook permits payment terms "
                    "up to 45 days."
                )
                counter_position = (
                    f"Accept payment terms of {days} days."
                )

            else:
                classification = "ESCALATE"
                reason = (
                    "The dealer requested payment terms "
                    "above the 45-day pre-approved limit."
                )
                counter_position = (
                    "Maintain the standard 30-day payment "
                    "term or escalate the requested "
                    f"{days}-day term for approval."
                )

    # --------------------------------------------------
    # Section 7.1 — Agreement Term
    # --------------------------------------------------

    elif section_number == "7.1":

        year_match = re.search(
            r"(\d+)\s*years?",
            dealer_text,
        )

        if year_match:
            years = int(year_match.group(1))

        else:
            word_to_number = {
                "one": 1,
                "two": 2,
                "three": 3,
                "four": 4,
                "five": 5,
                "six": 6,
                "seven": 7,
                "eight": 8,
                "nine": 9,
                "ten": 10,
                "eleven": 11,
                "twelve": 12,
                "thirteen": 13,
                "fourteen": 14,
                "fifteen": 15,
            }

            years = None

            for word, value in word_to_number.items():
                if re.search(
                    rf"\b{word}\s+years?\b",
                    dealer_text,
                ):
                    years = value
                    break

        if years is not None:

            if years <= 7:
                classification = "PRE-APPROVED"

                reason = (
                    "The playbook permits agreement terms "
                    "up to 7 years."
                )

                counter_position = (
                    f"Accept the {years}-year agreement term."
                )

            else:
                classification = "REFUSE"

                reason = (
                    "The requested agreement term exceeds "
                    "the 7-year playbook limit."
                )

                counter_position = (
                    "Maintain the approved five-year "
                    "initial agreement term."
                )
    
    # --------------------------------------------------
    # Section 9.3 — Territory
    # --------------------------------------------------

    elif section_number == "9.3":

        if (
            "outside" in dealer_text
            or "expand" in dealer_text
        ):
            classification = "ESCALATE"
            reason = (
                "The dealer requests an expansion "
                "of territory rights."
            )
            counter_position = (
                "Maintain the assigned territory unless "
                "the requested expansion is approved "
                "through escalation."
            )

    # --------------------------------------------------
    # Section 12.1 — Termination
    # --------------------------------------------------

    elif section_number == "12.1":

        match = re.search(
            r"(\d+)\s*days",
            dealer_text,
        )

        if match:
            days = int(match.group(1))

            if days > 60:
                classification = "REFUSE"
                reason = (
                    "The requested termination notice "
                    "period exceeds the 60-day limit."
                )
                counter_position = (
                    "Maintain the approved 30-day "
                    "termination notice period."
                )

            else:
                classification = "ESCALATE"
                reason = (
                    "The termination notice change "
                    "requires review."
                )
                counter_position = (
                    "Review the requested termination "
                    "notice period before acceptance."
                )

    return {
        **deviation,
        "classification": classification,
        "reason": reason,
        "counter_position": counter_position,
    }