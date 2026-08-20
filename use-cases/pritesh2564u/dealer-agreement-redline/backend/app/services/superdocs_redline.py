from app.superdocs.client import SuperDocsClient


async def apply_approved_redlines(
    client: SuperDocsClient,
    session_id: str,
    findings: list[dict],
):
    approved = [
        finding
        for finding in findings
        if finding["decision"] == "approve"
    ]

    if not approved:
        return {
            "applied": False,
            "message": "No approved findings to apply.",
        }

    instructions = []

    for finding in approved:
        instructions.append(
            f"""
Section: {finding["section"]}

Current dealer language:
{finding["dealer_text"]}

Approved counter-position:
{finding["counter_position"]}

Human decision:
APPROVED
""".strip()
        )

    message = f"""
Update the active dealer agreement using the
human-approved redline decisions below.

IMPORTANT:
- Only modify the sections explicitly listed below.
- Preserve all other document content.
- Do not modify formatting unnecessarily.
- Apply the approved counter-position as the
  replacement language.
- Do not invent additional changes.

Approved redlines:

{"\n\n---\n\n".join(instructions)}
""".strip()

    response = await client.chat(
        session_id=session_id,
        message=message,
    )

    return {
        "applied": True,
        "chat_response": response,
    }