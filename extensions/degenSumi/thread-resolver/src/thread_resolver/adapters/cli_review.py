"""The review gate as a terminal screen.

One item at a time, showing the passage, what everyone said, and the proposed
change. Items carrying no edit are shown too, with the reason no edit was
drafted, because a contested thread is the output rather than an omission.

Approval is offered only where there is a change to approve. For everything
else the choices are to dismiss the finding or leave it for later, so that no
keystroke can close a thread nobody resolved.
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from thread_resolver.domain.models import Decision, Disposition, ReviewItem
from thread_resolver.ports.review import ReviewGate

STYLES: dict[Disposition, str] = {
    Disposition.ACTIONABLE: "green",
    Disposition.CONTESTED: "yellow",
    Disposition.UNCLEAR: "yellow",
    Disposition.QUESTION: "cyan",
    Disposition.UNANCHORED: "magenta",
    Disposition.QUARANTINED: "red",
}


class ReviewAborted(Exception):
    """Raised when the person reviewing chose to stop before deciding everything."""


class CliReviewGate(ReviewGate):
    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()

    def present(self, items: tuple[ReviewItem, ...]) -> tuple[ReviewItem, ...]:
        if not items:
            return ()
        if not sys.stdin.isatty():
            raise ReviewAborted(
                "The terminal review gate needs an interactive terminal. "
                "Drive the run with a scripted gate instead, or run it in a terminal."
            )

        self._summary(items)

        decided: list[ReviewItem] = []
        for position, item in enumerate(items, start=1):
            self._show(position, len(items), item)
            decided.append(item.with_decision(self._ask(item)))

        return tuple(decided)

    # -- rendering ----------------------------------------------------------

    def _summary(self, items: tuple[ReviewItem, ...]) -> None:
        table = Table(title=f"{len(items)} open threads", title_justify="left", box=None)
        table.add_column("disposition")
        table.add_column("count", justify="right")
        table.add_column("edit drafted", justify="right")

        for disposition in Disposition:
            matching = [i for i in items if i.classification.disposition is disposition]
            if not matching:
                continue
            drafted = sum(1 for i in matching if i.proposed_edits)
            table.add_row(
                Text(str(disposition), style=STYLES.get(disposition, "")),
                str(len(matching)),
                str(drafted),
            )

        self._console.print()
        self._console.print(table)

    def _show(self, position: int, total: int, item: ReviewItem) -> None:
        disposition = item.classification.disposition
        style = STYLES.get(disposition, "white")

        body = Text()
        if item.thread.anchor is not None:
            body.append("Passage\n", style="bold")
            body.append(f"{item.thread.anchor.text.strip()}\n\n", style="italic")

        body.append("Thread\n", style="bold")
        for comment in item.thread.comments:
            body.append(f"  {comment.author}: ", style="bold cyan")
            body.append(f"{comment.text}\n")

        body.append("\nJudgement\n", style="bold")
        body.append(f"  {item.classification.reason}\n")
        body.append(f"  decided by {item.classification.decided_by}\n", style="dim")

        for note in item.notes:
            body.append(f"  {note}\n", style="dim yellow")

        if item.proposed_edits:
            body.append("\nProposed change\n", style="bold")
            for edit in item.proposed_edits:
                body.append(f"  - {_plain(edit.old_html)}\n", style="red")
                body.append(f"  + {_plain(edit.new_html)}\n", style="green")
        else:
            body.append("\nNo edit drafted.\n", style="dim")

        label = str(disposition).upper()
        title = f"[{style}]{label}[/{style}]  thread {position} of {total}"

        self._console.print()
        self._console.print(Panel(body, title=title, title_align="left", border_style=style))

    def _ask(self, item: ReviewItem) -> Decision:
        if item.proposed_edits:
            choices = {"a": Decision.APPROVE, "r": Decision.REJECT, "d": Decision.DEFER}
            prompt = r"\[a] approve  \[r] reject  \[d] defer  \[q] quit"
        else:
            choices = {"r": Decision.REJECT, "d": Decision.DEFER}
            prompt = r"\[r] dismiss finding  \[d] leave open  \[q] quit"

        self._console.print(prompt, style="dim")
        answer = Prompt.ask("  decision", choices=[*choices, "q"], default="d", show_default=False)
        if answer == "q":
            raise ReviewAborted(
                "Review stopped before every item was decided; nothing was written."
            )
        return choices[answer]


def _plain(fragment: str) -> str:
    from thread_resolver.adapters.docx_writer import html_to_text

    return html_to_text(fragment)
