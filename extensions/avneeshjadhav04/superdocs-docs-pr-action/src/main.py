"""Entry point for the SuperDocs Docs PR action.

Flow:
1. Read the merge event and decide whether anything needs saying.
2. If yes: upload the current doc, ask SuperDocs for the changelog entry,
   approve the proposed changes (the machine drives the gate), export the
   finished file.
3. If the export differs from the current doc, open a pull request with the
   diff for human review. If nothing changed, skip silently.

Dry-run mode prints every decision and never calls the API, never writes
files, and never opens a pull request.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Optional

from decisions import (
    MergeContext,
    build_instruction,
    decide_should_run,
    diff_is_empty,
    find_existing_entry,
)
from github_client import GitHubClient, GitHubError
from superdocs_client import SuperDocsClient, SuperDocsError

SESSION_PREFIX = "docs-pr-action"
BRANCH_PREFIX = "docs/changelog"


class ActionError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _load_merge_context() -> MergeContext:
    event_path = _env("GITHUB_EVENT_PATH")
    if not event_path or not os.path.exists(event_path):
        raise ActionError("GITHUB_EVENT_PATH is not set; the action must run on pull_request closed")

    with open(event_path, encoding="utf-8") as fh:
        event = json.load(fh)

    pr = event.get("pull_request") or {}
    if not pr.get("merged"):
        raise ActionError("The triggering pull request was not merged; nothing to do")

    changed_files = [f["filename"] for f in (pr.get("files") or [])]
    if not changed_files:
        changed_files = _changed_files_from_merge_commit(event)

    return MergeContext(
        pr_number=pr.get("number", 0),
        pr_title=pr.get("title", ""),
        pr_body=pr.get("body") or "",
        merged_sha=pr.get("merge_commit_sha") or "",
        base_branch=(pr.get("base") or {}).get("ref", "main"),
        changed_files=changed_files,
    )


def _changed_files_from_merge_commit(event: dict) -> list[str]:
    """Fallback: derive changed files from the merge commit's parents.

    The pull_request.closed event does not carry the file list, so we diff the
    merge commit against its first parent. Requires checkout with fetch-depth 0.
    """
    import subprocess

    sha = (event.get("pull_request") or {}).get("merge_commit_sha")
    if not sha:
        return []
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{sha}^1", sha],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return [line for line in result.stdout.splitlines() if line.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def _read_doc(doc_path: str) -> str:
    path = Path(doc_path)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_doc(doc_path: str, content: str) -> None:
    path = Path(doc_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _session_id(pr_number: int) -> str:
    return f"{SESSION_PREFIX}-{pr_number}"


def _branch_name(pr_number: int, merged_sha: str) -> str:
    short_sha = merged_sha[:8] if merged_sha else "unknown"
    return f"{BRANCH_PREFIX}/{pr_number}-{short_sha}"


def _pr_title(pr_number: int) -> str:
    return f"docs: changelog entry for #{pr_number}"


def _pr_body(pr_number: int, source_title: str, source_sha: str) -> str:
    return (
        f"Automated documentation update drafted by the SuperDocs Docs PR action.\n\n"
        f"Adds a changelog entry for merged pull request #{pr_number} "
        f'("{source_title}", {source_sha}).\n\n'
        f"Review the diff and merge if it is accurate; close if it is not."
    )


def _existing_docs_pr(
    github_token: str,
    repo: str,
    pr_number: int,
) -> Optional[int]:
    """Idempotency: return the number of an open docs PR for this merge, if any."""
    client = GitHubClient(github_token, repo)
    title = _pr_title(pr_number)
    for pull in client.open_pulls():
        if pull.get("title") == title:
            return pull["number"]
    return None


def _open_docs_pr(
    github_token: str,
    repo: str,
    base_branch: str,
    branch_name: str,
    pr_number: int,
    source_title: str,
    source_sha: str,
) -> int:
    client = GitHubClient(github_token, repo)
    owner = repo.split("/")[0]
    return client.create_pull(
        title=_pr_title(pr_number),
        body=_pr_body(pr_number, source_title, source_sha),
        head=f"{owner}:{branch_name}",
        base=base_branch,
    )


def _commit_doc(
    github_token: str,
    repo: str,
    base_branch: str,
    branch_name: str,
    doc_path: str,
    content: str,
    pr_number: int,
) -> None:
    client = GitHubClient(github_token, repo)
    base_sha = client.branch_sha(base_branch)
    if base_sha is None:
        raise GitHubError(f"base branch {base_branch!r} not found")

    branch_sha = client.branch_sha(branch_name)
    if branch_sha is None:
        client.create_branch(branch_name, base_sha)

    message = f"docs: changelog entry for #{pr_number}"
    existing_sha = client.file_sha(doc_path, branch_name)
    if existing_sha is not None:
        client.update_file(doc_path, content, branch_name, message, existing_sha)
    else:
        client.create_file(doc_path, content, branch_name, message)


def main() -> int:
    dry_run = _env_bool("DRY_RUN")
    doc_path = _env("DOC_PATH", "CHANGELOG.md")
    base_branch_override = _env("BASE_BRANCH")
    skip_patterns = [
        p.strip() for p in _env("SKIP_PATTERNS", "skip-docs,no-docs").split(",") if p.strip()
    ]
    api_key = _env("SUPERDOCS_API_KEY")
    github_token = _env("GITHUB_TOKEN")
    repo = _env("GITHUB_REPOSITORY")

    def log(message: str) -> None:
        print(f"[docs-pr] {message}")

    try:
        context = _load_merge_context()
    except ActionError as exc:
        log(f"skipping: {exc}")
        return 0

    log(
        f"merge #{context.pr_number} \"{context.pr_title}\" "
        f"({context.merged_sha}) into {context.base_branch}"
    )

    decision = decide_should_run(context, skip_patterns, doc_path)
    log(f"decision: {decision.reason}")
    if not decision.should_run:
        return 0

    if not api_key:
        log("error: SUPERDOCS_API_KEY is not set")
        return 1

    if dry_run:
        log("dry-run: would ask SuperDocs for a changelog entry and open a PR")
        log(f"dry-run: instruction = {build_instruction(context, doc_path)!r}")
        return 0

    if not github_token:
        log("error: GITHUB_TOKEN is not set")
        return 1

    existing = _existing_docs_pr(github_token, repo, context.pr_number)
    if existing is not None:
        log(f"skipping: docs PR #{existing} for this merge already exists")
        return 0

    current_text = _read_doc(doc_path)
    if current_text and find_existing_entry(current_text, context.pr_number):
        log(f"skipping: {doc_path} already mentions #{context.pr_number}")
        return 0

    session_id = _session_id(context.pr_number)
    client = SuperDocsClient(api_key)

    try:
        if current_text:
            client.upload_document(doc_path, session_id)
        else:
            log(f"note: {doc_path} does not exist yet; starting from a blank document")

        job_id = client.start_edit(
            session_id=session_id,
            message=build_instruction(context, doc_path),
            document_html="",
            approval_mode="ask_every_time",
        )
        log(f"edit job {job_id} started; waiting for SuperDocs")

        result = client.wait_for_edit(session_id, job_id, approve=True)
        log(f"edit completed: {len(result.changes)} proposed change(s) approved")

        exported = client.export_document(session_id, format="markdown")
        new_text = exported.decode("utf-8")
    except SuperDocsError as exc:
        log(f"error: {exc}")
        return 1

    if diff_is_empty(current_text, new_text):
        log("skipping: SuperDocs produced no change to the document")
        return 0

    _write_doc(doc_path, new_text)

    base_branch = base_branch_override or context.base_branch
    branch_name = _branch_name(context.pr_number, context.merged_sha)

    try:
        _commit_doc(
            github_token,
            repo,
            base_branch,
            branch_name,
            doc_path,
            new_text,
            context.pr_number,
        )
        pr_number = _open_docs_pr(
            github_token,
            repo,
            base_branch,
            branch_name,
            context.pr_number,
            context.pr_title,
            context.merged_sha,
        )
    except Exception as exc:
        log(f"error opening docs PR: {exc}")
        return 1

    log(f"opened docs PR #{pr_number} with the changelog diff for review")
    return 0


if __name__ == "__main__":
    sys.exit(main())
