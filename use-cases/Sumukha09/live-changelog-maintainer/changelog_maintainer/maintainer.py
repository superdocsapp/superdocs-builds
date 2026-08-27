"""High-level orchestrator for the Living Changelog Maintainer.

``ChangelogMaintainer`` is the seam between the CLI, the renderer, the
SuperDocs client, the verifier, and the GitHub publisher. It owns:

- the loading and saving of the on-disk document state (JSON file);
- the explicit two-phase commit (preview -> confirm -> apply) so we never
  spend a SuperDocs operation we did not authorize;
- the explicit STOP after one successful update (no watching, no loop).

The class never imports or watches the SuperDocs output. It performs one
discrete operation per call and returns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from changelog_maintainer.models import (
    ChangelogDocument,
    HouseStyle,
    ReleaseEntry,
    UpdateRun,
    VerificationResult,
)
from changelog_maintainer.publisher import GitHubPublisher, PullRequestResult
from changelog_maintainer.renderer import render_entry, render_full_changelog
from changelog_maintainer.superdocs_client import (
    SuperDocsClient,
    SurgicalInsertResult,
)
from changelog_maintainer.verification import (
    canonical_hash,
    verify_entries,
    verify_html_anchors,
    AnchorCheckResult,
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PreviewResult:
    """Output of a no-spend preview run."""

    document_title: str
    rendered_entry: str
    full_markdown: str
    new_entry_hash: str
    prior_hash: str
    next_prior_hash: str
    would_anchor_at: str  # which heading we plan to insert after


@dataclass(frozen=True)
class UpdateOutcome:
    """Output of a successful (or attempted) update."""

    run: UpdateRun
    exported_paths: tuple[str, ...]
    pr: Optional[PullRequestResult] = None
    html_check: Optional[AnchorCheckResult] = None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class ChangelogMaintainer:
    """Drive the surgical-update lifecycle."""

    def __init__(
        self,
        state_path: Path | str,
        superdocs: SuperDocsClient,
        github: Optional[GitHubPublisher] = None,
        output_dir: Path | str = "output",
    ) -> None:
        self.state_path = Path(state_path)
        self.superdocs = superdocs
        self.github = github
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # State I/O
    # ------------------------------------------------------------------

    def load(self) -> ChangelogDocument:
        if not self.state_path.exists():
            raise FileNotFoundError(
                f"No changelog state at {self.state_path}. "
                "Run `python changelog.py init` first."
            )
        return ChangelogDocument.load(self.state_path)

    def save(self, document: ChangelogDocument) -> None:
        document.save(self.state_path)

    # ------------------------------------------------------------------
    # init
    # ------------------------------------------------------------------

    def init(
        self,
        title: str,
        owner: str,
        repo: str,
        style: HouseStyle | None = None,
        create_remote: bool = False,
        force: bool = False,
    ) -> ChangelogDocument:
        """Create a brand-new standing changelog.

        If ``create_remote`` is true, also creates a SuperDocs document and
        stores its id in the local state. The local state file is the source
        of truth — losing it loses the SuperDocs id.
        """
        if self.state_path.exists() and not force:
            raise FileExistsError(
                f"Changelog state already exists at {self.state_path}. "
                "Pass --force to overwrite."
            )
        document = ChangelogDocument(
            title=title,
            style=style or HouseStyle.keep_a_changelog(),
            owner=owner,
            repo=repo,
        )
        if create_remote:
            markdown = render_full_changelog(document)
            document_id = self.superdocs.create_document(document.title, markdown)
            object.__setattr__(document, "superdocs_document_id", document_id)
        self.save(document)
        return document

    # ------------------------------------------------------------------
    # preview (no-spend)
    # ------------------------------------------------------------------

    def preview(self, entry: ReleaseEntry) -> PreviewResult:
        """Compute the new entry bytes + hashes WITHOUT calling SuperDocs.

        Zero billable operations. The user can review the rendered Markdown
        and confirm the canonical hashes are stable before authorizing an
        update.
        """
        document = self.load()
        prior_hash = canonical_hash(document.entries, document)
        next_document = document.with_new_entry(entry)
        next_prior_hash = canonical_hash(next_document.entries[1:], next_document)
        rendered = render_entry(entry, document.style, next_document)
        full_markdown = render_full_changelog(next_document)
        anchor = _select_anchor(document)
        return PreviewResult(
            document_title=document.title,
            rendered_entry=rendered,
            full_markdown=full_markdown,
            new_entry_hash=_sha256(rendered),
            prior_hash=prior_hash,
            next_prior_hash=next_prior_hash,
            would_anchor_at=anchor,
        )

    # ------------------------------------------------------------------
    # update (the only place that spends SuperDocs operations)
    # ------------------------------------------------------------------

    def update(
        self,
        entry: ReleaseEntry,
        dry_run: bool = False,
        publish: bool = False,
        export_formats: Iterable[str] = ("md",),
    ) -> UpdateOutcome:
        """Perform the surgical update end-to-end.

        1. Load document state.
        2. Render the new entry under the existing house style.
        3. If ``dry_run`` is true, stop here — return the would-be run record
           with verification based on local hash comparison.
        4. Otherwise, perform the SuperDocs surgical insert.
        5. Re-render the document locally, run identity verification.
        6. Export to the requested formats.
        7. Optionally publish a GitHub PR.
        8. STOP. Never re-trigger.
        """
        document = self.load()
        before_entries = document.entries
        before_html = (
            self.superdocs.get_document_html(document.superdocs_document_id)
            if (document.superdocs_document_id and not dry_run)
            else None
        )

        # 1) Render the new entry.
        next_document = document.with_new_entry(entry)
        rendered_block = render_entry(entry, document.style, next_document)

        notes: list[str] = []

        # 2) Decide whether to actually call SuperDocs.
        if dry_run:
            verification = verify_entries(
                before_entries, next_document.entries, next_document
            )
            return UpdateOutcome(
                run=UpdateRun(
                    release=entry,
                    preview=False,
                    dry_run=True,
                    document_id_before=document.superdocs_document_id,
                    document_id_after=document.superdocs_document_id,
                    verification=verification,
                    exported_paths=(),
                    notes=("dry-run: no SuperDocs operation performed",),
                ),
                exported_paths=(),
            )

        # 3) Real insert.
        if document.superdocs_document_id is None:
            # No remote document yet — fall back to a local-only update with
            # a loud note. We never silently invent a SuperDocs document.
            notes.append(
                "No superdocs_document_id set; performed local-only update."
            )
            inserted_chunk_ids: tuple[str, ...] = ()
        else:
            anchor = _select_anchor(document)
            insert_result: SurgicalInsertResult = self.superdocs.surgical_insert(
                document_id=document.superdocs_document_id,
                anchor_text=anchor,
                new_markdown=rendered_block,
            )
            inserted_chunk_ids = insert_result.inserted_chunk_ids

        # 4) Verify identity based on local render.
        verification = verify_entries(
            before_entries, next_document.entries, next_document
        )
        if not verification.passed:
            raise RuntimeError(
                f"Identity verification failed after insert: {verification}"
            )

        # 5) Optional HTML anchor verification.
        html_check: Optional[AnchorCheckResult] = None
        if (
            document.superdocs_document_id is not None
            and before_html is not None
        ):
            after_html = self.superdocs.get_document_html(
                document.superdocs_document_id
            )
            html_check = verify_html_anchors(
                before_html=before_html,
                after_html=after_html,
                expected_new_titles=(_entry_heading_text(entry, document.style),),
            )
            if not html_check.passed:
                raise RuntimeError(
                    f"HTML anchor check failed: {html_check}"
                )

        # 6) Persist the new state BEFORE exporting. If export fails, the
        # state is still consistent (we already verified identity).
        self.save(next_document)

        # 7) Export.
        exported_paths: list[str] = []
        for fmt in export_formats:
            path = self._export(next_document, fmt)
            exported_paths.append(str(path))

        # 8) Optionally publish.
        pr: Optional[PullRequestResult] = None
        if publish:
            if self.github is None:
                raise RuntimeError(
                    "publish=True but no GitHub publisher configured. "
                    "Set GITHUB_TOKEN."
                )
            pr = self.github.publish(
                repo=f"{next_document.owner}/{next_document.repo}",
                files={
                    path.split("/")[-1]: Path(path).read_bytes()
                    for path in exported_paths
                },
                title=f"Release {entry.version}",
                body=_pr_body(entry, next_document),
            )

        # 9) STOP. No re-trigger logic. The process exits here.
        return UpdateOutcome(
            run=UpdateRun(
                release=entry,
                preview=False,
                dry_run=False,
                document_id_before=document.superdocs_document_id,
                document_id_after=next_document.superdocs_document_id,
                verification=verification,
                exported_paths=tuple(exported_paths),
                notes=tuple(notes),
            ),
            exported_paths=tuple(exported_paths),
            pr=pr,
            html_check=html_check,
        )

    # ------------------------------------------------------------------
    # verify (explicit command)
    # ------------------------------------------------------------------

    def verify(self) -> VerificationResult:
        document = self.load()
        # Recompute the canonical hash of every entry currently in the doc.
        return verify_entries(document.entries, document.entries, document)

    # ------------------------------------------------------------------
    # export (explicit command)
    # ------------------------------------------------------------------

    def export(self, formats: Iterable[str]) -> tuple[str, ...]:
        document = self.load()
        paths: list[str] = []
        for fmt in formats:
            paths.append(str(self._export(document, fmt)))
        return tuple(paths)

    def _export(self, document: ChangelogDocument, fmt: str) -> Path:
        fmt = fmt.lower()
        markdown = render_full_changelog(document)
        out_path = self.output_dir / f"CHANGELOG.{_ext_for(fmt)}"
        if fmt == "md":
            out_path.write_text(markdown, encoding="utf-8")
            return out_path
        # For non-md formats we go through SuperDocs.
        if document.superdocs_document_id is None:
            raise RuntimeError(
                f"Cannot export to {fmt}: no superdocs_document_id. "
                "Re-init with --create-remote or upload manually."
            )
        data = self.superdocs.export_document(document.superdocs_document_id, fmt)  # type: ignore[arg-type]
        out_path.write_bytes(data)
        return out_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _select_anchor(document: ChangelogDocument) -> str:
    """Pick the anchor heading text to insert after.

    Strategy: insert the new release immediately AFTER the current top entry's
    heading. That way the new release always sits at the very top, and we
    never touch older entries.
    """
    if document.entries:
        top = document.entries[0]
        return f"[{top.version}]"
    # Empty changelog — anchor on the H1 title.
    return document.title


def _entry_heading_text(entry: ReleaseEntry, style: HouseStyle) -> str:
    return style.title_format.format(version=entry.version, date=entry.date)


def _pr_body(entry: ReleaseEntry, document: ChangelogDocument) -> str:
    sections = "\n".join(
        f"- **{section.value}**: {len(items)} item(s)"
        for section, items in entry.sections.items()
    )
    return (
        f"Automated changelog update for release **{entry.version}** "
        f"({entry.date}).\n\n"
        f"Document: {document.title}\n\n"
        f"### Sections\n{sections or '(none)'}\n\n"
        f"Identity verification: prior entries byte-identical.\n"
    )


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ext_for(fmt: str) -> str:
    return {
        "md": "md",
        "markdown": "md",
        "pdf": "pdf",
        "docx": "docx",
        "html": "html",
        "txt": "txt",
    }.get(fmt, fmt)


__all__ = [
    "ChangelogMaintainer",
    "PreviewResult",
    "UpdateOutcome",
]
