"""Propagates a core amendment to affected languages and countries."""

from __future__ import annotations

import base64
import datetime
import time
from pathlib import Path

import httpx2

from . import config as config_module
from . import corelock
from . import sections as sections_module
from . import translate as translate_module
from .ledger import Ledger, ops_from_response
from .mcp_client import SuperDocsClient, SuperDocsClientError

ROOT = Path(__file__).resolve().parents[2]
POLICY_MASTER_PATH = config_module.CONFIG_DIR / "policy-master.md"
OUT_DIR = ROOT / "out"

# Falls back to the raw ISO code when a language isn't listed — adding a
# language must never require a code change here (CLAUDE.md rule 5); this
# dict only makes the instruction read naturally for the languages we know.
_LANGUAGE_NAMES = {"fr": "French", "pt": "Portuguese"}

# Business policy, not a live API characteristic (unlike annex_batch_size) —
# how long an office has to acknowledge a core amendment. A plain constant
# is fine here; nothing about it can be discovered by testing SuperDocs.
_NOTICE_RETURN_WINDOW_DAYS = 14

_NOTICE_LABELS = {
    "en": {
        "title": "Change Notice",
        "office_label": "Office",
        "date_label": "Date",
        "previously": "Previously:",
        "now": "Now:",
        "what_changed": "What changed:",
        "action_required": "Action required:",
        "action_body": (
            "Review the updated section(s) above with your team and confirm receipt "
            "using this office's acknowledgement form."
        ),
        "return_by": "Return the acknowledgement below by {date}.",
        "annexes_unchanged": (
            "Your annexes (6–9) are unchanged. Your reporting channels and escalation "
            "path are as before."
        ),
    },
    "fr": {
        "title": "Avis de modification",
        "office_label": "Bureau",
        "date_label": "Date",
        "previously": "Auparavant :",
        "now": "Désormais :",
        "what_changed": "Ce qui a changé :",
        "action_required": "Action requise :",
        "action_body": (
            "Examinez la ou les sections mises à jour ci-dessus avec votre équipe et "
            "confirmez la réception à l'aide du formulaire d'accusé de réception de ce bureau."
        ),
        "return_by": "Retournez l'accusé de réception ci-dessous avant le {date}.",
        "annexes_unchanged": (
            "Vos annexes (6 à 9) sont inchangées. Vos canaux de signalement et votre "
            "parcours d'escalade restent les mêmes qu'auparavant."
        ),
    },
    "pt": {
        "title": "Aviso de Alteração",
        "office_label": "Escritório",
        "date_label": "Data",
        "previously": "Anteriormente:",
        "now": "Agora:",
        "what_changed": "O que mudou:",
        "action_required": "Ação necessária:",
        "action_body": (
            "Revise a(s) seção(ões) atualizada(s) acima com sua equipe e confirme o "
            "recebimento usando o formulário de comprovante deste escritório."
        ),
        "return_by": "Devolva o comprovante de recebimento abaixo até {date}.",
        "annexes_unchanged": (
            "Seus anexos (6 a 9) permanecem inalterados. Seus canais de denúncia e "
            "seu caminho de escalonamento são os mesmos de antes."
        ),
    },
}

# Readable, language-appropriate placeholder for the notice's one genuinely
# interpretive line (the plain-language "what changed" summary) — filled in
# by the single billed chat call in generate_change_notice. Not a sentinel
# marker baked into a shipped policy document (CLAUDE.md rule 4 is about
# policy-master.md); this is internal-draft text in a document this module
# generates itself, checked afterward the same way packs.py checks its own
# annex placeholders never survive into a finished export.
_SUMMARY_PLACEHOLDER = {
    "en": "Summary pending.",
    "fr": "Résumé en attente.",
    "pt": "Resumo pendente.",
}


def diff_core_versions(manifest: dict, language: str, from_version: int, to_version: int) -> dict:
    """Which core sections changed between two locked versions, for one language.

    Compares only the persisted section hashes from
    state/core-lock-v{version}-{lang}.json — no document is read and no
    SuperDocs call is made. Zero operations: this is hash comparison, not
    intelligence. A section is "changed" only if its own locked hash
    differs; every other core section is scoped out before any later step
    (re-translation, notice generation) ever looks at it.
    """
    from_lock = corelock.load_lock(from_version, language)
    to_lock = corelock.load_lock(to_version, language)

    core_numbers = sorted(s["number"] for s in manifest["sections"] if s["role"] == "core")

    changed_sections = []
    unchanged_sections = []
    for number in core_numbers:
        key = str(number)
        from_hash = from_lock["section_hashes"].get(key)
        to_hash = to_lock["section_hashes"].get(key)
        if from_hash is None or to_hash is None:
            raise ValueError(
                f"section {number} is not covered by both the v{from_version} and "
                f"v{to_version} {language!r} locks — a core section was added or "
                "removed, not just edited; diff_core_versions only compares "
                "sections present in both locks."
            )
        if from_hash != to_hash:
            changed_sections.append(number)
        else:
            unchanged_sections.append(number)

    return {
        "language": language,
        "from_version": from_version,
        "to_version": to_version,
        "core_sections_total": len(core_numbers),
        "changed_sections": changed_sections,
        "unchanged_sections": unchanged_sections,
    }


def _join_numbers(numbers: list[int]) -> str:
    return ", ".join(str(n) for n in numbers)


def format_diff_report(diff: dict) -> str:
    """"Section 4 changed, 1 of 5" — and name every section that did not.

    Naming what did NOT change is not decoration: it is what lets a country
    office trust a change notice built from this diff without re-reading
    the whole core. `changed_sections` and `unchanged_sections` are already
    disjoint and exhaustive over every core section (diff_core_versions
    enforces that every core section lands in exactly one), so this only
    formats what is already known — no new comparison happens here.
    """
    changed = diff["changed_sections"]
    unchanged = diff["unchanged_sections"]
    total = diff["core_sections_total"]

    if not changed:
        return (
            f"No core sections changed between v{diff['from_version']} and "
            f"v{diff['to_version']} ({diff['language']}). All {total} unchanged."
        )

    changed_label = "section" if len(changed) == 1 else "sections"
    header = (
        f"{changed_label.capitalize()} {_join_numbers(changed)} changed, "
        f"{len(changed)} of {total}."
    )
    if not unchanged:
        return header

    return f"{header} Section{'s' if len(unchanged) != 1 else ''} {_join_numbers(unchanged)} unchanged."


def _build_retranslation_instruction(manifest: dict, language: str, changed_numbers: list[int]) -> str:
    """The one instruction in this module that legitimately names core section
    numbers — mirrors translate.py's _build_translation_instruction, but
    scoped to only the sections that changed in this amendment, not every
    core section. Every section not listed, core or annex, must be left
    exactly as it is including its language: re-translating a section that
    did not change would produce different bytes for identical meaning and
    would silently break the "unchanged sections carry forward byte for
    byte" guarantee this module exists to protect.

    Like translate.py, this module deliberately never imports packs.py, so
    packs.assert_no_core_sections_named — the guard built to reject an
    instruction naming a core section — is structurally unreachable from
    this path, not just unused.
    """
    heading_by_number = {s["number"]: s["heading"] for s in manifest["sections"]}
    language_name = _LANGUAGE_NAMES.get(language, language)
    lines = [
        f"Translate ONLY the following section(s) of this policy into {language_name}, "
        "preserving their legal meaning exactly and keeping each section's clause "
        "numbering (its leading section number) unchanged. Do not add, remove, or "
        "reword anything in any other section — every section not listed below must "
        "be left exactly as it is in the source document, including its language.",
        "",
    ]
    for number in changed_numbers:
        lines.append(f'Section {number} "{heading_by_number[number]}"')
    return "\n".join(lines)


async def _translate_changed_sections(
    manifest: dict,
    language: str,
    changed_numbers: list[int],
    *,
    ledger: Ledger,
    client_factory=SuperDocsClient,
) -> dict[int, dict]:
    """Send exactly one chat call translating `changed_numbers` into
    `language`, from the current (v2) policy-master.md, and return the
    translated section dicts keyed by number.

    Cost: one operation for this call, regardless of how many sections are
    in `changed_numbers` or how many countries share `language` — the same
    per-language, not per-country, economics as translate.derive_core. The
    caller (retranslate_changed_sections) is responsible for combining this
    with the unchanged sections carried forward from the prior lock; this
    function only ever touches the sections it was told changed.
    """
    instruction = _build_retranslation_instruction(manifest, language, changed_numbers)
    session_id = f"amend-translate-{language}-v{manifest['core_version']}"
    file_base64 = base64.b64encode(POLICY_MASTER_PATH.read_bytes()).decode("ascii")

    async with client_factory() as client:
        started = time.monotonic()
        await client.upload(filename="policy-master.md", file_base64=file_base64, session_id=session_id)
        ledger.record("upload", language, chat_calls=0, wall_time=time.monotonic() - started)

        started = time.monotonic()
        response = await client.chat(message=instruction, session_id=session_id, response_mode="compact")
        ledger.record(
            "chat", f"retranslate {language} sections {changed_numbers}",
            chat_calls=ops_from_response(response), wall_time=time.monotonic() - started,
        )

        started = time.monotonic()
        export = await client.export(session_id=session_id, format="markdown")
        ledger.record("export-markdown", language, chat_calls=0, wall_time=time.monotonic() - started)

    markdown_text = export.get("text") or export.get("markdown") or export.get("content")
    if not markdown_text:
        raise SuperDocsClientError(
            f"export_document response for the {language!r} section re-translation "
            "carried no text. Fix: check the response shape hasn't changed."
        )

    all_sections = sections_module.parse_sections(markdown_text)
    changed_set = set(changed_numbers)
    translated = {s["number"]: s for s in all_sections if s["number"] in changed_set}

    missing = changed_set - set(translated)
    if missing:
        raise SuperDocsClientError(
            f"Re-translation export for {language!r} is missing section(s) "
            f"{sorted(missing)} — requested {sorted(changed_set)}. Fix: the "
            "instruction named these sections; check the export text or retry."
        )
    return translated


def _content_key(language: str, from_version: int, to_version: int) -> str:
    return f"retranslate:{language}:v{from_version}-v{to_version}"


async def retranslate_changed_sections(
    manifest: dict,
    language: str,
    diff: dict,
    *,
    ledger: Ledger | None = None,
    client_factory=SuperDocsClient,
) -> dict:
    """Derive the v2 core lock for one affected language: unchanged sections
    carried forward from the v1 lock byte for byte, changed sections
    re-translated fresh. Writes state/core-lock-v{to_version}-{lang}.json.

    This is the "carry forward" half of the amendment guarantee: every
    section in diff['unchanged_sections'] is taken verbatim from the v1
    lock's persisted 'sections' text (translate.derive_core saves this,
    never just the hash) and passed through corelock.lock() completely
    untouched — no SuperDocs call ever sees it. Only diff['changed_sections']
    is sent to _translate_changed_sections, which costs exactly one
    operation regardless of country count. If the resulting v2 hash for an
    "unchanged" section number ever failed to match its v1 hash, that would
    mean this function's own carry-forward logic is broken, not SuperDocs —
    the recomputation happens locally, from text this function chose, never
    from a network response.

    `diff` must come from the SOURCE language (diff_core_versions(manifest,
    manifest['source_language'], from_version, to_version)), not from
    `language` itself: a target language's v2 lock does not exist yet — it
    is what this function produces — so diff_core_versions cannot be run
    against it beforehand. Section numbers correspond 1:1 across every
    translation, so the source-language diff's changed/unchanged section
    numbers apply unchanged to every other language. (Once this function
    has run, diff_core_versions(manifest, language, from_version,
    to_version) becomes callable for `language` too, and produces the same
    changed/unchanged split by construction — useful as a check afterward.)

    Cached by (language, from_version, to_version): a rerun for a language
    already re-translated at this version pair makes no SuperDocs call and
    spends no operation.
    """
    ledger = ledger if ledger is not None else Ledger()
    if diff["language"] != manifest["source_language"]:
        raise ValueError(
            f"diff was computed for language {diff['language']!r}, but must come from "
            f"the source language {manifest['source_language']!r} — {language!r}'s v2 "
            "lock does not exist yet, so diff_core_versions cannot run against it."
        )

    from_version, to_version = diff["from_version"], diff["to_version"]
    content_key = _content_key(language, from_version, to_version)

    if ledger.already_charged(content_key) and corelock.lock_exists(to_version, language):
        ledger.record(
            "retranslate", language, chat_calls=0, wall_time=0.0,
            content_key=content_key, output_exists=True,
        )
        return corelock.load_lock(to_version, language)

    changed_numbers = diff["changed_sections"]

    if not corelock.lock_exists(from_version, language):
        # state/ lost this language's pre-amendment lock (e.g. a wiped or
        # fresh state/ directory) — unlike the source language (a pure
        # re-hash of archived text, see service.lock_core), a translated
        # core was never archived as a file, so the only honest recovery is
        # a genuine fresh translation of the archived v{from_version}
        # English master. This costs one real operation, same as deriving
        # it for the first time would have (CLAUDE.md: "translate core per
        # language: 1 op") — never silently assumed free or skipped.
        await translate_module.derive_core(
            language, ledger=ledger, manifest=manifest, client_factory=client_factory,
            version=from_version, master_path=archived_master_path(from_version, manifest),
        )

    v1_lock = corelock.load_lock(from_version, language)
    v1_sections = v1_lock.get("sections")
    if not v1_sections:
        raise ValueError(
            f"The v{from_version} lock for language {language!r} has no verbatim "
            "section text saved, only hashes. Fix: this lock predates "
            "translate.derive_core persisting 'sections' — re-derive it."
        )
    v1_sections_by_number = {s["number"]: s for s in v1_sections}

    translated_changed: dict[int, dict] = {}
    if changed_numbers:
        translated_changed = await _translate_changed_sections(
            manifest, language, changed_numbers, ledger=ledger, client_factory=client_factory
        )

    core_numbers = sorted(s["number"] for s in manifest["sections"] if s["role"] == "core")
    combined_sections = []
    for number in core_numbers:
        if number in changed_numbers:
            combined_sections.append(translated_changed[number])
        else:
            if number not in v1_sections_by_number:
                raise ValueError(
                    f"section {number} is in diff['unchanged_sections'] but has no "
                    f"verbatim text in the v{from_version} {language!r} lock. Fix: "
                    "check diff_core_versions and the v1 lock cover the same sections."
                )
            combined_sections.append(v1_sections_by_number[number])

    lock_data = corelock.lock(combined_sections, to_version, language)
    lock_data["sections"] = combined_sections
    corelock.save_lock(lock_data)

    ledger.record(
        "retranslate", language, chat_calls=0, wall_time=0.0,
        content_key=content_key, output_exists=False,
    )

    return lock_data


def _format_notice_change_summary(diff: dict) -> str:
    """"1 section changed of 5. Sections 1, 2, 3, 5 unchanged." — the change
    notice's own summary line.

    Deliberately different wording from format_diff_report's "Section 4
    changed, 1 of 5." (Prompt 18's general diff report): this prompt asks
    for this specific phrasing on the notice itself. Both are built from
    the same `diff`, never re-derived — only the wording differs.
    """
    changed = diff["changed_sections"]
    unchanged = diff["unchanged_sections"]
    total = diff["core_sections_total"]

    label = "section" if len(changed) == 1 else "sections"
    header = f"{len(changed)} {label} changed of {total}."
    if not unchanged:
        return header

    return f"{header} Section{'s' if len(unchanged) != 1 else ''} {_join_numbers(unchanged)} unchanged."


def archived_master_path(version: int, manifest: dict) -> Path:
    """Path to the exact English master text for one core_version.

    config/policy-master.md always holds the CURRENT core_version — whatever
    manifest['core_version'] is right now. Every prior version is archived at
    config/policy-master-v{version}.md by the amendment that superseded it
    (Prompt 18 archived v1 before amending section 4 to v2), so both the
    "before" and "after" text of any past amendment stay quotable verbatim,
    not just hash-locked.

    Public (not `_`-prefixed) because service.lock_core also needs it, to
    re-derive a lost source-language lock for a prior version deterministically
    — the same archived text, hashed the same way, always reproduces the same
    hash, so this is safe to call from outside this module.
    """
    if version == manifest["core_version"]:
        return POLICY_MASTER_PATH
    archived = config_module.CONFIG_DIR / f"policy-master-v{version}.md"
    if not archived.exists():
        raise ValueError(
            f"No archived master text for core_version {version} at {archived}. Fix: "
            "an amendment must archive the master text it is about to overwrite, the "
            "way policy-master-v1.md was archived before section 4 changed to v2."
        )
    return archived


def _core_sections_at(version: int, language: str, manifest: dict) -> dict[int, dict]:
    """Verbatim core section text (number/heading/body) at one core_version,
    in one language — the source for a change notice's quoted before/after.

    Source language reads straight from the archived/current master text
    (archived_master_path); every other language reads the verbatim
    'sections' its lock already carries (translate.derive_core and
    retranslate_changed_sections persist this, never just hashes) — the
    same two-path split packs._assemble_upload_document already uses for
    assembling a pack's core.
    """
    if language == manifest["source_language"]:
        text = archived_master_path(version, manifest).read_text(encoding="utf-8")
        parsed = sections_module.parse_sections(text)
        core_numbers = {s["number"] for s in manifest["sections"] if s["role"] == "core"}
        return {s["number"]: s for s in parsed if s["number"] in core_numbers}

    lock_data = corelock.load_lock(version, language)
    sections = lock_data.get("sections")
    if not sections:
        raise ValueError(
            f"The v{version} lock for language {language!r} has no verbatim section "
            "text saved, only hashes. Fix: this lock predates translate.derive_core "
            "or retranslate_changed_sections persisting 'sections' — re-derive it."
        )
    return {s["number"]: s for s in sections}


def _quote_block(text: str) -> str:
    """A markdown blockquote of `text`, verbatim — never paraphrased,
    never re-typed by a model. Every changed section's previous and new
    text in a notice comes from here, straight from locked/archived text.
    """
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def generate_change_notice(
    country_code: str,
    manifest: dict,
    diff: dict,
    *,
    country: dict | None = None,
    today: datetime.date | None = None,
) -> str:
    """Build one country's change notice as markdown: a short document, not
    a pack — the office reads what moved, not a 40-page reissue.

    Deterministic except one line: office name and code, "core v1 → v2",
    the date, the notice's summary line (_format_notice_change_summary),
    every changed section's heading with its previous and new text quoted
    VERBATIM (never model-generated — pulled from locked/archived text via
    _core_sections_at, the same text corelock already hash-verified), the
    action required with a return date, and an explicit line confirming
    annexes 6–9 are unchanged. Known fields and known text into a known
    structure, no ambiguity for a model to resolve — the same reasoning
    ack.py already applies to the acknowledgement form.

    The annexes-unchanged line is not decoration: it is what lets an
    office trust that the notice is complete rather than silent about
    something that also moved — the same instinct as the core-identity
    attestation (corelock.verify), just stated in words instead of a hash.
    It is unconditional here because a change notice, by construction,
    only ever exists for a core amendment (diff_core_versions compares
    core sections only) — annexes 6–9 are never in scope for one.

    The one genuinely interpretive piece (a plain-language "what changed"
    summary) is left as a placeholder here, filled in by the single billed
    SuperDocs call layered on top of this function.
    """
    country = (
        country if country is not None
        else config_module.load_country(config_module.COUNTRIES_DIR / f"{country_code}.yaml")
    )
    today = today or datetime.date.today()
    language = country["language"]
    labels = _NOTICE_LABELS.get(language, _NOTICE_LABELS["en"])
    return_date = (today + datetime.timedelta(days=_NOTICE_RETURN_WINDOW_DAYS)).isoformat()
    summary_placeholder = _SUMMARY_PLACEHOLDER.get(language, _SUMMARY_PLACEHOLDER["en"])

    before_sections = _core_sections_at(diff["from_version"], language, manifest)
    after_sections = _core_sections_at(diff["to_version"], language, manifest)

    lines = [
        f"## {labels['title']}",
        "",
        f"**{labels['office_label']}:** {country['office']} ({country['code']})",
        f"**Core v{diff['from_version']} → v{diff['to_version']}**",
        f"**{labels['date_label']}:** {today.isoformat()}",
        "",
        _format_notice_change_summary(diff),
        "",
    ]

    for number in diff["changed_sections"]:
        after_section = after_sections[number]
        lines += [
            f"### Section {number} — {after_section['heading']}",
            "",
            labels["previously"],
            _quote_block(before_sections[number]["body"]),
            "",
            labels["now"],
            _quote_block(after_section["body"]),
            "",
            labels["what_changed"],
            "",
            summary_placeholder,
            "",
        ]

    lines += [
        labels["action_required"],
        "",
        labels["action_body"],
        labels["return_by"].format(date=return_date),
        "",
        labels["annexes_unchanged"],
        "",
    ]
    return "\n".join(lines)


class NoticeIntegrityError(RuntimeError):
    """Raised when a change notice's one billed step did not land cleanly:
    the placeholder summary is still present, or the quoted before/after
    text no longer matches the locked/archived text verbatim. A notice
    that raises this is not written to out/ and the run does not report
    success for this country — the same discipline packs.PackIntegrityError
    applies to a pack, scoped to a notice instead.
    """


async def _default_downloader(url: str) -> bytes:
    async with httpx2.AsyncClient() as http:
        response = await http.get(url)
        response.raise_for_status()
        return response.content


async def _write_notice_export(export_response: dict, dest_path: Path, format: str, downloader=_default_downloader) -> Path:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if format == "markdown":
        text = export_response.get("text") or export_response.get("markdown") or export_response.get("content")
        if text is None:
            raise SuperDocsClientError(
                "export_document response for the change notice carried no markdown "
                "text. Fix: check the response shape hasn't changed."
            )
        dest_path.write_text(text, encoding="utf-8")
    else:
        download_url = export_response.get("download_url")
        if not download_url:
            raise SuperDocsClientError(
                f"export_document response for format={format!r} carried no "
                "download_url. Fix: binary formats are documented to return a "
                "signed download_url — check the response shape hasn't changed."
            )
        dest_path.write_bytes(await downloader(download_url))
    return dest_path


def _content_key_notice(country_code: str, from_version: int, to_version: int) -> str:
    return f"notice:{country_code}:v{from_version}-v{to_version}"


# Bounded retry for the notice's one billed chat call — see
# send_change_notice's docstring for the live failure mode this protects
# against (a billed call that returns a confused non-edit response).
_MAX_NOTICE_ATTEMPTS = 2


async def send_change_notice(
    country_code: str,
    manifest: dict,
    diff: dict,
    *,
    ledger: Ledger | None = None,
    country: dict | None = None,
    today: datetime.date | None = None,
    out_dir: Path = OUT_DIR,
    client_factory=SuperDocsClient,
    downloader=_default_downloader,
) -> dict:
    """Send one country's change notice: build the deterministic draft
    (generate_change_notice), fill in its one interpretive line with a
    single billed SuperDocs call, verify it landed without disturbing the
    quoted before/after text, and export.

    Cost: one operation for this country — a single-document call, unlike
    a pack's multi-section batch (CLAUDE.md's economics). Unlike
    translate.derive_core, this is NOT cached across countries sharing a
    language: each notice is a distinct per-office document (its header,
    return date, and the model's summary text all belong to that one
    document instance), so IN and KE — both English — each cost their own
    operation, matching CLAUDE.md's worked example (2 en notices = 2 ops,
    not 1). Idempotency is still per (country_code, from_version,
    to_version): rerunning for a country already notified at this version
    pair makes no SuperDocs call and spends no operation.

    The model is asked to do exactly one thing — replace the placeholder
    with a short plain-language explanation, grounded only in the
    'Previously'/'Now' text already in the draft — and never to touch
    anything else. The response is not trusted on its own: after export,
    this function checks the placeholder is gone AND that every quoted
    before/after section body still appears verbatim (normalised), the
    same "verify the artifact, not the promise" discipline packs.py
    applies to an annex batch.

    Bounded retry (_MAX_NOTICE_ATTEMPTS): live testing showed a call can
    come back with a confused non-edit response ("I am not sure how to
    help you...", changes: null) while still being billed — the same class
    of unreliability documented for pack generation in
    evidence/superdocs-batch-limit-report.md, here on a single-section
    document instead of a batch. Each attempt is its own ledger line, so a
    notice that needed a retry honestly costs 2 operations, not the
    idealised 1 — the ledger reports what actually happened, never an
    assumed constant.
    """
    ledger = ledger if ledger is not None else Ledger()
    country = (
        country if country is not None
        else config_module.load_country(config_module.COUNTRIES_DIR / f"{country_code}.yaml")
    )
    from_version, to_version = diff["from_version"], diff["to_version"]
    content_key = _content_key_notice(country_code, from_version, to_version)
    notice_dir = out_dir / country_code
    markdown_path = notice_dir / f"change-notice-v{from_version}-v{to_version}.md"
    docx_path = notice_dir / f"change-notice-v{from_version}-v{to_version}.docx"

    if ledger.already_charged(content_key) and markdown_path.exists() and docx_path.exists():
        ledger.record(
            "notice", country_code, chat_calls=0, wall_time=0.0,
            content_key=content_key, output_exists=True,
        )
        return {"country_code": country_code, "exports": {"markdown": markdown_path, "docx": docx_path}, "skipped": True}

    if not diff["changed_sections"]:
        raise ValueError(
            f"diff has no changed_sections — there is nothing to notify {country_code} "
            "about. Fix: this diff must come from an actual core amendment."
        )

    language = country["language"]
    draft = generate_change_notice(country_code, manifest, diff, country=country, today=today)
    placeholder = _SUMMARY_PLACEHOLDER.get(language, _SUMMARY_PLACEHOLDER["en"])
    language_name = _LANGUAGE_NAMES.get(language, language)

    before_sections = _core_sections_at(from_version, language, manifest)
    after_sections = _core_sections_at(to_version, language, manifest)

    instruction = "\n".join([
        f"This document is a change notice for {country['office']} ({country['country']}). "
        f"Replace every occurrence of the placeholder text {placeholder!r} with a short "
        f"(1-2 sentence) plain-language explanation, in {language_name}, of what changed in "
        "the section immediately above it. Base the explanation only on the text already "
        "shown under 'Previously'/'Now' in that section — do not invent any fact not shown "
        "there. Do not change anything else in the document.",
    ])
    session_id = f"notice-{country_code.lower()}-v{from_version}-v{to_version}"

    async with client_factory() as client:
        started = time.monotonic()
        await client.upload(
            filename="change-notice.md",
            file_base64=base64.b64encode(draft.encode("utf-8")).decode("ascii"),
            session_id=session_id,
        )
        ledger.record("upload", country_code, chat_calls=0, wall_time=time.monotonic() - started)

        markdown_text = None
        for attempt in range(1, _MAX_NOTICE_ATTEMPTS + 1):
            started = time.monotonic()
            response = await client.chat(message=instruction, session_id=session_id, response_mode="compact")
            ledger.record(
                "chat", f"notice summary {country_code} (attempt {attempt})",
                chat_calls=ops_from_response(response), wall_time=time.monotonic() - started,
            )

            started = time.monotonic()
            export = await client.export(session_id=session_id, format="markdown")
            ledger.record(
                "export-markdown", country_code, chat_calls=0, wall_time=time.monotonic() - started
            )

            candidate = export.get("text") or export.get("markdown") or export.get("content")
            if not candidate:
                raise SuperDocsClientError(
                    f"export_document response for the {country_code} change notice "
                    "carried no text. Fix: check the response shape hasn't changed."
                )
            if placeholder not in candidate:
                markdown_text = candidate
                break

        if markdown_text is None:
            raise NoticeIntegrityError(
                f"The {country_code} change notice still contains the placeholder "
                f"{placeholder!r} after {_MAX_NOTICE_ATTEMPTS} attempt(s) — the summary "
                "did not land. Fix: inspect the chat responses, or retry this country later."
            )

        normalised_export = corelock.normalise(markdown_text)
        for number in diff["changed_sections"]:
            for label, section in (("previous", before_sections[number]), ("new", after_sections[number])):
                body_norm = corelock.normalise(section["body"])
                if body_norm not in normalised_export:
                    raise NoticeIntegrityError(
                        f"The {country_code} change notice's quoted {label} text for "
                        f"section {number} no longer matches the locked/archived text "
                        "verbatim after the summary call — the model may have altered "
                        "the quote. Fix: this notice is not shipped."
                    )

        exports = {
            "markdown": await _write_notice_export({"text": markdown_text}, markdown_path, "markdown"),
        }
        started = time.monotonic()
        docx_export = await client.export(session_id=session_id, format="docx")
        exports["docx"] = await _write_notice_export(docx_export, docx_path, "docx", downloader=downloader)
        ledger.record("export-docx", country_code, chat_calls=0, wall_time=time.monotonic() - started)

    ledger.record(
        "notice", country_code, chat_calls=0, wall_time=0.0,
        content_key=content_key, output_exists=False,
    )

    return {"country_code": country_code, "exports": exports, "skipped": False}
