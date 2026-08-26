"""Generates per-country packs by batching the annex replacement into config-sized calls."""

from __future__ import annotations

import base64
import difflib
import re
import time
from pathlib import Path

import httpx2

from . import config as config_module
from . import corelock
from . import sections as sections_module
from . import translate
from .ledger import Ledger, ops_from_response
from .mcp_client import SuperDocsClient, SuperDocsClientError

ROOT = Path(__file__).resolve().parents[2]
POLICY_MASTER_PATH = config_module.CONFIG_DIR / "policy-master.md"
OUT_DIR = ROOT / "out"


class PackIntegrityError(RuntimeError):
    """Raised when an exported pack fails core or annex verification.

    A pack that raises this is quarantined per CLAUDE.md rule 3: it is never
    written to disk as a finished pack, and the run does not report success.
    """


class PackReissueError(RuntimeError):
    """Raised when generate_pack is about to silently overwrite an
    already-shipped pack from an older core_version with one from a newer
    version.

    No pack is ever reissued by a core amendment — offices get a change
    notice instead (amend.send_change_notice); that guarantee is the whole
    point of the amendment design. Nothing enforced it at the generation
    boundary itself, though: an ordinary generate_pack() call made after an
    amendment bumped manifest['core_version'] has its own, never-before-
    charged content_key (pack:{code}:v{new_version}), so the existing
    idempotency skip-check never even looks at what is already on disk —
    it just proceeds to generate and ship over it. This is exactly what
    happened live to Brazil and Kenya: their packs were regenerated
    (chasing an unrelated export-duplication bug) after the core had
    already moved to v2, silently replacing their genuine v1 packs with
    v2-core ones. verify_after_amendment caught it after the fact, from
    the exported hash; this guard catches it before a single SuperDocs
    call is spent.
    """


_LANGUAGE_NAMES = {"en": "English", "fr": "French", "pt": "Portuguese"}


def _render_reporting(country: dict) -> str:
    reporting = country["reporting"]
    external = "; ".join(f"{item['name']} ({item['detail']})" for item in reporting["external"])
    return (
        f"internal contact reachable at {reporting['internal_email']} or "
        f"{reporting['internal_phone']}; external channels are {external}"
    )


def _render_legal(country: dict) -> str:
    return "; ".join(country["legal"])


def _render_escalation(country: dict) -> str:
    escalation = country["escalation"]
    return (
        f"tier 1 — {escalation['tier_1']}; tier 2 — {escalation['tier_2']}; "
        f"tier 3 — {escalation['tier_3']}; regulator notification — "
        f"{escalation['regulator_notification']}"
    )


def _render_acknowledgement(country: dict) -> str:
    return (
        f"office {country['office']!r} in {country['country']!r}, safeguarding lead "
        f"{country['safeguarding_lead']!r}, with blank fields for recipient name, role, "
        "date, and signature"
    )


_SLOT_RENDERERS = {
    "reporting": _render_reporting,
    "legal": _render_legal,
    "escalation": _render_escalation,
    "acknowledgement": _render_acknowledgement,
}


def build_instruction(manifest: dict, country: dict, sections: list[dict] | None = None) -> str:
    """Build one instruction that replaces the given annex sections in one call.

    A multi-section edit sent as one chat request costs one operation; the
    same edits as separate calls would cost one each. Batching is
    deliberate — it is why a pack costs a small number of operations, not
    one per section. `sections` defaults to every annex section (build the
    full instruction); generate_pack calls this per-batch with a subset,
    since SuperDocs does not reliably apply all of them in a single call
    (see PROGRESS.md and config/manifest.yaml's annex_batch_size).
    """
    annex_sections = sections if sections is not None else [
        s for s in manifest["sections"] if s["role"] == "annex"
    ]
    language_name = _LANGUAGE_NAMES.get(country["language"], country["language"])

    lines = [
        f"Localise this policy for {country['country']} ({country['office']}), writing "
        f"all replaced text in {language_name}. Replace each of the following annex "
        "sections independently with the content given for it. Do not add, remove, or "
        "reword anything outside these sections; every other section must be left "
        "exactly as it is.",
        "",
    ]
    for section in annex_sections:
        content = _SLOT_RENDERERS[section["slot"]](country)
        lines.append(f'Section {section["number"]} "{section["heading"]}": {content}')
    return "\n".join(lines)


_SECTION_MENTION_RE = re.compile(r"\bsection\s+(\d+)\b", re.IGNORECASE)


def assert_no_core_sections_named(instruction: str, manifest: dict) -> None:
    """Raise if a core section number is named anywhere in an outbound instruction.

    Core sections are never named in any instruction sent to SuperDocs — that
    is the intent half of the core's protection (CLAUDE.md rule 3); the hash
    check in corelock.verify after export is the enforcement half. This is a
    hard stop, not a warning: a violating instruction is never sent.
    """
    core_numbers = {s["number"] for s in manifest["sections"] if s["role"] == "core"}
    named_numbers = {int(match) for match in _SECTION_MENTION_RE.findall(instruction)}
    violating = sorted(named_numbers & core_numbers)
    if violating:
        raise ValueError(
            f"Instruction names core section number(s) {violating} — core sections "
            "must never be named in an instruction sent to SuperDocs. This is a bug "
            "in the instruction builder; the call is not sent."
        )


def _master_annex_placeholders(manifest: dict) -> dict[int, str]:
    """The unedited annex body text in policy-master.md, per annex section number.

    Used as the corruption signal in verify_pack: if an exported pack's
    annex section still contains this placeholder text, that section was
    never cleanly localised — whether because the edit never landed, or
    because a concurrent-merge response spliced the old body back in
    alongside the new content. Observed live: a single-section retry after
    a partial batch apply collided with the settling batched edit and the
    merged, exported result kept both the placeholder sentence and the new
    content in Section 8.
    """
    master_sections = sections_module.parse_sections(POLICY_MASTER_PATH.read_text(encoding="utf-8"))
    annex_numbers = {s["number"] for s in manifest["sections"] if s["role"] == "annex"}
    return {
        s["number"]: corelock.normalise(s["body"])
        for s in master_sections
        if s["number"] in annex_numbers
    }


def extract_core_sections(markdown_text: str, manifest: dict) -> list[dict]:
    """Parse an exported pack back into sections and keep only the core ones.

    This is the read side of the verification round trip: `corelock.lock()`
    was built from `policy-master.md`'s core sections; this extracts the
    same-shaped sections (number, heading, body) from what SuperDocs actually
    exported, so the two can be compared on equal terms — same parser
    (sections.parse_sections), same section shape, same core/annex split
    (from the manifest, not re-derived from the text).
    """
    all_sections = sections_module.parse_sections(markdown_text)
    core_numbers = {s["number"] for s in manifest["sections"] if s["role"] == "core"}
    return [s for s in all_sections if s["number"] in core_numbers]


def compare_core_to_lock(core_sections: list[dict], manifest: dict, language: str) -> dict:
    """Compare an exported core against the locked hash for this core_version/language.

    Loads the lock corelock.lock() wrote at lock time and recomputes hashes
    from `core_sections` through the SAME normalise() function — never a
    second one — so the only thing that can make this fail is a real
    difference in content, not a difference in how the two sides were
    canonicalised.
    """
    lock_data = corelock.load_lock(manifest["core_version"], language)
    return corelock.verify(core_sections, lock_data)


def verify_pack(markdown_text: str, manifest: dict, language: str) -> dict:
    """Verify an exported pack: the core is untouched and every annex section landed.

    Two independent checks, both must pass:
    - core: recompute the core hash from the export and compare it to the
      locked hash for this core_version/language (corelock.verify) — the
      enforcement half of CLAUDE.md rule 3.
    - annex: no annex section may still contain the master's unedited
      placeholder text. This is the annex-side counterpart of the core hash
      check: it catches an edit that silently didn't land, and it catches a
      corrupted merge that spliced the old body back in next to the new one
      (a hash comparison alone would not have caught the latter, since the
      corrupted section is neither core nor byte-identical to anything
      previously locked).

    Verifies from the markdown export, never the docx — docx is shipped to
    the reader, but its text is not what gets hashed.
    """
    all_sections = sections_module.parse_sections(markdown_text)
    core_sections = extract_core_sections(markdown_text, manifest)
    core_result = compare_core_to_lock(core_sections, manifest, language)

    placeholders = _master_annex_placeholders(manifest)
    section_by_number = {s["number"]: s for s in all_sections}
    unlocalised = []
    for number, placeholder in placeholders.items():
        section = section_by_number.get(number)
        if section is None or placeholder in corelock.normalise(section["body"]):
            unlocalised.append(number)

    return {
        "passed": core_result["passed"] and not unlocalised,
        "core": core_result,
        "unlocalised_annex_sections": unlocalised,
        "exported_core_sections": core_sections,
    }


def _master_core_sections(manifest: dict) -> dict[int, dict]:
    master_sections = sections_module.parse_sections(POLICY_MASTER_PATH.read_text(encoding="utf-8"))
    core_numbers = {s["number"] for s in manifest["sections"] if s["role"] == "core"}
    return {s["number"]: s for s in master_sections if s["number"] in core_numbers}


def _word_diff(expected: str, actual: str) -> str:
    """A compact word-level diff.

    A core section is a single long paragraph with no internal line breaks,
    so a line-level diff would just print the whole paragraph twice with
    nothing visually marking what changed. Diffing word-by-word instead
    shows only the words that actually differ.
    """
    expected_words = expected.split()
    actual_words = actual.split()
    matcher = difflib.SequenceMatcher(None, expected_words, actual_words)
    changes = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        removed = " ".join(expected_words[i1:i2])
        added = " ".join(actual_words[j1:j2])
        if removed:
            changes.append(f"  - {removed!r}")
        if added:
            changes.append(f"  + {added!r}")
    return "\n".join(changes) if changes else "  (no word-level difference found)"


def format_verification_report(
    verification: dict, manifest: dict, country_code: str, quarantine_path: Path
) -> str:
    """Name what failed, and show a diff for every diverged core section.

    The lock (corelock.lock()) stores only hashes, not text, so there is
    nothing in it to diff against. The diff instead compares the exported
    section to policy-master.md's core section — the exact text the hash
    was originally computed from — normalised through the same normalise()
    the hash comparison itself used, so the diff shows only what could have
    caused the mismatch, not incidental formatting noise.
    """
    core = verification["core"]
    lines = [
        f"{country_code} pack failed verification and was quarantined to {quarantine_path} "
        "— not exported, and this run does not report success for this country."
    ]

    if core["diverged_sections"]:
        master_by_number = _master_core_sections(manifest)
        exported_by_number = {s["number"]: s for s in verification["exported_core_sections"]}
        for number in core["diverged_sections"]:
            expected = corelock.normalise(master_by_number[number]["body"])
            exported_section = exported_by_number.get(number)
            if exported_section is None:
                lines.append(f"\nSection {number} diverged from the lock: section missing from export.")
                continue
            actual = corelock.normalise(exported_section["body"])
            lines.append(f"\nSection {number} diverged from the lock:\n{_word_diff(expected, actual)}")

    if core["missing_sections"]:
        lines.append(f"\nCore sections missing from the export: {core['missing_sections']}")
    if core["unexpected_sections"]:
        lines.append(f"\nUnexpected core-numbered sections in the export: {core['unexpected_sections']}")
    if verification["unlocalised_annex_sections"]:
        lines.append(
            "\nAnnex sections still carrying the master's unedited placeholder text: "
            f"{verification['unlocalised_annex_sections']}"
        )

    return "\n".join(lines)


def _content_key(country_code: str, core_version: int) -> str:
    return f"pack:{country_code}:v{core_version}"


def _pack_files_exist(pack_dir: Path) -> bool:
    return all((pack_dir / filename).exists() for _, filename in _EXPORT_FILES)


def _cached_pack_is_valid(pack_dir: Path, manifest: dict, language: str) -> bool:
    """Whether the pack already on disk can be trusted as 'already done' for
    idempotency, not just present.

    A cached export that exists but is corrupted (e.g. a duplicated
    SuperDocs export — see sections.parse_sections) must never be treated
    as already-correct: that would let generate_pack's idempotency check
    permanently protect a known-bad pack from ever being regenerated, since
    "the ledger says charged and the file exists" would be true forever.
    Idempotency means "don't re-buy a GOOD result" — it was never meant to
    mean "trust whatever is on disk unconditionally."
    """
    markdown_filename = next(filename for fmt, filename in _EXPORT_FILES if fmt == "markdown")
    try:
        markdown_text = (pack_dir / markdown_filename).read_text(encoding="utf-8")
        return verify_pack(markdown_text, manifest, language)["passed"]
    except (OSError, ValueError):
        return False


def _shipped_pack_prior_version(
    pack_dir: Path, manifest: dict, language: str, current_version: int
) -> int | None:
    """If `pack_dir` already holds a pack that cleanly verifies against some
    OLDER, already-locked core_version (not `current_version`), return that
    version number.

    Returns None if there is nothing on disk yet (first-ever generation —
    always safe), or if what is there does not cleanly verify against any
    older lock either — genuine corruption, which is what the existing
    idempotency check (_cached_pack_is_valid) already handles by
    regenerating over it. Only a pack that is provably a GOOD, complete
    pack for some other version is a reissue hazard worth blocking.
    """
    markdown_filename = next(filename for fmt, filename in _EXPORT_FILES if fmt == "markdown")
    path = pack_dir / markdown_filename
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for version in range(1, current_version):
        if not corelock.lock_exists(version, language):
            continue
        pinned_manifest = {**manifest, "core_version": version}
        try:
            if verify_pack(text, pinned_manifest, language)["passed"]:
                return version
        except ValueError:
            continue
    return None


_TEXT_EXPORT_FORMATS = {"markdown", "html", "txt"}
_TEXT_EXPORT_KEYS = ("text", "markdown", "content")
_EXPORT_FILES = (("markdown", "policy-pack.md"), ("docx", "policy-pack.docx"))


async def _default_downloader(url: str) -> bytes:
    async with httpx2.AsyncClient() as http:
        response = await http.get(url)
        response.raise_for_status()
        return response.content


async def _write_export(
    export_response: dict, dest_path: Path, format: str, downloader=_default_downloader
) -> Path:
    """Write one export_document response to disk, text or binary as the format demands.

    Text formats (markdown/html/txt) return content inline; binary formats
    (docx/pdf) return a short-lived signed download_url that must be fetched
    to get the file, per SuperDocs' own tool documentation.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if format in _TEXT_EXPORT_FORMATS:
        text = next((export_response[k] for k in _TEXT_EXPORT_KEYS if export_response.get(k)), None)
        if text is None:
            raise SuperDocsClientError(
                f"export_document response for format={format!r} carried no text under "
                f"any of {_TEXT_EXPORT_KEYS}. Fix: check the response shape hasn't changed."
            )
        dest_path.write_text(text, encoding="utf-8")
    else:
        download_url = export_response.get("download_url")
        if not download_url:
            raise SuperDocsClientError(
                f"export_document response for format={format!r} carried no download_url. "
                "Fix: binary formats (docx/pdf) are documented to return a signed "
                "download_url — check the response shape hasn't changed."
            )
        dest_path.write_bytes(await downloader(download_url))
    return dest_path


_MAX_RETRY_DEPTH = 4
_MAX_FINAL_EXPORT_ATTEMPTS = 2


def _chunk(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _sections_landed(numbers: list[int], markdown_text: str, placeholders: dict[int, str]) -> set[int]:
    """Which of `numbers` no longer carry the master's unedited placeholder text.

    The only reliable signal that an edit actually happened: SuperDocs'
    chat response text is not one — observed live, a batch of 4 sections
    returned "Successfully updated all 4 sections" (and, on other attempts,
    "went through 4 section(s) but nothing actually changed") while the
    document itself was untouched either way. This checks the document.
    """
    current = {s["number"]: s for s in sections_module.parse_sections(markdown_text)}
    landed = set()
    for number in numbers:
        section = current.get(number)
        if section is not None and placeholders[number] not in corelock.normalise(section["body"]):
            landed.add(number)
    return landed


async def _export_markdown_text(client, session_id: str, ledger: Ledger, country_code: str, label: str) -> str:
    started = time.monotonic()
    export = await client.export(session_id=session_id, format="markdown")
    ledger.record(f"export-markdown ({label})", country_code, chat_calls=0, wall_time=time.monotonic() - started)
    return export.get("text") or export.get("markdown") or export.get("content")


async def _apply_annex_batch(
    client,
    session_id: str,
    manifest: dict,
    country: dict,
    ledger: Ledger,
    country_code: str,
    section_numbers: list[int],
    annex_by_number: dict[int, dict],
    placeholders: dict[int, str],
    depth: int = 0,
) -> None:
    """Send one batch as a single chat call, then verify every section in it
    actually changed — a success-shaped response is not trusted on its own.

    If any section did not land, this is the decision point: split just the
    sections that failed into smaller batches and retry them (bounded by
    _MAX_RETRY_DEPTH), rather than resending the same batch and hoping, or
    trusting the response text. A single section that still will not land
    after being isolated to a batch of one is left for verify_pack's
    placeholder check downstream to catch and quarantine.
    """
    if not section_numbers:
        return

    batch_sections = [annex_by_number[n] for n in section_numbers]
    instruction = build_instruction(manifest, country, sections=batch_sections)
    assert_no_core_sections_named(instruction, manifest)

    started = time.monotonic()
    response = await client.chat(message=instruction, session_id=session_id, response_mode="compact")
    ledger.record(
        "chat", f"{country_code} annex batch {section_numbers} (depth {depth})",
        chat_calls=ops_from_response(response), wall_time=time.monotonic() - started,
    )

    markdown_text = await _export_markdown_text(
        client, session_id, ledger, country_code, f"verify batch {section_numbers}"
    )
    try:
        landed = _sections_landed(section_numbers, markdown_text, placeholders)
    except ValueError:
        # sections.parse_sections already collapses a duplicated-but-
        # identical export on its own, so reaching here means some
        # section's duplicate copies genuinely conflict — a live SuperDocs
        # export defect, not a "did this section land" question. Treat it
        # as nothing in this batch landed and fall through to the same
        # bisect/retry machinery a normal partial-apply failure uses,
        # rather than crashing the whole pack.
        landed = set()
    missing = [n for n in section_numbers if n not in landed]

    if not missing or depth >= _MAX_RETRY_DEPTH:
        return
    if missing == section_numbers and len(section_numbers) == 1:
        return  # isolated to one section and still won't land; not a batching problem

    retry_size = max(1, len(missing) // 2)
    for retry_batch in _chunk(missing, retry_size):
        await _apply_annex_batch(
            client, session_id, manifest, country, ledger, country_code,
            retry_batch, annex_by_number, placeholders, depth=depth + 1,
        )


async def _localise_annex(
    client, session_id: str, manifest: dict, country: dict, ledger: Ledger, country_code: str
) -> str:
    """Replace every annex section, batched at manifest['annex_batch_size'] per
    call, with each batch's result verified against the document before moving
    on. Returns the final exported markdown text.
    """
    annex_by_number = {s["number"]: s for s in manifest["sections"] if s["role"] == "annex"}
    placeholders = _master_annex_placeholders(manifest)
    batch_size = manifest["annex_batch_size"]

    for batch in _chunk(sorted(annex_by_number), batch_size):
        await _apply_annex_batch(
            client, session_id, manifest, country, ledger, country_code,
            batch, annex_by_number, placeholders,
        )

    return await _export_markdown_text(client, session_id, ledger, country_code, "final")


def _translated_core_sections(manifest: dict, language: str) -> list[dict]:
    """The verbatim translated core sections locked for `language`.

    Reads translate.derive_core's persisted lock — never calls SuperDocs.
    """
    lock_data = corelock.load_lock(manifest["core_version"], language)
    sections = lock_data.get("sections")
    if not sections:
        raise PackIntegrityError(
            f"The locked core for language {language!r} has no verbatim section text "
            "saved, only hashes. Fix: this lock predates translate.derive_core "
            "persisting 'sections' — re-derive it."
        )
    return sections


def _assemble_upload_document(manifest: dict, country: dict, master_path: Path | None = None) -> str:
    """Build the document text to upload for one country's pack.

    A source-language country uploads policy-master.md unchanged, exactly as
    before. Every other country uploads the master's structure with its core
    sections replaced, verbatim, by that language's locked translation
    (translate.derive_core) — never regenerated, never re-translated, never
    passed through a model here. Annex sections are left as the master's
    placeholders in both cases; annex localisation happens afterward via the
    batched chat edit, identically for every country regardless of language.

    `master_path` defaults to the current policy-master.md — unchanged
    behaviour. A caller may override it to reproduce a PRIOR core_version's
    pack from its archived config/policy-master-v{n}.md (e.g. re-deriving a
    pre-amendment pack after state/out was lost) — only meaningful for the
    source language here, since a translated core never reads this file at
    all, it reads its own locked 'sections' (see _translated_core_sections).
    """
    master_path = master_path or POLICY_MASTER_PATH
    if country["language"] == manifest["source_language"]:
        return master_path.read_text(encoding="utf-8")

    master_sections = sections_module.parse_sections(POLICY_MASTER_PATH.read_text(encoding="utf-8"))
    master_body_by_number = {s["number"]: s["body"] for s in master_sections}
    core_by_number = {
        s["number"]: s for s in _translated_core_sections(manifest, country["language"])
    }

    lines = []
    for section in manifest["sections"]:
        number = section["number"]
        if section["role"] == "core":
            translated = core_by_number[number]
            heading, body = translated["heading"], translated["body"]
        else:
            heading, body = section["heading"], master_body_by_number[number]
        lines.append(f"## {number} {heading}")
        lines.append("")
        lines.append(body)
        lines.append("")
    return "\n".join(lines)


def _assert_core_verbatim(document_text: str, manifest: dict, language: str) -> None:
    """Prove, locally and with zero SuperDocs calls, that the document about
    to be uploaded already carries the locked core exactly.

    This is the "never regenerate it" guarantee made concrete before a
    single network call is made, not just hoped for: the pack session's
    chat calls only ever name annex sections (assert_no_core_sections_named
    enforces that), so the core arriving at SuperDocs must already be
    correct — there is no later step that could fix it. A failure here
    means _assemble_upload_document or the persisted lock is wrong, never
    that SuperDocs mishandled the core.
    """
    if language == manifest["source_language"]:
        return  # unlocalised master core is verified via service.lock_core elsewhere
    core_sections = extract_core_sections(document_text, manifest)
    lock_data = corelock.load_lock(manifest["core_version"], language)
    result = corelock.verify(core_sections, lock_data)
    if not result["passed"]:
        raise PackIntegrityError(
            f"The document assembled for language {language!r} does not match its "
            f"locked core before any SuperDocs call was made: {result}. This is a bug "
            "in _assemble_upload_document or the persisted lock, not in SuperDocs — "
            "no call was sent."
        )


async def generate_pack(
    country_code: str,
    *,
    ledger: Ledger | None = None,
    manifest: dict | None = None,
    country: dict | None = None,
    out_dir: Path = OUT_DIR,
    client_factory=SuperDocsClient,
    downloader=_default_downloader,
    master_path: Path | None = None,
    allow_reissue: bool = False,
) -> dict:
    """Generate one country's pack: upload, then the annex edit in batches.

    Flow: upload the master, then replace every annex section via
    _localise_annex, which sends the edit in manifest['annex_batch_size']
    -sized batches and verifies each one against the document rather than
    trusting the response — see _apply_annex_batch. A pack now costs one
    operation per batch, not one operation total: live testing proved
    SuperDocs does not reliably apply all four annex sections in a single
    call (see PROGRESS.md and evidence/superdocs-batch-limit-report.md), so
    CLAUDE.md's economics were corrected to match what actually happens.

    `master_path` defaults to None (current policy-master.md) — unchanged
    behaviour for the normal flow, where a pack is never reissued. It exists
    only for a deliberate, explicit state-repair call: regenerating a
    source-language pack against an archived prior core_version, passed
    straight through to _assemble_upload_document. Pair it with a `manifest`
    whose core_version matches that prior version, or the resulting pack
    will be locked/labelled under the wrong version.

    `allow_reissue` defaults to False: before doing any real work, this
    checks whether `out_dir/country_code` already holds a pack that
    cleanly verifies against some OLDER, already-locked core_version than
    `manifest['core_version']` — a sign that generating now would silently
    overwrite an already-shipped pack with new core content (PackReissueError,
    see its docstring for the live incident this closes). A call made by
    regenerate_pack_at_version's explicit repair path never trips this: it
    always passes a `manifest` PINNED to the version being repaired, so
    there is no "older" version left to guard against. Set True only for a
    deliberate, one-off real reissue outside that repair path.
    """
    ledger = ledger if ledger is not None else Ledger()
    manifest = manifest if manifest is not None else config_module.load_manifest()
    country = (
        country
        if country is not None
        else config_module.load_country(config_module.COUNTRIES_DIR / f"{country_code}.yaml")
    )

    pack_dir = out_dir / country_code
    content_key = _content_key(country_code, manifest["core_version"])

    if (
        ledger.already_charged(content_key)
        and _pack_files_exist(pack_dir)
        and _cached_pack_is_valid(pack_dir, manifest, country["language"])
    ):
        ledger.record(
            "pack", country_code, chat_calls=0, wall_time=0.0,
            content_key=content_key, output_exists=True,
        )
        return {
            "country_code": country_code,
            "session_id": None,
            "instruction": None,
            "exports": {fmt: pack_dir / filename for fmt, filename in _EXPORT_FILES},
            "skipped": True,
        }

    if not allow_reissue:
        prior_version = _shipped_pack_prior_version(
            pack_dir, manifest, country["language"], manifest["core_version"]
        )
        if prior_version is not None:
            raise PackReissueError(
                f"{country_code} already has a pack on disk that verifies cleanly "
                f"against core_version {prior_version}, but this call would generate "
                f"one against core_version {manifest['core_version']} — silently "
                f"reissuing it. No pack is ever reissued by a core amendment; an "
                "amendment produces a change notice instead "
                "(amend.send_change_notice/service.run_amendment). If this pack "
                "genuinely needs replacing (state lost or corrupted), use the "
                f"explicit repair path instead: service.regenerate_pack_at_version("
                f"{country_code!r}, {prior_version}) or `python -m localizer "
                f"repair-pack-version --countries {country_code} --version "
                f"{prior_version}`. If a real reissue is truly intended, call "
                "generate_pack(..., allow_reissue=True) explicitly."
            )

    if country["language"] != manifest["source_language"]:
        # Cached by (core_version, language) inside derive_core itself: the
        # first country in a language pays the one translation operation,
        # every other country sharing that language pays nothing.
        await translate.derive_core(
            country["language"], ledger=ledger, manifest=manifest, client_factory=client_factory
        )

    session_id = f"pack-{country_code.lower()}"
    document_text = _assemble_upload_document(manifest, country, master_path=master_path)
    _assert_core_verbatim(document_text, manifest, country["language"])
    file_base64 = base64.b64encode(document_text.encode("utf-8")).decode("ascii")
    instruction = build_instruction(manifest, country)  # full instruction, kept for the return value

    async with client_factory() as client:
        started = time.monotonic()
        await client.upload(filename="policy-master.md", file_base64=file_base64, session_id=session_id)
        ledger.record("upload", country_code, chat_calls=0, wall_time=time.monotonic() - started)

        markdown_text = await _localise_annex(client, session_id, manifest, country, ledger, country_code)

        # export_document, not the chat response, is the one export used for
        # everything downstream: verification, quarantine, and the shipped file.
        # sections.parse_sections now silently collapses a duplicated-but-
        # byte-identical export on its own (the common case: a flaky export
        # repeats the whole already-correct document verbatim — observed
        # live compounding with each further export on the same session, 9
        # sections becoming 72 headings across 3 exports), so a ValueError
        # here means every copy of some section's content genuinely
        # disagrees — a real conflict, not mere repetition. Retrying more
        # exports on an already-conflicted session is not reliable (the
        # live Brazil trace above never cleared across 3 attempts, and each
        # attempt costs nothing but is not guaranteed to help either), so
        # this allows exactly one re-export to catch a transient race (e.g.
        # a concurrent-merge notice settling) before quarantining rather
        # than looping and hoping.
        verification = None
        for attempt in range(1, _MAX_FINAL_EXPORT_ATTEMPTS + 1):
            try:
                verification = verify_pack(markdown_text, manifest, country["language"])
                break
            except ValueError as exc:
                if attempt == _MAX_FINAL_EXPORT_ATTEMPTS:
                    quarantine_filename = next(fname for fmt, fname in _EXPORT_FILES if fmt == "markdown")
                    quarantine_path = await _write_export(
                        {"text": markdown_text},
                        out_dir / "_quarantine" / country_code / quarantine_filename,
                        "markdown",
                    )
                    raise PackIntegrityError(
                        f"{country_code} pack export carried conflicting duplicate section "
                        f"content on every one of {_MAX_FINAL_EXPORT_ATTEMPTS} attempts and "
                        f"could not be safely verified: {exc}. Quarantined at {quarantine_path}."
                    ) from exc
                markdown_text = await _export_markdown_text(
                    client, session_id, ledger, country_code, f"final retry {attempt}"
                )

        markdown_export = {"text": markdown_text}
        if not verification["passed"]:
            # Quarantined, not dropped: the failing export is preserved for
            # inspection at QUARANTINE_DIR, never at the real out/{code}/ path
            # a passing pack would use. The run still does not report success.
            quarantine_filename = next(filename for fmt, filename in _EXPORT_FILES if fmt == "markdown")
            quarantine_path = await _write_export(
                markdown_export,
                out_dir / "_quarantine" / country_code / quarantine_filename,
                "markdown",
            )
            raise PackIntegrityError(
                format_verification_report(verification, manifest, country_code, quarantine_path)
            )

        markdown_filename = next(filename for fmt, filename in _EXPORT_FILES if fmt == "markdown")
        exports = {"markdown": await _write_export(markdown_export, pack_dir / markdown_filename, "markdown")}
        for fmt, filename in _EXPORT_FILES:
            if fmt == "markdown":
                continue
            started = time.monotonic()
            export_response = await client.export(session_id=session_id, format=fmt)
            dest = await _write_export(export_response, pack_dir / filename, fmt, downloader=downloader)
            ledger.record(f"export-{fmt}", country_code, chat_calls=0, wall_time=time.monotonic() - started)
            exports[fmt] = dest

    # Marks this content_key as charged for future idempotency checks (see the
    # early-return above), without adding to total_operations a second time —
    # the actual operation was already counted by the chat step(s) above.
    ledger.record(
        "pack", country_code, chat_calls=0, wall_time=0.0,
        content_key=content_key, output_exists=False,
    )

    return {
        "country_code": country_code,
        "session_id": session_id,
        "instruction": instruction,
        "exports": exports,
        "skipped": False,
    }
