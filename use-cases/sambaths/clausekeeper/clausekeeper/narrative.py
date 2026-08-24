def gap_narrative(clause_id: str, heading: str, operation: str, change_id: str,
                  instruction: str, job_id: str, occurred_at: str) -> str:
    verb = {"delete": "deleted", "edit": "rewritten",
            "create": "changed"}.get(operation, operation)
    short_instruction = (instruction or "direct web-UI edit").strip()
    if len(short_instruction) > 200:
        short_instruction = short_instruction[:197] + "..."
    return (
        f"Clause {clause_id} lost its evidence: section '{heading}' was {verb} "
        f"by edit `{change_id}` at {occurred_at}, instruction "
        f"'{short_instruction}', job `{job_id}`."
    )


def verification_gap_narrative(clause_id: str, job_id: str,
                               occurred_at: str) -> str:
    return (
        f"Clause {clause_id} has no covering section after verification pass in "
        f"job `{job_id}` at {occurred_at}; the document was checked and no "
        f"evidencing section remains."
    )
