"""Proves core translation is derived once per (core_version, language),
locked from the export, and never reaches the pack-generation core-naming
assertion — the one legitimate instruction path that names core sections."""

from __future__ import annotations

import asyncio

from pathlib import Path

from localizer import config as config_module
from localizer import corelock
from localizer import packs
from localizer import sections as sections_module
from localizer import translate
from localizer.ledger import Ledger

_TRANSLATED_PREFIX = "[FR] "


def _manifest():
    return config_module.load_manifest()


class _TranslatingFakeClient:
    """A fake client that actually mutates core section bodies to simulate a
    real translation, and tracks every call made — so tests can assert what
    was sent, not just what a response claims."""

    def __init__(self, manifest: dict):
        self.manifest = manifest
        self.calls: list[tuple[str, dict]] = []
        master_sections = sections_module.parse_sections(
            translate.POLICY_MASTER_PATH.read_text(encoding="utf-8")
        )
        self.body_by_number = {s["number"]: s["body"] for s in master_sections}
        self.heading_by_number = {s["number"]: s["heading"] for s in master_sections}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def upload(self, **kwargs):
        self.calls.append(("upload", kwargs))
        return {"session_id": kwargs.get("session_id")}

    async def chat(self, **kwargs):
        self.calls.append(("chat", kwargs))
        core_numbers = {s["number"] for s in self.manifest["sections"] if s["role"] == "core"}
        for number in core_numbers:
            self.body_by_number[number] = _TRANSLATED_PREFIX + self.body_by_number[number]
        return {
            "response": f"Translated {len(core_numbers)} sections.",
            "usage": {"was_billable": True, "ops_charged": 1},
        }

    def _current_markdown(self) -> str:
        lines = []
        for section in self.manifest["sections"]:
            lines.append(f"## {section['number']} {self.heading_by_number[section['number']]}")
            lines.append("")
            lines.append(self.body_by_number[section["number"]])
            lines.append("")
        return "\n".join(lines)

    async def export(self, **kwargs):
        self.calls.append(("export", kwargs))
        return {"text": self._current_markdown()}


def test_build_translation_instruction_names_every_core_section_and_no_annex_section():
    manifest = _manifest()

    instruction = translate._build_translation_instruction(manifest, "fr")

    for number in (1, 2, 3, 4, 5):
        assert f"Section {number} " in instruction
    for number in (6, 7, 8, 9):
        assert f"Section {number} " not in instruction
    assert "French" in instruction


def test_build_translation_instruction_falls_back_to_the_raw_code_for_an_unmapped_language():
    manifest = _manifest()

    instruction = translate._build_translation_instruction(manifest, "es")

    assert "into es," in instruction  # adding a language costs no code change


def test_derive_core_rejects_the_source_language():
    manifest = _manifest()

    raised = False
    try:
        asyncio.run(translate.derive_core("en", manifest=manifest))
    except ValueError as exc:
        raised = True
        assert "source language" in str(exc)
    assert raised


def test_derive_core_returns_a_lock_covering_only_the_core_sections(tmp_path, monkeypatch):
    manifest = _manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path)
    fake_client = _TranslatingFakeClient(manifest)

    lock_data = asyncio.run(
        translate.derive_core("fr", manifest=manifest, client_factory=lambda: fake_client)
    )

    assert lock_data["language"] == "fr"
    assert lock_data["core_version"] == manifest["core_version"]
    assert sorted(lock_data["section_numbers"]) == [1, 2, 3, 4, 5]
    assert sorted(lock_data["section_hashes"]) == ["1", "2", "3", "4", "5"]
    assert "core_hash" in lock_data


def test_derive_core_writes_the_lock_to_state_and_it_reloads_identically(tmp_path, monkeypatch):
    manifest = _manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path)
    fake_client = _TranslatingFakeClient(manifest)

    lock_data = asyncio.run(
        translate.derive_core("fr", manifest=manifest, client_factory=lambda: fake_client)
    )

    lock_path = tmp_path / f"core-lock-v{manifest['core_version']}-fr.json"
    assert lock_path.exists()
    reloaded = corelock.load_lock(manifest["core_version"], "fr")
    assert reloaded == lock_data


def test_derive_core_never_translates_annex_sections(tmp_path, monkeypatch):
    manifest = _manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path)
    fake_client = _TranslatingFakeClient(manifest)

    asyncio.run(translate.derive_core("fr", manifest=manifest, client_factory=lambda: fake_client))

    for number in (6, 7, 8, 9):
        assert not fake_client.body_by_number[number].startswith(_TRANSLATED_PREFIX)


def test_derive_core_costs_exactly_one_operation(tmp_path, monkeypatch):
    manifest = _manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path)
    ledger = Ledger()
    fake_client = _TranslatingFakeClient(manifest)

    asyncio.run(
        translate.derive_core("fr", ledger=ledger, manifest=manifest, client_factory=lambda: fake_client)
    )

    assert ledger.total_operations == 1


def test_derive_core_is_cached_by_core_version_and_language(tmp_path, monkeypatch):
    manifest = _manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path)
    ledger = Ledger()
    fake_client = _TranslatingFakeClient(manifest)
    kwargs = dict(ledger=ledger, manifest=manifest, client_factory=lambda: fake_client)

    first = asyncio.run(translate.derive_core("fr", **kwargs))
    calls_after_first = len(fake_client.calls)
    ops_after_first = ledger.total_operations

    second = asyncio.run(translate.derive_core("fr", **kwargs))

    assert len(fake_client.calls) == calls_after_first  # no new SuperDocs calls
    assert ledger.total_operations == ops_after_first  # still 1, never 2
    assert second == first  # the identical locked text is reused, not re-derived


def test_derive_core_re_runs_when_the_lock_file_is_missing(tmp_path, monkeypatch):
    # Mirrors packs.generate_pack's idempotency guard: a stale ledger entry
    # with no lock file actually on disk must not skip real work.
    manifest = _manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path)
    ledger = Ledger()
    content_key = translate._content_key(manifest["core_version"], "fr")
    ledger.record("translate", "fr", chat_calls=0, wall_time=0.0, content_key=content_key)
    fake_client = _TranslatingFakeClient(manifest)

    asyncio.run(
        translate.derive_core("fr", ledger=ledger, manifest=manifest, client_factory=lambda: fake_client)
    )

    assert len(fake_client.calls) > 0


def test_translation_instruction_would_be_rejected_by_the_annex_editing_assertion():
    """Proves the translation instruction really does name core sections — and
    that packs.assert_no_core_sections_named, the guard that exists
    specifically to reject that, would correctly reject it."""
    manifest = _manifest()
    instruction = translate._build_translation_instruction(manifest, "fr")

    raised = False
    try:
        packs.assert_no_core_sections_named(instruction, manifest)
    except ValueError:
        raised = True
    assert raised


def test_translate_module_never_imports_packs():
    """A structural check, not a behavioural one: translate.py must never
    import packs.py, so packs.assert_no_core_sections_named — the guard
    built to reject exactly this module's instruction — is not just unused
    here but unreachable, regardless of what any docstring says about it.
    """
    source = Path(translate.__file__).read_text(encoding="utf-8")

    assert "import packs" not in source
    assert not hasattr(translate, "packs")
    assert not hasattr(translate, "assert_no_core_sections_named")
