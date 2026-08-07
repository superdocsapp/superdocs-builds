"""Command-line interface for the exhibit indexer and cover-page engine.

Usage:
    exhibit-engine run --brief brief.md --evidence evidence/ [--out out/]
                       [--format html|pdf|docx] [--live | --mock]
                       [--add-late extra.pdf --after 2]...

``--live`` drives the real SuperDocs API (key from ``SUPERDOCS_API_KEY`` or
``--key``); ``--mock`` drives the bundled in-memory fake — both run the exact
same four-call contract (upload, chat with approval gate, approve, export).
Each ``--add-late`` insertion renumbers covers, index and citations together, and
the exported packet always matches the renumbered set.
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

from . import crew, proposals
from .covers import render_cover, render_packet_cover
from .flow import run_filing
from .index import render_index
from .loader import load_evidence
from .paging import paginate_set, render_packet
from .superdocs import SuperDocsClient


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    out = Path(args.out) if args.out else Path.cwd() / "packet-out"
    out.mkdir(parents=True, exist_ok=True)

    brief = Path(args.brief).read_text(encoding="utf-8", errors="replace")

    evidence_paths: list[Path] = []
    for entry in args.evidence:
        p = Path(entry)
        if p.is_dir():
            evidence_paths.extend(
                f for f in sorted(p.iterdir())
                if f.suffix.lower() in {".pdf", ".docx", ".txt", ".md", ".html", ".htm", ".rtf"}
            )
        else:
            evidence_paths.append(p)
    for extra in args.files:
        evidence_paths.append(Path(extra))
    if not evidence_paths:
        print("error: no evidence files found", file=sys.stderr)
        return 2

    items = load_evidence([str(p) for p in evidence_paths])

    # Optionally let the CrewAI CoverWriter produce the cover-page text.
    cover_writer = None
    if crew.available() and not args.no_crew:
        cover_writer = crew.make_cover_writer()
    proposal = proposals.propose(brief, items, cover_writer=cover_writer)

    # Late insertions: add each exhibit, then renumber + re-cite everything.
    for extra in args.add_late:
        _insert_late(proposal, extra.file, extra.after, brief)

    # 1. Render the local, reviewable packet (page ranges always match the index).
    paginate_set(proposal.set)
    html = render_packet(proposal.set)
    local_html = out / "packet.html"
    local_html.write_text(html, encoding="utf-8")

    # 2. If requested, drive the SuperDocs flow and keep its export too. The
    # export is the *edited brief* (citations spliced in), so it gets its own
    # filename — never overwrite the assembled review packet.
    if args.mock or args.live:
        client = _build_client(args)
        result = run_filing(
            client, brief, proposal,
            fmt=args.format, model_tier=args.model_tier,
        )
        ext = ".pdf" if args.format == "pdf" else (
            ".docx" if args.format == "docx" else f".{args.format}"
        )
        export_path = out / f"brief-with-citations{ext}"
        export_path.write_bytes(result.export.content)
        print(f"exported: {export_path}  (session {result.session_id}, job {result.job_id})")
        print(f"approved {len(result.approved)} / "
              f"{len(result.approved) + len(result.denied)} proposed changes")

    # 3. Summary that proves the invariant.
    print(f"wrote review packet: {local_html}")
    _print_summary(proposal)

    if not (args.mock or args.live):
        print("\n(no SuperDocs run: pass --mock or --live to execute the 4-call contract)")
    return 0


def _insert_late(proposal: proposals.Proposal, file: str, after: int, brief: str) -> None:
    item = load_evidence([file])[0]
    title = proposals._human_title(item.source)
    proposal.set.add(
        source=Path(item.source),
        title=title,
        proves=proposals._default_cover_writer(title, item.text),
        content=item.text,
        after=after,
    )
    # Renumber covers, index and citations together.
    proposal.repropose(brief)
    print(f"late-inserted {file} after exhibit {after}; "
          f"renumbered covers, index, citations and page ranges")


def _build_client(args: argparse.Namespace) -> SuperDocsClient:
    if args.mock:
        return SuperDocsClient(base_url=_mock_base_url(), api_key=None)
    key = args.key or os.environ.get("SUPERDOCS_API_KEY") or _personal_key()
    if not key:
        print(
            "error: no SuperDocs API key. Export SUPERDOCS_API_KEY, pass --key, "
            "or save the dashboard key to ~/.superdocs/personal_key.txt "
            "(use.superdocs.app → Settings → API Keys).",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return SuperDocsClient(base_url="https://api.superdocs.app", api_key=key)


def _personal_key() -> str | None:
    """The dashboard API key saved to ``~/.superdocs/personal_key.txt``, if any.

    Read straight from the file into the request — never echoed. (The earlier
    agent-account flow is retired: an agent account stays on its own free tier
    and cannot be merged into an existing human account, so live runs use the
    human account's key — and its credits — instead.)
    """
    from pathlib import Path

    keyfile = Path.home() / ".superdocs" / "personal_key.txt"
    if not keyfile.exists():
        return None
    return keyfile.read_text(encoding="utf-8").strip() or None


def _mock_base_url() -> str:
    from .mock_server import start_server

    base, _stop, _state = start_server()
    return base


def _print_summary(proposal: proposals.Proposal) -> None:
    print(f"\nExhibit order ({len(proposal.set)} exhibits):")
    for ex in proposal.set:
        print(f"  Ex. {ex.number:<2} {ex.title:<40} pages {ex.page_range}")
    print(f"\nIn-brief citations ({len(proposal.citations)}):")
    for c in proposal.citations:
        print(f"  Ex. {c.exhibit_number:<2} anchor: {c.anchor[:52]!r}  [{c.rationale[:44]}]")
    print(f"\nOrder note: {proposal.order_note}")


def _parse(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="exhibit-engine", description=__doc__)
    ap.add_argument("run", nargs="?", default="run")
    ap.add_argument("--brief", required=True)
    ap.add_argument("--evidence", action="append", default=[])
    ap.add_argument("files", nargs="*", help="additional evidence files")
    ap.add_argument("--out")
    ap.add_argument("--format", default="pdf", choices=["pdf", "docx", "html", "markdown", "txt"])
    ap.add_argument("--model-tier", choices=["core", "turbo", "pro", "max"])
    ap.add_argument("--live", action="store_true", help="call the real SuperDocs API")
    ap.add_argument("--mock", action="store_true", help="call the bundled mock server")
    ap.add_argument("--key")
    ap.add_argument("--no-crew", action="store_true", help="skip the CrewAI cover writer")
    ap.add_argument("--add-late", action="append", type=_late_parse, default=[],
                    metavar="FILE:AFTER", help="insert an exhibit late, e.g. --add-late scan.pdf:2")
    return ap.parse_args(argv)


def _late_parse(value: str) -> argparse.Namespace:
    if ":" not in value:
        raise argparse.ArgumentTypeError("expected FILE:AFTER, e.g. scan.pdf:2")
    file, after = value.rsplit(":", 1)
    return argparse.Namespace(file=file, after=int(after))


if __name__ == "__main__":
    raise SystemExit(main())
