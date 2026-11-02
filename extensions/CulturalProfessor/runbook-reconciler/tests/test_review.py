"""The gate, and the properties that make it a gate rather than a prompt.

Three things are worth pinning here, and only the first is obvious.

**Nothing reaches a document without a decision.** Easy to state, easy to lose:
any future code path that writes without consulting `decision` breaks a test in
here rather than a wiki somewhere.

**Rejecting one leaves the rest.** The natural implementation collects approvals
and applies them as a batch, and then a single rejection either discards the
batch or is silently carried along with it. Both have been shipped by real
tools. The test is the one with two findings on one page and opposite decisions.

**A machine can drive the whole flow.** `ReviewQueue` is asserted to contain no
`input()` at all -- not by inspecting behaviour but by reading the module -- so
the MCP server at stage 11 drives the same object a human does, rather than a
reimplementation that drifts from it.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from reconciler import review as review_module
from reconciler.check.vertical import check_page
from reconciler.claims import Anchor, Claim, Finding
from reconciler.config import Config
from reconciler.confluence.local import LocalSource
from reconciler.estate import Estate
from reconciler.extract.patterns import extract_claims
from reconciler.register import Register
from reconciler.review import ReviewItem, ReviewQueue, iter_pages, run_terminal_review


@pytest.fixture
def workspace(tmp_path: Path, runbooks_dir: Path) -> Path:
    target = tmp_path / "runbooks"
    target.mkdir()
    for path in runbooks_dir.iterdir():
        if path.is_file():
            (target / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return target


@pytest.fixture
def register(tmp_path: Path) -> Register:
    with Register(tmp_path / "register.db") as reg:
        yield reg


def seed(register: Register, source: LocalSource, page_id: str) -> list[Finding]:
    estate = Estate.load(Config.load())
    document = source.read(page_id)
    claims = extract_claims(document)
    register.upsert_claims(claims)
    findings = check_page(page_id, claims, estate)
    register.upsert_findings(findings)
    return [f for f in findings if f.verdict == "contradicts"]


def with_proposals(register: Register, findings: list[Finding], text: str = "1.2s") -> None:
    """The gate only offers what `rr propose` has already produced text for."""
    for finding in findings:
        register.set_proposed(finding.finding_id, text)


def decision_of(register: Register, finding_id: str) -> str | None:
    stored = register.finding(finding_id)
    assert stored is not None, f"{finding_id} is not in the register"
    return stored.decision


class Scripted:
    """A reviewer, as a list of keystrokes."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.asked: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.asked.append(prompt)
        return self.answers.pop(0) if self.answers else "q"


# ------------------------------------------------------------- the queue --


def test_the_queue_offers_only_undecided_contradictions(
    workspace: Path, register: Register
) -> None:
    source = LocalSource(workspace)
    seed(register, source, "1001")
    queue = ReviewQueue(register)

    assert queue.items(), "the corpus has drift on 1001; the queue should not be empty"
    for item in queue.items():
        assert item.finding.verdict == "contradicts"
        assert item.finding.decision is None


def test_a_decided_finding_leaves_the_queue(workspace: Path, register: Register) -> None:
    source = LocalSource(workspace)
    findings = seed(register, source, "1001")
    queue = ReviewQueue(register)
    before = len(queue.items())

    queue.reject(findings[0].finding_id)

    assert len(queue.items()) == before - 1


def test_a_rejection_is_recorded_not_deleted(workspace: Path, register: Register) -> None:
    """The next sweep must not ask the same question again.

    A rejection that deleted the row would re-appear on the next sweep, and a
    tool that asks the same question every night is a tool somebody turns off.
    """
    source = LocalSource(workspace)
    findings = seed(register, source, "1001")
    ReviewQueue(register).reject(findings[0].finding_id)

    stored = register.finding(findings[0].finding_id)
    assert stored is not None
    assert stored.decision == "rejected"


# ------------------------------------------------------- item by item --


def test_rejecting_one_finding_leaves_the_others(workspace: Path, register: Register) -> None:
    """The batch-shaped bug, in the shape it actually appears.

    Two findings, one page, opposite decisions. A implementation that applied
    approvals as a batch would either write both or write neither.
    """
    source = LocalSource(workspace)
    findings = seed(register, source, "1001")
    if len(findings) < 2:
        pytest.skip("this page carries only one contradiction in the current corpus")

    approved, rejected = findings[0], findings[1]
    with_proposals(register, [approved, rejected])
    queue = ReviewQueue(register)
    queue.approve(approved.finding_id)
    queue.reject(rejected.finding_id)

    assert [f.finding_id for f in register.approved_unapplied()] == [approved.finding_id]


def test_only_approved_findings_are_written(workspace: Path, register: Register) -> None:
    source = LocalSource(workspace)
    findings = seed(register, source, "1001")
    target = next(f for f in findings if f.subject == "alert:PaymentsApiHighLatency:threshold")
    with_proposals(register, [target])
    before = source.read("1001").body

    queue = ReviewQueue(register)
    for finding in findings:
        if finding.finding_id != target.finding_id:
            queue.reject(finding.finding_id)
    queue.approve(target.finding_id)
    result = queue.commit(source)

    after = source.read("1001").body
    assert result.applied == [target.finding_id]
    assert "1.2s" in after
    assert after != before


def test_a_queue_nobody_decided_writes_nothing(workspace: Path, register: Register) -> None:
    """Rule 1, from the gate's side: no decision, no write."""
    source = LocalSource(workspace)
    findings = seed(register, source, "1001")
    with_proposals(register, findings)
    before = source.read("1001").body

    result = ReviewQueue(register).commit(source)

    assert result.applied == []
    assert source.read("1001").body == before


# -------------------------------------------------- what a reviewer sees --


def test_an_item_shows_both_sides_and_the_evidence(workspace: Path, register: Register) -> None:
    """A reviewer who cannot see the evidence is a rubber stamp."""
    source = LocalSource(workspace)
    findings = seed(register, source, "1001")
    target = next(f for f in findings if f.subject == "alert:PaymentsApiHighLatency:threshold")
    with_proposals(register, [target])

    item = next(i for i in ReviewQueue(register).items() if i.finding_id == target.finding_id)
    text = "\n".join(item.lines())

    assert item.claim is not None
    assert item.claim.asserted in text
    assert (target.observed or "") in text
    assert target.evidence_file in text
    assert "1.2s" in text


def test_an_item_with_no_proposal_says_so_rather_than_offering_a_blank(
    workspace: Path, register: Register
) -> None:
    source = LocalSource(workspace)
    seed(register, source, "1001")

    item = ReviewQueue(register).items()[0]

    assert not item.has_proposal
    assert "rr propose" in "\n".join(item.lines())


def test_a_passage_this_tool_will_not_edit_says_what_happens_instead() -> None:
    """The comment fallback has to be visible *before* approving, not after."""
    claim = Claim(
        page_id="1004",
        kind="threshold",
        subject="alert:CheckoutQueueBacklog:threshold",
        asserted="500",
        excerpt="Page when the backlog passes 500 messages.",
        anchor=Anchor(
            heading_path=("Thresholds",),
            node_index=0,
            content_hash="abc",
            char_start=0,
            char_end=3,
            editable=False,
            refusal="the passage contains a macro this tool cannot reconstruct",
        ),
    )
    finding = Finding(
        rule_id="alert-threshold",
        kind="threshold",
        subject=claim.subject,
        verdict="contradicts",
        evidence_file="fixtures/infra/observability/alerts.yaml",
        evidence_line=12,
        observed="1200",
        page_id="1004",
    )
    text = "\n".join(ReviewItem(finding=finding, claim=claim).lines())

    assert "macro" in text
    assert "posts a comment" in text


def test_items_can_be_walked_a_page_at_a_time(workspace: Path, register: Register) -> None:
    source = LocalSource(workspace)
    for page_id in ("1001", "1002"):
        seed(register, source, page_id)

    grouped = dict(iter_pages(ReviewQueue(register).items()))

    assert grouped
    for page_id, items in grouped.items():
        assert all(item.finding.page_id == (page_id or None) for item in items)


# ------------------------------------------------------ the terminal loop --


def test_the_terminal_loop_applies_what_the_reviewer_approved(
    workspace: Path, register: Register
) -> None:
    source = LocalSource(workspace)
    findings = seed(register, source, "1001")
    target = next(f for f in findings if f.subject == "alert:PaymentsApiHighLatency:threshold")
    with_proposals(register, [target])
    queue = ReviewQueue(register)
    order = [item.finding_id for item in queue.items()]
    answers = ["a" if finding_id == target.finding_id else "r" for finding_id in order]
    lines: list[str] = []

    result = run_terminal_review(queue, source, prompt=Scripted(*answers), output=lines.append)

    assert result.applied == [target.finding_id]
    assert "1.2s" in source.read("1001").body


def test_quitting_keeps_the_decisions_already_made(workspace: Path, register: Register) -> None:
    """Ctrl-C is a normal way to leave a review, not a rollback."""
    source = LocalSource(workspace)
    findings = seed(register, source, "1001")
    with_proposals(register, findings)
    queue = ReviewQueue(register)
    first = queue.items()[0].finding_id
    lines: list[str] = []

    run_terminal_review(queue, source, prompt=Scripted("a", "q"), output=lines.append)

    assert decision_of(register, first) == "approved"
    assert any("stopped" in line for line in lines)


def test_skip_leaves_a_finding_in_the_queue(workspace: Path, register: Register) -> None:
    source = LocalSource(workspace)
    seed(register, source, "1001")
    queue = ReviewQueue(register)
    before = len(queue.items())

    run_terminal_review(queue, source, prompt=Scripted(*(["s"] * before)), output=lambda _: None)

    assert len(queue.items()) == before


def test_an_empty_queue_says_so_and_writes_nothing(workspace: Path, register: Register) -> None:
    source = LocalSource(workspace)
    lines: list[str] = []

    result = run_terminal_review(ReviewQueue(register), source, output=lines.append)

    assert result.applied == []
    assert any("nothing to review" in line for line in lines)


def test_auto_drives_the_loop_without_a_terminal(workspace: Path, register: Register) -> None:
    """What the CI action and the tests use, and why it is a parameter.

    An environment variable left set is how an unattended run approves an estate
    nobody looked at; a parameter has to be passed by the caller that meant it.
    """
    source = LocalSource(workspace)
    findings = seed(register, source, "1001")
    with_proposals(register, findings)

    result = run_terminal_review(
        ReviewQueue(register), source, auto="reject", output=lambda _: None
    )

    assert result.applied == []
    assert all(decision_of(register, f.finding_id) == "rejected" for f in findings)


# --------------------------------------------------------- machine-drivable --


def test_the_queue_contains_no_terminal_at_all() -> None:
    """Behaviour four: a machine drives the same gate a human does.

    Asserted by reading the source rather than by exercising it, because the
    property is *absence* -- a single `input()` added to `ReviewQueue` in a
    later stage would pass every behavioural test in this file and quietly make
    the MCP server hang forever waiting on stdin.
    """
    source = inspect.getsource(ReviewQueue)

    assert "input(" not in source
    assert "print(" not in source


def test_the_terminal_loop_is_the_only_thing_that_prompts() -> None:
    module = inspect.getsource(review_module)

    assert module.count("ask = prompt or input") == 1
