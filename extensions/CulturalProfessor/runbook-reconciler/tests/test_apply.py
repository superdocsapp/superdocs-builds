"""The write path, against a source that really writes.

`LocalSource` implements the same contract as the Confluence adapter — read,
version-checked write, comment — so these tests exercise the real apply logic
rather than a mock that agrees with it. The one thing they cannot cover is
Confluence's own behaviour, and `test_confluence.py` is honest about which of
those endpoints have been run against a live site and which have not.

The tests that matter most are the ones about failure: a page that moved under
us, a batch where the second write fails, and a crash between the write and the
record of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reconciler.apply import apply_approved
from reconciler.check.vertical import check_page
from reconciler.claims import Finding
from reconciler.config import Config
from reconciler.confluence.local import LocalSource, VersionConflict
from reconciler.confluence.splice import (
    SpliceRefused,
    assert_only_these_ranges_changed,
    changed_ranges,
)
from reconciler.estate import Estate
from reconciler.extract.patterns import extract_claims
from reconciler.register import Register


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
    """Sweep one page into the register and return its contradictions."""
    estate = Estate.load(Config.load())
    document = source.read(page_id)
    claims = extract_claims(document)
    register.upsert_claims(claims)
    findings = check_page(page_id, claims, estate)
    register.upsert_findings(findings)
    return [f for f in findings if f.verdict == "contradicts"]


def approve(register: Register, finding: Finding, proposed: str) -> str:
    register.set_proposed(finding.finding_id, proposed)
    register.decide(finding.finding_id, "approved")
    return finding.finding_id


# ------------------------------------------------------------ the happy path --


def test_an_approved_fix_lands_and_nothing_else_moves(workspace: Path, register: Register) -> None:
    source = LocalSource(workspace)
    before = source.read("1001").body
    finding = next(
        f
        for f in seed(register, source, "1001")
        if f.subject == "alert:PaymentsApiHighLatency:threshold"
    )
    approve(register, finding, "1.2s")

    result = apply_approved(register, source)

    assert result.applied == [finding.finding_id]
    after = source.read("1001").body
    assert "stays above <strong>1.2s</strong>" in after
    assert len(changed_ranges(before, after)) == 1
    assert after.count("<ac:structured-macro") == before.count("<ac:structured-macro")


def test_an_applied_finding_is_recorded_and_not_reapplied(
    workspace: Path, register: Register
) -> None:
    source = LocalSource(workspace)
    finding = next(
        f
        for f in seed(register, source, "1001")
        if f.subject == "alert:PaymentsApiHighLatency:threshold"
    )
    approve(register, finding, "1.2s")

    apply_approved(register, source)
    assert register.approved_unapplied() == []

    second = apply_approved(register, source)
    assert second.applied == []


def test_two_fixes_on_one_page_each_change_one_range(workspace: Path, register: Register) -> None:
    """Splices are applied from the end backwards.

    Forwards, the first edit invalidates every offset after it and the damage
    looks like a parser bug rather than an ordering bug.
    """
    source = LocalSource(workspace)
    before = source.read("1001").body
    findings = seed(register, source, "1001")
    threshold = next(f for f in findings if f.subject.endswith(":threshold"))
    job = next(f for f in findings if f.subject == "job:rollback-production")
    approve(register, threshold, "1.2s")
    approve(register, job, "manual-rollback")

    result = apply_approved(register, source)

    assert len(result.applied) == 2
    after = source.read("1001").body
    # Stated as a reconstruction rather than a diff count: two values changed
    # and every other byte is the same one it was.
    assert after == before.replace("800ms", "1.2s").replace(
        "rollback-production", "manual-rollback"
    )


# --------------------------------------------------------------- refusals ----


def test_a_passage_with_a_macro_gets_a_comment_not_an_edit(
    workspace: Path, register: Register
) -> None:
    source = LocalSource(workspace)
    before = source.read("1004").body
    finding = next(
        f
        for f in seed(register, source, "1004")
        if f.subject.endswith("LabelPrinterQueueDepth:threshold")
    )
    approve(register, finding, "500")

    result = apply_approved(register, source)

    assert result.commented == [finding.finding_id]
    assert result.applied == []
    assert source.read("1004").body == before, "the page must not have been touched"

    comments = source.comments("1004")
    assert len(comments) == 1
    assert "status macro" in comments[0]["body"] or "status" in comments[0]["body"]
    assert "needs a human" in comments[0]["body"]


def test_a_finding_with_no_replacement_text_is_escalated(
    workspace: Path, register: Register
) -> None:
    source = LocalSource(workspace)
    finding = next(f for f in seed(register, source, "1001") if f.subject.endswith(":threshold"))
    register.decide(finding.finding_id, "approved")  # approved, but nothing proposed

    result = apply_approved(register, source)

    assert result.applied == []
    assert result.escalated and "no replacement text" in result.escalated[0][1]


def test_a_page_edited_after_review_is_escalated_not_guessed(
    workspace: Path, register: Register
) -> None:
    """Somebody rewrote the passage between the sweep and the approval.

    The anchor is re-resolved by heading path and content hash, so this is
    detected rather than being written over.
    """
    source = LocalSource(workspace)
    finding = next(f for f in seed(register, source, "1001") if f.subject.endswith(":threshold"))
    approve(register, finding, "1.2s")

    document = source.read("1001")
    rewritten = document.body.replace(
        "stays above <strong>800ms</strong> for 10 minutes",
        "is now tracked in the SLO document instead",
    )
    source.write("1001", rewritten, document.version)

    result = apply_approved(register, source)

    assert result.applied == []
    assert result.escalated
    assert "changed after this was reviewed" in result.escalated[0][1]


def test_a_version_conflict_stops_the_write(workspace: Path, register: Register) -> None:
    source = LocalSource(workspace)
    document = source.read("1001")
    with pytest.raises(VersionConflict):
        source.write("1001", document.body + "<p>x</p>", document.version + 5)


# ------------------------------------------------------ multi-page batches ----


def test_a_batch_that_fails_halfway_rolls_the_earlier_pages_back(
    workspace: Path, register: Register
) -> None:
    """Rule 7, as far as it can honestly be kept without a transaction.

    The second page's write fails; the first page must be restored, and the
    result must say so rather than reporting a partial success.
    """
    source = LocalSource(workspace)
    before_1001 = source.read("1001").body
    before_1007 = source.read("1007").body

    first = next(f for f in seed(register, source, "1001") if f.subject.endswith(":threshold"))
    second = next(f for f in seed(register, source, "1007") if f.subject.endswith(":threshold"))
    approve(register, first, "1.2s")
    approve(register, second, "1.2s")

    real_write = source.write
    calls: list[str] = []

    def failing_write(page_id: str, body: str, expected_version: int) -> int:
        calls.append(page_id)
        if page_id == "1007" and len(calls) == 2:
            raise VersionConflict("somebody else got there first")
        return real_write(page_id, body, expected_version)

    source.write = failing_write  # type: ignore[method-assign]
    result = apply_approved(register, source)

    assert result.conflicts == ["1007"]
    assert result.rolled_back == ["1001"]
    assert result.applied == []
    assert source.read("1001").body == before_1001, "the first page was not restored"
    assert source.read("1007").body == before_1007
    assert register.approved_unapplied(), "the work must survive for the next run"


def test_every_version_a_failed_batch_produced_is_in_the_ledger(
    workspace: Path, register: Register
) -> None:
    """Rule 6 on the path that used to leak it.

    A batch that fails on its second page has already bumped the first page's
    version, and rolling it back bumps it again. Both are versions this tool
    caused. The ledger used to be written only in the transaction that closes a
    fully successful batch, so neither was recorded and the watcher read its own
    two writes as somebody else's edits — then swept on them, which is the loop
    the ledger exists to stop.
    """
    source = LocalSource(workspace)
    first = next(f for f in seed(register, source, "1001") if f.subject.endswith(":threshold"))
    second = next(f for f in seed(register, source, "1007") if f.subject.endswith(":threshold"))
    approve(register, first, "1.2s")
    approve(register, second, "1.2s")

    started_at = source.read("1001").version
    real_write = source.write
    calls: list[str] = []

    def failing_write(page_id: str, body: str, expected_version: int) -> int:
        calls.append(page_id)
        if page_id == "1007":
            raise VersionConflict("somebody else got there first")
        return real_write(page_id, body, expected_version)

    source.write = failing_write  # type: ignore[method-assign]
    result = apply_approved(register, source)

    assert result.rolled_back == ["1001"]
    landed = source.read("1001").version
    assert landed > started_at + 1, "the edit and its compensation are two versions"
    for version in range(started_at + 1, landed + 1):
        assert register.wrote_version("1001", version), (
            f"version {version} of page 1001 was written by this tool and is not in the ledger"
        )


def test_a_failed_rollback_is_reported_as_stranded_not_swallowed(
    workspace: Path, register: Register
) -> None:
    """The case the design cannot fix, and therefore has to be loud about."""
    source = LocalSource(workspace)
    first = next(f for f in seed(register, source, "1001") if f.subject.endswith(":threshold"))
    second = next(f for f in seed(register, source, "1007") if f.subject.endswith(":threshold"))
    approve(register, first, "1.2s")
    approve(register, second, "1.2s")

    real_write = source.write
    calls: list[str] = []

    def hostile_write(page_id: str, body: str, expected_version: int) -> int:
        calls.append(page_id)
        if page_id == "1007":
            raise VersionConflict("conflict")
        if calls.count("1001") > 1:  # the rollback attempt
            raise VersionConflict("and the rollback fails too")
        return real_write(page_id, body, expected_version)

    source.write = hostile_write  # type: ignore[method-assign]
    result = apply_approved(register, source)

    assert result.stranded == ["1001"]
    assert not result.ok
    assert "STRANDED" in result.summary_line()


# --------------------------------------------------------------- the resume --


def test_a_crash_between_the_write_and_the_record_is_detected(
    workspace: Path, register: Register
) -> None:
    """The window that makes naive retry write twice.

    The page was updated; the register never heard. On the next run the anchor
    does not resolve *because the fix is already there*, and that specific
    shape — the proposal present, the old value gone, same heading — is what
    distinguishes "already done" from "somebody else edited this".
    """
    source = LocalSource(workspace)
    finding = next(f for f in seed(register, source, "1001") if f.subject.endswith(":threshold"))
    approve(register, finding, "1.2s")

    document = source.read("1001")
    claim = register.claim(finding.claim_id)
    block = document.find_block(claim.anchor.heading_path, claim.anchor.content_hash)
    at = block.text.index("800ms")
    start, end = block.body_range(at, at + 5)
    from reconciler.confluence.splice import splice

    source.write("1001", splice(document.body, start, end, "1.2s"), document.version)
    body_after_crash = source.read("1001").body

    result = apply_approved(register, source)

    assert result.already_applied == [finding.finding_id]
    assert result.applied == []
    assert source.read("1001").body == body_after_crash, "it must not have written twice"
    assert register.finding(finding.finding_id).applied_at is not None


def test_a_successful_write_is_recorded_as_ours(workspace: Path, register: Register) -> None:
    """Rule 6's other end: the watcher can only ignore what apply recorded.

    Without this row the watcher sees the version bump its own sweep caused,
    treats it as somebody's edit, and sweeps again — forever. The version
    recorded has to be the one the page ended up at, not the one it was read at.
    """
    source = LocalSource(workspace)
    finding = next(f for f in seed(register, source, "1001") if f.subject.endswith(":threshold"))
    version_before = source.read("1001").version
    approve(register, finding, "1.2s")

    apply_approved(register, source)

    version_after = source.read("1001").version
    assert version_after == version_before + 1
    assert register.wrote_version("1001", version_after)
    assert not register.wrote_version("1001", version_before)


def test_a_write_that_never_landed_is_not_recorded_as_ours(
    workspace: Path, register: Register
) -> None:
    """A conflict means somebody else's version is current.

    Recording it as ours anyway would make the watcher ignore a real edit by a
    real person — the one failure mode of a version ledger, and the reason the
    row is written after the PUT returns rather than alongside it.

    The conflict has to be injected at the write itself: `_prepare` re-reads the
    page, so an edit that landed *before* apply started is not a conflict, it is
    just the current version.
    """
    source = LocalSource(workspace)
    finding = next(f for f in seed(register, source, "1001") if f.subject.endswith(":threshold"))
    approve(register, finding, "1.2s")
    current = source.read("1001").version

    def conflicting_write(page_id: str, body: str, expected_version: int) -> int:
        raise VersionConflict("somebody else got there first")

    source.write = conflicting_write  # type: ignore[method-assign]
    result = apply_approved(register, source)

    assert result.conflicts == ["1001"]
    assert not register.wrote_version("1001", current)
    assert not register.wrote_version("1001", current + 1)
    assert register.approved_unapplied(), "the work must survive for the next run"


# ------------------------------------------------------------- assertions ----


def test_everything_outside_the_approved_passages_must_be_identical() -> None:
    old = "<p>alpha</p><p>beta</p><p>gamma</p>"
    edits = [
        (old.index("alpha"), old.index("alpha") + 5, "ALPHA"),
        (old.index("gamma"), old.index("gamma") + 5, "GAMMA"),
    ]
    good = "<p>ALPHA</p><p>beta</p><p>GAMMA</p>"
    assert_only_these_ranges_changed(old, good, edits)

    meddled = "<p>ALPHA</p><p>BETA</p><p>GAMMA</p>"
    with pytest.raises(SpliceRefused, match="outside every approved passage"):
        assert_only_these_ranges_changed(old, meddled, edits)


def test_overlapping_approved_passages_are_refused() -> None:
    with pytest.raises(SpliceRefused, match="overlap"):
        assert_only_these_ranges_changed("abcdef", "abcdef", [(1, 4, "x"), (3, 5, "y")])


def test_a_character_diff_can_split_one_logical_edit() -> None:
    """Why the page-level assertion reconstructs rather than counts.

    `rollback-production` and `manual-rollback` share `ll`, `back` and `o`, so a
    character-level diff reports one rename as three changed ranges. Counting
    them would have refused a correct two-edit page.
    """
    ranges = changed_ranges(
        "<p>run the rollback-production job</p>", "<p>run the manual-rollback job</p>"
    )
    assert len(ranges) > 1


def test_both_copies_of_a_repeated_value_are_corrected(
    workspace: Path, register: Register
) -> None:
    """Two identical wrong values in one paragraph are two edits, not one twice.

    `str.find` used to answer both anchors with the first occurrence, so the
    page came back with one value corrected, one still wrong, and two findings
    marked applied. The ordinal is carried on the claim and sought here, and the
    end-of-page assertion proves the two splices landed in different places.
    """
    page = workspace / "9100.storage.xhtml"
    page.write_text(
        "<h2>Latency</h2>\n<p>PaymentsApiHighLatency fires when p99 latency stays above "
        "800ms. The mirrored rule in the failover region also pages above 800ms.</p>",
        encoding="utf-8",
    )
    (workspace / "9100.page.json").write_text(
        '{"id": "9100", "title": "Mirrored latency", "version": {"number": 1}}\n',
        encoding="utf-8",
    )

    source = LocalSource(workspace)
    before = source.read("9100").body
    findings = [
        f
        for f in seed(register, source, "9100")
        if f.subject == "alert:PaymentsApiHighLatency:threshold"
    ]
    assert len(findings) == 2

    for finding in findings:
        approve(register, finding, "1.2s")

    result = apply_approved(register, source)

    assert sorted(result.applied) == sorted(f.finding_id for f in findings)
    after = source.read("9100").body
    assert "800ms" not in after
    assert after.count("1.2s") == 2
    assert len(changed_ranges(before, after)) == 2
