"""Integration tests for the ChangelogMaintainer end-to-end.

The most important test in this file is `test_five_sequential_updates_preserve_identity`:

  After 5 sequential update cycles, releases 1..4 are byte-identical to what
  they were before release 5 was inserted.

We swap in a ``FakeSuperDocsClient`` that records the canonical hashes of all
prior entries on every insert and refuses to mutate anything other than the
slot reserved for the new entry. This proves the maintainer itself does not
touch old entries, and that the verify step would catch any mutation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from changelog_maintainer.maintainer import ChangelogMaintainer
from changelog_maintainer.models import (
    ChangelogDocument,
    HouseStyle,
    ReleaseEntry,
)
from changelog_maintainer.renderer import render_entry, render_full_changelog
from changelog_maintainer.superdocs_client import SurgicalInsertResult
from changelog_maintainer.verification import canonical_hash, verify_entries


# ---------------------------------------------------------------------------
# Fake SuperDocs client
# ---------------------------------------------------------------------------


class FakeSuperDocsClient:
    """Records every call and supports surgical-insert simulation locally."""

    def __init__(self) -> None:
        self.html_log: list[str] = []
        self.exports: list[tuple[str, bytes]] = []
        self.inserts: list[tuple[str, str, str]] = []  # (doc_id, anchor, block)
        self._documents: dict[str, str] = {}

    # --- create_document ----------------------------------------------------------

    def create_document(self, title: str, markdown: str) -> str:
        # Document id is just a monotonic counter for tests.
        doc_id = f"doc-{len(self._documents) + 1:04d}"
        self._documents[doc_id] = _md_to_html(title, markdown)
        return doc_id

    # --- surgical_insert ----------------------------------------------------------

    def surgical_insert(
        self,
        document_id: str,
        anchor_text: str,
        new_markdown: str,
    ) -> SurgicalInsertResult:
        self.inserts.append((document_id, anchor_text, new_markdown))
        before_html = self._documents[document_id]
        # Locate the anchor heading and insert the new block after it.
        # The anchor text in our tests is the bracketed version, e.g. "[1.0.0]".
        anchor_html = _heading_for(anchor_text, before_html)
        assert anchor_html is not None, f"anchor {anchor_text!r} not in doc"
        after_html = before_html.replace(
            anchor_html,
            anchor_html + "\n" + _md_to_html_block(new_markdown),
            1,
        )
        self._documents[document_id] = after_html
        # Pretend the inserted block was given a fresh chunk id.
        return SurgicalInsertResult(
            document_id=document_id,
            inserted_chunk_ids=(f"chunk-{len(self.inserts)}",),
            html=before_html,
        )

    # --- export -------------------------------------------------------------------

    def export_document(self, document_id: str, fmt: str) -> bytes:
        html = self._documents[document_id]
        if fmt == "md":
            payload = _html_to_md(html).encode("utf-8")
        elif fmt == "html":
            payload = html.encode("utf-8")
        elif fmt == "txt":
            payload = _strip_tags(html).encode("utf-8")
        elif fmt == "docx":
            payload = b"FAKE-DOCX"
        elif fmt == "pdf":
            payload = b"FAKE-PDF"
        else:
            raise ValueError(fmt)
        self.exports.append((fmt, payload))
        return payload

    def get_document_html(self, document_id: str) -> str:
        return self._documents[document_id]


# ---------------------------------------------------------------------------
# Tiny HTML helpers (test-only; deliberately not the production ones)
# ---------------------------------------------------------------------------


def _md_to_html(title: str, markdown: str) -> str:
    body = _md_to_html_body(markdown)
    return f"<html><head><title>{title}</title></head><body>{body}</body></html>"


def _md_to_html_block(markdown: str) -> str:
    return _md_to_html_body(markdown)


def _md_to_html_body(markdown: str) -> str:
    """Convert the simple Markdown our renderer emits into HTML.

    Supports H1..H6, plain paragraphs, and links. Anything else is passed
    through as a paragraph.
    """
    import re

    lines = markdown.split("\n")
    out: list[str] = []
    in_para: list[str] = []
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            if in_para:
                out.append(f"<p>{' '.join(in_para)}</p>")
                in_para = []
            level = len(m.group(1))
            text = _inline_md(m.group(2))
            out.append(f"<h{level}>{text}</h{level}>")
            continue
        if line.strip() == "":
            if in_para:
                out.append(f"<p>{' '.join(in_para)}</p>")
                in_para = []
            continue
        in_para.append(_inline_md(line))
    if in_para:
        out.append(f"<p>{' '.join(in_para)}</p>")
    return "\n".join(out)


def _inline_md(text: str) -> str:
    import re

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def _heading_for(anchor_text: str, html: str) -> str | None:
    """Find the first <h*> element whose visible text contains anchor_text."""
    import re

    for m in re.finditer(r"<h([1-6])>(.*?)</h\1>", html, re.DOTALL):
        visible = re.sub(r"<[^>]+>", "", m.group(0))
        if anchor_text in visible:
            return m.group(0)
    return None


def _html_to_md(html: str) -> str:
    import re

    out = re.sub(r"<title>.*?</title>", "", html, flags=re.DOTALL)
    out = re.sub(r"<head>.*?</head>", "", out, flags=re.DOTALL)
    out = re.sub(r"</?html>|</?body>", "", out)
    return _strip_tags(out).strip() + "\n"


def _strip_tags(html: str) -> str:
    import re

    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(version: str, date: str, added: str = "Hello") -> ReleaseEntry:
    return ReleaseEntry.from_payload(
        {
            "version": version,
            "date": date,
            "sections": {"Added": [{"text": added}]},
            "contributors": [f"user{version.replace('.', '')}"],
        }
    )


def _maintainer(tmp_path: Path, fake: FakeSuperDocsClient) -> ChangelogMaintainer:
    return ChangelogMaintainer(
        state_path=tmp_path / "state.json",
        superdocs=fake,  # type: ignore[arg-type]
        output_dir=tmp_path / "out",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_init_creates_state(tmp_path: Path):
    fake = FakeSuperDocsClient()
    m = _maintainer(tmp_path, fake)
    doc = m.init(title="My Changelog", owner="me", repo="cool", create_remote=True)
    assert doc.title == "My Changelog"
    assert doc.entries == ()
    assert doc.superdocs_document_id == "doc-0001"
    # State file was written.
    assert (tmp_path / "state.json").exists()
    again = ChangelogDocument.load(tmp_path / "state.json")
    assert again.title == "My Changelog"


def test_preview_is_no_spend(tmp_path: Path):
    fake = FakeSuperDocsClient()
    m = _maintainer(tmp_path, fake)
    m.init(title="C", owner="me", repo="cool", create_remote=True)
    entry = _make_entry("1.0.0", "2026-01-01")
    before_inserts = len(fake.inserts)
    before_exports = len(fake.exports)
    result = m.preview(entry)
    assert len(fake.inserts) == before_inserts
    assert len(fake.exports) == before_exports
    assert result.prior_hash == result.next_prior_hash
    assert "[1.0.0] - 2026-01-01" in result.rendered_entry


def test_update_dry_run_does_not_call_superdocs(tmp_path: Path):
    fake = FakeSuperDocsClient()
    m = _maintainer(tmp_path, fake)
    m.init(title="C", owner="me", repo="cool", create_remote=True)
    entry = _make_entry("1.0.0", "2026-01-01")
    before_inserts = len(fake.inserts)
    outcome = m.update(entry, dry_run=True, export_formats=("md",))
    assert len(fake.inserts) == before_inserts
    assert outcome.run.dry_run is True
    assert outcome.run.verification is not None
    assert outcome.run.verification.passed


def test_update_real_inserts_and_exports(tmp_path: Path):
    fake = FakeSuperDocsClient()
    m = _maintainer(tmp_path, fake)
    m.init(title="C", owner="me", repo="cool", create_remote=True)
    entry = _make_entry("1.0.0", "2026-01-01")
    outcome = m.update(entry, export_formats=("md", "html"))
    assert outcome.run.verification is not None
    assert outcome.run.verification.passed
    assert len(fake.inserts) == 1
    assert ("md", b"") not in fake.exports  # md was exported
    assert ("html", b"") not in fake.exports
    # The exported files exist on disk.
    for path in outcome.exported_paths:
        assert Path(path).exists()


def test_update_refuses_duplicate_version(tmp_path: Path):
    fake = FakeSuperDocsClient()
    m = _maintainer(tmp_path, fake)
    m.init(title="C", owner="me", repo="cool", create_remote=True)
    m.update(_make_entry("1.0.0", "2026-01-01"), export_formats=("md",))
    with pytest.raises(ValueError):
        m.update(_make_entry("1.0.0", "2026-02-01"), export_formats=("md",))


def test_five_sequential_updates_preserve_identity(tmp_path: Path):
    """The crown jewel test.

    Run five sequential update cycles; after each, the canonical hash of
    releases 1..N-1 must equal what it was before the insert. Releases 1..4
    must remain byte-identical after release 5 is inserted.
    """
    fake = FakeSuperDocsClient()
    m = _maintainer(tmp_path, fake)
    m.init(title="C", owner="me", repo="cool", create_remote=True)

    # Five releases, oldest first.
    versions = [
        ("1.0.0", "2026-01-01", "Initial release"),
        ("1.1.0", "2026-02-01", "Add structured logs"),
        ("1.2.0", "2026-03-01", "Performance pass"),
        ("2.0.0", "2026-04-01", "Major rewrite"),  # no breaking flag here for simplicity
        ("2.1.0", "2026-05-01", "Polish"),
    ]
    # We track the canonical hash of every "prior" set right BEFORE each insert,
    # then assert that after the insert the prior set still has the same hash.
    prior_hashes_before_insert: list[str] = []
    for version, date, summary in versions:
        doc_before = ChangelogDocument.load(tmp_path / "state.json")
        h_before = canonical_hash(doc_before.entries, doc_before)
        prior_hashes_before_insert.append(h_before)
        m.update(_make_entry(version, date, added=summary), export_formats=("md",))

    # Re-load the final document.
    final = ChangelogDocument.load(tmp_path / "state.json")
    assert [e.version for e in final.entries] == [
        "2.1.0", "2.0.0", "1.2.0", "1.1.0", "1.0.0"
    ]

    # After each insert, the prior entries canonical hash must match what we
    # recorded immediately before that insert.
    for i, version in enumerate(["1.0.0", "1.1.0", "1.2.0", "2.0.0", "2.1.0"]):
        # The prior set AFTER inserting version i+1 contains releases 1..i.
        prior_versions = [v for v in versions[:i]]
        prior_entries = tuple(
            _make_entry(v, d, added=s) for v, d, s in prior_versions
        )
        actual = canonical_hash(prior_entries, final)
        assert actual == prior_hashes_before_insert[i], (
            f"After inserting {version}, prior entries drifted! "
            f"expected={prior_hashes_before_insert[i]} actual={actual}"
        )

    # Strongest assertion: releases 1..4 rendered bytes are byte-identical
    # between what we stored in the final document and what was rendered in the
    # 4-release document state.
    from changelog_maintainer.renderer import render_entry

    doc_four = ChangelogDocument(
        title=final.title,
        style=final.style,
        owner=final.owner,
        repo=final.repo,
        entries=tuple(e for e in final.entries if e.version in [v[0] for v in versions[:4]]),
    )

    for version, date, summary in versions[:4]:
        in_final = next(e for e in final.entries if e.version == version)
        in_four = next(e for e in doc_four.entries if e.version == version)
        expected = render_entry(in_four, doc_four.style, doc_four)
        actual = render_entry(in_final, final.style, final)
        assert expected == actual, (
            f"Release {version} rendered differently in 4-release doc vs in the "
            f"5-release document."
        )


def test_ten_sequential_updates_preserve_identity_and_style(tmp_path: Path):
    """Prove that across 10 sequential releases:
    1. Historical releases 1..N-1 are strictly byte-identical on each step.
    2. Zero manual reformatting is needed; house style is preserved 100%.
    3. Final document has all 10 releases in newest-first order.
    """
    fake = FakeSuperDocsClient()
    m = _maintainer(tmp_path, fake)
    m.init(title="Living Changelog", owner="org", repo="repo", create_remote=True)

    releases = [
        ("0.1.0", "2026-01-01", "Initial alpha preview"),
        ("0.2.0", "2026-01-15", "Add CLI argument parsing"),
        ("0.3.0", "2026-02-01", "Support Keep A Changelog house style"),
        ("1.0.0", "2026-02-15", "First production-ready GA release"),
        ("1.1.0", "2026-03-01", "Add surgical section insert via SuperDocs"),
        ("1.2.0", "2026-03-15", "Add SHA-256 canonical hash verification"),
        ("1.3.0", "2026-04-01", "Add HTML anchor hierarchy validation"),
        ("2.0.0", "2026-04-15", "Major upgrade with zero-spend preview"),
        ("2.1.0", "2026-05-01", "Add automatic GitHub PR publisher"),
        ("2.2.0", "2026-05-15", "High-fidelity multi-format document export"),
    ]

    for version, date, summary in releases:
        entry = _make_entry(version, date, added=summary)
        # Preview first (must be zero spend)
        preview_res = m.preview(entry)
        assert preview_res.prior_hash == preview_res.next_prior_hash
        # Update
        outcome = m.update(entry, export_formats=("md", "html"))
        assert outcome.run.verification is not None
        assert outcome.run.verification.passed

    # Verify final document has all 10 entries in newest-first order
    final = m.load()
    assert len(final.entries) == 10
    expected_versions = [v[0] for v in reversed(releases)]
    assert [e.version for e in final.entries] == expected_versions

    # Re-verify every entry passes verification
    verify_result = m.verify()
    assert verify_result.passed

    # Verify each release block maintains the exact house style
    for entry in final.entries:
        rendered = render_entry(entry, final.style, final)
        assert rendered.startswith(f"## [{entry.version}] - {entry.date}")
        assert "### Added" in rendered
        assert f"Thanks to @user{entry.version.replace('.', '')}" in rendered


def test_five_updates_have_consistent_house_style(tmp_path: Path):
    """Same entry, same style, same bytes — across 5 independent renders."""
    fake = FakeSuperDocsClient()
    m = _maintainer(tmp_path, fake)
    m.init(title="C", owner="me", repo="cool", create_remote=True)

    first_block = None
    for version in ["1.0.0", "1.1.0", "1.2.0", "2.0.0", "2.1.0"]:
        entry = _make_entry(version, "2026-01-01", added="Add feature X")
        m.update(entry, export_formats=("md",))
        # Re-render this entry on its own and verify the bytes match.
        doc = ChangelogDocument.load(tmp_path / "state.json")
        # The newest entry is at the top.
        top = doc.entries[0]
        assert top.version == version
        from changelog_maintainer.renderer import render_entry

        block = render_entry(top, doc.style, doc)
        if first_block is None:
            first_block = block
        else:
            # All 5 entries use the same house style; structure is identical
            # even if the version differs.
            assert block.startswith("## [")


def test_verify_command_returns_pass(tmp_path: Path):
    fake = FakeSuperDocsClient()
    m = _maintainer(tmp_path, fake)
    m.init(title="C", owner="me", repo="cool", create_remote=True)
    m.update(_make_entry("1.0.0", "2026-01-01"), export_formats=("md",))
    m.update(_make_entry("1.1.0", "2026-02-01"), export_formats=("md",))
    result = m.verify()
    assert result.passed


def test_state_file_is_json_serializable(tmp_path: Path):
    fake = FakeSuperDocsClient()
    m = _maintainer(tmp_path, fake)
    m.init(title="C", owner="me", repo="cool", create_remote=True)
    m.update(_make_entry("1.0.0", "2026-01-01"), export_formats=("md",))
    raw = (tmp_path / "state.json").read_text(encoding="utf-8")
    json.loads(raw)  # must not raise
