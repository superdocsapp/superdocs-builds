"""The single source of truth for CRediT role identifiers and display text."""

CREDIT_ROLES = {
    "conceptualization": {
        "label": "Conceptualization",
        "description": "Ideas; formulation or evolution of the overarching research goals and aims.",
    },
    "data_curation": {
        "label": "Data curation",
        "description": "Management activities to annotate, scrub, maintain, and prepare research data for initial use and later reuse.",
    },
    "formal_analysis": {
        "label": "Formal analysis",
        "description": "Application of statistical, mathematical, computational, or other formal techniques to analyze or synthesize study data.",
    },
    "funding_acquisition": {
        "label": "Funding acquisition",
        "description": "Acquisition of financial support for the project leading to this publication.",
    },
    "investigation": {
        "label": "Investigation",
        "description": "Conducting the research and investigation process, specifically performing experiments or collecting data and evidence.",
    },
    "methodology": {
        "label": "Methodology",
        "description": "Development or design of methodology; creation of models.",
    },
    "project_administration": {
        "label": "Project administration",
        "description": "Management and coordination responsibility for the research activity planning and execution.",
    },
    "resources": {
        "label": "Resources",
        "description": "Provision of study materials, reagents, samples, instrumentation, computing resources, or other analysis tools.",
    },
    "software": {
        "label": "Software",
        "description": "Programming, software development, implementation of computer code and supporting algorithms, and testing of existing code components.",
    },
    "supervision": {
        "label": "Supervision",
        "description": "Oversight responsibility for the research activity planning and execution, including mentorship external to the core team.",
    },
    "validation": {
        "label": "Validation",
        "description": "Verification of the overall replication or reproducibility of results, experiments, and other research outputs.",
    },
    "visualization": {
        "label": "Visualization",
        "description": "Preparation, creation, or presentation of the published work, specifically visualization and data presentation.",
    },
    "writing_original_draft": {
        "label": "Writing – original draft",
        "description": "Preparation, creation, or presentation of the published work, specifically writing the initial draft.",
    },
    "writing_review_editing": {
        "label": "Writing – review & editing",
        "description": "Preparation, creation, or presentation of the published work, specifically critical review, commentary, or revision.",
    },
}

CREDIT_ROLE_IDS = frozenset(CREDIT_ROLES)
