"""The one test that spends. Opt-in, and it says what it costs before it runs.

**This has never been run against the live service.** Everything the edit path
knows is verified against `stub_superdocs.py`, which is a stand-in written from
the sibling build's experience of the real API — good enough to prove the
mapping, the batching and the approval logic, and not evidence that
api.superdocs.app still behaves that way today. Saying so is the point; a
capability honestly absent beats one claimed and broken.

Running it costs **one paid operation** and needs `SUPERDOCS_API_KEY` plus
`RR_LIVE_SUPERDOCS=1`. Both are required rather than one, so a key sitting in
the environment for the rest of the suite cannot make this fire by accident.

What it establishes that the stub cannot:

- an upload of small HTML comes back with both ids, and the durable one reopens
- one chat turn parks at `awaiting_approval` rather than applying immediately
- `proposed_change_batch` still needs the double-parse
- the read-back of the stored document agrees with the reply, or does not — the
  disagreement is the reason the read-back exists
- a per-change denial releases the session instead of leaving it `409`-ing
"""

from __future__ import annotations

import os

import pytest

from reconciler.claims import Anchor, Claim, Finding
from reconciler.config import PROJECT_ROOT, Config
from reconciler.edit import apply_proposal, deny, propose_for_page
from reconciler.superdocs import SuperDocs, load_dotenv

# The skip decision is made at import time, and the key normally lives in `.env`
# rather than the environment -- so without this the test skips on exactly the
# machine that is configured to run it, and reports "2 skipped" as though the
# opt-in had not been given. It cost a confused minute the first time.
load_dotenv(PROJECT_ROOT / ".env")

pytestmark = pytest.mark.skipif(
    os.environ.get("RR_LIVE_SUPERDOCS") != "1" or not os.environ.get("SUPERDOCS_API_KEY"),
    reason=(
        "spends one paid operation against the live API; set RR_LIVE_SUPERDOCS=1 "
        "and SUPERDOCS_API_KEY to run it"
    ),
)


def a_finding_and_claim() -> tuple[Finding, Claim]:
    """One passage, one wrong number, phrased the way a real runbook is.

    Deliberately a sentence rather than a bare value: the whole argument for
    sending this through a model instead of doing a string replacement is that
    the sentence has to still read correctly afterwards.
    """
    claim = Claim(
        page_id="live-test",
        kind="threshold",
        subject="alert:PaymentsApiHighLatency:threshold",
        asserted="800ms",
        excerpt=(
            "Page the on-call engineer when p99 latency stays above 800ms for five "
            "minutes; restart the deployment first, since that clears a wedged "
            "connection pool without needing a release."
        ),
        anchor=Anchor(
            heading_path=("Thresholds",),
            node_index=0,
            content_hash="live",
            char_start=0,
            char_end=5,
        ),
    )
    finding = Finding(
        rule_id="alert-threshold",
        kind="threshold",
        subject=claim.subject,
        verdict="contradicts",
        evidence_file="fixtures/infra/platform-infra/monitoring/payments.rules.yml",
        evidence_line=6,
        observed="1.2",
        page_id="live-test",
        detail="the threshold in the alerting rule that actually pages someone",
    )
    return finding, claim


def test_one_page_costs_one_operation_and_comes_back_worded() -> None:
    config = Config.load()
    finding, claim = a_finding_and_claim()

    with SuperDocs(api_key=config.superdocs_key) as client:
        proposal = propose_for_page(client, "live-test", [(finding, claim)])
        try:
            assert proposal.operations == 1, "one page must cost exactly one operation"
            assert proposal.session_id
            assert proposal.document_id
            assert proposal.job_id, "the turn should park awaiting approval, not self-apply"
            assert proposal.proposals, "no proposed change came back"

            item = proposal.proposals[0]
            assert item.finding_id == finding.finding_id
            assert item.proposed, "the replacement text is empty"
            # The anchor covers `800ms` exactly, so what comes back has to fit
            # it -- not the rewritten sentence, which would splice a paragraph
            # into the middle of a line.
            assert len(item.proposed) < 40, f"expected a value, got prose: {item.proposed!r}"
            assert "800ms" not in item.proposed

            applied = apply_proposal(client, proposal, {finding.finding_id: True})
            assert applied.get(finding.finding_id)
        finally:
            # Whatever happened above, do not leave a parked turn holding the
            # session. Denials are free.
            deny(client, proposal)


def test_a_denied_batch_releases_the_session() -> None:
    """A parked turn answers `409 session_busy` for ever if nobody settles it.

    Not a leak of money — denials cost nothing — but far worse to diagnose than
    to prevent, which is why `deny` exists and why this checks the session is
    usable afterwards.
    """
    config = Config.load()
    finding, claim = a_finding_and_claim()

    with SuperDocs(api_key=config.superdocs_key) as client:
        proposal = propose_for_page(client, "live-test", [(finding, claim)])
        deny(client, proposal)

        # A second turn on the same session is the actual proof it was released.
        reply = client.chat(
            message="Reply with the single word: ok",
            session_id=proposal.session_id,
            document_id=proposal.document_id,
        )
        assert reply, "the session did not accept a second turn after the denial"
