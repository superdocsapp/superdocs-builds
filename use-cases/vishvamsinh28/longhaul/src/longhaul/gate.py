"""The human gate.

Every proposed change is decided one at a time, and the decision is written to the
ledger before anything is committed. Rejecting one change never discards the others:
decisions are per ``change_id``, and the approve call carries all of them together.

Three gates share one decision core, so the CLI, the web review UI and the MCP tools
cannot drift apart:

* :class:`PolicyGate` — deterministic rules from the job spec. Used by the proof suite,
  where the oracle has to be fixed, and by unattended runs.
* :class:`ManualGate` — a person at the terminal, change by change.
* :class:`DeferredGate` — decides nothing and pauses the run. The web UI and the MCP
  ``decide_changes`` tool write decisions into the ledger; the next resume picks them up.
  This is what makes the gate part of a machine-drivable flow rather than a UI detour.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from .injection import scan
from .ledger import Ledger
from .model import Decision, Proposal
from .planner import GateSpec

#: Feedback text used when the gate refuses to auto-approve instruction-shaped content.
INJECTION_FEEDBACK = (
    "Held for a named human: this change carries text that reads as an instruction "
    "aimed at an automated system. Reported, not obeyed."
)


class Gate(Protocol):
    name: str

    def decide(
        self, run_id: str, step_index: int, proposals: list[Proposal]
    ) -> list[Decision] | None:
        """Return one decision per proposal, or ``None`` to pause the run."""


@dataclass
class PolicyGate:
    """Deterministic decisions from the job spec's gate rules."""

    spec: GateSpec
    name: str = "policy"

    def decide(
        self, run_id: str, step_index: int, proposals: list[Proposal]
    ) -> list[Decision]:
        now = time.time()
        return [
            _decision(run_id, step_index, p, *self._verdict(p), self.name, now)
            for p in proposals
        ]

    def _verdict(self, p: Proposal) -> tuple[bool, str | None]:
        # A policy is not a person. It never auto-approves content that is trying to
        # give orders; it refuses and says why, leaving the call to a named human.
        if scan(p.new_html, where=p.change_id) or scan(p.old_html, where=p.change_id):
            return False, INJECTION_FEEDBACK
        for rule in self.spec.reject_when:
            if rule.old_html_contains and rule.old_html_contains in p.old_html:
                return False, rule.description or f"matched rule on {rule.old_html_contains!r}"
            if rule.new_html_contains and rule.new_html_contains in p.new_html:
                return False, rule.description or f"matched rule on {rule.new_html_contains!r}"
        return self.spec.default == "approve", None


@dataclass
class DeferredGate:
    """Decides nothing. The run pauses; a human or a machine decides out of band."""

    name: str = "deferred"

    def decide(
        self, run_id: str, step_index: int, proposals: list[Proposal]
    ) -> list[Decision] | None:
        return None


@dataclass
class ManualGate:
    """A person at the terminal, one change at a time."""

    console: object | None = None
    name: str = "manual"

    def decide(
        self, run_id: str, step_index: int, proposals: list[Proposal]
    ) -> list[Decision] | None:
        from rich.console import Console
        from rich.panel import Panel

        console = self.console or Console()
        decisions: list[Decision] = []
        for i, p in enumerate(proposals, start=1):
            findings = scan(p.new_html, where=p.change_id) + scan(p.old_html, where=p.change_id)
            body = [
                f"[dim]{p.ai_explanation}[/dim]",
                "",
                f"[red]- {_clip(p.old_html)}[/red]" if p.old_html else "[dim](new content)[/dim]",
                f"[green]+ {_clip(p.new_html)}[/green]" if p.new_html else "[dim](removed)[/dim]",
            ]
            if findings:
                body += ["", "[bold yellow]This change carries instruction-shaped text:[/bold yellow]"]
                body += [f"  [yellow]{f.render()}[/yellow]" for f in findings]
            console.print(Panel(
                "\n".join(body),
                title=f"step {step_index} · change {i}/{len(proposals)} · {p.operation}",
                subtitle=p.change_id,
            ))
            answer = _ask(console, "approve this change? [y/N/q] ")
            if answer == "q":
                return None  # walked away; the run pauses and loses nothing
            approved = answer == "y"
            feedback = None
            if not approved:
                feedback = _ask(console, "reason (optional, sent to the model): ", lower=False) or None
            decisions.append(
                _decision(run_id, step_index, p, approved, feedback, self.name, time.time())
            )
        return decisions


def _ask(console: object, prompt: str, *, lower: bool = True) -> str:
    console.print(prompt, end="")  # type: ignore[attr-defined]
    try:
        answer = input().strip()
    except EOFError:
        return "q"
    return answer.lower() if lower else answer


def _clip(html: str, limit: int = 300) -> str:
    flat = " ".join(html.split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def _decision(
    run_id: str,
    step_index: int,
    p: Proposal,
    approved: bool,
    feedback: str | None,
    by: str,
    at: float,
) -> Decision:
    return Decision(
        run_id=run_id,
        step_index=step_index,
        change_id=p.change_id,
        approved=approved,
        feedback=feedback,
        decided_by=by,
        decided_at=at,
    )


def record_decisions(
    ledger: Ledger,
    run_id: str,
    step_index: int,
    verdicts: dict[str, tuple[bool, str | None]],
    *,
    decided_by: str,
) -> list[Decision]:
    """Write out-of-band decisions (web UI, MCP) into the ledger.

    Only ``change_id``s that actually exist as proposals for this step are accepted, so a
    caller cannot invent a decision for a change that was never proposed.
    """
    proposals = {p.change_id: p for p in ledger.get_proposals(run_id, step_index)}
    unknown = sorted(set(verdicts) - set(proposals))
    if unknown:
        raise ValueError(f"no such proposed changes on step {step_index}: {unknown}")
    now = time.time()
    decisions = [
        _decision(run_id, step_index, proposals[cid], approved, feedback, decided_by, now)
        for cid, (approved, feedback) in verdicts.items()
    ]
    ledger.put_decisions(decisions)
    return decisions


def build_gate(mode: str, spec: GateSpec) -> Gate:
    if mode == "policy":
        return PolicyGate(spec)
    if mode == "manual":
        return ManualGate()
    if mode == "deferred":
        return DeferredGate()
    raise ValueError(f"unknown gate mode {mode!r}; expected policy, manual or deferred")
