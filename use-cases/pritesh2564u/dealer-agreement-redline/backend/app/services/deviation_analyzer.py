from difflib import SequenceMatcher


def normalize(text: str) -> str:
    return " ".join(text.lower().split())


def analyze_deviations(
    master_sections: list[dict],
    dealer_sections: list[dict],
) -> list[dict]:

    master_by_section = {
        item["section"]: item["text"]
        for item in master_sections
    }

    dealer_by_section = {
        item["section"]: item["text"]
        for item in dealer_sections
    }

    deviations: list[dict] = []

    for section, dealer_text in dealer_by_section.items():
        master_text = master_by_section.get(section)

        if master_text is None:
            deviations.append(
                {
                    "section": section,
                    "master_text": None,
                    "dealer_text": dealer_text,
                    "deviation_type": "added_section",
                }
            )
            continue

        if normalize(master_text) == normalize(dealer_text):
            continue

        similarity = SequenceMatcher(
            None,
            normalize(master_text),
            normalize(dealer_text),
        ).ratio()

        deviations.append(
            {
                "section": section,
                "master_text": master_text,
                "dealer_text": dealer_text,
                "deviation_type": "modified_section",
                "similarity": round(similarity, 3),
            }
        )

    for section, master_text in master_by_section.items():
        if section not in dealer_by_section:
            deviations.append(
                {
                    "section": section,
                    "master_text": master_text,
                    "dealer_text": None,
                    "deviation_type": "removed_section",
                }
            )

    return deviations