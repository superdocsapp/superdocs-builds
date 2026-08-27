"""Putting the letter back where the conversation was.

The card says the letter comes back "attached to a reply draft". This build writes a
real RFC 5322 message — correct ``In-Reply-To`` and ``References`` headers, the letter as
an attachment — which Gmail, Outlook and Apple Mail all import as a draft reply in the
right thread.

That is the same deliverable as the Gmail add-on path produces, without requiring OAuth
to demonstrate. The Apps Script adapter in ``gmail-addon/`` does it through Gmail's own
API instead; see the README for what is and is not tested there.
"""

from __future__ import annotations

import re
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid, parseaddr
from pathlib import Path

from .commitments import Commitment
from .thread import Thread

_MEDIA = {
    "docx": ("application", "vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "pdf": ("application", "pdf"),
    "html": ("text", "html"),
    "markdown": ("text", "markdown"),
    "txt": ("text", "plain"),
}
_SUFFIX = {"markdown": "md"}


def _body(thread: Thread, commitments: list[Commitment], filename: str) -> str:
    if not commitments:
        return (
            "I have put our discussion on record. Reading it back, I could not find "
            "anything either of us actually committed to — no dates and no "
            "undertakings — so the attached says exactly that.\n\n"
            "If you believe something was agreed, tell me and I will correct it.\n\n"
            f"Attached: {filename}\n"
        )

    lines = [
        "I have put what we agreed into the attached, so we are working from the "
        "same record.",
        "",
        "It states only what was actually committed to in this thread:",
        "",
    ]
    for c in commitments:
        due = f" by {c.due}" if c.due else ""
        lines.append(f"  - {c.party}: {c.obligation.rstrip('.')}{due}")
    lines += [
        "",
        "Anything that was discussed but not agreed has been left out on purpose.",
        "If I have recorded any of it wrongly, tell me and I will correct it.",
        "",
        f"Attached: {filename}",
        "",
    ]
    return "\n".join(lines)


def build_reply(
    thread: Thread,
    commitments: list[Commitment],
    attachment: bytes,
    *,
    fmt: str = "docx",
    from_address: str = "",
    stem: str = "",
    now: object = None,
) -> bytes:
    """A draft reply to the thread's last message, with the letter attached."""
    if not thread.messages:
        raise ValueError("cannot reply to an empty thread")
    last = thread.messages[-1]

    subject = last.subject or thread.subject
    if not re.match(r"^\s*re:", subject, re.I):
        subject = f"Re: {subject}"

    filename = f"{stem or _slug(thread.subject)}.{_SUFFIX.get(fmt, fmt)}"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["To"] = f"{last.sender} <{last.sender_email}>" if last.sender_email else last.to
    if from_address:
        msg["From"] = from_address
    msg["Message-ID"] = make_msgid()
    # Threading headers, so a mail client files this under the original conversation
    # rather than starting a new one.
    reply_to = thread.last_message_id
    if reply_to:
        msg["In-Reply-To"] = reply_to
        msg["References"] = reply_to
    if now is not None:
        msg["Date"] = format_datetime(now)  # type: ignore[arg-type]

    msg.set_content(_body(thread, commitments, filename))
    maintype, subtype = _MEDIA.get(fmt, ("application", "octet-stream"))
    msg.add_attachment(attachment, maintype=maintype, subtype=subtype, filename=filename)
    return msg.as_bytes()


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (text or "letter").lower()).strip("-")
    return cleaned[:60] or "letter"


def write(path: str | Path, data: bytes) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p
