"""PRISMA-style reporting checklist, mapped to anchor text we can locate in
the exported PDF. Each item's `anchor_text` must be a string that appears
ONCE, verbatim, in the rendered document — used to find its real page
number via pymupdf's text search, not a hand-typed guess."""

CHECKLIST_ITEMS = [
    {
        "item": "Title",
        "description": "Identify the report as a systematic review",
        "anchor_text": "Effectiveness of Lifestyle Interventions for Type 2 Diabetes Remission",
    },
    {
        "item": "Abstract",
        "description": "Structured summary of background, methods, results",
        "anchor_text": "Type 2 diabetes remission through lifestyle intervention has gained clinical interest",
    },
    {
        "item": "Search strategy",
        "description": "Full search strategy for at least one database",
        "anchor_text": "Search Strategy Appendix",
    },
    {
        "item": "Study selection process",
        "description": "Methods used to decide study eligibility",
        "anchor_text": "We searched multiple databases for relevant studies",
    },
    {
        "item": "Study flow diagram",
        "description": "Flow diagram of the study selection process",
        "anchor_text": "Study flow diagram",  # matches "Figure: Study flow diagram" in the actual export
    },
    {
        "item": "Results of individual studies",
        "description": "Characteristics and results for each included study",
        "anchor_text": "Alvarez 2021",
    },
    {
        "item": "Risk of bias assessment",
        "description": "Risk-of-bias assessment for each included study",
        "anchor_text": "Risk of Bias Summary",
    },
    {
        "item": "Discussion",
        "description": "General interpretation of results",
        "anchor_text": "The findings suggest lifestyle interventions may support diabetes remission",
    },
]
