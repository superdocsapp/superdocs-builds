from __future__ import annotations

import re
from typing import Any

from ..config import Settings
from ..core.documents import title_from_filename
from ..core.negotiation import MessengerPort, NegotiationService
from .cards import (
    build_document_list_blocks,
    build_search_results_blocks,
    build_text_blocks,
)

HELP_TEXT = (
    "*/redline propose <deal_id> [--doc <name>] <instruction>* — request an edit "
    "(must be sent in the shared channel)\n"
    "*/redline search <deal_id> <query>* — search this deal's documents, proposals "
    "and history\n"
    "*/redline docs <deal_id>* — list the documents attached to this deal\n"
    "*/redline contract <deal_id> <filename>* — make an attached document the "
    "authoritative contract\n"
    "*/redline close <deal_id>* — finish this negotiation so the next document "
    "shared here starts a new one\n"
    "*/redline status <deal_id>*\n"
    "*/redline refresh <deal_id>* — redraw the decision cards if one got lost or stale\n"
    "*/redline history <deal_id>*\n"
    "*/redline export <deal_id> clean|redline*\n"
    "*/redline note <deal_id> <note>* — internal-only, sent from your internal channel\n"
    "Share a document into the shared channel to start a new deal, or share another "
    "file to attach it to the newest deal."
)


def _split_document_flag(text: str) -> tuple[str | None, str]:
    """Pull an optional `--doc <name>` targeting flag out of an instruction."""
    match = re.search(r"--doc\s+(\S+)\s*", text)
    if not match:
        return None, text.strip()
    remainder = (text[: match.start()] + text[match.end() :]).strip()
    return match.group(1), remainder


async def internal_error_reply(
    messenger: MessengerPort, settings: Settings, side: str, message: str
) -> None:
    blocks, text = build_text_blocks(f":warning: {message}")
    await messenger.post_message(settings.internal_channel_for(side), blocks, text)


async def handle_file_share(
    service: NegotiationService,
    settings: Settings,
    *,
    channel_id: str,
    user_id: str,
    team_id: str,
    filename: str,
    file_bytes: bytes,
    deal_name: str | None = None,
    attach_to_deal_id: str | None = None,
    role: str = "supporting",
) -> dict[str, Any]:
    side = settings.side_for(team_id, user_id)
    if channel_id != settings.shared_channel:
        raise ValueError(
            "documents must be shared in the shared channel so both sides see the same file"
        )
    if attach_to_deal_id:
        document = await service.add_document(
            attach_to_deal_id,
            side,
            user_id,
            filename,
            file_bytes,
            role=role,
            source_channel_id=channel_id,
        )
        return {"deal_id": attach_to_deal_id, "document_id": document.id}
    deal = await service.start_deal(
        name=deal_name or title_from_filename(filename),
        started_by_side=side,
        started_by_user=user_id,
        filename=filename,
        file_bytes=file_bytes,
    )
    return {"deal_id": deal.id}


async def _reply(service: NegotiationService, channel_id: str, text: str) -> dict[str, Any]:
    blocks, msg = build_text_blocks(text)
    await service.messenger.post_message(channel_id, blocks, msg)
    return {"ok": True}


async def handle_slash_command(
    service: NegotiationService,
    settings: Settings,
    *,
    channel_id: str,
    user_id: str,
    team_id: str,
    text: str,
) -> dict[str, Any]:
    side = settings.side_for(team_id, user_id)
    parts = text.strip().split(maxsplit=2)
    if not parts:
        return await _reply(service, channel_id, HELP_TEXT)

    verb = parts[0].lower()
    args = parts[1:]

    if verb == "propose":
        if len(args) < 2:
            usage = "usage: /redline propose <deal_id> [--doc <name>] <instruction>"
            return await _reply(service, channel_id, usage)
        deal_id, rest = args[0], args[1]
        document_id, instruction = _split_document_flag(rest)
        if not instruction:
            return await _reply(
                service, channel_id, "that propose had no instruction after the --doc flag"
            )
        job = await service.propose(
            deal_id,
            side,
            user_id,
            instruction,
            source_channel_id=channel_id,
            document_id=document_id,
        )
        await service.drive_job(job.job_id)
        return {"job_id": job.job_id}

    if verb == "search":
        if len(args) < 2:
            return await _reply(service, channel_id, "usage: /redline search <deal_id> <query>")
        deal_id, query = args[0], args[1]
        hits = service.search(deal_id, query, source_channel_id=channel_id, side=side)
        deal = service.store.get_deal(deal_id)
        blocks, text = build_search_results_blocks(deal.name, query, hits)
        await service.messenger.post_message(channel_id, blocks, text)
        return {"hits": len(hits)}

    if verb == "docs":
        if not args:
            return await _reply(service, channel_id, "usage: /redline docs <deal_id>")
        deal = service.store.get_deal(args[0])
        documents = service.list_documents(args[0])
        blocks, text = build_document_list_blocks(deal.name, documents)
        await service.messenger.post_message(channel_id, blocks, text)
        return {"documents": len(documents)}

    if verb == "close":
        if not args:
            return await _reply(service, channel_id, "usage: /redline close <deal_id>")
        await service.close_deal(args[0], side, user_id)
        return {"closed": args[0]}

    if verb == "contract":
        if len(args) < 2:
            return await _reply(
                service, channel_id, "usage: /redline contract <deal_id> <filename>"
            )
        document = await service.promote_document(args[0], args[1], side, user_id)
        return {"contract": document.filename}

    if verb == "refresh":
        if not args:
            return await _reply(service, channel_id, "usage: /redline refresh <deal_id>")
        redrawn = await service.refresh_cards(args[0])
        if not redrawn:
            return await _reply(service, channel_id, "no proposals are awaiting a decision")
        return {"refreshed": redrawn}

    if verb == "status":
        if not args:
            return await _reply(service, channel_id, "usage: /redline status <deal_id>")
        status = service.status(args[0])
        lines = "\n".join(f"*{k}*: {v}" for k, v in status.items())
        return await _reply(service, channel_id, lines)

    if verb == "history":
        if not args:
            return await _reply(service, channel_id, "usage: /redline history <deal_id>")
        lines = service.history_lines(args[0])
        return await _reply(service, channel_id, "\n".join(lines) or "(no history yet)")

    if verb == "export":
        if len(args) < 2 or args[1] not in ("clean", "redline"):
            return await _reply(
                service, channel_id, "usage: /redline export <deal_id> clean|redline"
            )
        deal_id, kind = args[0], args[1]
        exported = (
            await service.export_clean(deal_id)
            if kind == "clean"
            else await service.export_redline(deal_id)
        )
        await service.messenger.upload_file(
            channel_id,
            exported.filename,
            exported.content,
            initial_comment=f"Export ({kind}) for deal {deal_id}",
        )
        return {"filename": exported.filename}

    if verb == "note":
        if len(args) < 2:
            return await _reply(service, channel_id, "usage: /redline note <deal_id> <note text>")
        if channel_id != settings.internal_channel_for(side):
            return await _reply(
                service, channel_id, "internal notes must be sent from your own internal channel"
            )
        deal_id, body = args[0], args[1]
        await service.add_internal_note(deal_id, side, user_id, body)
        return {"ok": True}

    return await _reply(service, channel_id, HELP_TEXT)


async def handle_block_action(
    service: NegotiationService,
    settings: Settings,
    *,
    action_id: str,
    user_id: str,
    team_id: str,
) -> dict[str, Any]:
    parts = action_id.split(":")
    if len(parts) != 5 or parts[0] != "redline" or parts[1] != "decide":
        raise ValueError(f"unrecognised action_id {action_id!r}")
    _, _, proposal_id, claimed_side, decision = parts
    actual_side = settings.side_for(team_id, user_id)
    if actual_side != claimed_side:
        raise ValueError(
            f"a {actual_side} user attempted to record a decision on behalf of {claimed_side}"
        )
    proposal = service.store.get_proposal(proposal_id)
    deal = service.store.get_deal(proposal.deal_id)
    approved = decision == "approve"
    result = await service.decide(deal.id, proposal_id, actual_side, user_id, approved)
    return {"proposal_id": result.id, "state": result.state}
