"""Top-level orchestration entry points used by the API layer.

The single place lock/generate/verify are called from. The CLI (__main__.py)
and any future FastAPI route both call these functions; neither reimplements
the sequence itself.
"""

from __future__ import annotations

from pathlib import Path

from . import amend as amend_module
from . import config as config_module
from . import corelock
from . import packs
from . import sections as sections_module
from .ledger import Ledger, apply_limit
from .mcp_client import SuperDocsClient


def lock_core(
    manifest: dict | None = None, language: str | None = None, version: int | None = None
) -> dict:
    """Lock the source-language master's core sections for one core_version.
    0 ops — arithmetic, never a SuperDocs call.

    `version` defaults to manifest['core_version'] (the current master at
    config/policy-master.md) but may name any prior version instead, in
    which case the text comes from the archived
    config/policy-master-v{version}.md (amend.archived_master_path) rather
    than the current file. This is only ever safe for the SOURCE language:
    a prior English lock is a pure re-hash of static, git-committed text,
    so re-deriving it always reproduces the exact same hash a first
    derivation would have — there is nothing non-deterministic in the path.
    It lets a lost state/core-lock-v{version}-{source_language}.json
    self-heal (relock_v2 does this) without ever risking a different hash
    than the one that would have been locked originally. It is NOT safe to
    use this to re-derive a lost lock for a translated language — that
    text only ever existed as a live SuperDocs translation, never as an
    archived file, so it cannot be reproduced deterministically here.
    """
    manifest = manifest if manifest is not None else config_module.load_manifest()
    language = language or manifest["source_language"]
    version = version if version is not None else manifest["core_version"]

    master_path = amend_module.archived_master_path(version, manifest)
    master_sections = sections_module.parse_sections(master_path.read_text(encoding="utf-8"))
    sections_module.assert_matches_manifest(master_sections, manifest)

    core_numbers = {s["number"] for s in manifest["sections"] if s["role"] == "core"}
    core_sections = [s for s in master_sections if s["number"] in core_numbers]

    lock_data = corelock.lock(core_sections, version, language)
    corelock.save_lock(lock_data)
    return lock_data


async def relock_v2(
    *,
    manifest: dict | None = None,
    ledger: Ledger | None = None,
    client_factory=SuperDocsClient,
) -> dict:
    """Re-lock the core at manifest['core_version'] across every language a
    configured country actually uses — the source language directly
    (lock_core, 0 ops, arithmetic), every other language via
    amend.retranslate_changed_sections (1 op the first time a language is
    re-locked at this version, 0 thereafter — idempotent per (language,
    from_version, to_version), so a language already re-locked in an
    earlier run costs nothing here).

    Zero packs are touched. This only produces
    state/core-lock-v{to_version}-{lang}.json files — the same artifact
    lock_core has always produced for the source language, now derived for
    every other language too. Generating a pack from this lock is a
    separate, later decision (packs.generate_pack); this function makes no
    such decision.
    """
    manifest = manifest if manifest is not None else config_module.load_manifest()
    ledger = ledger if ledger is not None else Ledger()
    source_language = manifest["source_language"]
    to_version = manifest["core_version"]
    from_version = to_version - 1

    lock_core(manifest=manifest)  # source language, 0 ops

    if not corelock.lock_exists(from_version, source_language):
        # state/ lost the pre-amendment source-language lock (e.g. a wiped
        # or fresh state/ directory) — safe to self-heal: see lock_core's
        # docstring for why this can never produce a different hash than
        # whatever was originally locked. 0 ops; no SuperDocs call.
        lock_core(manifest=manifest, version=from_version)

    diff = amend_module.diff_core_versions(manifest, source_language, from_version, to_version)

    countries = config_module.load_all_countries()
    other_languages = sorted({c["language"] for c in countries.values()} - {source_language})

    locks = {source_language: corelock.load_lock(to_version, source_language)}
    for language in other_languages:
        locks[language] = await amend_module.retranslate_changed_sections(
            manifest, language, diff, ledger=ledger, client_factory=client_factory
        )

    return {"diff": diff, "locks": locks}


def verify_after_amendment(
    country_codes: list[str],
    *,
    manifest: dict | None = None,
    from_version: int | None = None,
    out_dir: Path = packs.OUT_DIR,
) -> dict:
    """Re-verify every pack after a core amendment WITHOUT reissuing any of
    them, and confirm the newly re-locked core is structurally consistent
    across every affected language.

    Two independent checks:

    1. Every pack is re-verified against `from_version` — the core_version
       it was ACTUALLY generated at — never manifest['core_version']
       (the new one). No pack is reissued by an amendment; that is the
       entire point of a change notice. A pack passing here (via the
       existing verify()/packs.verify_pack()) proves its core is exactly
       what it always was and every annex section is still fully
       localised — i.e. the amendment touched nothing about any pack.
       "Confirm annexes are untouched" is this half.
    2. For every language present among `country_codes`, the just-relocked
       core at manifest['core_version'] is checked for cross-language
       consistency: amend.diff_core_versions(manifest, language,
       from_version, to_version) must report the SAME changed/unchanged
       section numbers as the source-language diff — proving
       retranslate_changed_sections correctly carried every unchanged
       section forward, in every language, not just the one language
       exercised live when it was first built.
    """
    manifest = manifest if manifest is not None else config_module.load_manifest()
    to_version = manifest["core_version"]
    from_version = from_version if from_version is not None else to_version - 1
    pinned_manifest = {**manifest, "core_version": from_version}

    packs_result = {code: verify(code, manifest=pinned_manifest, out_dir=out_dir) for code in country_codes}
    all_packs_pass = all(r["passed"] for r in packs_result.values())
    all_annexes_untouched = all(not r["unlocalised_annex_sections"] for r in packs_result.values())

    countries = config_module.load_all_countries()
    languages_present = sorted({countries[code]["language"] for code in country_codes})
    source_diff = amend_module.diff_core_versions(
        manifest, manifest["source_language"], from_version, to_version
    )

    core_v2_identity = {}
    for language in languages_present:
        diff = amend_module.diff_core_versions(manifest, language, from_version, to_version)
        core_v2_identity[language] = {
            "changed_sections": diff["changed_sections"],
            "unchanged_sections": diff["unchanged_sections"],
            "matches_source": (
                diff["changed_sections"] == source_diff["changed_sections"]
                and diff["unchanged_sections"] == source_diff["unchanged_sections"]
            ),
        }
    all_v2_identity_consistent = all(v["matches_source"] for v in core_v2_identity.values())

    return {
        "from_version": from_version,
        "to_version": to_version,
        "packs": packs_result,
        "all_packs_pass": all_packs_pass,
        "all_annexes_untouched": all_annexes_untouched,
        "core_v2_identity": core_v2_identity,
        "all_v2_identity_consistent": all_v2_identity_consistent,
    }


async def regenerate_pack_at_version(
    country_code: str,
    version: int,
    *,
    ledger: Ledger,
    manifest: dict | None = None,
    out_dir: Path = packs.OUT_DIR,
    client_factory=SuperDocsClient,
    downloader=packs._default_downloader,
) -> dict:
    """Explicit state-repair path, never called by the normal rollout or
    amendment flow: regenerate a country's pack against a prior core_version,
    for when state/out was lost or corrupted and the currently-shipped pack
    no longer represents that version (e.g. it holds the current, amended
    core instead of the pre-amendment one verify_after_amendment expects, or
    was generated from a translation that has since been re-derived).
    Neither run() nor run_amendment() ever reissues a pack — that guarantee
    is the whole point of the amendment design — so this exists only to
    correct a pack that already, wrongly, was, not to make reissuing
    routine.

    Two cases, per _assemble_upload_document's own split:
    - Source language: the core is a pure re-hash of archived, static text
      (amend.archived_master_path), so this is always safe and free (0 ops)
      to regenerate against — self-heals lock_core if needed.
    - Every other language: the core is never read from a file at all — it
      reads whatever is CURRENTLY locked for this language at `version`
      (corelock.load_lock via _translated_core_sections), which must
      already exist (from translate.derive_core or
      amend.retranslate_changed_sections's self-heal). This function does
      not derive one on your behalf: a translation is a real operation, and
      silently spending one here would hide that cost from the caller.
    """
    manifest = manifest if manifest is not None else config_module.load_manifest()
    country = config_module.load_country(config_module.COUNTRIES_DIR / f"{country_code}.yaml")
    pinned_manifest = {**manifest, "core_version": version}

    if country["language"] == manifest["source_language"]:
        master_path = amend_module.archived_master_path(version, manifest)
        lock_core(manifest=manifest, version=version)  # ensure the lock this pack verifies against exists; 0 ops
    else:
        master_path = None
        if not corelock.lock_exists(version, country["language"]):
            raise ValueError(
                f"No v{version} lock exists yet for language {country['language']!r} — "
                f"nothing to regenerate {country_code!r}'s pack against. Fix: run the "
                "amendment (or translate.derive_core) for this language first."
            )

    return await packs.generate_pack(
        country_code,
        ledger=ledger,
        manifest=pinned_manifest,
        country=country,
        out_dir=out_dir,
        client_factory=client_factory,
        downloader=downloader,
        master_path=master_path,
    )


async def generate(
    country_code: str,
    *,
    ledger: Ledger,
    manifest: dict | None = None,
    out_dir: Path = packs.OUT_DIR,
) -> dict:
    """Generate one country's pack. Thin wrapper over packs.generate_pack —
    the entry point everything else calls, so nothing reimplements it."""
    manifest = manifest if manifest is not None else config_module.load_manifest()
    return await packs.generate_pack(country_code, ledger=ledger, manifest=manifest, out_dir=out_dir)


def verify(country_code: str, manifest: dict | None = None, out_dir: Path = packs.OUT_DIR) -> dict:
    """Re-verify an already-generated pack on disk against the locked core."""
    manifest = manifest if manifest is not None else config_module.load_manifest()
    country = config_module.load_country(config_module.COUNTRIES_DIR / f"{country_code}.yaml")
    markdown_filename = next(filename for fmt, filename in packs._EXPORT_FILES if fmt == "markdown")
    pack_path = out_dir / country_code / markdown_filename
    markdown_text = pack_path.read_text(encoding="utf-8")
    return packs.verify_pack(markdown_text, manifest, country["language"])


def integrity_report(
    country_codes: list[str], manifest: dict | None = None, out_dir: Path = packs.OUT_DIR
) -> dict:
    """Build the integrity report: core identity per language, proved from
    every generated pack's actual exported core, not assumed from the lock.

    For each language present in `country_codes`, `expected` is the locked
    core_hash (corelock.load_lock) and `identical` is True only if every
    pack in that language, re-hashed from its own export, matches it —
    the same mechanism packs.verify_pack uses per pack, aggregated here
    across the whole run.
    """
    manifest = manifest if manifest is not None else config_module.load_manifest()
    core_version = manifest["core_version"]
    markdown_filename = next(filename for fmt, filename in packs._EXPORT_FILES if fmt == "markdown")

    annex_slots = [s["slot"] for s in manifest["sections"] if s["role"] == "annex" and s["slot"] != "acknowledgement"]
    slot_by_number = {s["number"]: s["slot"] for s in manifest["sections"] if s["role"] == "annex"}
    annex_bodies: dict[str, dict[str, str]] = {slot: {} for slot in annex_slots}

    languages: dict[str, int] = {}
    core_identity: dict[str, dict] = {}
    all_pass = True

    for code in country_codes:
        country = config_module.load_country(config_module.COUNTRIES_DIR / f"{code}.yaml")
        language = country["language"]
        languages[language] = languages.get(language, 0) + 1

        markdown_text = (out_dir / code / markdown_filename).read_text(encoding="utf-8")
        verification = packs.verify_pack(markdown_text, manifest, language)
        all_pass = all_pass and verification["passed"]

        actual_hash = corelock.lock(
            verification["exported_core_sections"], core_version, language
        )["core_hash"]
        entry = core_identity.setdefault(
            language,
            {"expected": corelock.load_lock(core_version, language)["core_hash"], "packs": [], "identical": True},
        )
        entry["packs"].append(code)
        if actual_hash != entry["expected"]:
            entry["identical"] = False

        for section in sections_module.parse_sections(markdown_text):
            slot = slot_by_number.get(section["number"])
            if slot in annex_bodies:
                annex_bodies[slot][code] = corelock.normalise(section["body"])

    for entry in core_identity.values():
        entry["packs"].sort()

    # Counted, not claimed: the same normalise() lock/verify use, so a
    # cosmetic export difference never inflates the distinct count — only a
    # genuine content difference does. acknowledgement is excluded: it is
    # deterministic office/date/name fields, not a claim about country
    # specificity, and would trivially read as "N distinct" for the wrong
    # reason (every office name differs).
    annex_divergence = {
        slot: f"{len(set(bodies.values()))} distinct" for slot, bodies in annex_bodies.items()
    }

    return {
        "core_version": core_version,
        "packs": len(country_codes),
        "languages": languages,
        "core_identity": core_identity,
        "all_packs_pass": all_pass,
        "annex_divergence": annex_divergence,
    }


async def run(
    country_codes: list[str],
    *,
    limit: int | None = None,
    out_dir: Path = packs.OUT_DIR,
    ledger: Ledger | None = None,
) -> dict:
    """Lock the core, then generate a pack per country (respecting --limit).

    Loads the persisted ledger so a resumed run does not double-count, and
    saves it back at the end. This is what the CLI's `run` command calls.

    A caller may pass its own `ledger` instead (e.g. the API's background
    run tracker, which holds a reference to it so a concurrent status
    request can read live entries while this coroutine is still running —
    the same object is mutated in place by every `ledger.record()` call
    made deep inside `generate()`/`packs.generate_pack`).
    """
    ledger = ledger if ledger is not None else Ledger.load()
    manifest = config_module.load_manifest()

    lock_core(manifest=manifest)

    codes = apply_limit(country_codes, limit)
    results = {}
    for code in codes:
        results[code] = await generate(code, ledger=ledger, manifest=manifest, out_dir=out_dir)

    ledger.save()
    return {"results": results, "ledger": ledger}


async def run_amendment(
    country_codes: list[str],
    *,
    client_factory=SuperDocsClient,
    ledger: Ledger | None = None,
) -> dict:
    """Propagate a core amendment to a set of countries: re-lock the core in
    every language they use, send each country its own change notice, then
    re-verify every pack against the version it was actually generated at
    to confirm no pack was reissued. What the API's amendment run calls;
    the CLI has no equivalent command yet, so this is the one place the
    sequence lives.

    Loads the persisted ledger so a resumed run does not double-count, and
    saves it back at the end — the same discipline `run()` applies to a
    rollout. A caller may pass its own `ledger` for the same live-read
    reason documented on `run()`.
    """
    ledger = ledger if ledger is not None else Ledger.load()
    manifest = config_module.load_manifest()

    relocked = await relock_v2(manifest=manifest, ledger=ledger, client_factory=client_factory)
    diff = relocked["diff"]

    notices = {}
    for code in country_codes:
        notices[code] = await amend_module.send_change_notice(
            code, manifest, diff, ledger=ledger, client_factory=client_factory
        )

    verification = verify_after_amendment(
        country_codes, manifest=manifest, from_version=diff["from_version"]
    )

    ledger.save()
    return {"diff": diff, "notices": notices, "verification": verification, "ledger": ledger}
