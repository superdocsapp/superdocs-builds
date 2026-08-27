#!/usr/bin/env python3
"""CLI entry point for the Living Changelog Maintainer.

Usage::

    python changelog.py init --title "My Changelog" --owner me --repo cool
    python changelog.py preview release.json
    python changelog.py update release.json --dry-run
    python changelog.py update release.json
    python changelog.py update release.json --publish
    python changelog.py verify
    python changelog.py export --format md,pdf,docx
    python changelog.py publish --repo me/cool --format md

The CLI is intentionally explicit and never re-triggers on its own output.
Each invocation performs ONE update cycle and exits.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from changelog_maintainer.maintainer import ChangelogMaintainer
from changelog_maintainer.models import (
    HouseStyle,
    ReleaseEntry,
)
from changelog_maintainer.publisher import GitHubPublisher
from changelog_maintainer.superdocs_client import SuperDocsClient, SuperDocsConfig


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    common_p = argparse.ArgumentParser(add_help=False)
    common_p.add_argument(
        "--state",
        default=argparse.SUPPRESS,
        help="Path to the local changelog state file (default: changelog.state.json).",
    )
    common_p.add_argument(
        "--output-dir",
        default=argparse.SUPPRESS,
        help="Directory to write exported artifacts (default: output/).",
    )
    common_p.add_argument(
        "--api-key",
        default=argparse.SUPPRESS,
        help="SuperDocs API key (overrides $SUPERDOCS_API_KEY).",
    )
    common_p.add_argument(
        "--github-token",
        default=argparse.SUPPRESS,
        help="GitHub token for the `publish` subcommand.",
    )
    common_p.add_argument(
        "--mode",
        choices=("http", "passthrough"),
        default=argparse.SUPPRESS,
        help="SuperDocs transport mode.",
    )

    p = argparse.ArgumentParser(
        prog="changelog.py",
        parents=[common_p],
        description=(
            "Living Changelog Maintainer — a standing changelog document that "
            "receives a targeted update on every release, leaving previous "
            "entries byte-identical."
        ),
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    # init
    init_p = sub.add_parser("init", parents=[common_p], help="Create a new standing changelog.")
    init_p.add_argument("--title", required=True)
    init_p.add_argument("--owner", required=True)
    init_p.add_argument("--repo", required=True)
    init_p.add_argument(
        "--style-file",
        default=None,
        help="Optional JSON file with a HouseStyle override.",
    )
    init_p.add_argument(
        "--create-remote",
        action="store_true",
        help="Create the SuperDocs document.",
    )
    init_p.add_argument(
        "--local-only",
        action="store_true",
        help="Initialize only local state file without creating remote document.",
    )
    init_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing state file if it already exists.",
    )

    # preview
    pre_p = sub.add_parser(
        "preview",
        parents=[common_p],
        help="Render the new entry and compute hashes WITHOUT spending.",
    )
    pre_p.add_argument(
        "release_json",
        nargs="?",
        default="release.json",
        help="Path to release payload JSON (default: release.json).",
    )

    # update
    up_p = sub.add_parser(
        "update",
        parents=[common_p],
        help="Perform the surgical update (one SuperDocs insert + verify + export).",
    )
    up_p.add_argument(
        "release_json",
        nargs="?",
        default="release.json",
        help="Path to release payload JSON (default: release.json).",
    )
    up_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute the new state locally and verify; do not call SuperDocs.",
    )
    up_p.add_argument(
        "--publish",
        action="store_true",
        help="After update + export, open a GitHub PR.",
    )
    up_p.add_argument(
        "--format",
        default="md",
        help="Comma-separated export formats (default: md).",
    )

    # verify
    sub.add_parser(
        "verify",
        parents=[common_p],
        help="Re-hash every entry currently in the state file and report.",
    )

    # export
    ex_p = sub.add_parser("export", parents=[common_p], help="Export the current changelog.")
    ex_p.add_argument(
        "--format",
        default="md",
        help="Comma-separated export formats (default: md).",
    )

    # publish
    pub_p = sub.add_parser(
        "publish",
        parents=[common_p],
        help="Publish the most recently EXPORTED files as a GitHub PR.",
    )
    pub_p.add_argument("--repo", required=True, help="owner/repo")
    pub_p.add_argument("--title", required=True)
    pub_p.add_argument("--format", default="md")
    pub_p.add_argument("--body", default=None)

    return p


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    style = HouseStyle.keep_a_changelog()
    if args.style_file:
        raw = json.loads(Path(args.style_file).read_text(encoding="utf-8"))
        style = HouseStyle.from_dict(raw)
    create_remote = not getattr(args, "local_only", False)
    client = SuperDocsClient(
        config=SuperDocsConfig.from_env(api_key=args.api_key),
        mode=args.mode,
    ) if create_remote else SuperDocsClient(
        config=SuperDocsConfig(api_key="noop"),  # not used
        mode="passthrough",
    )
    maintainer = ChangelogMaintainer(
        state_path=args.state,
        superdocs=client,
        output_dir=args.output_dir,
    )
    document = maintainer.init(
        title=args.title,
        owner=args.owner,
        repo=args.repo,
        style=style,
        create_remote=create_remote,
        force=getattr(args, "force", False),
    )
    print(f"Initialized changelog: {document.title}")
    print(f"  state: {args.state}")
    print(f"  superdocs_document_id: {document.superdocs_document_id}")
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    payload = _load_payload(args.release_json)
    entry = ReleaseEntry.from_payload(payload)
    client = SuperDocsClient(
        config=SuperDocsConfig(api_key="noop"),  # preview never calls remote
        mode="passthrough",
    )
    maintainer = ChangelogMaintainer(
        state_path=args.state, superdocs=client, output_dir=args.output_dir
    )
    result = maintainer.preview(entry)
    print(f"Document: {result.document_title}")
    print(f"Anchor: would insert after heading containing {result.would_anchor_at!r}")
    print(f"Prior entries canonical hash:    {result.prior_hash}")
    print(f"After-insert prior hash:         {result.next_prior_hash}")
    if result.prior_hash != result.next_prior_hash:
        # This should never happen — we hash the OLD set both times.
        print("WARNING: prior hash changed during preview computation!")
        return 2
    print(f"New entry sha256:                {result.new_entry_hash}")
    print("--- new entry ---")
    print(result.rendered_entry)
    print("--- end new entry ---")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    payload = _load_payload(args.release_json)
    entry = ReleaseEntry.from_payload(payload)
    client = (
        SuperDocsClient(
            config=SuperDocsConfig(api_key="dry-run"),
            mode="passthrough",
        )
        if args.dry_run
        else SuperDocsClient(
            config=SuperDocsConfig.from_env(api_key=args.api_key),
            mode=args.mode,
        )
    )
    github = GitHubPublisher.from_env(token=args.github_token) if args.publish else None
    maintainer = ChangelogMaintainer(
        state_path=args.state,
        superdocs=client,
        github=github,
        output_dir=args.output_dir,
    )
    if not Path(args.state).exists():
        repo_owner = "org"
        repo_name = "repo"
        for l in entry.links:
            if "github.com/" in l.url:
                parts = l.url.split("github.com/")[1].split("/")
                if len(parts) >= 2:
                    repo_owner = parts[0]
                    repo_name = parts[1]
                    break
        maintainer.init(
            title=f"{repo_name.replace('-', ' ').title()} Changelog",
            owner=repo_owner,
            repo=repo_name,
            create_remote=not args.dry_run,
        )
    formats = tuple(f.strip() for f in args.format.split(",") if f.strip())
    outcome = maintainer.update(
        entry=entry,
        dry_run=args.dry_run,
        publish=args.publish,
        export_formats=formats,
    )
    run = outcome.run
    print(f"[{'DRY-RUN' if run.dry_run else 'UPDATE'}] release {entry.version} ({entry.date})")
    if run.verification is not None:
        print(f"  identity: {run.verification}")
    if outcome.html_check is not None:
        print(f"  html:     {outcome.html_check}")
    if outcome.exported_paths:
        print("  exported:")
        for path in outcome.exported_paths:
            print(f"    - {path}")
    if outcome.pr is not None:
        print(f"  PR: {outcome.pr.url}")
    for note in run.notes:
        print(f"  note: {note}")
    if not run.verification or not run.verification.passed:
        return 1
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    client = SuperDocsClient(
        config=SuperDocsConfig(api_key="noop"), mode="passthrough"
    )
    maintainer = ChangelogMaintainer(
        state_path=args.state, superdocs=client, output_dir=args.output_dir
    )
    result = maintainer.verify()
    print(result)
    return 0 if result.passed else 1


def cmd_export(args: argparse.Namespace) -> int:
    client = SuperDocsClient(
        config=SuperDocsConfig.from_env(api_key=args.api_key),
        mode=args.mode,
    )
    maintainer = ChangelogMaintainer(
        state_path=args.state, superdocs=client, output_dir=args.output_dir
    )
    formats = tuple(f.strip() for f in args.format.split(",") if f.strip())
    paths = maintainer.export(formats)
    for path in paths:
        print(f"exported: {path}")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    from changelog_maintainer.publisher import GitHubPublisher, GitHubConfig

    client = SuperDocsClient(
        config=SuperDocsConfig.from_env(api_key=args.api_key), mode=args.mode
    )
    maintainer = ChangelogMaintainer(
        state_path=args.state, superdocs=client, output_dir=args.output_dir
    )
    formats = tuple(f.strip() for f in args.format.split(",") if f.strip())
    paths = maintainer.export(formats)
    files = {Path(p).name: Path(p).read_bytes() for p in paths}
    publisher = GitHubPublisher(config=GitHubConfig.from_env(token=args.github_token))
    pr = publisher.publish(
        repo=args.repo,
        files=files,
        title=args.title,
        body=args.body or "Automated changelog publish.",
    )
    print(f"PR opened: {pr.url}")
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_payload(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"release payload not found: {path}")
    return json.loads(p.read_text(encoding="utf-8"))


HANDLERS = {
    "init": cmd_init,
    "preview": cmd_preview,
    "update": cmd_update,
    "verify": cmd_verify,
    "export": cmd_export,
    "publish": cmd_publish,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "state"):
        args.state = "changelog.state.json"
    if not hasattr(args, "output_dir"):
        args.output_dir = "output"
    if not hasattr(args, "mode"):
        args.mode = "http"
    if not hasattr(args, "api_key"):
        args.api_key = None
    if not hasattr(args, "github_token"):
        args.github_token = None

    handler = HANDLERS[args.cmd]
    try:
        return handler(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
