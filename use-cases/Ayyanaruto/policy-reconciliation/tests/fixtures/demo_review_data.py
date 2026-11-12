"""Fixture artifacts used to render screenshot.png without a live SuperDocs key."""

MAPPING = {
    "policies": [
        {
            "id": "map_001",
            "title": "Remote work / Flexible working",
            "recommendation": "new",
            "evidence": "Northstar allows full WFH with no office days. Helios requires Tuesday–Thursday in office. These are opposite attendance rules, not a wording difference.",
            "doc_a": {"filename": "remote_work_policy.docx"},
            "doc_b": {"filename": "flexible_working.docx"},
        },
        {
            "id": "map_002",
            "title": "PTO / Time off",
            "recommendation": "new",
            "evidence": "Northstar accrues 15 days with 3-day notice; Helios is unlimited with 30-day notice for absences over 5 days. Accrual vs unlimited cannot be silently merged.",
            "doc_a": {"filename": "pto_policy.docx"},
            "doc_b": {"filename": "time_off_policy.docx"},
        },
        {
            "id": "map_003",
            "title": "Expenses / Reimbursement",
            "recommendation": "merge",
            "evidence": "Same eligible costs and alcohol cap ($40). Thresholds differ ($50 vs $75 receipts; $200 manager vs $250 director) and can be unified into one policy.",
            "doc_a": {"filename": "expense_policy.docx"},
            "doc_b": {"filename": "reimbursement_guidelines.docx"},
        },
        {
            "id": "map_004",
            "title": "Code of conduct / Workplace conduct",
            "recommendation": "keep_a",
            "evidence": "Both prohibit harassment and require disclosure of reporting-line relationships. Northstar also covers social media and a stricter $25 gift cap, so it is the more complete base policy.",
            "doc_a": {"filename": "code_of_conduct.docx"},
            "doc_b": {"filename": "workplace_conduct.docx"},
        },
        {
            "id": "map_005",
            "title": "Termination / Separation",
            "recommendation": "keep_b",
            "evidence": "Helios publishes a clear severance formula (1 week per year, cap 12). Northstar garden leave and 2-week notice remain A-only coverage items for the merged company to decide explicitly.",
            "doc_a": {"filename": "termination_policy.docx"},
            "doc_b": {"filename": "separation_policy.docx"},
        },
    ]
}

CONFLICTS = {
    "conflicts": [
        {
            "id": "conflict_001",
            "reason": "Full remote vs required in-office days",
            "document_a": "remote_work_policy.docx",
            "document_b": "flexible_working.docx",
            "policy_a_excerpt": "Employees may work fully remotely from any location in the United States.",
            "policy_b_excerpt": "Employees must work from a company office on Tuesday, Wednesday, and Thursday.",
        },
        {
            "id": "conflict_002",
            "reason": "Accrued PTO vs unlimited time off",
            "document_a": "pto_policy.docx",
            "document_b": "time_off_policy.docx",
            "policy_a_excerpt": "Full-time employees accrue 15 days of paid time off per calendar year.",
            "policy_b_excerpt": "Helios offers unlimited paid time off. There is no accrual and no year-end expiration.",
        },
        {
            "id": "conflict_003",
            "reason": "3 business days vs 30 days notice",
            "document_a": "pto_policy.docx",
            "document_b": "time_off_policy.docx",
            "policy_a_excerpt": "Employees must provide 3 business days' notice for PTO requests.",
            "policy_b_excerpt": "Employees must provide 30 days' notice for absences exceeding 5 consecutive days.",
        },
        {
            "id": "conflict_004",
            "reason": "Gift cap $25 vs $75",
            "document_a": "code_of_conduct.docx",
            "document_b": "workplace_conduct.docx",
            "policy_a_excerpt": "Gifts from vendors may not exceed $25 in fair market value in any calendar year.",
            "policy_b_excerpt": "Gifts from vendors may not exceed $75 in fair market value in any calendar year.",
        },
    ]
}

COVERAGE = {
    "totals": {
        "documents_a": 5,
        "documents_b": 5,
        "documents_total": 10,
        "obligations_a": 12,
        "obligations_b": 11,
        "obligations_total": 23,
        "mapped": 16,
        "gap_a_only": 4,
        "gap_b_only": 3,
    },
    "obligations": [
        {
            "id": "obl_a_001",
            "estate": "a",
            "document_filename": "remote_work_policy.docx",
            "topic": "Work location",
            "text": "Employees may work fully remotely from any location in the United States.",
            "disposition": "mapped",
        },
        {
            "id": "obl_b_001",
            "estate": "b",
            "document_filename": "flexible_working.docx",
            "topic": "Office attendance",
            "text": "Employees must work from a company office on Tuesday, Wednesday, and Thursday.",
            "disposition": "mapped",
        },
        {
            "id": "obl_a_010",
            "estate": "a",
            "document_filename": "code_of_conduct.docx",
            "topic": "Social media confidentiality",
            "text": "Employees must not post confidential company information on social media.",
            "disposition": "gap-A-only",
        },
        {
            "id": "obl_a_011",
            "estate": "a",
            "document_filename": "code_of_conduct.docx",
            "topic": "Social media disclaimer",
            "text": "Personal social media that identifies the employee as a Northstar worker must include a disclaimer that views are their own.",
            "disposition": "gap-A-only",
        },
        {
            "id": "obl_a_014",
            "estate": "a",
            "document_filename": "termination_policy.docx",
            "topic": "Garden leave",
            "text": "Senior employees (Director and above) serve a 4-week garden leave after notice.",
            "disposition": "gap-A-only",
        },
        {
            "id": "obl_b_012",
            "estate": "b",
            "document_filename": "separation_policy.docx",
            "topic": "Severance formula",
            "text": "Severance is 1 week of base pay per completed year of service, capped at 12 weeks, for involuntary termination without cause.",
            "disposition": "gap-B-only",
        },
        {
            "id": "obl_a_006",
            "estate": "a",
            "document_filename": "expense_policy.docx",
            "topic": "Receipt threshold",
            "text": "Receipts are required for any expense over $50.",
            "disposition": "mapped",
        },
        {
            "id": "obl_b_007",
            "estate": "b",
            "document_filename": "reimbursement_guidelines.docx",
            "topic": "Receipt threshold",
            "text": "Itemized receipts are required for expenses over $75.",
            "disposition": "mapped",
        },
    ],
}

MERGES = [
    {
        "id": "merge_001",
        "title": "Expenses / Reimbursement",
        "proposed_draft_ref": "merged_drafts/expense_policy.html",
        "status": "awaiting_approval",
    }
]
