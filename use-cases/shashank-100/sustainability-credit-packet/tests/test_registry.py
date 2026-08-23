"""Registry tests: evidence truth and status derivation. No API key, no network.

These cover the second grading criterion -- "the evidence index matches what is
really in the bundle" -- and the invariant that makes it hold: status is
derived from the filesystem, never authored.
"""

import shutil
from pathlib import Path

import pytest

import registry

PACKET = Path(__file__).parent.parent


@pytest.fixture
def bundle(tmp_path):
    """A disposable copy of the packet, so tests can delete evidence freely."""
    for item in ("credits.yaml", "corpus", "calc.py", "registry.py"):
        source = PACKET / item
        target = tmp_path / item
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    return tmp_path


class TestEvidenceIndexReflectsReality:
    def test_index_is_built_from_the_filesystem(self, bundle):
        scorecard = registry.load(bundle / "credits.yaml", root=bundle)
        water = scorecard.credit("WEc1")
        for item in water.evidence:
            expected = (bundle / "corpus" / "meridian" / item.file).is_file()
            assert item.present == expected

    def test_present_items_carry_a_real_location(self, bundle):
        scorecard = registry.load(bundle / "credits.yaml", root=bundle)
        for credit in scorecard.credits:
            for item in credit.evidence:
                if item.present:
                    assert Path(item.location).is_file()
                else:
                    assert item.location == "not in bundle"

    def test_deleting_evidence_changes_the_index_and_the_status(self, bundle):
        before = registry.load(bundle / "credits.yaml", root=bundle)
        assert before.credit("WEc1").status == registry.DOCUMENTED
        assert before.credit("WEc1").points_awarded == 4

        (bundle / "corpus" / "meridian" / "watersense_certificates.txt").unlink()

        after = registry.load(bundle / "credits.yaml", root=bundle)
        assert after.credit("WEc1").status == registry.EVIDENCE_OUTSTANDING
        assert after.credit("WEc1").points_awarded == 0
        # The maths itself is unchanged -- the credit still *earns* 4 points,
        # it just cannot claim them without the certificate.
        assert after.credit("WEc1").result.points == 4
        assert after.points_awarded == before.points_awarded - 4

    def test_restoring_evidence_restores_the_points(self, bundle):
        certificate = bundle / "corpus" / "meridian" / "watersense_certificates.txt"
        original = certificate.read_bytes()
        certificate.unlink()
        assert registry.load(bundle / "credits.yaml", root=bundle).points_awarded == 9

        certificate.write_bytes(original)
        assert registry.load(bundle / "credits.yaml", root=bundle).points_awarded == 13


class TestStatusCannotBeFaked:
    def test_cannot_mark_documented_while_evidence_is_missing(self, bundle):
        scorecard = registry.load(bundle / "credits.yaml", root=bundle)
        assert scorecard.credit("MRc2").status == registry.EVIDENCE_OUTSTANDING

        with pytest.raises(ValueError, match="cannot mark MRc2 documented"):
            registry.set_status(scorecard, "MRc2", registry.DOCUMENTED)

    def test_unknown_status_is_rejected(self, bundle):
        scorecard = registry.load(bundle / "credits.yaml", root=bundle)
        with pytest.raises(ValueError, match="unknown status"):
            registry.set_status(scorecard, "WEc1", "looks fine to me")

    def test_unknown_credit_is_rejected(self, bundle):
        scorecard = registry.load(bundle / "credits.yaml", root=bundle)
        with pytest.raises(KeyError):
            scorecard.credit("XXc9")


class TestStatusChangeMovesTheScorecard:
    """The card's headline mechanic, at the data layer."""

    def test_flagging_at_risk_removes_the_points(self, bundle):
        before = registry.load(bundle / "credits.yaml", root=bundle)
        assert before.points_awarded == 13

        after = registry.set_status(before, "EAc2", registry.AT_RISK)

        assert after.credit("EAc2").status == registry.AT_RISK
        assert after.credit("EAc2").points_awarded == 0
        assert after.points_awarded == 4
        assert after.points_at_risk == 11  # 9 at risk + 2 outstanding

    def test_the_original_scorecard_is_untouched(self, bundle):
        """set_status returns a new scorecard; the caller keeps the before."""
        before = registry.load(bundle / "credits.yaml", root=bundle)
        after = registry.set_status(before, "EAc2", registry.AT_RISK)

        assert before.credit("EAc2").status == registry.DOCUMENTED
        assert before.points_awarded == 13
        assert after is not before

    def test_clearing_a_risk_flag_restores_the_points(self, bundle):
        scorecard = registry.load(bundle / "credits.yaml", root=bundle)
        flagged = registry.set_status(scorecard, "EAc2", registry.AT_RISK)
        restored = registry.set_status(flagged, "EAc2", registry.DOCUMENTED)

        assert restored.credit("EAc2").status == registry.DOCUMENTED
        assert restored.points_awarded == 13

    def test_certification_level_follows_the_total(self, bundle):
        scorecard = registry.load(bundle / "credits.yaml", root=bundle)
        assert scorecard.level == "Not certified"
        assert not scorecard.meets_target
        assert scorecard.shortfall_to_target == 60 - 13


class TestRequirementTextIsAvailableForGrounding:
    """Criterion 1 depends on the requirement text being attachable."""

    def test_every_credit_can_read_its_requirement(self, bundle):
        scorecard = registry.load(bundle / "credits.yaml", root=bundle)
        for credit in scorecard.credits:
            text = credit.requirement_text
            assert len(text) > 200
            assert "Requirements" in text

    def test_requirement_text_contains_the_threshold_table(self, bundle):
        scorecard = registry.load(bundle / "credits.yaml", root=bundle)
        water = scorecard.credit("WEc1").requirement_text
        # The narrative must be able to quote the actual threshold it claims.
        assert "40%" in water and "4" in water
