#!/usr/bin/env python3
"""The terminal door to the same engine as the web page.

    python3 backend/cli.py broken.docx
    python3 backend/cli.py broken.docx --local-only

The recovery is one flow: the damaged file is rebuilt locally, and the rebuild
is styled through SuperDocs. The styled file is the deliverable — that is what
this build promises — and the plain rebuild is what you get instead when the
styling pass cannot run. `--local-only` skips the pass entirely, for working
offline or without spending an operation.

It prints a strict JSON manifest to stdout and exits 0 even when the styling
pass fails, because a styling failure is not the caller's failure: they still
have a recovered document.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from docrepair import engine
from docrepair.superdocs_client import SuperDocsClient


def run(path: Path, local_only: bool) -> int:
    data = path.read_bytes()
    name = path.name

    result = engine.repair(data, name)

    path_taken = "local_only" if local_only else "local"
    styling_note = ""
    delivered = result.output_path

    if result.ok and not local_only:
        styling = SuperDocsClient().style(
            result.output, Path(result.output_path).name,
            on_progress=lambda stage, message: print(
                f"  {message}", file=sys.stderr),
        )
        styling_note = styling.note
        if styling.ok:
            out = Path(result.output_path).with_name("final_recovered.docx")
            out.write_bytes(styling.output)
            delivered = str(out)
            path_taken = "superdocs_success"
        elif styling.rejected_for_content:
            path_taken = "superdocs_rejected"
        else:
            path_taken = "superdocs_failed"

    manifest = {
        "verdict": result.verdict,
        "word_count": result.word_count,
        # Reported because a recovery that lost the photographs is not the same
        # recovery as one that kept them, and a manifest that says only how many
        # words came back cannot tell the two apart.
        "images_recovered": result.images_recovered,
        "images_unplaced": result.images_unplaced,
        "images_lost": result.images_lost,
        "tables_recovered": result.tables_recovered,
        "structure_preserved": result.structure_preserved,
        "path_taken": path_taken,
        # Which file the caller should actually take. The styled one when there
        # is one, the plain rebuild when there is not -- named either way, so a
        # script never has to infer it from path_taken.
        "delivered": delivered,
        "styled": path_taken == "superdocs_success",
        "styling_note": styling_note,
    }
    print(json.dumps(manifest))
    # Graceful degradation: SuperDocs failure is not the caller's failure.
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Best-effort recovery for a Word document that will not open.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("filepath", type=Path, help="the damaged .docx file")
    p.add_argument("--local-only", action="store_true",
                   help="skip the SuperDocs styling pass and keep the plain "
                        "rebuild (no key needed, no operation spent)")
    # Accepted and ignored: styling is the default path now, and a script that
    # still passes this flag should keep working rather than fail on an
    # unrecognised argument.
    p.add_argument("--via-superdocs", action="store_true",
                   help=argparse.SUPPRESS)
    p.add_argument("--auto-approve", action="store_true",
                   help=argparse.SUPPRESS)
    a = p.parse_args(argv)

    if not a.filepath.exists():
        print(f"{a.filepath}: no such file", file=sys.stderr)
        return 2

    return run(a.filepath, a.local_only)


if __name__ == "__main__":
    raise SystemExit(main())
