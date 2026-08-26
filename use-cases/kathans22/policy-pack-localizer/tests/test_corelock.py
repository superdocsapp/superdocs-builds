"""Proves the core-lock mechanism: identity, sensitivity, and normalisation resilience."""

from __future__ import annotations

from pathlib import Path

from localizer import corelock, sections

FIXTURES = Path(__file__).parent / "fixtures"


def _core_sections(path: Path) -> list[dict]:
    return [s for s in sections.load_sections(path) if s["number"] <= 5]


def test_identical_core_in_two_different_files_produces_identical_hash():
    # fixture_a and fixture_b share byte-identical core sections 1-5 but have
    # completely different annex sections 6-9 — they are genuinely different files.
    core_a = _core_sections(FIXTURES / "policy_fixture_a.md")
    core_b = _core_sections(FIXTURES / "policy_fixture_b.md")

    lock_a = corelock.lock(core_a, core_version=1, language="en")
    lock_b = corelock.lock(core_b, core_version=1, language="en")

    assert lock_a["core_hash"] == lock_b["core_hash"]
    assert lock_a["section_hashes"] == lock_b["section_hashes"]


def test_core_edit_changes_only_that_section_and_the_core_hash():
    core = _core_sections(FIXTURES / "policy_fixture_a.md")
    baseline = corelock.lock(core, core_version=1, language="en")

    mutated = [dict(s) for s in core]
    mutated[3] = dict(mutated[3], body=mutated[3]["body"].replace("exploit", "endorse"))
    changed = corelock.lock(mutated, core_version=1, language="en")

    assert changed["section_hashes"]["4"] != baseline["section_hashes"]["4"]
    for number in ("1", "2", "3", "5"):
        assert changed["section_hashes"][number] == baseline["section_hashes"][number]
    assert changed["core_hash"] != baseline["core_hash"]


def test_annex_edit_changes_neither_core_section_hash_nor_core_hash():
    all_sections = sections.load_sections(FIXTURES / "policy_fixture_a.md")
    core = [s for s in all_sections if s["number"] <= 5]
    baseline = corelock.lock(core, core_version=1, language="en")

    mutated_all = [dict(s) for s in all_sections]
    mutated_all[5] = dict(
        mutated_all[5], body="An entirely rewritten reporting channel, unrelated to fixture A."
    )
    # Section 6 (annex) was rewritten above; the core sections fed to lock() are untouched.
    core_after_annex_edit = [s for s in mutated_all if s["number"] <= 5]
    after = corelock.lock(core_after_annex_edit, core_version=1, language="en")

    assert after["core_hash"] == baseline["core_hash"]
    assert after["section_hashes"] == baseline["section_hashes"]


# Round-trip resilience: each test isolates one cosmetic mutation the normaliser
# claims to absorb (see corelock.normalise's numbered contract) and proves the
# core_hash is unchanged between a clean and a noisy variant of the same text.
# One test per mutation, so a failure names the specific rule that broke.


def _lock_of(body: str) -> dict:
    section = [{"number": 1, "heading": "Test", "body": body}]
    return corelock.lock(section, core_version=1, language="en")


def test_roundtrip_survives_quote_style_change():
    straight = 'The term "Safeguarding Focal Point" reflects staff\'s duty to report.'
    curly = "The term “Safeguarding Focal Point” reflects staff’s duty to report."
    assert _lock_of(straight)["core_hash"] == _lock_of(curly)["core_hash"]


def test_roundtrip_survives_trailing_whitespace():
    clean = "First line of the clause.\nSecond line of the clause."
    noisy = "First line of the clause.   \nSecond line of the clause.\t\t"
    assert _lock_of(clean)["core_hash"] == _lock_of(noisy)["core_hash"]


def test_roundtrip_survives_blank_line_runs():
    clean = "First paragraph of core text.\n\nSecond paragraph of core text."
    noisy = "First paragraph of core text.\n\n\n\n\n\nSecond paragraph of core text."
    assert _lock_of(clean)["core_hash"] == _lock_of(noisy)["core_hash"]


def test_roundtrip_survives_line_endings():
    unix = "Line one of the clause.\nLine two continues the clause."
    windows = "Line one of the clause.\r\nLine two continues the clause."
    assert _lock_of(unix)["core_hash"] == _lock_of(windows)["core_hash"]


def test_roundtrip_survives_list_marker_style():
    clean = "Reports may include:\n- item one\n- item two"
    noisy = "Reports may include:\n* item one\n• item two"
    assert _lock_of(clean)["core_hash"] == _lock_of(noisy)["core_hash"]


def test_lock_exists_is_false_before_save_and_true_after(tmp_path, monkeypatch):
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path)

    assert corelock.lock_exists(core_version=1, language="fr") is False

    corelock.save_lock(_lock_of("Some translated core text.") | {"language": "fr"})

    assert corelock.lock_exists(core_version=1, language="fr") is True
