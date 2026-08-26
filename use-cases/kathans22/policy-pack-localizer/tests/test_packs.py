"""Proves pack generation batches the annex edit per config, verifies each
batch actually landed rather than trusting the response, and quarantines
anything that still fails verification."""

from __future__ import annotations

import asyncio
import base64
import math

from localizer import config as config_module
from localizer import corelock
from localizer import packs
from localizer import sections as sections_module
from localizer import service
from localizer import translate
from localizer.ledger import Ledger
from localizer.mcp_client import SuperDocsClientError


def _manifest_and_country():
    manifest = config_module.load_manifest()
    country = config_module.load_country(config_module.COUNTRIES_DIR / "IN.yaml")
    return manifest, country


def _valid_pack_markdown(manifest: dict, country: dict) -> str:
    """A correctly localised pack: real core sections, real rendered annex content."""
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


def _lock_real_core(monkeypatch, tmp_path, manifest, language="en"):
    """Point corelock's state dir at a fresh tmp dir and lock the real core there."""
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path)
    master_sections = sections_module.parse_sections(packs.POLICY_MASTER_PATH.read_text(encoding="utf-8"))
    core_numbers = {s["number"] for s in manifest["sections"] if s["role"] == "core"}
    core_sections = [s for s in master_sections if s["number"] in core_numbers]
    lock_data = corelock.lock(core_sections, manifest["core_version"], language)
    corelock.save_lock(lock_data)
    return lock_data


class _MutatingFakeClient:
    """A fake SuperDocs client that tracks real document state, so a chat call
    either actually mutates the targeted sections or it doesn't — independent
    of what the response text claims.

    `lands_at_size` reproduces the live-observed boundary: a batch whose
    section count is <= lands_at_size mutates the document and reports
    success; a larger batch reports success text but changes nothing,
    exactly as SuperDocs did with a real 4-section batch.
    """

    def __init__(self, manifest: dict, country: dict, lands_at_size: int,
                 docx_url: str = "https://downloads.example/policy-pack.docx",
                 duplicate_markdown_export_calls: set[int] = frozenset(),
                 conflicting_markdown_export_calls: set[int] = frozenset()):
        self.manifest = manifest
        self.country = country
        self.lands_at_size = lands_at_size
        self.docx_url = docx_url
        # Reproduces the live SuperDocs bug: an export call returns the whole
        # document repeated verbatim. Keyed by the 1-indexed markdown export
        # call number (across per-batch verify exports and the final
        # export), so a test can target "the Nth export is corrupted"
        # precisely. sections.parse_sections collapses this case silently
        # (every copy is byte-identical), so it is a recoverable corruption,
        # not a failure.
        self.duplicate_markdown_export_calls = duplicate_markdown_export_calls
        # A harsher variant: the repeated copy is NOT identical (one body
        # differs) — a genuine content conflict that parse_sections cannot
        # safely resolve on its own and must keep rejecting.
        self.conflicting_markdown_export_calls = conflicting_markdown_export_calls
        self._markdown_export_calls = 0
        self.calls: list[tuple[str, dict]] = []
        master_sections = sections_module.parse_sections(packs.POLICY_MASTER_PATH.read_text(encoding="utf-8"))
        self.body_by_number = {s["number"]: s["body"] for s in master_sections}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def upload(self, **kwargs):
        self.calls.append(("upload", kwargs))
        return {"session_id": kwargs.get("session_id")}

    async def chat(self, **kwargs):
        self.calls.append(("chat", kwargs))
        numbers = sorted({int(m) for m in packs._SECTION_MENTION_RE.findall(kwargs["message"])})
        if 0 < len(numbers) <= self.lands_at_size:
            for number in numbers:
                slot = next(s["slot"] for s in self.manifest["sections"] if s["number"] == number)
                self.body_by_number[number] = packs._SLOT_RENDERERS[slot](self.country)
            return {
                "response": f"Successfully updated all {len(numbers)} sections.",
                "usage": {"was_billable": True, "ops_charged": 1},
            }
        return {
            "response": f"I went through {len(numbers)} section(s) but nothing actually changed.",
            "usage": {"was_billable": True, "ops_charged": 1},
        }

    async def approve(self, **kwargs):
        self.calls.append(("approve", kwargs))
        raise SuperDocsClientError("approve_change is not exercised by the current batching design")

    def _current_markdown(self, overrides: dict[int, str] | None = None) -> str:
        overrides = overrides or {}
        lines = []
        for section in self.manifest["sections"]:
            lines.append(f"## {section['number']} {section['heading']}")
            lines.append("")
            lines.append(overrides.get(section["number"], self.body_by_number[section["number"]]))
            lines.append("")
        return "\n".join(lines)

    async def export(self, **kwargs):
        self.calls.append(("export", kwargs))
        if kwargs.get("format") == "docx":
            return {"download_url": self.docx_url}
        self._markdown_export_calls += 1
        text = self._current_markdown()
        if self._markdown_export_calls in self.conflicting_markdown_export_calls:
            first_number = self.manifest["sections"][0]["number"]
            conflicting_copy = self._current_markdown(
                overrides={first_number: self.body_by_number[first_number] + " (a genuinely different copy)"}
            )
            text = text + "\n\n" + conflicting_copy
        elif self._markdown_export_calls in self.duplicate_markdown_export_calls:
            text = text + "\n\n" + text
        return {"text": text}


async def _fake_downloader(url: str) -> bytes:
    return b"fake docx bytes"


class _MultiSessionFakeClient:
    """A fake client that tracks a separate document per session_id, so it
    can play both roles a multi-language pack run needs from one instance:
    translate.py's "translate-{language}" sessions (core translation) and
    packs.py's "pack-{code}" sessions (annex localisation), exactly as one
    real SuperDocs account would serve both.
    """

    def __init__(self, manifest: dict, countries: dict[str, dict],
                 docx_url: str = "https://downloads.example/policy-pack.docx"):
        self.manifest = manifest
        self.countries = countries  # country code -> country dict
        self.docx_url = docx_url
        self.calls: list[tuple[str, dict]] = []
        self.sessions: dict[str, dict] = {}
        master_sections = sections_module.parse_sections(packs.POLICY_MASTER_PATH.read_text(encoding="utf-8"))
        self._master_body = {s["number"]: s["body"] for s in master_sections}
        self._master_heading = {s["number"]: s["heading"] for s in master_sections}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def upload(self, **kwargs):
        self.calls.append(("upload", kwargs))
        session_id = kwargs["session_id"]
        text = base64.b64decode(kwargs["file_base64"]).decode("utf-8")
        parsed = sections_module.parse_sections(text)
        self.sessions[session_id] = {
            "body": {s["number"]: s["body"] for s in parsed},
            "heading": {s["number"]: s["heading"] for s in parsed},
        }
        return {"session_id": session_id}

    async def chat(self, **kwargs):
        self.calls.append(("chat", kwargs))
        session_id = kwargs["session_id"]
        doc = self.sessions[session_id]
        numbers = sorted({int(m) for m in packs._SECTION_MENTION_RE.findall(kwargs["message"])})

        if session_id.startswith("translate-"):
            language = session_id[len("translate-"):]
            for number in numbers:
                doc["body"][number] = f"[{language}] {self._master_body[number]}"
                doc["heading"][number] = f"[{language}] {self._master_heading[number]}"
        else:
            code = session_id[len("pack-"):].upper()
            country = self.countries[code]
            for number in numbers:
                slot = next(s["slot"] for s in self.manifest["sections"] if s["number"] == number)
                doc["body"][number] = packs._SLOT_RENDERERS[slot](country)

        return {
            "response": f"Updated {len(numbers)} section(s).",
            "usage": {"was_billable": True, "ops_charged": 1},
        }

    async def export(self, **kwargs):
        self.calls.append(("export", kwargs))
        if kwargs.get("format") == "docx":
            return {"download_url": self.docx_url}
        doc = self.sessions[kwargs["session_id"]]
        lines = []
        for section in self.manifest["sections"]:
            number = section["number"]
            lines.append(f"## {number} {doc['heading'][number]}")
            lines.append("")
            lines.append(doc["body"][number])
            lines.append("")
        return {"text": "\n".join(lines)}


def test_assemble_upload_document_defaults_to_the_current_master():
    manifest, country = _manifest_and_country()  # IN — source language

    document = packs._assemble_upload_document(manifest, country)

    assert document == packs.POLICY_MASTER_PATH.read_text(encoding="utf-8")


def test_assemble_upload_document_honours_an_explicit_master_path_override():
    # A deliberate state-repair call (e.g. regenerating a source-language
    # pack against the archived pre-amendment master) must read that file,
    # not silently fall back to the current policy-master.md.
    manifest, country = _manifest_and_country()  # IN — source language
    v1_path = config_module.CONFIG_DIR / "policy-master-v1.md"

    document = packs._assemble_upload_document(manifest, country, master_path=v1_path)

    assert document == v1_path.read_text(encoding="utf-8")
    assert document != packs.POLICY_MASTER_PATH.read_text(encoding="utf-8")


def test_build_instruction_batches_every_annex_section_into_one_message():
    manifest, country = _manifest_and_country()

    instruction = packs.build_instruction(manifest, country)

    for number in (6, 7, 8, 9):
        assert f"Section {number} " in instruction
    assert "safeguarding.in@meridian-relief.example" in instruction
    assert "POCSO" in instruction
    assert "Regional Director, South Asia" in instruction
    assert country["office"] in instruction


def test_build_instruction_accepts_an_explicit_section_subset():
    manifest, country = _manifest_and_country()
    annex_by_number = {s["number"]: s for s in manifest["sections"] if s["role"] == "annex"}

    instruction = packs.build_instruction(manifest, country, sections=[annex_by_number[6]])

    assert "Section 6 " in instruction
    for number in (7, 8, 9):
        assert f"Section {number} " not in instruction


def test_assert_no_core_sections_named_passes_a_real_annex_instruction():
    manifest, country = _manifest_and_country()
    instruction = packs.build_instruction(manifest, country)

    packs.assert_no_core_sections_named(instruction, manifest)  # must not raise


def test_assert_no_core_sections_named_raises_when_a_core_section_is_named():
    manifest, _ = _manifest_and_country()
    violating_instruction = 'Also rewrite Section 4 "Prohibited Conduct" while you are at it.'

    try:
        packs.assert_no_core_sections_named(violating_instruction, manifest)
        raised = False
    except ValueError as exc:
        raised = True
        assert "4" in str(exc)
    assert raised


def test_generate_pack_never_sends_a_core_section_number_to_the_client(tmp_path, monkeypatch):
    manifest, country = _manifest_and_country()
    _lock_real_core(monkeypatch, tmp_path / "state", manifest)
    ledger = Ledger()
    fake_client = _MutatingFakeClient(manifest, country, lands_at_size=manifest["annex_batch_size"])

    asyncio.run(
        packs.generate_pack(
            "IN",
            ledger=ledger,
            manifest=manifest,
            country=country,
            out_dir=tmp_path,
            client_factory=lambda: fake_client,
            downloader=_fake_downloader,
        )
    )

    core_numbers = {s["number"] for s in manifest["sections"] if s["role"] == "core"}
    for name, kwargs in fake_client.calls:
        if name != "chat":
            continue
        named = {int(m) for m in packs._SECTION_MENTION_RE.findall(kwargs["message"])}
        assert not (named & core_numbers)


def test_generate_pack_batches_the_annex_edit_per_manifest_batch_size(tmp_path, monkeypatch):
    manifest, country = _manifest_and_country()
    _lock_real_core(monkeypatch, tmp_path / "state", manifest)
    ledger = Ledger()
    fake_client = _MutatingFakeClient(manifest, country, lands_at_size=manifest["annex_batch_size"])

    result = asyncio.run(
        packs.generate_pack(
            "IN", ledger=ledger, manifest=manifest, country=country, out_dir=tmp_path,
            client_factory=lambda: fake_client, downloader=_fake_downloader,
        )
    )

    annex_numbers = [s["number"] for s in manifest["sections"] if s["role"] == "annex"]
    expected_batches = math.ceil(len(annex_numbers) / manifest["annex_batch_size"])
    chat_calls = [kwargs for name, kwargs in fake_client.calls if name == "chat"]

    assert len(chat_calls) == expected_batches
    assert ledger.total_operations == expected_batches
    assert result["skipped"] is False


def test_generate_pack_detects_a_success_shaped_response_that_changed_nothing_and_retries(tmp_path, monkeypatch):
    """Reproduces the exact live bug: a batch chat call reports success and
    changes zero sections. generate_pack must not trust the response text —
    it detects this from the document itself, splits the failed batch, and
    retries at a smaller size until every section lands.
    """
    manifest, country = _manifest_and_country()
    manifest = dict(manifest, annex_batch_size=4)  # provoke the exact live failure mode
    _lock_real_core(monkeypatch, tmp_path / "state", manifest)
    ledger = Ledger()
    fake_client = _MutatingFakeClient(manifest, country, lands_at_size=2)  # 4 fails; <=2 lands

    result = asyncio.run(
        packs.generate_pack(
            "IN", ledger=ledger, manifest=manifest, country=country, out_dir=tmp_path,
            client_factory=lambda: fake_client, downloader=_fake_downloader,
        )
    )

    chat_batches = [
        sorted({int(m) for m in packs._SECTION_MENTION_RE.findall(kwargs["message"])})
        for name, kwargs in fake_client.calls if name == "chat"
    ]
    assert chat_batches[0] == [6, 7, 8, 9]  # the doomed first attempt, as batch_size=4 dictates
    assert len(chat_batches) > 1  # detection triggered a retry rather than stopping here
    assert result["skipped"] is False

    markdown = (tmp_path / "IN" / "policy-pack.md").read_text(encoding="utf-8")
    verification = packs.verify_pack(markdown, manifest, country["language"])
    assert verification["passed"] is True  # the pack that shipped is fully localised


def test_generate_pack_recovers_when_a_batch_verify_export_comes_back_duplicated(tmp_path, monkeypatch):
    # Reproduces the exact live crash: a per-batch verify export came back
    # with the whole document duplicated, and sections.parse_sections
    # (correctly) raised on it. Before this fix that ValueError propagated
    # uncaught out of _apply_annex_batch and crashed the whole pack. It must
    # instead be treated like "nothing in this batch landed" and fall
    # through to the existing bisect/retry machinery.
    manifest, country = _manifest_and_country()
    _lock_real_core(monkeypatch, tmp_path / "state", manifest)
    ledger = Ledger()
    fake_client = _MutatingFakeClient(
        manifest, country, lands_at_size=manifest["annex_batch_size"],
        duplicate_markdown_export_calls={1},  # the first batch's own verify export
    )

    result = asyncio.run(
        packs.generate_pack(
            "IN", ledger=ledger, manifest=manifest, country=country, out_dir=tmp_path,
            client_factory=lambda: fake_client, downloader=_fake_downloader,
        )
    )

    assert result["skipped"] is False
    markdown = (tmp_path / "IN" / "policy-pack.md").read_text(encoding="utf-8")
    verification = packs.verify_pack(markdown, manifest, country["language"])
    assert verification["passed"] is True  # recovered, not crashed


def test_generate_pack_recovers_when_the_final_export_comes_back_duplicated_once(tmp_path, monkeypatch):
    # The final, whole-document export (after every annex batch has already
    # landed) can also come back duplicated. A single bad attempt must not
    # quarantine a pack whose content is actually fine — re-export (free,
    # exports never cost operations) and check again.
    manifest, country = _manifest_and_country()
    _lock_real_core(monkeypatch, tmp_path / "state", manifest)
    ledger = Ledger()
    # annex_batch_size=2, 4 annex sections -> 2 batches -> markdown export
    # calls 1 and 2 are the per-batch verifies; call 3 is the final export.
    fake_client = _MutatingFakeClient(
        manifest, country, lands_at_size=manifest["annex_batch_size"],
        duplicate_markdown_export_calls={3},
    )

    result = asyncio.run(
        packs.generate_pack(
            "IN", ledger=ledger, manifest=manifest, country=country, out_dir=tmp_path,
            client_factory=lambda: fake_client, downloader=_fake_downloader,
        )
    )

    assert result["skipped"] is False
    markdown = (tmp_path / "IN" / "policy-pack.md").read_text(encoding="utf-8")
    verification = packs.verify_pack(markdown, manifest, country["language"])
    assert verification["passed"] is True


def test_generate_pack_recovers_when_every_export_stays_verbatim_duplicated(tmp_path, monkeypatch):
    # sections.parse_sections collapses a duplicated-but-byte-identical
    # export on its own, so this must now recover and ship a real pack no
    # matter how many times (or how many-fold) the export repeats itself —
    # this is the exact live Brazil/Kenya symptom (9 sections -> 72
    # headings across compounding export calls), and it is a benign export
    # artifact, not lost or corrupted content.
    manifest, country = _manifest_and_country()
    _lock_real_core(monkeypatch, tmp_path / "state", manifest)
    ledger = Ledger()
    fake_client = _MutatingFakeClient(
        manifest, country, lands_at_size=manifest["annex_batch_size"],
        duplicate_markdown_export_calls=set(range(1, 50)),  # every export, always
    )

    result = asyncio.run(
        packs.generate_pack(
            "IN", ledger=ledger, manifest=manifest, country=country, out_dir=tmp_path,
            client_factory=lambda: fake_client, downloader=_fake_downloader,
        )
    )

    assert result["skipped"] is False
    markdown = (tmp_path / "IN" / "policy-pack.md").read_text(encoding="utf-8")
    verification = packs.verify_pack(markdown, manifest, country["language"])
    assert verification["passed"] is True


def test_generate_pack_quarantines_when_duplicate_copies_genuinely_conflict(tmp_path, monkeypatch):
    # A duplicated export whose copies do NOT agree (one body genuinely
    # differs from the other) is real corruption, not mere repetition, and
    # parse_sections correctly keeps rejecting it. generate_pack must still
    # end in a clean, named PackIntegrityError and quarantine — never an
    # uncaught ValueError, never a shipped pack.
    manifest, country = _manifest_and_country()
    _lock_real_core(monkeypatch, tmp_path / "state", manifest)
    ledger = Ledger()
    fake_client = _MutatingFakeClient(
        manifest, country, lands_at_size=manifest["annex_batch_size"],
        conflicting_markdown_export_calls=set(range(1, 50)),  # every export, always
    )

    raised = False
    try:
        asyncio.run(
            packs.generate_pack(
                "IN", ledger=ledger, manifest=manifest, country=country, out_dir=tmp_path,
                client_factory=lambda: fake_client, downloader=_fake_downloader,
            )
        )
    except packs.PackIntegrityError as exc:
        raised = True
        assert "conflicting" in str(exc)
    assert raised
    assert not (tmp_path / "IN" / "policy-pack.md").exists()  # never shipped to the real path
    assert (tmp_path / "_quarantine" / "IN" / "policy-pack.md").exists()


def test_generate_pack_exports_markdown_and_docx_to_disk(tmp_path, monkeypatch):
    manifest, country = _manifest_and_country()
    _lock_real_core(monkeypatch, tmp_path / "state", manifest)
    ledger = Ledger()
    fake_client = _MutatingFakeClient(manifest, country, lands_at_size=manifest["annex_batch_size"])

    async def fake_downloader(url: str) -> bytes:
        assert url == fake_client.docx_url
        return await _fake_downloader(url)

    result = asyncio.run(
        packs.generate_pack(
            "IN", ledger=ledger, manifest=manifest, country=country, out_dir=tmp_path / "out",
            client_factory=lambda: fake_client, downloader=fake_downloader,
        )
    )

    md_path = result["exports"]["markdown"]
    docx_path = result["exports"]["docx"]
    assert md_path == tmp_path / "out" / "IN" / "policy-pack.md"
    assert docx_path == tmp_path / "out" / "IN" / "policy-pack.docx"
    assert docx_path.read_bytes() == b"fake docx bytes"

    verification = packs.verify_pack(md_path.read_text(encoding="utf-8"), manifest, country["language"])
    assert verification["passed"] is True


def test_generate_pack_is_idempotent_for_the_same_country_and_core_version(tmp_path, monkeypatch):
    manifest, country = _manifest_and_country()
    _lock_real_core(monkeypatch, tmp_path / "state", manifest)
    ledger = Ledger()
    fake_client = _MutatingFakeClient(manifest, country, lands_at_size=manifest["annex_batch_size"])
    kwargs = dict(
        ledger=ledger, manifest=manifest, country=country, out_dir=tmp_path,
        client_factory=lambda: fake_client, downloader=_fake_downloader,
    )

    first = asyncio.run(packs.generate_pack("IN", **kwargs))
    assert first["skipped"] is False
    calls_after_first_run = len(fake_client.calls)
    ops_after_first_run = ledger.total_operations

    second = asyncio.run(packs.generate_pack("IN", **kwargs))

    assert second["skipped"] is True
    assert len(fake_client.calls) == calls_after_first_run  # no new SuperDocs calls at all
    assert ledger.total_operations == ops_after_first_run  # nothing re-bought
    assert second["exports"]["markdown"] == first["exports"]["markdown"]


def test_generate_pack_re_runs_when_the_output_files_are_missing(tmp_path, monkeypatch):
    # Idempotency is keyed on the ledger entry AND the files still being on
    # disk; a stale ledger with no output present must not skip real work.
    manifest, country = _manifest_and_country()
    _lock_real_core(monkeypatch, tmp_path / "state", manifest)
    ledger = Ledger()
    content_key = packs._content_key("IN", manifest["core_version"])
    ledger.record("pack", "IN", chat_calls=0, wall_time=0.0, content_key=content_key)
    fake_client = _MutatingFakeClient(manifest, country, lands_at_size=manifest["annex_batch_size"])

    result = asyncio.run(
        packs.generate_pack(
            "IN", ledger=ledger, manifest=manifest, country=country, out_dir=tmp_path,
            client_factory=lambda: fake_client, downloader=_fake_downloader,
        )
    )

    assert result["skipped"] is False
    assert len(fake_client.calls) > 0


def _synthetic_core(manifest: dict, *, amended: bool) -> list[dict]:
    return [
        {
            "number": s["number"],
            "heading": s["heading"],
            "body": f"Body for section {s['number']}." + (" AMENDED." if amended else ""),
        }
        for s in manifest["sections"]
        if s["role"] == "core"
    ]


def _synthetic_pack_markdown(manifest: dict, country: dict, core_sections: list[dict]) -> str:
    lines = []
    for section in core_sections:
        lines += [f"## {section['number']} {section['heading']}", "", section["body"], ""]
    for section in manifest["sections"]:
        if section["role"] != "annex":
            continue
        content = packs._SLOT_RENDERERS[section["slot"]](country)
        lines += [f"## {section['number']} {section['heading']}", "", content, ""]
    return "\n".join(lines)


def test_generate_pack_blocks_a_silent_reissue_over_an_older_shipped_pack(tmp_path, monkeypatch):
    # Reproduces the real live incident: Brazil's and Kenya's already-
    # shipped v1 packs were silently overwritten with v2 core content when
    # generate_pack was called again after the core had already been
    # amended to v2 (chasing an unrelated export-duplication bug) — because
    # the idempotency key is version-scoped, a never-before-charged v2
    # content_key skips straight past the "is there already a good pack
    # here" question entirely. This proves the new guard stops it before a
    # single SuperDocs call is made, rather than shipping over it and
    # letting verify_after_amendment catch it after the fact.
    manifest, country = _manifest_and_country()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path / "state")

    core_v1 = _synthetic_core(manifest, amended=False)
    core_v2 = _synthetic_core(manifest, amended=True)
    corelock.save_lock(corelock.lock(core_v1, 1, "en"))
    corelock.save_lock(corelock.lock(core_v2, 2, "en"))

    v1_markdown = _synthetic_pack_markdown(manifest, country, core_v1)
    pack_dir = tmp_path / "out" / "IN"
    pack_dir.mkdir(parents=True)
    (pack_dir / "policy-pack.md").write_text(v1_markdown, encoding="utf-8")
    (pack_dir / "policy-pack.docx").write_bytes(b"stale")

    v2_manifest = {**manifest, "core_version": 2}
    ledger = Ledger()
    fake_client = _MutatingFakeClient(v2_manifest, country, lands_at_size=v2_manifest["annex_batch_size"])

    raised = False
    try:
        asyncio.run(
            packs.generate_pack(
                "IN", ledger=ledger, manifest=v2_manifest, country=country, out_dir=tmp_path / "out",
                client_factory=lambda: fake_client, downloader=_fake_downloader,
            )
        )
    except packs.PackReissueError as exc:
        raised = True
        assert "core_version 1" in str(exc)
        assert "core_version 2" in str(exc)
    assert raised
    assert len(fake_client.calls) == 0  # blocked before any SuperDocs call was spent
    assert (pack_dir / "policy-pack.md").read_text(encoding="utf-8") == v1_markdown  # untouched


def test_generate_pack_allow_reissue_bypasses_the_guard_explicitly(tmp_path, monkeypatch):
    # The guard is a default-safe block, not a hard wall: a deliberate,
    # explicit reissue must still be possible.
    manifest, country = _manifest_and_country()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path / "state")

    core_v1 = _synthetic_core(manifest, amended=False)
    core_v2 = _synthetic_core(manifest, amended=True)
    corelock.save_lock(corelock.lock(core_v1, 1, "en"))
    corelock.save_lock(corelock.lock(core_v2, 2, "en"))

    v1_markdown = _synthetic_pack_markdown(manifest, country, core_v1)
    pack_dir = tmp_path / "out" / "IN"
    pack_dir.mkdir(parents=True)
    (pack_dir / "policy-pack.md").write_text(v1_markdown, encoding="utf-8")
    (pack_dir / "policy-pack.docx").write_bytes(b"stale")

    v2_manifest = {**manifest, "core_version": 2}
    ledger = Ledger()
    fake_client = _MutatingFakeClient(v2_manifest, country, lands_at_size=v2_manifest["annex_batch_size"])

    # The synthetic v2 lock above doesn't match the real master's actual
    # core text the fake client generates from, so the round trip itself
    # fails verification downstream (an artifact of this test's synthetic
    # locks, not of the guard) — what this test proves is narrower: that
    # allow_reissue=True gets PAST the guard and into real generation at
    # all, unlike the previous test where it never got that far.
    try:
        asyncio.run(
            packs.generate_pack(
                "IN", ledger=ledger, manifest=v2_manifest, country=country, out_dir=tmp_path / "out",
                client_factory=lambda: fake_client, downloader=_fake_downloader, allow_reissue=True,
            )
        )
    except packs.PackIntegrityError:
        pass
    assert len(fake_client.calls) > 0  # actually went ahead and tried, unlike the blocked case


def test_generate_pack_re_runs_when_the_cached_export_is_corrupted(tmp_path, monkeypatch):
    # Reproduces the live bug: a prior run charged content_key and wrote a
    # file, but that file was never actually localised (annex sections
    # still carry the master's unedited placeholder text). The idempotency
    # check must not trust "ledger charged + file present" alone forever —
    # a cached pack that fails its own verification must be regenerated for
    # real, not skipped and shipped again as "OK". (A duplicated-but-
    # byte-identical cached export is NOT this case any more — see
    # test_sections.py's collapse test and
    # test_generate_pack_recovers_when_every_export_stays_verbatim_duplicated
    # — so this uses a corruption dedup genuinely cannot paper over.)
    manifest, country = _manifest_and_country()
    _lock_real_core(monkeypatch, tmp_path / "state", manifest)
    ledger = Ledger()
    content_key = packs._content_key("IN", manifest["core_version"])
    ledger.record("pack", "IN", chat_calls=0, wall_time=0.0, content_key=content_key)

    pack_dir = tmp_path / "IN"
    pack_dir.mkdir(parents=True)
    corrupted_markdown = packs.POLICY_MASTER_PATH.read_text(encoding="utf-8")  # annexes never localised
    (pack_dir / "policy-pack.md").write_text(corrupted_markdown, encoding="utf-8")
    (pack_dir / "policy-pack.docx").write_bytes(b"stale")

    fake_client = _MutatingFakeClient(manifest, country, lands_at_size=manifest["annex_batch_size"])

    result = asyncio.run(
        packs.generate_pack(
            "IN", ledger=ledger, manifest=manifest, country=country, out_dir=tmp_path,
            client_factory=lambda: fake_client, downloader=_fake_downloader,
        )
    )

    assert result["skipped"] is False
    assert len(fake_client.calls) > 0  # real work happened, not a trusted stale skip

    final_markdown = (pack_dir / "policy-pack.md").read_text(encoding="utf-8")
    verification = packs.verify_pack(final_markdown, manifest, country["language"])
    assert verification["passed"] is True  # the corrupted file was overwritten with a clean one


def test_verify_pack_passes_for_a_correctly_localised_export(tmp_path, monkeypatch):
    manifest, country = _manifest_and_country()
    _lock_real_core(monkeypatch, tmp_path, manifest)
    markdown = _valid_pack_markdown(manifest, country)

    result = packs.verify_pack(markdown, manifest, country["language"])

    assert result["passed"] is True
    assert result["core"]["passed"] is True
    assert result["unlocalised_annex_sections"] == []


def test_verify_pack_fails_when_an_annex_section_still_has_placeholder_text(tmp_path, monkeypatch):
    manifest, country = _manifest_and_country()
    _lock_real_core(monkeypatch, tmp_path, manifest)
    master_sections = sections_module.parse_sections(packs.POLICY_MASTER_PATH.read_text(encoding="utf-8"))
    original_section_8_body = next(s["body"] for s in master_sections if s["number"] == 8)

    lines = []
    for section in manifest["sections"]:
        lines.append(f"## {section['number']} {section['heading']}")
        lines.append("")
        if section["role"] == "core":
            lines.append(next(s["body"] for s in master_sections if s["number"] == section["number"]))
        elif section["number"] == 8:
            # Simulates the live corruption: new content spliced next to the
            # unedited placeholder, rather than replacing it.
            lines.append(packs._SLOT_RENDERERS["escalation"](country) + "\n\n" + original_section_8_body)
        else:
            lines.append(packs._SLOT_RENDERERS[section["slot"]](country))
        lines.append("")
    corrupted_markdown = "\n".join(lines)

    result = packs.verify_pack(corrupted_markdown, manifest, country["language"])

    assert result["passed"] is False
    assert result["core"]["passed"] is True  # the corruption is annex-only
    assert result["unlocalised_annex_sections"] == [8]


def test_verify_pack_fails_when_a_core_section_diverges(tmp_path, monkeypatch):
    manifest, country = _manifest_and_country()
    _lock_real_core(monkeypatch, tmp_path, manifest)
    markdown = _valid_pack_markdown(manifest, country)
    markdown = markdown.replace(
        "Meridian Relief Trust (MRT) exists",
        "Meridian Relief Trust (MRT) no longer exists",
        1,
    )

    result = packs.verify_pack(markdown, manifest, country["language"])

    assert result["passed"] is False
    assert result["core"]["passed"] is False
    assert 1 in result["core"]["diverged_sections"]


def test_generate_pack_builds_a_non_english_country_from_the_locked_translated_core(tmp_path, monkeypatch):
    manifest = config_module.load_manifest()
    fr = config_module.load_country(config_module.COUNTRIES_DIR / "FR.yaml")
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path / "state")
    ledger = Ledger()
    fake_client = _MultiSessionFakeClient(manifest, {"FR": fr})

    result = asyncio.run(
        packs.generate_pack(
            "FR", ledger=ledger, manifest=manifest, country=fr, out_dir=tmp_path / "out",
            client_factory=lambda: fake_client, downloader=_fake_downloader,
        )
    )

    assert result["skipped"] is False
    markdown = (tmp_path / "out" / "FR" / "policy-pack.md").read_text(encoding="utf-8")
    core_sections = packs.extract_core_sections(markdown, manifest)
    for section in core_sections:
        assert section["body"].startswith("[fr] ")  # translated, not the English master text

    verification = packs.verify_pack(markdown, manifest, "fr")
    assert verification["passed"] is True

    # Translation happened exactly once, in its own session, before the pack session:
    translate_chats = [
        kwargs for name, kwargs in fake_client.calls
        if name == "chat" and kwargs["session_id"] == "translate-fr"
    ]
    assert len(translate_chats) == 1


def test_regenerate_pack_at_version_uses_the_currently_locked_translation(tmp_path, monkeypatch):
    # A non-source-language pack's core is never read from a file — it reads
    # whatever is CURRENTLY locked for that language at the pinned version
    # (_translated_core_sections). This proves service.regenerate_pack_at_version
    # regenerates FR's pack against a pre-seeded v1 lock — the same mechanism
    # that fixes a French/Portuguese pack shipped before a self-healed v1
    # language lock existed, or before it was re-derived.
    manifest = config_module.load_manifest()
    fr = config_module.load_country(config_module.COUNTRIES_DIR / "FR.yaml")
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path / "state")

    core_numbers = {s["number"] for s in manifest["sections"] if s["role"] == "core"}
    master_sections = sections_module.parse_sections(packs.POLICY_MASTER_PATH.read_text(encoding="utf-8"))
    v1_fr_sections = [
        {"number": s["number"], "heading": f"[fr-v1] {s['heading']}", "body": f"[fr-v1] {s['body']}"}
        for s in master_sections if s["number"] in core_numbers
    ]
    v1_lock = corelock.lock(v1_fr_sections, 1, "fr")
    v1_lock["sections"] = v1_fr_sections
    corelock.save_lock(v1_lock)

    ledger = Ledger()
    # Mark it already charged, the way translate.derive_core's own
    # idempotency check expects — otherwise generate_pack's unconditional
    # derive_core call for a non-source-language country would treat the
    # seeded lock as not-yet-derived and silently overwrite it with a fresh
    # (billed) translation before ever reading it.
    ledger.record("translate", "fr", chat_calls=0, wall_time=0.0, content_key=translate._content_key(1, "fr"))
    fake_client = _MultiSessionFakeClient(manifest, {"FR": fr})

    result = asyncio.run(
        service.regenerate_pack_at_version(
            "FR", 1, ledger=ledger, manifest=manifest, out_dir=tmp_path / "out",
            client_factory=lambda: fake_client, downloader=_fake_downloader,
        )
    )

    assert result["skipped"] is False
    markdown = (tmp_path / "out" / "FR" / "policy-pack.md").read_text(encoding="utf-8")
    core_sections = packs.extract_core_sections(markdown, manifest)
    for section in core_sections:
        assert section["body"].startswith("[fr-v1] ")  # the seeded v1 text, not a fresh translation

    pinned = {**manifest, "core_version": 1}
    assert packs.verify_pack(markdown, pinned, "fr")["passed"] is True


def test_regenerate_pack_at_version_raises_when_no_lock_exists_for_the_language(tmp_path, monkeypatch):
    # Regenerating against a translated language must never silently spend a
    # fresh translation operation on the caller's behalf — if the version
    # isn't already locked, this is a named, actionable error, not a bill.
    manifest = config_module.load_manifest()
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path / "state")
    ledger = Ledger()

    raised = False
    try:
        asyncio.run(
            service.regenerate_pack_at_version("FR", 1, ledger=ledger, manifest=manifest, out_dir=tmp_path / "out")
        )
    except ValueError as exc:
        raised = True
        assert "fr" in str(exc)
    assert raised
    assert ledger.total_operations == 0


def test_generate_pack_blocks_before_any_superdocs_call_on_a_corrupted_core_lock(tmp_path, monkeypatch):
    """If the persisted translated-core lock's verbatim text ever disagreed
    with its own hashes — a corrupted write, never expected in practice —
    generate_pack must refuse to assemble a document from it, and must
    never make a single SuperDocs call while doing so: the check runs
    entirely locally, before upload."""
    manifest = config_module.load_manifest()
    fr = config_module.load_country(config_module.COUNTRIES_DIR / "FR.yaml")
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path / "state")

    core_numbers = {s["number"] for s in manifest["sections"] if s["role"] == "core"}
    master_sections = sections_module.parse_sections(packs.POLICY_MASTER_PATH.read_text(encoding="utf-8"))
    core_sections = [s for s in master_sections if s["number"] in core_numbers]
    lock_data = corelock.lock(core_sections, manifest["core_version"], "fr")
    # Corrupt: the hashes were computed from the real core text, but the
    # verbatim text saved alongside them is something else entirely.
    lock_data["sections"] = [dict(s, body="CORRUPTED TEXT") for s in core_sections]
    corelock.save_lock(lock_data)

    ledger = Ledger()
    content_key = translate._content_key(manifest["core_version"], "fr")
    ledger.record("translate", "fr", chat_calls=0, wall_time=0.0, content_key=content_key)
    fake_client = _MultiSessionFakeClient(manifest, {"FR": fr})

    raised = False
    try:
        asyncio.run(
            packs.generate_pack(
                "FR", ledger=ledger, manifest=manifest, country=fr, out_dir=tmp_path / "out",
                client_factory=lambda: fake_client, downloader=_fake_downloader,
            )
        )
    except packs.PackIntegrityError:
        raised = True

    assert raised
    assert fake_client.calls == []  # blocked before any SuperDocs call at all


def test_france_and_senegal_share_an_identical_core_hash_with_distinct_annexes(tmp_path, monkeypatch):
    """The hero claim, made provable: two French-speaking countries, two
    entirely different annexes, one identical core hash — and the core
    translation is spent exactly once, not once per country."""
    manifest = config_module.load_manifest()
    fr = config_module.load_country(config_module.COUNTRIES_DIR / "FR.yaml")
    sn = config_module.load_country(config_module.COUNTRIES_DIR / "SN.yaml")
    monkeypatch.setattr(corelock, "STATE_DIR", tmp_path / "state")
    ledger = Ledger()
    fake_client = _MultiSessionFakeClient(manifest, {"FR": fr, "SN": sn})
    out_dir = tmp_path / "out"
    common_kwargs = dict(
        ledger=ledger, manifest=manifest, out_dir=out_dir,
        client_factory=lambda: fake_client, downloader=_fake_downloader,
    )

    async def run_both():
        await packs.generate_pack("FR", country=fr, **common_kwargs)
        await packs.generate_pack("SN", country=sn, **common_kwargs)

    asyncio.run(run_both())

    fr_markdown = (out_dir / "FR" / "policy-pack.md").read_text(encoding="utf-8")
    sn_markdown = (out_dir / "SN" / "policy-pack.md").read_text(encoding="utf-8")

    fr_core = packs.extract_core_sections(fr_markdown, manifest)
    sn_core = packs.extract_core_sections(sn_markdown, manifest)
    fr_hash = corelock.lock(fr_core, manifest["core_version"], "fr")["core_hash"]
    sn_hash = corelock.lock(sn_core, manifest["core_version"], "fr")["core_hash"]

    print(f"FR core_hash: {fr_hash}")
    print(f"SN core_hash: {sn_hash}")
    assert fr_hash == sn_hash, "FR and SN must carry byte-identical core text"

    for verification in (
        packs.verify_pack(fr_markdown, manifest, "fr"),
        packs.verify_pack(sn_markdown, manifest, "fr"),
    ):
        assert verification["passed"] is True

    fr_annex = {s["number"]: s["body"] for s in sections_module.parse_sections(fr_markdown) if s["number"] >= 6}
    sn_annex = {s["number"]: s["body"] for s in sections_module.parse_sections(sn_markdown) if s["number"] >= 6}
    assert fr_annex != sn_annex  # genuinely different annexes, not a swapped name

    # Exactly one translation call across both countries, not one each:
    translate_chats = [
        kwargs for name, kwargs in fake_client.calls
        if name == "chat" and kwargs["session_id"] == "translate-fr"
    ]
    assert len(translate_chats) == 1


def test_generate_pack_quarantines_a_pack_whose_annex_never_lands(tmp_path, monkeypatch):
    # lands_at_size=0: no batch, however small, ever actually mutates the
    # document — reproducing a total, unrecovered failure of the live bug,
    # where retries are exhausted and the annex is still all placeholder.
    manifest, country = _manifest_and_country()
    _lock_real_core(monkeypatch, tmp_path / "state", manifest)
    ledger = Ledger()
    fake_client = _MutatingFakeClient(manifest, country, lands_at_size=0)
    out_dir = tmp_path / "out"

    raised = False
    try:
        asyncio.run(
            packs.generate_pack(
                "IN", ledger=ledger, manifest=manifest, country=country, out_dir=out_dir,
                client_factory=lambda: fake_client, downloader=_fake_downloader,
            )
        )
    except packs.PackIntegrityError as exc:
        raised = True
        assert "6" in str(exc) or "unlocalised" in str(exc).lower()

    assert raised
    assert not (out_dir / "IN" / "policy-pack.md").exists()
    assert not (out_dir / "IN" / "policy-pack.docx").exists()
    content_key = packs._content_key("IN", manifest["core_version"])
    assert not ledger.already_charged(content_key)  # never marked as a successfully bought pack
    assert (out_dir / "_quarantine" / "IN" / "policy-pack.md").exists()
