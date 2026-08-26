"""Status propagation across the bundle, and the two bugs that hid behind it.

The README's headline claim is that changing a credit's status updates the
scorecard and the narrative together. Nothing exercised that path, so it was
possible for `change_status` to call a prompt builder that no longer existed
and for the suite to stay green. These tests drive the real method against a
fake transport, so a signature drift fails here rather than in front of a user.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import calc
import packet
import prompts
import registry


class FakeSuperDocs:
    """Records what would have been sent, and hands back a plausible reply."""

    def __init__(self):
        self.calls = []

    def chat_async(self, message, session_id, *, stage="chat", **extra):
        self.calls.append({"message": message, "stage": stage, **extra})
        n = len(self.calls)
        return {
            "proposed_change_batch": [
                {"change_id": f"c{n}", "chunk_id": f"k{n}",
                 "original": "old", "replacement": "new"}
            ]
        }

    def changes_from(self, response):
        import client
        return client.SuperDocs.changes_from(self, response)


@pytest.fixture
def bundle():
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def pk(bundle):
    scorecard = registry.load(bundle / "credits.yaml", root=bundle)
    p = packet.Packet.__new__(packet.Packet)
    p.sd = FakeSuperDocs()
    p.session_id = "s-test"
    p.scorecard = scorecard
    p.documents = {
        "scorecard": packet.Document("scorecard", "Scorecard", "<p>cover</p>", "s-test", "doc-cover"),
        "WEc1": packet.Document("WEc1", "WEc1", "<p>narrative</p>", "s-test", "doc-wec1"),
    }
    p.unattached = []
    p.last_propagation = None
    return p


class TestStatusChangeReachesBothDocuments:
    """The claim the card is graded on: scorecard and narrative move together."""

    def test_change_status_sends_one_instruction_per_document(self, pk):
        after, changes = pk.change_status("WEc1", registry.AT_RISK)

        stages = [c["stage"] for c in pk.sd.calls]
        assert stages == ["propagate:scorecard", "propagate:WEc1"]
        assert len(changes) == 2, "changes from both documents must be returned"
        assert after.credit("WEc1").status == registry.AT_RISK

    def test_each_instruction_is_targeted_at_its_own_document(self, pk):
        pk.change_status("WEc1", registry.AT_RISK)

        # Untargeted edits are how a status change rewrites more than it should.
        assert pk.sd.calls[0]["document_id"] == "doc-cover"
        assert pk.sd.calls[1]["document_id"] == "doc-wec1"

    def test_the_prompt_builders_it_calls_actually_exist(self):
        # The original bug: packet.py called prompts.propagate(), which the
        # previous commit had split in two without updating the caller.
        assert hasattr(prompts, "propagate_scorecard")
        assert hasattr(prompts, "propagate_narrative")
        assert not hasattr(prompts, "propagate"), \
            "if this is reintroduced, packet.change_status must be updated with it"

    def test_a_missing_document_is_skipped_not_fatal(self, pk):
        del pk.documents["scorecard"]
        after, changes = pk.change_status("WEc1", registry.AT_RISK)
        assert [c["stage"] for c in pk.sd.calls] == ["propagate:WEc1"]
        assert len(changes) == 1


class TestAnAtRiskFlagCanBeLifted:
    """A credit flagged at risk must be able to return to its derived status."""

    def test_at_risk_can_be_cleared_when_evidence_is_still_missing(self, bundle):
        scorecard = registry.load(bundle / "credits.yaml", root=bundle)
        credit = next(c for c in scorecard.credits if c.missing_evidence)

        flagged = registry.set_status(scorecard, credit.id, registry.AT_RISK)
        assert flagged.credit(credit.id).status == registry.AT_RISK

        cleared = registry.set_status(flagged, credit.id, registry.EVIDENCE_OUTSTANDING)
        assert cleared.credit(credit.id).override is None
        assert cleared.credit(credit.id).status == registry.EVIDENCE_OUTSTANDING

    def test_clearing_does_not_let_an_incomplete_credit_claim_points(self, bundle):
        scorecard = registry.load(bundle / "credits.yaml", root=bundle)
        credit = next(c for c in scorecard.credits if c.missing_evidence)

        flagged = registry.set_status(scorecard, credit.id, registry.AT_RISK)
        cleared = registry.set_status(flagged, credit.id, registry.EVIDENCE_OUTSTANDING)
        assert cleared.credit(credit.id).points_awarded == 0

    def test_documented_is_still_refused_while_evidence_is_missing(self, bundle):
        scorecard = registry.load(bundle / "credits.yaml", root=bundle)
        credit = next(c for c in scorecard.credits if c.missing_evidence)
        with pytest.raises(ValueError, match="evidence is missing"):
            registry.set_status(scorecard, credit.id, registry.DOCUMENTED)


class TestEveryInstalledFixtureIsCounted:
    """A fixture in the schedule that the arithmetic ignores is a silent error."""

    def test_private_lavatories_enter_the_calculation(self, bundle):
        result = calc.indoor_water_reduction(
            bundle / "corpus/meridian/fixture_schedule.csv",
            bundle / "corpus/meridian/occupancy_assumptions.csv",
        )
        split = result.inputs["lavatory_split"]
        assert split["private_fixtures"] == 12
        assert split["private_share"] > 0, \
            "private lavatories were resolved but never billed"
        assert round(split["public_share"] + split["private_share"], 6) == 1.0

    def test_reported_rates_are_the_rates_actually_used(self, bundle):
        # Reporting a design rate to a reviewer that the sum never applied
        # is the kind of quiet inconsistency the evidence index exists to stop.
        result = calc.indoor_water_reduction(
            bundle / "corpus/meridian/fixture_schedule.csv",
            bundle / "corpus/meridian/occupancy_assumptions.csv",
        )
        assert result.inputs["design_flow_rates"]["private_lav"] == 1.20
        assert result.inputs["lavatory_split"]["private_share"] > 0

    def test_the_claimed_points_still_hold(self, bundle):
        result = calc.indoor_water_reduction(
            bundle / "corpus/meridian/fixture_schedule.csv",
            bundle / "corpus/meridian/occupancy_assumptions.csv",
        )
        # 41.69% clears the 40% threshold for 4 points with room to spare,
        # rather than the 40.55% the incomplete sum produced.
        assert result.value > 40.0
        assert result.points == 4
