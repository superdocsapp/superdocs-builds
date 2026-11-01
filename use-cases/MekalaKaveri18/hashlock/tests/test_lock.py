import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lock import SOURCE, fingerprints, offline_tighten, proof, tamper_locked


def test_source_has_three_locks():
    assert set(fingerprints(SOURCE)) == {
        "parties",
        "governing-law",
        "limitation-of-liability",
    }


def test_offline_tighten_holds_locks_and_changes_unlocked():
    after = offline_tighten(SOURCE)
    p = proof(SOURCE, after)
    assert p["verdict"] == "PASS"
    assert p["all_locks_held"] is True
    assert p["document_changed"] is True
    assert "Ninety days" in after
    assert "Acme Vendor Co." in after
    assert "laws of Singapore" in after


def test_tamper_fails_closed():
    after = tamper_locked(SOURCE)
    p = proof(SOURCE, after)
    assert p["verdict"] == "FAIL"
    held = {row["id"]: row["held"] for row in p["locks"]}
    assert held["parties"] is False
    assert held["governing-law"] is True
