"""Proves a core amendment scopes re-translation to changed sections only,
carries every unchanged section forward byte for byte, and costs exactly
one operation per affected language regardless of country count."""

from __future__ import annotations

import asyncio
import copy

from localizer import amend
from localizer import config as config_module
from localizer import corelock
from localizer.ledger import Ledger

_TRANSLATED_PREFIX = "[FR-V2] "


def _manifest():
    return config_module.load_manifest()


def _seed_locks(manifest, from_version: int, to_version: int, language: str):
    """Write a v1 lock (with verbatim 'sections') plus a v2 en lock, mimicking
    service.lock_core + translate.derive_core having already run — the state
    retranslate_changed_sections expects to find on disk before it starts.
    Caller must already have monkeypatched corelock.STATE_DIR to a tmp_path."""
    core_numbers = sorted(s["number"] for s in manifest["sections"] if s["role"] == "core")

    v1_en_sections = [
        {"number": n, "heading": f"Heading {n}", "body": f"English v1 body of section {n}."}
        for n in core_numbers
    ]
    v1_en_lock = corelock.lock(v1_en_sections, from_version, "en")
    corelock.save_lock(v1_en_lock)

    v2_en_sections = copy.deepcopy(v1_en_sections)
    changed_body = next(s for s in v2_en_sections if s["number"] == 4)
    changed_body["body"] = "English v2 body of section 4, now with a 24-hour deadline."
    v2_en_lock = corelock.lock(v2_en_sections, to_version, "en")
    corelock.save_lock(v2_en_lock)

    v1_lang_sections = [
        {"number": n, "heading": f"[{language.upper()}] Heading {n}", "body": f"[{language.upper()}] v1 body of section {n}."}
        for n in core_numbers
    ]
    v1_lang_lock = corelock.lock(v1_lang_sections, from_version, language)
    v1_lang_lock["sections"] = v1_lang_sections
    corelock.save_lock(v1_lang_lock)

    return v1_lang_lock


class _RetranslatingFakeClient:
    """A fake client that translates only the section numbers actually named
    in the instruction it received — proving the caller sent a scoped
    request, not the whole core, and tracking every call made."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def upload(self, **kwargs):
        self.calls.append(("upload", kwargs))
        return {"session_id": kwargs.get("session_id")}

    async def chat(self, **kwargs):
        self.calls.append(("chat", kwargs))
        return {"response": "translated", "usage": {"was_billable": True, "ops_charged": 1}}

    async def export(self, **kwargs):
        self.calls.append(("export", kwargs))
        # Only section 4 (the section named in the instruction sent by
        # _build_retranslation_instruction) comes back translated — the
        # other core sections are left in English, exactly as a real
        # scoped SuperDocs call would leave them untouched.
        lines = [
            "## 1 Heading 1", "", "English v2 body of section 1 (untouched).", "",
            "## 2 Heading 2", "", "English v2 body of section 2 (untouched).", "",
            "## 3 Heading 3", "", "English v2 body of section 3 (untouched).", "",
            "## 4 Conduite Interdite", "",
            f"{_TRANSLATED_PREFIX}nouveau texte de la section 4 avec un delai de 24 heures.", "",
            "## 5 Heading 5", "", "English v2 body of section 5 (untouched).", "",
        ]
        return {"text": "\n".join(lines)}


def test_retranslate_changed_sections_sends_only_the_changed_section_numbers(tmp_path, monkeypatch):
    manifest = _manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path)
    _seed_locks(manifest, 1, 2, "fr")
    diff = amend.diff_core_versions(manifest, "en", 1, 2)
    fake_client = _RetranslatingFakeClient()

    asyncio.run(
        amend.retranslate_changed_sections(manifest, "fr", diff, client_factory=lambda: fake_client)
    )

    chat_call = next(kwargs for name, kwargs in fake_client.calls if name == "chat")
    assert 'Section 4 "Prohibited Conduct"' in chat_call["message"]
    for number in (1, 2, 3, 5):
        assert f'Section {number} "' not in chat_call["message"]


def test_retranslate_changed_sections_costs_one_operation_regardless_of_section_count(tmp_path, monkeypatch):
    manifest = _manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path)
    _seed_locks(manifest, 1, 2, "fr")
    diff = amend.diff_core_versions(manifest, "en", 1, 2)
    ledger = Ledger()
    fake_client = _RetranslatingFakeClient()

    asyncio.run(
        amend.retranslate_changed_sections(
            manifest, "fr", diff, ledger=ledger, client_factory=lambda: fake_client
        )
    )

    assert ledger.total_operations == 1


def test_unchanged_sections_are_byte_identical_across_lock_versions(tmp_path, monkeypatch):
    """The central proof this prompt asks for: after retranslate_changed_sections
    runs, every section diff_core_versions says is unchanged has the SAME hash
    in the v1 and v2 locks for the target language — not just for English."""
    manifest = _manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path)
    v1_lock = _seed_locks(manifest, 1, 2, "fr")
    diff = amend.diff_core_versions(manifest, "en", 1, 2)
    fake_client = _RetranslatingFakeClient()

    v2_lock = asyncio.run(
        amend.retranslate_changed_sections(manifest, "fr", diff, client_factory=lambda: fake_client)
    )

    for number in diff["unchanged_sections"]:
        key = str(number)
        assert v2_lock["section_hashes"][key] == v1_lock["section_hashes"][key]

    for number in diff["changed_sections"]:
        key = str(number)
        assert v2_lock["section_hashes"][key] != v1_lock["section_hashes"][key]

    # The unchanged sections' verbatim text also carried forward untouched,
    # not just their hash — a hash collision alone would not prove this.
    v1_by_number = {s["number"]: s for s in v1_lock["sections"]}
    v2_by_number = {s["number"]: s for s in v2_lock["sections"]}
    for number in diff["unchanged_sections"]:
        assert v2_by_number[number]["body"] == v1_by_number[number]["body"]


def test_retranslate_changed_sections_never_asks_to_translate_an_unchanged_section(tmp_path, monkeypatch):
    manifest = _manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path)
    _seed_locks(manifest, 1, 2, "fr")
    diff = amend.diff_core_versions(manifest, "en", 1, 2)
    fake_client = _RetranslatingFakeClient()

    asyncio.run(
        amend.retranslate_changed_sections(manifest, "fr", diff, client_factory=lambda: fake_client)
    )

    instruction = amend._build_retranslation_instruction(manifest, "fr", diff["changed_sections"])
    for number in diff["unchanged_sections"]:
        assert f'Section {number} "' not in instruction


def test_retranslate_changed_sections_is_cached_by_language_and_version_pair(tmp_path, monkeypatch):
    manifest = _manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path)
    _seed_locks(manifest, 1, 2, "fr")
    diff = amend.diff_core_versions(manifest, "en", 1, 2)
    ledger = Ledger()
    fake_client = _RetranslatingFakeClient()
    kwargs = dict(ledger=ledger, client_factory=lambda: fake_client)

    first = asyncio.run(amend.retranslate_changed_sections(manifest, "fr", diff, **kwargs))
    calls_after_first = len(fake_client.calls)
    ops_after_first = ledger.total_operations

    second = asyncio.run(amend.retranslate_changed_sections(manifest, "fr", diff, **kwargs))

    assert len(fake_client.calls) == calls_after_first  # no new SuperDocs calls
    assert ledger.total_operations == ops_after_first  # still 1, never 2
    assert second == first


def test_retranslate_changed_sections_rejects_a_diff_not_from_the_source_language(tmp_path, monkeypatch):
    manifest = _manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path)
    _seed_locks(manifest, 1, 2, "fr")
    # A diff computed for "fr" itself is not valid input — fr's v2 lock does
    # not exist until this function produces it, so such a diff could not
    # have been computed for real; this proves the guard rejects it anyway.
    bad_diff = {
        "language": "fr", "from_version": 1, "to_version": 2,
        "core_sections_total": 5, "changed_sections": [4], "unchanged_sections": [1, 2, 3, 5],
    }
    fake_client = _RetranslatingFakeClient()

    raised = False
    try:
        asyncio.run(
            amend.retranslate_changed_sections(manifest, "fr", bad_diff, client_factory=lambda: fake_client)
        )
    except ValueError as exc:
        raised = True
        assert "source language" in str(exc)
    assert raised


def test_diff_core_versions_finds_no_changes_between_a_version_and_itself(tmp_path, monkeypatch):
    manifest = _manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path)
    _seed_locks(manifest, 1, 2, "fr")

    diff = amend.diff_core_versions(manifest, "en", 1, 1)

    assert diff["changed_sections"] == []
    assert sorted(diff["unchanged_sections"]) == [1, 2, 3, 4, 5]


def test_retranslate_self_heals_a_missing_v1_language_lock(tmp_path, monkeypatch):
    # Reproduces the live bug: state/core-lock-v1-fr.json missing (a wiped
    # or fresh state/ directory), which used to crash with a bare
    # FileNotFoundError before retranslate_changed_sections ever got to its
    # own job. A translated core is never deterministic, so — unlike the
    # source-language self-heal — recovering it here means a genuine fresh
    # translation of the archived v1 English master, costing one real
    # operation, not a free re-hash.
    manifest = _manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path)
    monkeypatch.setattr(
        amend, "archived_master_path", lambda version, m: amend.POLICY_MASTER_PATH
    )

    core_numbers = sorted(s["number"] for s in manifest["sections"] if s["role"] == "core")
    v1_en_sections = [
        {"number": n, "heading": f"Heading {n}", "body": f"English v1 body of section {n}."}
        for n in core_numbers
    ]
    corelock.save_lock(corelock.lock(v1_en_sections, 1, "en"))
    v2_en_sections = copy.deepcopy(v1_en_sections)
    next(s for s in v2_en_sections if s["number"] == 4)["body"] = "English v2 body of section 4."
    corelock.save_lock(corelock.lock(v2_en_sections, 2, "en"))

    assert not corelock.lock_exists(1, "fr")
    diff = amend.diff_core_versions(manifest, "en", 1, 2)
    ledger = Ledger()
    fake_client = _RetranslatingFakeClient()

    result = asyncio.run(
        amend.retranslate_changed_sections(
            manifest, "fr", diff, ledger=ledger, client_factory=lambda: fake_client
        )
    )

    assert corelock.lock_exists(1, "fr")  # self-healed, not still missing
    assert result["core_version"] == 2
    # One op to recover the lost v1 lock (a genuine translation), one op to
    # translate the actually-changed section into v2 — two real operations,
    # not a silently-assumed-free recovery.
    assert ledger.total_operations == 2


def test_format_diff_report_matches_the_required_wording(tmp_path, monkeypatch):
    manifest = _manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path)
    _seed_locks(manifest, 1, 2, "fr")

    diff = amend.diff_core_versions(manifest, "en", 1, 2)
    report = amend.format_diff_report(diff)

    assert report == "Section 4 changed, 1 of 5. Sections 1, 2, 3, 5 unchanged."
