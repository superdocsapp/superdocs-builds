"""Reading an email thread into something quotable.

Everything downstream depends on one property: a claimed commitment must be checkable
against words somebody actually wrote. So a thread is parsed into messages that keep
their sender, their date, and their body text — and the body is kept in two forms.

The raw form is what a human reads. The *normalised* form collapses whitespace, because
mail wraps lines at seventy-odd characters and a sentence someone typed as one thought
arrives split across three lines. A quote check that missed those would reject true
quotes, and a build that then dropped true commitments would be worse than useless.
"""

from __future__ import annotations

import email
import email.policy
import re
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

#: Lines a mail client added, not the person. Stripped before quoting.
_QUOTED_LINE = re.compile(r"^\s*>+")
_ON_WROTE = re.compile(
    r"^\s*On .{0,80}(wrote|schrieb|a écrit)\s*:\s*$", re.I | re.M
)
_SIGNATURE = re.compile(r"^--\s*$", re.M)


@dataclass(frozen=True)
class Message:
    """One message. ``index`` is its position in the thread, counting from one."""

    index: int
    sender: str
    sender_email: str
    to: str
    date: str
    subject: str
    body: str
    #: The RFC 5322 id, when the source carried one. Threading a reply needs it.
    message_id: str = ""

    @property
    def normalised(self) -> str:
        return normalise(self.body)

    def cite(self) -> str:
        return f"message {self.index} ({self.sender}, {self.date})"


@dataclass(frozen=True)
class Thread:
    """A whole conversation, in the order it happened."""

    messages: tuple[Message, ...]
    source: str

    @property
    def subject(self) -> str:
        return self.messages[0].subject if self.messages else "(no subject)"

    @property
    def participants(self) -> list[str]:
        seen: dict[str, None] = {}
        for m in self.messages:
            seen.setdefault(f"{m.sender} <{m.sender_email}>", None)
        return list(seen)

    @property
    def last_message_id(self) -> str:
        """The id to reply to, so a mail client files the draft in this conversation."""
        return self.messages[-1].message_id if self.messages else ""

    @property
    def normalised(self) -> str:
        """The whole thread as one whitespace-normalised string, for quote checking."""
        return normalise(" ".join(m.body for m in self.messages))

    def render(self) -> str:
        """The thread as the model will see it, with stable per-message markers.

        The markers matter: an extracted commitment names the message it came from, and
        that is only checkable if the model and the verifier agree on the numbering.
        """
        return "\n\n".join(
            f"--- message {m.index} ---\n"
            f"From: {m.sender} <{m.sender_email}>\n"
            f"To: {m.to}\n"
            f"Date: {m.date}\n\n"
            f"{m.body.strip()}"
            for m in self.messages
        )


def normalise(text: str) -> str:
    """Collapse whitespace so a quote survives line wrapping.

    Also folds the quote characters mail clients substitute, so a commitment typed with
    a curly apostrophe still matches when the model echoes a straight one.
    """
    folded = (
        (text or "")
        .replace("’", "'").replace("‘", "'")
        .replace("“", '"').replace("”", '"')
        .replace("–", "-").replace("—", "-")
        .replace(" ", " ")
    )
    return " ".join(folded.split())


def _clean_body(raw: str) -> str:
    """Drop quoted history and signatures, keeping only what this sender typed."""
    without_attribution = _ON_WROTE.sub("", raw)
    kept: list[str] = []
    for line in without_attribution.splitlines():
        if _QUOTED_LINE.match(line):
            continue
        kept.append(line)
    body = "\n".join(kept)
    parts = _SIGNATURE.split(body)
    return parts[0].strip() if parts else body.strip()


def _from_email_message(msg: EmailMessage, index: int) -> Message:
    name, address = email.utils.parseaddr(msg.get("From", ""))
    if msg.is_multipart():
        part = msg.get_body(preferencelist=("plain",))
        raw = part.get_content() if part else ""
    else:
        raw = msg.get_content()
    return Message(
        index=index,
        sender=name or address or "(unknown)",
        sender_email=address,
        to=msg.get("To", ""),
        date=msg.get("Date", ""),
        subject=msg.get("Subject", "(no subject)"),
        body=_clean_body(raw if isinstance(raw, str) else str(raw)),
        message_id=(msg.get("Message-ID") or "").strip(),
    )


def parse_mbox(text: str, source: str = "mbox") -> Thread:
    """Split an mbox into messages. Gmail exports a thread in exactly this shape."""
    chunks = re.split(r"^From \S+.*$", text, flags=re.M)
    messages: list[Message] = []
    for chunk in chunks:
        if not chunk.strip():
            continue
        msg = email.message_from_string(chunk.lstrip("\n"), policy=email.policy.default)
        messages.append(_from_email_message(msg, len(messages) + 1))
    return Thread(messages=tuple(messages), source=source)


def parse_eml(text: str, source: str = "eml") -> Thread:
    msg = email.message_from_string(text, policy=email.policy.default)
    return Thread(messages=(_from_email_message(msg, 1),), source=source)


def parse_plain(text: str, source: str = "pasted") -> Thread:
    """A pasted thread, split on the ``From:`` lines a mail client leaves behind.

    Deliberately forgiving: someone pasting out of Gmail should not have to reformat
    anything. What cannot be attributed is still kept, because dropping text silently is
    how a real commitment goes missing.
    """
    blocks = re.split(r"\n(?=From:\s)", text.strip())
    messages: list[Message] = []
    for block in blocks:
        if not block.strip():
            continue
        header: dict[str, str] = {}
        lines = block.splitlines()
        body_start = 0
        for i, line in enumerate(lines):
            match = re.match(r"^(From|To|Date|Subject|Sent):\s*(.*)$", line, re.I)
            if not match:
                body_start = i
                break
            header[match.group(1).lower()] = match.group(2).strip()
        else:
            body_start = len(lines)
        name, address = email.utils.parseaddr(header.get("from", ""))
        messages.append(Message(
            index=len(messages) + 1,
            sender=name or address or "(unknown)",
            sender_email=address,
            to=header.get("to", ""),
            date=header.get("date") or header.get("sent", ""),
            subject=header.get("subject", "(no subject)"),
            body=_clean_body("\n".join(lines[body_start:])),
        ))
    return Thread(messages=tuple(messages), source=source)


def load(path: str | Path) -> Thread:
    """Read a thread from disk, choosing the parser by extension."""
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix.lower() == ".mbox":
        return parse_mbox(text, source=p.name)
    if p.suffix.lower() in (".eml", ".msg"):
        return parse_eml(text, source=p.name)
    return parse_plain(text, source=p.name)
