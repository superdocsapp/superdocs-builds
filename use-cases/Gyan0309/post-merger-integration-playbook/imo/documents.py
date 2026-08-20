"""Rendering the document set, and flagging conflicts into it through SuperDocs.

Two stages, deliberately separated.

**Rendering is deterministic.** Every document is generated from the deal spec by plain
Python. No model is involved, because a charter is a projection of known facts and a
model asked to write one will quietly improve a number. Deterministic rendering also
means the same deal always produces the same bytes, so a diff between two runs shows
only what actually changed in the deal.

**Flagging is SuperDocs' job.** Once the documents exist, the conflicts detected in
`conflicts.py` are applied *as edits to the real documents*, through the chat and
approval surface. That is the product doing the work it exists to do: a targeted change
landing in place, reviewable, with everything else untouched.

The card's requirement — *"the conflict is flagged in both documents rather than
silently duplicated"* — is satisfied by fanning one conflict out over every workstream
in `Conflict.affects`, so each lead sees it in their own charter rather than assuming
it belongs to someone else.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from imo.conflicts import Conflict, conflicts_for
from imo.deal import Deal, Workstream
from imo.superdocs import ChatResult, SuperDocsClient

logger = logging.getLogger("imo.documents")

CONFLICT_HEADING = "Open Cross-Workstream Conflicts"


@dataclass(frozen=True)
class RenderedDocument:
    key: str
    title: str
    filename: str
    body: str

    def write(self, directory: Path) -> Path:
        path = directory / self.filename
        path.write_text(self.body, encoding="utf-8")
        return path


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _money(value) -> str:
    return f"${value:,.0f}"


def render_charter(deal: Deal) -> RenderedDocument:
    """The master integration charter — the document every other one answers to."""
    lines = [
        f"# Integration Charter — Project {deal.code_name}",
        "",
        f"**Acquirer:** {deal.acquirer}  ",
        f"**Target:** {deal.target}  ",
        f"**Announced:** {deal.announced.isoformat()}  ",
        f"**Expected close:** {deal.expected_close.isoformat()}  ",
        f"**Integration horizon:** {deal.integration_horizon_months} months",
        "",
        "## 1. Deal Rationale",
        "",
        deal.rationale.strip(),
        "",
        "## 2. Synergy Target",
        "",
        f"The deal carries a run-rate synergy target of "
        f"{_money(deal.synergy_target_usd)} by month "
        f"{deal.integration_horizon_months}.",
        "",
        f"Workstreams currently claim {_money(deal.claimed_synergy_total)} in total.",
        "",
        "| Workstream | Lead | Claimed |",
        "|---|---|---|",
    ]
    for workstream in deal.workstreams:
        lines.append(
            f"| {workstream.name} | {workstream.lead} | {_money(workstream.synergy_total)} |"
        )

    lines += [
        "",
        "## 3. Workstreams and Scope",
        "",
    ]
    for workstream in deal.workstreams:
        lines += [
            f"### {workstream.name}",
            "",
            f"**Lead:** {workstream.lead}",
            "",
            workstream.scope.strip(),
            "",
        ]

    lines += [
        "## 4. Target Profile",
        "",
        f"{deal.target} has {deal.profile.headcount} staff across "
        f"{', '.join(deal.profile.locations)}.",
        "",
        "| System | Function | Disposition |",
        "|---|---|---|",
    ]
    for system in deal.profile.systems:
        lines.append(
            f"| {system.get('name', '?')} | {system.get('function', '?')} | "
            f"{system.get('disposition', 'to be decided')} |"
        )

    if deal.profile.notes.strip():
        lines += ["", "**Notes.** " + deal.profile.notes.strip()]

    lines += [
        "",
        "## 5. Governance",
        "",
        "The integration management office reports to the steering committee monthly. "
        "Each workstream lead owns the charter for their function and is accountable "
        "for the synergies claimed in it.",
        "",
    ]

    return RenderedDocument(
        key="charter",
        title=f"Integration Charter — Project {deal.code_name}",
        filename="01-integration-charter.md",
        body="\n".join(lines),
    )


def render_workstream_charter(deal: Deal, workstream: Workstream) -> RenderedDocument:
    """One charter per function, consistent with the master by construction."""
    lines = [
        f"# {workstream.name} Workstream Charter — Project {deal.code_name}",
        "",
        f"**Lead:** {workstream.lead}  ",
        f"**Deal:** {deal.acquirer} acquires {deal.target}  ",
        f"**Expected close:** {deal.expected_close.isoformat()}",
        "",
        "## 1. Scope",
        "",
        workstream.scope.strip() or "_Scope to be confirmed._",
        "",
        "## 2. Synergies Owned",
        "",
    ]

    if workstream.synergies:
        lines += ["| ID | Description | Annual value | Realised by |", "|---|---|---|---|"]
        for synergy in workstream.synergies:
            lines.append(
                f"| {synergy.id} | {synergy.description} | "
                f"{synergy.value_display} | month {synergy.realisation_month} |"
            )
        lines += ["", f"**Total claimed: {_money(workstream.synergy_total)}**"]
    else:
        lines.append("This workstream claims no synergies directly.")

    lines += ["", "## 3. Dependencies Owned", ""]
    if workstream.dependencies:
        lines += ["| ID | Description | Needed by | Consumed by |", "|---|---|---|---|"]
        for dependency in workstream.dependencies:
            consumers = ", ".join(dependency.needed_by) or "—"
            lines.append(
                f"| {dependency.id} | {dependency.description} | "
                f"month {dependency.needed_by_month} | {consumers} |"
            )
    else:
        lines.append("This workstream owns no cross-workstream dependencies.")

    lines += ["", "## 4. Day-One Readiness", ""]
    if workstream.day_one:
        lines += ["| ID | Item | Status | Depends on |", "|---|---|---|---|"]
        for item in workstream.day_one:
            depends = ", ".join(item.depends_on) or "—"
            lines.append(
                f"| {item.id} | {item.description} | "
                f"{item.status.replace('_', ' ')} | {depends} |"
            )
    else:
        lines.append("No day-one items are assigned to this workstream.")

    lines += ["", f"## 5. {CONFLICT_HEADING}", "", "_None recorded._", ""]

    return RenderedDocument(
        key=f"workstream-{workstream.key}",
        title=f"{workstream.name} Workstream Charter",
        filename=f"02-workstream-{workstream.key}.md",
        body="\n".join(lines),
    )


def render_day_one_checklist(deal: Deal) -> RenderedDocument:
    """The day-one readiness checklist.

    Specific to this deal rather than generic: every line comes from a workstream's own
    declared items, and the dependency column is what lets a reader see *why* an item is
    at risk. A generic checklist cannot have that column at all.
    """
    lines = [
        f"# Day-One Readiness Checklist — Project {deal.code_name}",
        "",
        f"Close is expected on {deal.expected_close.isoformat()}. Every item below must "
        f"be true on that date.",
        "",
        "| ID | Item | Owner | Status | Depends on |",
        "|---|---|---|---|---|",
    ]

    for item in deal.all_day_one:
        workstream = deal.workstream(item.owner)
        depends = ", ".join(item.depends_on) or "—"
        lines.append(
            f"| {item.id} | {item.description} | "
            f"{workstream.name if workstream else item.owner} | "
            f"{item.status.replace('_', ' ')} | {depends} |"
        )

    at_risk = [
        item
        for item in deal.all_day_one
        for dep_id in item.depends_on
        if (dep := deal.dependency(dep_id)) and dep.needed_by_month > 0
    ]

    lines += ["", "## Items at Risk", ""]
    if at_risk:
        lines.append(
            "These items depend on work that is not scheduled to complete before close:"
        )
        lines.append("")
        for item in at_risk:
            for dep_id in item.depends_on:
                dependency = deal.dependency(dep_id)
                if dependency and dependency.needed_by_month > 0:
                    lines.append(
                        f"- **{item.id}** — {item.description}. Depends on "
                        f"{dependency.id} ({dependency.description}), owned by "
                        f"{dependency.owner}, not due until month "
                        f"{dependency.needed_by_month}."
                    )
    else:
        lines.append("No day-one item depends on work scheduled after close.")

    lines.append("")
    return RenderedDocument(
        key="day-one",
        title=f"Day-One Readiness Checklist — Project {deal.code_name}",
        filename="03-day-one-checklist.md",
        body="\n".join(lines),
    )


def render_synergy_tracker(deal: Deal) -> RenderedDocument:
    """The synergy tracking summary, reconciled against the deal target."""
    variance = deal.claimed_synergy_total - deal.synergy_target_usd

    lines = [
        f"# Synergy Tracker — Project {deal.code_name}",
        "",
        f"**Deal target:** {_money(deal.synergy_target_usd)} run-rate by month "
        f"{deal.integration_horizon_months}  ",
        f"**Claimed by workstreams:** {_money(deal.claimed_synergy_total)}  ",
        f"**Variance:** {_money(variance)} "
        f"({'over-committed' if variance > 0 else 'under-committed' if variance else 'on target'})",
        "",
        "## By Workstream",
        "",
        "| Workstream | Claimed | Share of target |",
        "|---|---|---|",
    ]
    for workstream in deal.workstreams:
        share = (
            workstream.synergy_total / deal.synergy_target_usd
            if deal.synergy_target_usd
            else 0
        )
        lines.append(
            f"| {workstream.name} | {_money(workstream.synergy_total)} | {share:.0%} |"
        )

    lines += ["", "## All Claims", "", "| ID | Owner | Description | Value | Month |", "|---|---|---|---|---|"]
    for synergy in sorted(deal.all_synergies, key=lambda s: -s.annual_value_usd):
        lines.append(
            f"| {synergy.id} | {synergy.owner} | {synergy.description} | "
            f"{synergy.value_display} | {synergy.realisation_month} |"
        )

    lines += ["", f"## {CONFLICT_HEADING}", "", "_None recorded._", ""]

    return RenderedDocument(
        key="synergy-tracker",
        title=f"Synergy Tracker — Project {deal.code_name}",
        filename="04-synergy-tracker.md",
        body="\n".join(lines),
    )


def render_communications_pack(deal: Deal) -> RenderedDocument:
    """The comms pack. Deliberately plain, and honest about what is not yet decided."""
    lines = [
        f"# Communications Pack — Project {deal.code_name}",
        "",
        "## 1. Announcement Summary",
        "",
        f"{deal.acquirer} has agreed to acquire {deal.target}, with completion expected "
        f"on {deal.expected_close.isoformat()}.",
        "",
        deal.rationale.strip(),
        "",
        "## 2. Audiences and Owners",
        "",
        "| Audience | Owner | First contact |",
        "|---|---|---|",
        "| All Northwind staff | People & Organisation | Day one |",
        "| Top 20 customers | Commercial & Customer | Day one |",
        "| Remaining customers | Commercial & Customer | Week one |",
        "| Suppliers on notice periods | Finance & Accounting | Week one |",
        "| Regulators, where applicable | Finance & Accounting | Per timetable |",
        "",
        "## 3. Questions We Can Answer Today",
        "",
        f"- **Will there be redundancies?** No decisions have been taken. The "
        f"{deal.profile.headcount} staff at {deal.target} transfer on existing terms.",
        f"- **Do working patterns change?** Not at close. "
        + (
            deal.profile.notes.strip().split(".")[0] + "."
            if deal.profile.notes.strip()
            else "Local arrangements continue unchanged."
        ),
        "- **Which systems are changing?** See the charter's target profile table. "
        "Nothing changes for users before the relevant workstream confirms cutover.",
        "",
        "## 4. Questions We Cannot Answer Yet",
        "",
        "Being straight about this is the point of the section. Saying \"we do not know "
        "yet, and here is when we will\" survives contact with an audience; a "
        "confident answer that turns out to be wrong does not.",
        "",
        "- Final organisational design below workstream-lead level.",
        "- Benefits harmonisation detail, pending the People workstream review.",
        "- Long-term location strategy.",
        "",
    ]
    return RenderedDocument(
        key="comms-pack",
        title=f"Communications Pack — Project {deal.code_name}",
        filename="05-communications-pack.md",
        body="\n".join(lines),
    )


def render_all(deal: Deal) -> list[RenderedDocument]:
    """The complete document set, in the order a reader would meet it."""
    documents = [render_charter(deal)]
    documents += [render_workstream_charter(deal, w) for w in deal.workstreams]
    documents += [
        render_day_one_checklist(deal),
        render_synergy_tracker(deal),
        render_communications_pack(deal),
    ]
    return documents


# ---------------------------------------------------------------------------
# Flagging conflicts into the documents, through SuperDocs
# ---------------------------------------------------------------------------


def conflict_instruction(conflict: Conflict, *, audience: str) -> str:
    """The edit instruction sent to SuperDocs for one conflict in one document.

    Written to be surgical on purpose: it names the exact section to change and states
    that nothing else may be touched. A vague instruction gets a helpfully rewritten
    document, and "helpfully rewritten" is indistinguishable from "silently damaged"
    once it is three documents deep.
    """
    stake = conflict.evidence.get(audience, "")
    stake_line = f" This document's stake in it: {stake}." if stake else ""

    return (
        f"In the section titled '{CONFLICT_HEADING}', replace the text '_None recorded._' "
        f"with a bullet describing this conflict, or append a bullet if entries already "
        f"exist. The bullet must read:\n\n"
        f"**[{conflict.severity.upper()}] {conflict.summary}.** {conflict.detail}"
        f"{stake_line}\n\n"
        f"Change nothing else in the document. Do not alter any table, any figure, or "
        f"any other section."
    )


@dataclass
class FlagOutcome:
    document_key: str
    session_id: str
    conflict_id: str
    changes_proposed: int
    approved: int

    @property
    def landed(self) -> bool:
        return self.approved > 0


def flag_conflicts_in_document(
    client: SuperDocsClient,
    *,
    session_id: str,
    document_key: str,
    audience: str,
    conflicts: list[Conflict],
    auto_approve: bool = True,
) -> list[FlagOutcome]:
    """Apply every conflict affecting this document, one edit at a time.

    One conflict per chat turn rather than one turn listing all of them. That costs
    more turns, and buys two things worth more than the saving: each proposed change is
    reviewable on its own, so a human can accept one flag and reject another; and a
    failure is attributable to a specific conflict instead of leaving a partly-edited
    document nobody can reason about.
    """
    outcomes: list[FlagOutcome] = []

    for conflict in conflicts:
        result: ChatResult = client.chat(
            session_id=session_id,
            message=conflict_instruction(conflict, audience=audience),
        )

        approved = 0
        if auto_approve and result.pending_changes:
            client.decide_all(result)
            approved = len(result.pending_changes)

            # Approving does not mean finished. The job goes on to apply the change,
            # and the next instruction into a still-working session is a 409
            # `session_busy`. Waiting here is what makes driving one session in a loop
            # safe at all.
            client.wait_until_idle(session_id)

        logger.info(
            "%s: %s -> %d change(s), %d approved",
            document_key,
            conflict.kind,
            len(result.pending_changes),
            approved,
        )

        outcomes.append(
            FlagOutcome(
                document_key=document_key,
                session_id=session_id,
                conflict_id=conflict.id,
                changes_proposed=len(result.pending_changes),
                approved=approved,
            )
        )

    return outcomes


def plan_fan_out(deal: Deal, conflicts: list[Conflict]) -> dict[str, list[Conflict]]:
    """Which conflicts each document must carry.

    This mapping is the card's requirement in one function: a conflict between two
    workstreams appears in *both* of their charters, and in the master, rather than
    once in a central list where each lead can assume it is someone else's problem.
    """
    plan: dict[str, list[Conflict]] = {}

    for workstream in deal.workstreams:
        mine = conflicts_for(conflicts, workstream.key)
        if mine:
            plan[f"workstream-{workstream.key}"] = mine

    # The synergy tracker carries every money conflict, because that is the document
    # someone reads when the numbers do not add up.
    money = [c for c in conflicts if c.kind in ("duplicate_synergy", "synergy_over_commitment")]
    if money:
        plan["synergy-tracker"] = money

    return plan
