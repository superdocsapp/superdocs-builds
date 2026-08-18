def detect_section_title(items):
    """
    Detect the semantic section title from sticky-note content.
    """

    texts = [
        item["text"].lower().strip()
        for item in items
        if item.get("text")
    ]

    combined = " ".join(texts)

    # ---------------------------------------------------------
    # QUESTIONS
    # ---------------------------------------------------------

    question_keywords = [
        "why ",
        "which ",
        "do customers ",
        "what ",
        "how ",
        "question",
        "prefer "
    ]

    if any(keyword in combined for keyword in question_keywords):
        return "Questions"

    # ---------------------------------------------------------
    # IDEAS / SOLUTIONS
    # ---------------------------------------------------------

    idea_keywords = [
        "add ",
        "improve ",
        "one-click",
        "implement ",
        "enable ",
        "introduce ",
        "create "
    ]

    if any(keyword in combined for keyword in idea_keywords):
        return "Ideas"

    # ---------------------------------------------------------
    # CUSTOMER PROBLEMS
    # ---------------------------------------------------------

    problem_keywords = [
        "slow",
        "fails",
        "poor",
        "abandon",
        "problem",
        "issue",
        "broken",
        "difficult",
        "error"
    ]

    if any(keyword in combined for keyword in problem_keywords):
        return "Customer Problems"

    return "Other"