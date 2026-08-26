"""Proves the integrity report aggregates per-language core identity from
each pack's actual exported core, not merely asserted from the lock."""

from __future__ import annotations

import asyncio

from localizer import config as config_module
from localizer import corelock
from localizer import packs
from localizer import sections as sections_module
from localizer import service


def _valid_pack_markdown(manifest: dict, country: dict) -> str:
    master_sections = sections_module.parse_sections(packs.POLICY_MASTER_PATH.read_text(encoding="utf-8"))
    body_by_number = {s["number"]: s["body"] for s in master_sections}
    lines = []
    for section in manifest["sections"]:
        lines.append(f"## {section['number']} {section['heading']}")
        lines.append("")
        if section["role"] == "core":
            lines.append(body_by_number[section["number"]])
        else:
            lines.append(packs._SLOT_RENDERERS[section["slot"]](country))
        lines.append("")
    return "\n".join(lines)


def _write_pack(out_dir, code: str, markdown: str) -> None:
    pack_dir = out_dir / code
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "policy-pack.md").write_text(markdown, encoding="utf-8")


def _lock_english_core(manifest: dict) -> None:
    master_sections = sections_module.parse_sections(packs.POLICY_MASTER_PATH.read_text(encoding="utf-8"))
    core_numbers = {s["number"] for s in manifest["sections"] if s["role"] == "core"}
    core_sections = [s for s in master_sections if s["number"] in core_numbers]
    corelock.save_lock(corelock.lock(core_sections, manifest["core_version"], "en"))


def test_integrity_report_marks_identical_core_across_two_english_packs(tmp_path, monkeypatch):
    manifest = config_module.load_manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path / "state")
    _lock_english_core(manifest)

    in_country = config_module.load_country(config_module.COUNTRIES_DIR / "IN.yaml")
    ke_country = config_module.load_country(config_module.COUNTRIES_DIR / "KE.yaml")
    out_dir = tmp_path / "out"
    _write_pack(out_dir, "IN", _valid_pack_markdown(manifest, in_country))
    _write_pack(out_dir, "KE", _valid_pack_markdown(manifest, ke_country))

    report = service.integrity_report(["IN", "KE"], manifest=manifest, out_dir=out_dir)

    assert report["core_version"] == manifest["core_version"]
    assert report["packs"] == 2
    assert report["languages"] == {"en": 2}
    assert report["core_identity"]["en"]["identical"] is True
    assert report["core_identity"]["en"]["packs"] == ["IN", "KE"]
    assert report["all_packs_pass"] is True


def test_integrity_report_flags_a_diverged_core_as_not_identical(tmp_path, monkeypatch):
    manifest = config_module.load_manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path / "state")
    _lock_english_core(manifest)

    in_country = config_module.load_country(config_module.COUNTRIES_DIR / "IN.yaml")
    ke_country = config_module.load_country(config_module.COUNTRIES_DIR / "KE.yaml")
    out_dir = tmp_path / "out"
    _write_pack(out_dir, "IN", _valid_pack_markdown(manifest, in_country))
    corrupted = _valid_pack_markdown(manifest, ke_country).replace(
        "Meridian Relief Trust (MRT) exists", "Meridian Relief Trust (MRT) no longer exists", 1
    )
    _write_pack(out_dir, "KE", corrupted)

    report = service.integrity_report(["IN", "KE"], manifest=manifest, out_dir=out_dir)

    assert report["core_identity"]["en"]["identical"] is False
    assert report["all_packs_pass"] is False


def test_integrity_report_counts_distinct_annex_content_per_slot(tmp_path, monkeypatch):
    manifest = config_module.load_manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path / "state")
    _lock_english_core(manifest)

    in_country = config_module.load_country(config_module.COUNTRIES_DIR / "IN.yaml")
    ke_country = config_module.load_country(config_module.COUNTRIES_DIR / "KE.yaml")
    out_dir = tmp_path / "out"
    _write_pack(out_dir, "IN", _valid_pack_markdown(manifest, in_country))
    _write_pack(out_dir, "KE", _valid_pack_markdown(manifest, ke_country))

    report = service.integrity_report(["IN", "KE"], manifest=manifest, out_dir=out_dir)

    assert report["annex_divergence"] == {
        "reporting": "2 distinct",
        "legal": "2 distinct",
        "escalation": "2 distinct",
    }
    assert "acknowledgement" not in report["annex_divergence"]


def test_integrity_report_counts_one_distinct_when_annex_content_matches(tmp_path, monkeypatch):
    # Two packs given the SAME country's annex content must count as one
    # distinct value per slot — proving the count reacts to real content,
    # not just to how many packs there are.
    manifest = config_module.load_manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path / "state")
    _lock_english_core(manifest)

    in_country = config_module.load_country(config_module.COUNTRIES_DIR / "IN.yaml")
    out_dir = tmp_path / "out"
    identical_markdown = _valid_pack_markdown(manifest, in_country)
    _write_pack(out_dir, "IN", identical_markdown)
    _write_pack(out_dir, "KE", identical_markdown)

    report = service.integrity_report(["IN", "KE"], manifest=manifest, out_dir=out_dir)

    assert report["annex_divergence"] == {
        "reporting": "1 distinct",
        "legal": "1 distinct",
        "escalation": "1 distinct",
    }


def test_relock_v2_self_heals_a_missing_source_language_v1_lock(tmp_path, monkeypatch):
    # Reproduces the live bug: state/core-lock-v1-en.json missing (a wiped
    # or fresh state/ directory), which used to crash diff_core_versions
    # with a bare FileNotFoundError before any operation was even attempted.
    # A prior-version SOURCE-language lock is always safely re-derivable
    # from the archived config/policy-master-v{version}.md — a pure re-hash
    # of static, git-committed text — so relock_v2 must self-heal it rather
    # than require it to have magically survived on disk.
    manifest = config_module.load_manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(
        service.config_module,
        "load_all_countries",
        lambda: {
            "IN": config_module.load_country(config_module.COUNTRIES_DIR / "IN.yaml"),
            "KE": config_module.load_country(config_module.COUNTRIES_DIR / "KE.yaml"),
        },
    )
    from_version, to_version = manifest["core_version"] - 1, manifest["core_version"]
    assert not corelock.lock_exists(from_version, manifest["source_language"])

    result = asyncio.run(service.relock_v2(manifest=manifest))

    assert corelock.lock_exists(from_version, manifest["source_language"])
    assert result["diff"]["from_version"] == from_version
    assert result["diff"]["to_version"] == to_version
    assert result["diff"]["changed_sections"] == [4]
    # English-only country set in this test: nothing needed translating, so
    # the self-heal (arithmetic) plus the v2 lock (also arithmetic for the
    # source language) must together cost nothing.
    assert result["locks"][manifest["source_language"]]["core_version"] == to_version


def test_relock_v2_self_healed_v1_lock_matches_a_freshly_locked_v1(tmp_path, monkeypatch):
    # The self-heal must reproduce the exact hash a direct v1 lock would —
    # never a different one — since both hash the same archived, static text
    # through the same pure lock() function. Computed in two independent
    # state dirs so relock_v2 is genuinely forced through the self-heal
    # path in the second, rather than finding an already-present v1 lock.
    manifest = config_module.load_manifest()
    from_version = manifest["core_version"] - 1

    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path / "state-direct")
    direct = service.lock_core(manifest=manifest, version=from_version)

    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path / "state-healed")
    monkeypatch.setattr(
        service.config_module,
        "load_all_countries",
        lambda: {"IN": config_module.load_country(config_module.COUNTRIES_DIR / "IN.yaml")},
    )
    asyncio.run(service.relock_v2(manifest=manifest))
    healed = corelock.load_lock(from_version, manifest["source_language"])

    assert healed["core_hash"] == direct["core_hash"]
    assert healed["section_hashes"] == direct["section_hashes"]
