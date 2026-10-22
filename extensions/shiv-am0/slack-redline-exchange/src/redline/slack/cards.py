from __future__ import annotations

import html as html_mod
import re
from typing import Any

from ..core.store import ProposalRow

SIDE_LABELS = {"vendor": "Vendor", "customer": "Customer"}
OP_LABELS = {"edit": "Edit", "delete": "Delete", "create": "Add"}


def _mrkdwn(text: str) -> dict[str, Any]:
    return {"type": "mrkdwn", "text": text}


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": _mrkdwn(text)}


def _button(label: str, action_id: str, style: str | None = None) -> dict[str, Any]:
    button: dict[str, Any] = {
        "type": "button",
        "text": {"type": "plain_text", "text": label},
        "action_id": action_id,
        "value": action_id,
    }
    if style:
        button["style"] = style
    return button


def clean_html(html_text: str | None) -> str:
    if not html_text:
        return ""
    return html_mod.unescape(re.sub(r"<[^>]+>", "", html_text)).strip()


def flatten_blocks_text(blocks: list[dict[str, Any]] | None) -> str:
    chunks: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("text", "alt_text", "value", "placeholder"):
                value = node.get(key)
                if isinstance(value, str):
                    chunks.append(value)
                elif isinstance(value, dict):
                    walk(value)
            for value in node.values():
                if isinstance(value, (list, dict)):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(blocks or [])
    return " ".join(chunks)


def build_deal_started_blocks(
    deal_name: str, filename: str, started_by_side: str, deal_id: str | None = None
) -> tuple[list[dict[str, Any]], str]:
    """Announce a new negotiation, and hand back the id every command needs.

    Every `/redline` verb takes a deal id as its first argument, so a card that
    announces a deal without showing its id sends people to the database to find one.
    It goes in the message text rather than only in a context block, because context
    elements are the first thing Slack truncates on a narrow screen.
    """
    text = (
        f":page_facing_up: *{deal_name}* negotiation started from `{filename}` "
        f"by {SIDE_LABELS[started_by_side]}."
    )
    if deal_id:
        text += f"\nDeal id: `{deal_id}`"
    hint = "Both sides will see proposed changes here as they are made."
    if deal_id:
        hint = f"Use `{deal_id}` with any /redline command. " + hint
    blocks = [
        _section(text),
        {"type": "context", "elements": [_mrkdwn(hint)]},
    ]
    return blocks, text


def _decision_status_block(proposal: ProposalRow, side: str) -> dict[str, Any]:
    decision = proposal.vendor_decision if side == "vendor" else proposal.customer_decision
    icon = {"approved": ":white_check_mark:", "rejected": ":x:"}.get(
        decision, ":hourglass_flowing_sand:"
    )
    label = decision or "pending"
    return {"type": "context", "elements": [_mrkdwn(f"{icon} {SIDE_LABELS[side]}: *{label}*")]}


def build_proposal_card_blocks(
    proposal: ProposalRow, deal_name: str, version: str
) -> tuple[list[dict[str, Any]], str]:
    old = clean_html(proposal.old_html) or "_(new text)_"
    new = clean_html(proposal.new_html) or "_(removed)_"
    op_label = OP_LABELS.get(proposal.operation, proposal.operation)
    header = (
        f":memo: *{op_label}* proposed by *{SIDE_LABELS[proposal.proposed_by_side]}* "
        f"— {deal_name} ({version})"
    )
    body_lines = [header, f"> {proposal.ai_explanation}"]
    if proposal.operation != "create":
        body_lines.append(f"*Was:* {old}")
    if proposal.operation != "delete":
        body_lines.append(f"*Now:* {new}")
    text = "\n".join(body_lines)

    blocks: list[dict[str, Any]] = [_section(text)]
    blocks.append(_decision_status_block(proposal, "vendor"))
    blocks.append(_decision_status_block(proposal, "customer"))

    if proposal.state == "pending":
        blocks.append(
            {
                "type": "actions",
                "block_id": f"redline_actions_{proposal.id}",
                "elements": [
                    _button(
                        f"Approve ({SIDE_LABELS['vendor']})",
                        f"redline:decide:{proposal.id}:vendor:approve",
                        "primary",
                    ),
                    _button(
                        f"Reject ({SIDE_LABELS['vendor']})",
                        f"redline:decide:{proposal.id}:vendor:reject",
                        "danger",
                    ),
                    _button(
                        f"Approve ({SIDE_LABELS['customer']})",
                        f"redline:decide:{proposal.id}:customer:approve",
                        "primary",
                    ),
                    _button(
                        f"Reject ({SIDE_LABELS['customer']})",
                        f"redline:decide:{proposal.id}:customer:reject",
                        "danger",
                    ),
                ],
            }
        )
    else:
        blocks.append(_section(f"*Resolved:* {proposal.state}"))
    return blocks, text


def build_outcome_card_blocks(
    deal_name: str,
    version: str,
    committed: list[ProposalRow],
    rejected: list[ProposalRow],
) -> tuple[list[dict[str, Any]], str]:
    lines = [f":checkered_flag: *{deal_name}* updated to *{version}*."]
    if committed:
        lines.append(f"Committed {len(committed)} change(s):")
        lines += [f"  • {clean_html(p.new_html) or '(removed content)'}" for p in committed]
    if rejected:
        lines.append(f"Rejected {len(rejected)} change(s) — see history for feedback.")
    if not committed and not rejected:
        lines.append("No changes were committed.")
    text = "\n".join(lines)
    return [_section(text)], text


def build_deal_closed_blocks(
    deal_name: str, version: str, side: str
) -> tuple[list[dict[str, Any]], str]:
    text = (
        f":lock: *{SIDE_LABELS.get(side, side)}* closed *{deal_name}* at *{version}*.\n"
        "Its history and exports stay available. The next document shared here starts a "
        "new negotiation."
    )
    return [_section(text)], text


def build_contract_changed_blocks(
    deal_name: str, filename: str, previous: str | None, side: str
) -> tuple[list[dict[str, Any]], str]:
    was = f" It replaces `{previous}`, which is now a supporting document." if previous else ""
    text = (
        f":page_facing_up: *{SIDE_LABELS.get(side, side)}* made `{filename}` the "
        f"authoritative contract for *{deal_name}*.{was}\n"
        "Edits that do not name a document now apply to it."
    )
    return [_section(text)], text


def build_decision_notice_blocks(
    deal_name: str,
    proposal: ProposalRow,
    side: str,
    approved: bool,
    waiting_on: list[str],
) -> tuple[list[dict[str, Any]], str]:
    """Announce a single decision so nobody has to scroll back to the card to read it.

    The card is the control surface and stays authoritative; this is the notification
    that something moved. It restates *what* was decided, not just that a decision
    happened, so the message is useful on its own in a busy channel.
    """
    verb = "approved" if approved else "rejected"
    icon = ":white_check_mark:" if approved else ":x:"
    summary = clean_html(proposal.new_html if approved else proposal.old_html)
    lines = [
        f"{icon} *{SIDE_LABELS.get(side, side)}* {verb} a change to *{deal_name}*.",
        f"> {proposal.ai_explanation}",
    ]
    if summary:
        lines.append(f"*{'Now' if approved else 'Was'}:* {summary}")
    if waiting_on:
        pending = " and ".join(SIDE_LABELS.get(s, s) for s in waiting_on)
        lines.append(f":hourglass_flowing_sand: Waiting on *{pending}* to decide.")
    else:
        lines.append(":gear: Both sides have decided — applying the outcome now.")
    text = "\n".join(lines)
    return [_section(text)], text


def build_job_expired_blocks(
    deal_name: str, reason: str
) -> tuple[list[dict[str, Any]], str]:
    """Tell both sides plainly that an approved batch could not be applied.

    Silence here would be the worst outcome: both parties agreed, the card says
    approved, and nothing reached the document. This says so and gives the way out.
    """
    text = (
        f":warning: *{deal_name}*: both sides decided, but SuperDocs could no longer "
        f"apply this edit ({reason}).\n"
        "Nothing was changed in the document, and the decisions are recorded in the "
        "history. Re-run `/redline propose` to raise the same change against the "
        "current version."
    )
    return [_section(text)], text


def build_revision_card_blocks(
    deal_name: str, round_number: int
) -> tuple[list[dict[str, Any]], str]:
    text = (
        f":arrows_counterclockwise: *{deal_name}*: revision round {round_number} — "
        "new proposal(s) below based on the feedback given."
    )
    return [_section(text)], text


def build_document_added_blocks(
    deal_name: str, filename: str, role: str, side: str
) -> tuple[list[dict[str, Any]], str]:
    text = (
        f":paperclip: *{SIDE_LABELS.get(side, side)}* added `{filename}` "
        f"({role}) to *{deal_name}*. It is searchable and can be targeted for edits; "
        "the authoritative contract is unchanged."
    )
    return [_section(text)], text


def build_progress_blocks(
    deal_name: str, elapsed_seconds: float, status: str
) -> tuple[list[dict[str, Any]], str]:
    text = (
        f":hourglass_flowing_sand: Still working on *{deal_name}* — "
        f"{int(elapsed_seconds)}s elapsed, status `{status}`. "
        "Large documents can take a few minutes; this is not a failure."
    )
    return [_section(text)], text


def build_search_results_blocks(
    deal_name: str, query: str, hits: list[Any]
) -> tuple[list[dict[str, Any]], str]:
    if not hits:
        text = (
            f":mag: No matches for *{query}* in *{deal_name}*. "
            "Nothing in the sources supports that term."
        )
        return [_section(text)], text
    lines = [f":mag: *{len(hits)}* match(es) for *{query}* in *{deal_name}*:"]
    for hit in hits:
        lines.append(f"• *{hit.kind}* — {hit.label}\n   {hit.snippet}")
    text = "\n".join(lines)
    return [_section(text)], text


def build_document_list_blocks(
    deal_name: str, documents: list[Any]
) -> tuple[list[dict[str, Any]], str]:
    if not documents:
        text = f":file_folder: *{deal_name}* has no documents yet."
        return [_section(text)], text
    lines = [f":file_folder: *{deal_name}* documents:"]
    for document in documents:
        lines.append(
            f"• `{document.filename}` — {document.role}, added by "
            f"{SIDE_LABELS.get(document.added_by_side, document.added_by_side)} "
            f"(`{document.id}`)"
        )
    text = "\n".join(lines)
    return [_section(text)], text


def build_boundary_alert_blocks(reason: str) -> tuple[list[dict[str, Any]], str]:
    text = f":rotating_light: Blocked an outbound message to the shared channel: {reason}"
    return [_section(text)], text


def build_provenance_error_blocks(reason: str) -> tuple[list[dict[str, Any]], str]:
    text = f":no_entry: Could not start that edit: {reason}"
    return [_section(text)], text


def build_text_blocks(text: str) -> tuple[list[dict[str, Any]], str]:
    return [_section(text)], text
