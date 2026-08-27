"""Command-line surface for the review round-trip.

``demo`` runs the whole thing keyless on the fake providers — send a Notion page for review,
read a marked-up Word file, and approve each change item by item — so a reviewer of this project
can watch the round-trip end to end without any setup. It is also what ``make demo`` runs.
"""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

import click

from notion_review.clients import build_boards, build_channel, build_clients
from notion_review.config import Config
from notion_review.docx_markup.stamp import identify_round, stamp_round_id
from notion_review.domain import ChangeSource, ProposalStatus, ProposedChange, ReviewRound
from notion_review.logging import setup_logging
from notion_review.notion.base import NotionClient
from notion_review.notion.models import row_cells
from notion_review.notion.queue_schema import summarize
from notion_review.roundtrip import (
    InboundController,
    ReviewGate,
    send_for_review,
    send_packet_for_review,
)
from notion_review.roundtrip.checkpoint import open_checkpointer
from notion_review.roundtrip.inbound import plain_text_from_html
from notion_review.roundtrip.intake import NotionRowIntake
from notion_review.roundtrip.notion_gate import (
    await_decisions,
    publish_pending,
    record_outcomes,
)
from notion_review.roundtrip.requests import create_request_database
from notion_review.roundtrip.service import ReviewService
from notion_review.sample import demo_page, demo_review_docx
from notion_review.store import SQLiteStore
from notion_review.superdocs import FakeSuperDocsClient

# Under ``data/`` because that directory is mounted from the host: a review round and its
# graph checkpoint have to outlive the container that created them.
_STATE_DEFAULT = "data/notion-review-state.db"


@click.group()
def main() -> None:
    """Notion ⇄ Word review-cycle round-trip, built on SuperDocs."""


@main.command()
@click.option("--interactive", is_flag=True, help="Approve each change by hand instead of all.")
def demo(interactive: bool) -> None:
    """Run the full round-trip on the fake providers — no keys, no operations."""
    setup_logging("console")
    notion, page_id = demo_page()
    superdocs = FakeSuperDocsClient()
    store = SQLiteStore()

    click.secho("\n1. Sending the Notion page out for review…", fg="cyan", bold=True)
    packet = send_for_review(notion=notion, superdocs=superdocs, store=store, page_id=page_id)
    click.echo(
        f"   → review round {packet.round.id}: "
        f"{len(packet.round.block_map)} blocks, {len(packet.docx.content):,}-byte Word file."
    )

    click.secho("\n2. Reading the reviewer's marked-up Word file…", fg="cyan", bold=True)
    controller = InboundController(
        notion=notion, superdocs=superdocs, store=store, config=Config.from_env({})
    )
    gate = controller.start(round_id=packet.round.id, docx_bytes=demo_review_docx())
    click.echo(f"   → {len(gate.pending)} change(s) proposed, awaiting your approval.\n")

    click.secho("3. Approving each change, then applying it to Notion…", fg="cyan", bold=True)
    final = _run_gates(controller, round_id=packet.round.id, gate=gate, interactive=interactive)
    _print_outcome(final.proposals, notion)
    click.echo(f"\n   cost: {final.cost_summary()}")
    click.secho(f"Round {final.id} finished: {final.status.value}.", fg="green", bold=True)


@main.command()
@click.option(
    "--page-id",
    "page_ids",
    required=True,
    multiple=True,
    help="A Notion page id to send for review. Repeat to send several pages as one packet.",
)
@click.option(
    "--out",
    default="",
    type=click.Path(),
    help="Where to write the Word file (default: review-<round-id>.docx).",
)
@click.option("--state", default=_STATE_DEFAULT, type=click.Path(), help="Round store file.")
def send(page_ids: tuple[str, ...], out: str, state: str) -> None:
    """Send one or more Notion pages out for review; writes a Word file and records the round.

    The Word file carries its own review-round id, so whatever route it takes back — an email
    reply, an upload, a shared folder — it can be matched to its round without anyone quoting it.

    Uses the live providers when PROVIDER=live, otherwise the fakes.
    """
    config = Config.from_env()
    setup_logging(config.log_format)
    notion, superdocs = build_clients(config)
    store = SQLiteStore(state)
    packet = send_packet_for_review(
        notion=notion, superdocs=superdocs, store=store, page_ids=list(page_ids)
    )
    # Into outbox/ by default, because that is a directory the host can see. Writing beside the
    # working directory looked fine and destroyed the file with the container: the command runs
    # under `docker compose run --rm`, and a document nobody can open is not a document sent.
    destination = Path(out) if out else Path("outbox") / f"review-{packet.round.id}.docx"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(stamp_round_id(packet.docx.content, packet.round.id))
    click.secho(f"Sent for review. round={packet.round.id}", fg="green", bold=True)
    click.echo(
        f"  {len(page_ids)} page(s) · {len(packet.round.block_map)} blocks · "
        f"Word file → {destination}"
    )
    click.echo("  Send that file to your reviewers. When it comes back, run:")
    click.echo("    notion-review review --markup <the returned file>")


@main.command()
@click.option("--round-id", default="", help="Usually detected from the file; overrides it.")
@click.option("--markup", required=True, type=click.Path(exists=True), help="The marked-up .docx.")
@click.option("--state", default=_STATE_DEFAULT, type=click.Path(), help="Round store file.")
@click.option("--interactive", is_flag=True, help="Approve each change by hand.")
def review(round_id: str, markup: str, state: str, interactive: bool) -> None:
    """Apply a reviewer's marked-up Word file back onto the Notion page, with approval."""
    config = Config.from_env()
    setup_logging(config.log_format)
    round_id = _resolve_round(round_id, markup)
    notion, superdocs = build_clients(config)
    store = SQLiteStore(state)
    # A durable graph checkpoint beside the state file: if this command is killed at the gate,
    # a re-run resumes there instead of re-proposing (and so never re-spends an operation).
    controller = InboundController(
        notion=notion,
        superdocs=superdocs,
        store=store,
        config=config,
        checkpointer=open_checkpointer(f"{state}.ckpt"),
    )
    gate = controller.start(
        round_id=round_id, docx_bytes=Path(markup).read_bytes(), filename=Path(markup).name
    )
    click.echo(f"{len(gate.pending)} change(s) proposed.\n")
    final = _run_gates(controller, round_id=round_id, gate=gate, interactive=interactive)
    _print_outcome(final.proposals, notion)
    click.echo(f"\n   cost: {final.cost_summary()}")
    click.secho(f"Round {final.id} finished: {final.status.value}.", fg="green", bold=True)


@main.command("review-in-notion")
@click.option("--round-id", default="", help="Usually detected from the file; overrides it.")
@click.option("--markup", required=True, type=click.Path(exists=True), help="The marked-up .docx.")
@click.option("--state", default=_STATE_DEFAULT, type=click.Path(), help="Round store file.")
@click.option("--poll", default=15.0, help="Seconds between checks for the owner's decisions.")
@click.option("--timeout", default=86_400.0, help="Give up waiting after this many seconds.")
def review_in_notion(round_id: str, markup: str, state: str, poll: float, timeout: float) -> None:
    """Approve changes inside Notion: each one becomes a row you set to Approved or Rejected.

    The page owner never leaves Notion — no second app, no extra login. This command publishes the
    queue, waits for the decisions, applies the approved changes, and records each outcome.
    """
    config = Config.from_env()
    setup_logging(config.log_format)
    round_id = _resolve_round(round_id, markup)
    notion, superdocs = build_clients(config)
    store = SQLiteStore(state)
    controller = InboundController(
        notion=notion,
        superdocs=superdocs,
        store=store,
        config=config,
        checkpointer=open_checkpointer(f"{state}.ckpt"),
    )
    gate = controller.start(
        round_id=round_id, docx_bytes=Path(markup).read_bytes(), filename=Path(markup).name
    )
    final = gate.round
    batch = 0
    while gate.pending:
        batch += 1
        added = publish_pending(gate.round, notion, store)
        click.secho(f"\nBatch {batch}: {added} change(s) waiting in Notion.", fg="cyan", bold=True)
        click.echo("  Open the “Review queue” database on the page and set each Status.")

        decisions = await_decisions(
            gate.round,
            notion,
            poll_interval_s=poll,
            timeout_s=timeout,
            on_wait=lambda done, total: click.echo(f"   … {done}/{total} decided"),
        )
        if not decisions:
            click.secho(
                "  No decisions yet — stopping; re-run to pick up where you left off.", fg="yellow"
            )
            return
        final = controller.submit(round_id=round_id, decisions=decisions)
        record_outcomes(final, notion, final.proposals)
        store.save(final)
        gate = ReviewGate(round=final, pending=final.pending())

    _print_outcome(final.proposals, notion)
    click.echo(f"\n   cost: {final.cost_summary()}")
    click.secho(f"Round {final.id} finished: {final.status.value}.", fg="green", bold=True)


@main.command("init-requests")
@click.option(
    "--parent-page-id",
    required=True,
    help="A Notion page you have shared with the integration; the database is created under it.",
)
def init_requests(parent_page_id: str) -> None:
    """Create the Review requests database — how a team starts a review without a terminal.

    Someone adds a row (the page to review, who should review it), sets Status to Requested, and
    the service sends it out. Put the id this prints in NOTION_REQUESTS_DB.
    """
    config = Config.from_env()
    setup_logging(config.log_format)
    notion, _ = build_clients(config)
    database_id = create_request_database(notion, parent_page_id=parent_page_id)
    click.secho("Review requests database created.", fg="green", bold=True)
    click.echo(f"  NOTION_REQUESTS_DB={database_id}")
    click.echo("  Add a row with the page id or URL, the reviewers' emails, Status = Requested.")


@main.command()
@click.option(
    "--inbox",
    default="inbox",
    type=click.Path(),
    help="Folder returned reviews land in (a synced Drive/Dropbox folder works).",
)
@click.option(
    "--outbox",
    default="outbox",
    type=click.Path(),
    help="Where requested documents are delivered when no mail server is configured.",
)
@click.option("--state", default=_STATE_DEFAULT, type=click.Path(), help="Round store file.")
@click.option("--interval", default=15.0, help="Seconds between passes.")
@click.option("--once", is_flag=True, help="Run a single pass and exit (for cron).")
def watch(inbox: str, outbox: str, state: str, interval: float, once: bool) -> None:
    """Run the review service: reviews are sent, taken in, and driven to completion on their own.

    A request row in Notion sends a page out; a reviewer's file arriving is matched to its round,
    proposed through SuperDocs, and queued in Notion for the page owner; their decisions are read
    back and applied. Nobody runs a command per review.
    """
    config = Config.from_env()
    setup_logging(config.log_format)
    notion, superdocs = build_clients(config)
    store = SQLiteStore(state)
    boards = build_boards(config, notion)
    intake, delivery = build_channel(config, notion, inbox=inbox, outbox=outbox, boards=boards)
    service = ReviewService(
        intake=intake,
        notion=notion,
        superdocs=superdocs,
        store=store,
        config=config,
        checkpointer=open_checkpointer(f"{state}.ckpt"),
        delivery=delivery,
        boards=boards,
    )
    if isinstance(intake, NotionRowIntake):
        found = boards.ids()
        click.secho(
            f"Watching {len(found)} Review requests board(s) shared with this integration…",
            fg="cyan",
            bold=True,
        )
        click.echo("  A row sends its page out and the document lands on that row.")
        click.echo("  Reviewers drop the marked-up copy back on the row; nobody leaves Notion.")
        click.echo("  Share another board with the integration and it is picked up — no restart.")
    else:
        click.secho(f"Watching {inbox}/ for returned reviews…", fg="cyan", bold=True)
        click.echo("  No Review requests board is shared with this integration yet.")
        click.echo("  Create one with `init-requests`, or share an existing one, to use Notion.")
    while True:
        report = service.tick()
        for round_id in report.sent:
            click.secho(f"  ✓ sent {round_id} out for review", fg="green")
        for round_id in report.ingested:
            click.secho(f"  ✓ took in a review for {round_id}", fg="green")
        for name in report.rejected:
            click.secho(f"  ! set aside {name} — see its Result in Notion", fg="yellow")
        for name in report.deferred:
            click.echo(f"  · {name} waits for the current changes to be decided")
        if report.applied:
            click.echo(f"  → applied {report.applied} approved change(s) to Notion")
        for round_id in report.completed:
            click.secho(f"  ✓ round {round_id} complete", fg="green", bold=True)
        if once:
            click.echo(f"  {report.summary()}")
            return
        time.sleep(interval)


@main.command()
@click.option("--round-id", default="", help="Show every change in one round, in full.")
@click.option("--state", default=_STATE_DEFAULT, type=click.Path(), help="Round store file.")
@click.option("--inbox", default="inbox", type=click.Path(), help="Intake folder to report on.")
def status(round_id: str, state: str, inbox: str) -> None:
    """Show what every review round is doing — the first place to look when something is wrong.

    Without --round-id: one line per round. With it: every change, its outcome, the error if it
    failed, and the ids needed to trace it through SuperDocs, Notion, and the logs.
    """
    store = SQLiteStore(state)
    if round_id:
        round_ = store.get(round_id)
        if round_ is None:
            raise click.ClickException(f"no such round: {round_id}")
        _print_round_detail(round_)
        return

    ids = store.list_ids()
    if not ids:
        click.echo("No review rounds yet.")
    for rid in ids:
        round_ = store.get(rid)
        if round_ is None:
            continue
        counts = Counter(p.status.value for p in round_.proposals)
        tally = " ".join(f"{name}={n}" for name, n in sorted(counts.items())) or "no changes"
        colour = {"completed": "green", "failed": "red", "parked": "yellow"}.get(
            round_.status.value, "cyan"
        )
        click.secho(f"{round_.id}  {round_.status.value:18s}", fg=colour, nl=False)
        click.echo(f"{tally}  ·  {round_.cost_summary()}")

    # The intake folder is the other place things go wrong: a file nobody could match.
    failed = Path(inbox) / "failed"
    if failed.is_dir():
        rejects = sorted(p for p in failed.iterdir() if p.suffix == ".docx")
        if rejects:
            click.secho(f"\n{len(rejects)} file(s) set aside in {failed}:", fg="yellow")
            for path in rejects:
                reason = path.with_suffix(path.suffix + ".reason.txt")
                why = reason.read_text().strip() if reason.exists() else "(no reason recorded)"
                click.echo(f"  {path.name}: {why}")


def _print_round_detail(round_: ReviewRound) -> None:
    click.secho(f"{round_.id}  {round_.status.value}", fg="cyan", bold=True)
    click.echo(f"  page       {round_.notion_page_id}")
    click.echo(f"  session    {round_.session_id}  (SuperDocs)")
    click.echo(f"  queue      {round_.review_url or '(not created yet)'}")
    click.echo(f"  blocks     {len(round_.block_map)} mapped")
    click.echo(f"  cost       {round_.cost_summary()}")
    click.echo(f"  updated    {round_.updated_at.isoformat()}  (v{round_.version})")
    click.echo(f"\n  {len(round_.proposals)} change(s):")
    for proposal in round_.proposals:
        colour = {
            ProposalStatus.APPLIED: "green",
            ProposalStatus.REJECTED: "white",
            ProposalStatus.CONFLICT: "yellow",
            ProposalStatus.FAILED: "red",
        }.get(proposal.status, "cyan")
        click.secho(f"    {proposal.status.value:9s}", fg=colour, nl=False)
        # Show what differs, not two truncated copies of the same sentence.
        detail = (
            summarize(_text(proposal.old_html), _text(proposal.new_html))
            if proposal.new_html
            else proposal.reviewer_comment
        )
        click.echo(f"{proposal.source.value:15s} {proposal.reviewer_name:18s} {detail}")
        if proposal.error:
            click.secho(f"              error: {proposal.error}", fg="red")
        click.echo(
            f"              block={proposal.notion_block_id} chunk={proposal.chunk_id or '-'} "
            f"change={proposal.change_id or '-'} job={proposal.job_id or '-'}"
        )
        if proposal.links:
            click.secho(f"              links: {', '.join(proposal.links)}", fg="yellow")


@main.command()
def whoami() -> None:
    """Check which SuperDocs account the configured API key belongs to."""
    from notion_review.superdocs.base import SuperDocsError
    from notion_review.superdocs.live import LiveSuperDocsClient

    config = Config.from_env()
    if not config.superdocs_api_key:
        raise click.ClickException("SUPERDOCS_API_KEY is not set (see .env.example)")
    client = LiveSuperDocsClient(
        api_key=config.superdocs_api_key, base_url=config.superdocs_base_url, config=config
    )
    try:
        click.echo(client.whoami())
    except SuperDocsError as exc:
        click.secho(f"whoami unavailable for this key: {exc}", fg="yellow")
    finally:
        client.close()


def _resolve_round(round_id: str, markup: str) -> str:
    """Which round a returned file belongs to: the file says so, unless told otherwise."""
    if round_id:
        return round_id
    path = Path(markup)
    detected = identify_round(path.read_bytes(), path.name)
    if not detected:
        raise click.ClickException(
            "could not tell which review round this file belongs to — it carries no round id "
            "and the filename has none. Pass --round-id explicitly."
        )
    click.echo(f"Review round {detected} (read from the returned file).")
    return detected


def _run_gates(
    controller: InboundController,
    *,
    round_id: str,
    gate: ReviewGate,
    interactive: bool,
) -> ReviewRound:
    """Drive every approval gate to the end of the round.

    A review larger than one SuperDocs operation is proposed batch by batch — each batch is gated
    and applied before the next goes out — so the driver keeps approving until nothing is pending.
    """
    batch = 0
    final = gate.round
    while gate.pending:
        batch += 1
        if batch > 1:
            click.secho(f"\nBatch {batch}: {len(gate.pending)} more change(s).", fg="cyan")
        decisions = _collect_decisions(gate.pending, interactive=interactive)
        final = controller.submit(round_id=round_id, decisions=decisions)
        gate = ReviewGate(round=final, pending=final.pending())
    return final


def _collect_decisions(
    pending: list[ProposedChange], *, interactive: bool
) -> list[dict[str, object]]:
    decisions: list[dict[str, object]] = []
    for i, proposal in enumerate(pending, start=1):
        _print_card(i, proposal)
        approved = click.confirm("   Approve?", default=True) if interactive else True
        if not interactive:
            click.echo("   → approved (pass --interactive to decide each one)")
        decisions.append({"proposal_id": proposal.id, "approved": approved})
    return decisions


def _print_card(number: int, proposal: ProposedChange) -> None:
    click.secho(f"  [{number}] {proposal.reviewer_name}", fg="yellow", bold=True)
    if proposal.source == ChangeSource.COMMENT:
        click.echo(f"      comment: {proposal.reviewer_comment}")
    else:
        if proposal.source == ChangeSource.COMMENT_INTENT:
            click.echo(f"      request: {proposal.reviewer_comment}")
            if proposal.ai_explanation:
                click.echo(f"      SuperDocs: {proposal.ai_explanation}")
        click.echo(f"      was: {_text(proposal.old_html)}")
        click.echo(f"      now: {_text(proposal.new_html)}")
    for link in proposal.links:  # surface any URL an edit would introduce, before it lands
        click.secho(f"      ⚠ link: {link}", fg="red")


def _print_outcome(proposals: list[ProposedChange], notion: NotionClient) -> None:
    for proposal in proposals:
        icon = {
            ProposalStatus.APPLIED: "✓ applied",
            ProposalStatus.REJECTED: "✗ rejected",
            ProposalStatus.CONFLICT: "⚠ conflict (page changed)",
            ProposalStatus.FAILED: "! failed",
        }.get(proposal.status, proposal.status.value)
        block = notion.retrieve_block(proposal.notion_block_id)
        # A table row has no rich text of its own, so `plain()` is empty for one and the line
        # would read as though nothing had been written. Show the row's cells instead.
        cells = row_cells(block)
        shown = " | ".join(cells) if cells else block.plain()
        click.echo(f"   {icon}: {proposal.reviewer_name} → “{shown[:60]}”")


def _text(html: str) -> str:
    return plain_text_from_html(html) or "(removed)"


if __name__ == "__main__":
    main()
