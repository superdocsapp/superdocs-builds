"""Turning confirmed commitments into a formal letter or memo.

The second billable turn. It is given the commitments a human confirmed — not the thread
— because the letter must be able to say only what somebody accepted, and the surest way
to keep speculation out of it is to keep the raw conversation out of it.

The letter states each commitment with its date and its party. It does not editorialise,
does not add warmth that was not there, and does not fill gaps. Where nothing was
committed, it says that, which is a more useful letter than an invented one.
"""

from __future__ import annotations

from dataclasses import dataclass

from .client import Client, document_html
from .commitments import Commitment
from .thread import Thread

LETTER = "letter"
MEMO = "memo"

_SHAPE = {
    LETTER: (
        "a formal business letter: sender block, date, recipient block, subject line, "
        "salutation, body, closing and signature block"
    ),
    MEMO: (
        "an internal memorandum: a TO / FROM / DATE / SUBJECT block at the top, then "
        "the body under short headings. No salutation and no signature block"
    ),
}

PROMPT = """\
Create {shape}.

Its purpose is to put on record what was agreed in a discussion titled "{subject}", \
between {participants}.

State exactly these commitments and nothing else. Do not add commitments, do not soften \
them, do not add dates that are not listed, and do not add warmth or intent that is not \
here:

{commitments}

Requirements:
- Every commitment above must appear in the body, with its party and its date.
- Write in plain, formal English. No exclamation marks, no filler, no "I hope this \
finds you well".
- Do not invent a company address, a reference number, or a signatory name. Where a \
letter would normally carry one and you have not been given it, leave a clearly marked \
placeholder in square brackets, for example [SENDER ADDRESS].
- Close with a single sentence inviting correction if anything is recorded wrongly.
- Today's date is {today}.
"""

NOTHING_PROMPT = """\
Create {shape}.

Its purpose is to put on record that a discussion titled "{subject}", between \
{participants}, concluded without either side committing to anything.

Say that plainly and briefly: the discussion took place, and no commitments, dates or \
obligations were agreed by anyone in it. Do not invent any. Do not pad it out. \
Invite correction if the recipient believes something was agreed.

Do not invent a company address, a reference number, or a signatory name; use clearly \
marked placeholders in square brackets where one would normally go. Today's date is \
{today}.
"""


@dataclass
class Letter:
    html: str
    session_id: str
    shape: str
    operations: int
    commitments: list[Commitment]

    @property
    def states_nothing(self) -> bool:
        return not self.commitments


def render_commitments(commitments: list[Commitment]) -> str:
    """The confirmed commitments, as the letter turn will see them."""
    lines = []
    for i, c in enumerate(commitments, start=1):
        due = f", due {c.due}" if c.due else ", no date was given"
        lines.append(
            f"{i}. {c.party} will {c.obligation.rstrip('.')}{due}. "
            f"Owed to {c.owes_to or 'the other party'}. "
            f'Recorded because they wrote: "{c.quote}"'
        )
    return "\n".join(lines)


def draft(
    client: Client,
    thread: Thread,
    commitments: list[Commitment],
    session_id: str,
    *,
    shape: str = LETTER,
    today: str = "",
    model_tier: str | None = None,
) -> Letter:
    """One billable turn: confirmed commitments in, a formal document out."""
    if shape not in _SHAPE:
        raise ValueError(f"shape must be {LETTER!r} or {MEMO!r}, not {shape!r}")

    common = {
        "shape": _SHAPE[shape],
        "subject": thread.subject,
        "participants": "; ".join(thread.participants),
        "today": today or "[DATE]",
    }
    prompt = (
        PROMPT.format(commitments=render_commitments(commitments), **common)
        if commitments
        else NOTHING_PROMPT.format(**common)
    )
    result = client.chat(session_id, prompt, model_tier=model_tier, note=f"draft {shape}")
    return Letter(
        html=document_html(result),
        session_id=session_id,
        shape=shape,
        operations=1 if client.usage_from(result).get("was_billable") else 0,
        commitments=list(commitments),
    )
