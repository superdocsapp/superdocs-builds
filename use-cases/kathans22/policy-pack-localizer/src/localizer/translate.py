"""Translates the locked core per language, cached by (core_version, language).

For every language other than the source, the translated core is derived
exactly once per core_version and locked — every pack generated in that
language afterward (packs.generate_pack) reuses this locked text byte for
byte instead of re-translating. A second, third, or Nth country sharing a
language costs zero additional operations; see CLAUDE.md's operation
economics.

This module sends the one instruction in this codebase that legitimately
names core section numbers (_build_translation_instruction). Every other
instruction sent to SuperDocs — packs.build_instruction, used to localise a
pack's annex — must never name a core section, and
packs.assert_no_core_sections_named is a hard stop enforcing exactly that
before such an instruction is ever sent. Deriving a translation is different
in kind, not degree: it is not editing a shipped pack, it is producing the
one text every pack in `language` will carry afterward, and naming the core
sections is the only way to ask for precisely that translation and nothing
else.

This module deliberately never imports packs.py, so
packs.assert_no_core_sections_named is structurally unreachable from this
path — there is no code path by which a translation instruction could be
run through the assertion that exists specifically to reject it. The two
flows share only corelock, ledger, and mcp_client.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path

from . import config as config_module
from . import corelock
from . import sections as sections_module
from .ledger import Ledger, ops_from_response
from .mcp_client import SuperDocsClient, SuperDocsClientError

POLICY_MASTER_PATH = config_module.CONFIG_DIR / "policy-master.md"

# Falls back to the raw ISO code when a language isn't listed — adding a
# language must never require a code change here (CLAUDE.md rule 5); this
# dict only makes the instruction read naturally for the languages we know.
_LANGUAGE_NAMES = {"fr": "French", "pt": "Portuguese"}


def _build_translation_instruction(manifest: dict, language: str) -> str:
    """Build the one instruction in this codebase that legitimately names
    core section numbers — see this module's docstring for why. Its output
    must never be passed to packs.assert_no_core_sections_named (it would,
    correctly, reject it); this module never imports that function.
    """
    core_sections = [s for s in manifest["sections"] if s["role"] == "core"]
    language_name = _LANGUAGE_NAMES.get(language, language)
    lines = [
        f"Translate the following sections of this policy into {language_name}, "
        "preserving their legal meaning exactly and keeping each section's clause "
        "numbering (its leading section number) unchanged. Do not add, remove, or "
        "reword anything in any other section — every section not listed below "
        "must be left exactly as it is in the source document, including its "
        "language.",
        "",
    ]
    for section in core_sections:
        lines.append(f'Section {section["number"]} "{section["heading"]}"')
    return "\n".join(lines)


def _extract_core_sections(markdown_text: str, manifest: dict) -> list[dict]:
    """Parse a translated export back into sections and keep only the core ones."""
    all_sections = sections_module.parse_sections(markdown_text)
    core_numbers = {s["number"] for s in manifest["sections"] if s["role"] == "core"}
    return [s for s in all_sections if s["number"] in core_numbers]


def _content_key(core_version: int, language: str) -> str:
    return f"translate:{language}:v{core_version}"


async def derive_core(
    language: str,
    *,
    ledger: Ledger | None = None,
    manifest: dict | None = None,
    client_factory=SuperDocsClient,
    version: int | None = None,
    master_path: Path | None = None,
) -> dict:
    """Translate the core sections into `language`, hash them, and lock them.

    Cached by (core_version, language): a call for a language already locked
    at this core_version makes no SuperDocs call at all and spends no
    operation — it loads the existing lock from disk instead. A second (or
    Nth) country sharing a language is free; only the first call for a given
    (core_version, language) pair is ever billed. Upload is free; the chat
    call that applies the translation is the one billed step; export is
    free. The extracted core sections are hashed and written to
    state/core-lock-v{version}-{lang}.json via the same corelock.lock()/
    save_lock() lock-time path the source language uses (service.lock_core)
    — one lock format, one place that produces it.

    `version`/`master_path` default to manifest['core_version'] and the
    current policy-master.md — unchanged behaviour. A caller may override
    both to derive a PRIOR version's translation instead (amend.py's
    retranslate_changed_sections does this to self-heal a lost pre-amendment
    language lock, reading from the archived config/policy-master-v{n}.md).
    Unlike the source language's lock, a translated core is never
    deterministic — this genuinely re-translates and costs one operation,
    the same as deriving it the first time would have.
    """
    ledger = ledger if ledger is not None else Ledger()
    manifest = manifest if manifest is not None else config_module.load_manifest()

    if language == manifest["source_language"]:
        raise ValueError(
            f"{language!r} is the source language — lock it directly from "
            "policy-master.md via service.lock_core(), not by translation. "
            "derive_core is for every language other than the source."
        )

    core_version = version if version is not None else manifest["core_version"]
    master_path = master_path if master_path is not None else POLICY_MASTER_PATH
    content_key = _content_key(core_version, language)

    if ledger.already_charged(content_key) and corelock.lock_exists(core_version, language):
        ledger.record(
            "translate", language, chat_calls=0, wall_time=0.0,
            content_key=content_key, output_exists=True,
        )
        return corelock.load_lock(core_version, language)

    instruction = _build_translation_instruction(manifest, language)
    session_id = f"translate-{language}"
    file_base64 = base64.b64encode(master_path.read_bytes()).decode("ascii")

    async with client_factory() as client:
        started = time.monotonic()
        await client.upload(filename="policy-master.md", file_base64=file_base64, session_id=session_id)
        ledger.record("upload", language, chat_calls=0, wall_time=time.monotonic() - started)

        started = time.monotonic()
        response = await client.chat(message=instruction, session_id=session_id, response_mode="compact")
        ledger.record(
            "chat", f"translate core -> {language}",
            chat_calls=ops_from_response(response), wall_time=time.monotonic() - started,
        )

        started = time.monotonic()
        export = await client.export(session_id=session_id, format="markdown")
        ledger.record("export-markdown", language, chat_calls=0, wall_time=time.monotonic() - started)

    markdown_text = export.get("text") or export.get("markdown") or export.get("content")
    if not markdown_text:
        raise SuperDocsClientError(
            f"export_document response for the {language!r} core translation carried "
            "no text. Fix: check the response shape hasn't changed."
        )

    core_sections = _extract_core_sections(markdown_text, manifest)
    lock_data = corelock.lock(core_sections, core_version, language)
    # corelock.lock() stores only hashes. packs.py needs the actual verbatim
    # translated text to insert into a pack without ever re-translating, so
    # the parsed section dicts (number/heading/body) ride along in the same
    # lock file, under a key corelock.verify() itself never reads.
    lock_data["sections"] = core_sections
    corelock.save_lock(lock_data)

    # Marks this content_key as charged for future idempotency checks, without
    # adding to total_operations a second time — the actual operation was
    # already counted by the chat step above (mirrors packs.generate_pack).
    ledger.record(
        "translate", language, chat_calls=0, wall_time=0.0,
        content_key=content_key, output_exists=False,
    )

    return lock_data
