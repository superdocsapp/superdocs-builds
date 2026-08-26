"""Pure function: DB-shaped state in, Slack Block Kit Home tab view out. No I/O here."""


def build_home_tab_view(
    open_documents: list[dict] | None = None,
    pending_approvals: list[dict] | None = None,
    running_jobs: list[dict] | None = None,
    recent_output: list[dict] | None = None,
) -> dict:
    open_documents = open_documents or []
    pending_approvals = pending_approvals or []
    running_jobs = running_jobs or []
    recent_output = recent_output or []

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "📄 Document Desk"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Open documents*"}},
    ]
    blocks.extend(_document_blocks(open_documents))

    blocks.append({"type": "divider"})
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Waiting on your approval*"}})
    blocks.extend(_approval_blocks(pending_approvals))

    blocks.append({"type": "divider"})
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Jobs running*"}})
    blocks.extend(_job_blocks(running_jobs))

    blocks.append({"type": "divider"})
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Recent output*"}})
    blocks.extend(_output_blocks(recent_output))

    return {"type": "home", "blocks": blocks}


def _document_blocks(documents: list[dict]) -> list[dict]:
    if not documents:
        return [_empty("No documents open yet. Share a file in a channel to get started.")]
    blocks = []
    for doc in documents:
        is_focused = doc.get("is_focused", False)
        # The focused document is the one @mention edits — mark it so the user
        # can see which doc their next edit will hit, and label its button
        # "Active" (clicking it just re-focuses the same doc, a harmless no-op).
        text = f"📄 *{doc['title']}*" + ("  ·  _active_" if is_focused else "")
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Active" if is_focused else "Open"},
                    "action_id": "open_document",
                    "value": doc["superdocs_document_id"],
                },
            }
        )
    return blocks


def _approval_blocks(pending_approvals: list[dict]) -> list[dict]:
    if not pending_approvals:
        return [_empty("Nothing pending.")]
    blocks = []
    for change in pending_approvals:
        value = f"{change['job_id']}:{change['change_id']}"
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"✏️ {change['ai_explanation']}"}}
        )
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "action_id": "approve_change",
                        "value": value,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "action_id": "reject_change",
                        "value": value,
                    },
                ],
            }
        )
    return blocks


def _job_blocks(running_jobs: list[dict]) -> list[dict]:
    if not running_jobs:
        return [_empty("Nothing running.")]
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"⏳ {job['status']} — job `{job['job_id']}`"}}
        for job in running_jobs
    ]


def _output_blocks(recent_output: list[dict]) -> list[dict]:
    if not recent_output:
        return [_empty("Nothing exported yet.")]
    blocks = []
    for output in recent_output:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"✅ {output['export_format'].upper()} export ready"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Download"},
                    "action_id": "download_export",
                    "value": str(output["id"]),
                },
            }
        )
    return blocks


def _empty(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": f"_{text}_"}}
