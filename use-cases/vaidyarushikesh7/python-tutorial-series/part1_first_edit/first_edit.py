"""Part one. Connect, make one real edit, prove the rest of the document did not move.

    export SUPERDOCS_API_KEY=sk_...
    python3 sample/make_samples.py
    python3 part1_first_edit/first_edit.py

Costs one operation. Writes the edited HTML and a .docx into out/.

The point of this script is the check at the end. Anything can add a clause. The
reason to reach for a document API rather than a chat window is that the sections
you did not name come back with their text intact, so verifying that is the
lesson, not the decoration.

Two things the check has to know. Every element comes back carrying a new
data-chunk-id, so a raw string comparison reports the whole document as changed
and tells you nothing. And an insertion can land in the wrong place while the
summary line still reads correct, which is why placement is checked separately.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from superdocs import SuperDocs, SuperDocsError, Usage, save_export  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "sample" / "service-agreement.html"
OUT = ROOT / "out"

INSTRUCTION = """Insert a new section titled "Confidentiality" immediately after section 3, and renumber the sections that follow it.

The new section says: each party keeps the other's commercial information confidential for three years after the agreement ends; the obligation does not cover information already public, or information a party can show it held before disclosure; and either party may disclose where a court or regulator requires it, having first told the other party where it is lawful to do so.

Change nothing else. Leave the charges table, its rows and its formatting exactly as they are. Plain contractual English, no marketing language."""


def strip_chunk_ids(html: str) -> str:
    """Every element comes back carrying a data-chunk-id it did not go in with.

    That is how targeted edits address a paragraph later, so it is a feature. It
    also means a raw string comparison always reports every section as changed,
    which is the first thing that confuses people. Compare with these removed.
    """
    return re.sub(r'\s*data-chunk-id="[^"]*"', "", html)


def visible_text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def number_free(heading: str) -> str:
    return re.sub(r"^\d+(\.\d+)*\.?\s*", "", heading).strip().lower()


def sections(html: str) -> dict[str, str]:
    """Split a document into {heading: body} so two versions can be compared.

    Crude on purpose. A tutorial that needs an HTML parser to explain its own
    check has lost the reader before the check happens.
    """
    out: dict[str, str] = {}
    parts = re.split(r"<h2[^>]*>(.*?)</h2>", strip_chunk_ids(html), flags=re.S)
    for i in range(1, len(parts) - 1, 2):
        heading = re.sub(r"<[^>]+>", "", parts[i]).strip()
        out[heading] = parts[i + 1].strip()
    return out


def orphan_headings(html: str) -> list[str]:
    """Headings whose own body no longer follows them.

    This catches an insertion that landed between a heading and its paragraph,
    which is the failure this API actually produced on this document. Without a
    check like this the document looks fine in a summary line and wrong on paper.
    """
    clean = strip_chunk_ids(html)
    found = []
    for match in re.finditer(r"<h2[^>]*>(.*?)</h2>(.*?)(?=<h2|\Z)", clean, flags=re.S):
        heading = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        body = match.group(2)
        # A heading with nothing between it and the next heading means new content
        # was inserted into this section rather than after it, pushing this
        # section's own text below the newcomer.
        if not visible_text(body):
            found.append(heading)
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", default="docx", help="docx, pdf, html, markdown or txt")
    ap.add_argument("--model-tier", default=None, help="core, turbo, pro or max")
    args = ap.parse_args()

    if not SAMPLE.exists():
        print("Run python3 sample/make_samples.py first.", file=sys.stderr)
        return 2

    client = SuperDocs()

    # Step one: know what you are spending before you spend it.
    me = client.whoami()
    quota = me.get("quota", {})
    print(f"account   {me['account_id'][:8]}  tier {me['tier']}  "
          f"{quota.get('remaining')} of {quota.get('monthly_limit')} operations left")
    if quota.get("remaining", 0) < 1:
        print("No operations left this month. Nothing was sent.", file=sys.stderr)
        return 1

    original = SAMPLE.read_text(encoding="utf-8")
    before = sections(original)

    # Step two: a session. It holds the document, so later turns do not resend it.
    session_id = client.init_session()
    print(f"session   {session_id}")

    # Step three: the edit. document_html goes in on this turn and never again.
    print("editing   (a quiet wait here is the model working, not a hang)")
    result = client.chat(
        session_id=session_id,
        message=INSTRUCTION,
        document_html=original,
        model_tier=args.model_tier,
    )

    changes = result.get("document_changes") or {}
    edited = changes.get("updated_html")
    if not edited:
        print(f"No document HTML came back. Summary: {changes.get('changes_summary')!r}", file=sys.stderr)
        return 1

    usage = Usage.from_response(result.get("usage"))
    print(f"charged   {usage.ops_charged} operation, {usage.monthly_remaining} left")
    if changes.get("changes_summary"):
        print(f"summary   {changes['changes_summary'][:160]}")

    # Step four: the checks that make the whole thing worth doing.
    after = sections(edited)
    keys_before = {number_free(h) for h in before}
    added = [h for h in after if number_free(h) not in keys_before]
    print(f"\nadded     {added or 'nothing, which means the edit missed'}")

    untouched, changed, missing = [], [], []
    for heading, body in before.items():
        # Headings get renumbered by design, so match on the words, not the number.
        match = next((h for h in after if number_free(h) == number_free(heading)), None)
        if match is None:
            missing.append(heading)
        elif visible_text(after[match]) == visible_text(body):
            untouched.append(heading)
        else:
            changed.append(heading)

    print(f"unchanged {len(untouched)} of {len(before)} original sections kept their text exactly")
    if changed:
        print(f"changed   {changed}")
    if missing:
        print(f"MISSING   {missing}   <-- a section the edit was told not to touch is gone")

    rows_before = original.count("<tr>")
    rows_after = edited.count("<tr>")
    print(f"table     {rows_before} rows before, {rows_after} after"
          f"{'' if rows_before == rows_after else '   <-- the table lost or gained rows, which it should not have'}")

    # Presentational attributes on the table are worth checking separately, since
    # a table with the right rows and no borders still prints wrong.
    attrs_before = set(re.findall(r"<table([^>]*)>", original))
    attrs_after = set(re.findall(r"<table([^>]*)>", strip_chunk_ids(edited)))
    if attrs_before != attrs_after:
        print(f"table     attributes changed on the round trip: {attrs_before} -> {attrs_after}")

    orphans = orphan_headings(edited)
    if orphans:
        print(f"PLACEMENT {orphans}   <-- new content landed inside this section, "
              f"between its heading and its own text")
        print("          Part two adds the review step that catches this before it applies.")

    # Step five: leave something on disk a person can open.
    OUT.mkdir(exist_ok=True)
    (OUT / "service-agreement.edited.html").write_text(edited, encoding="utf-8")
    try:
        payload = client.export(session_id=session_id, fmt=args.format,
                                filename=f"service-agreement.{args.format}")
        written = save_export(payload, OUT / f"service-agreement.{args.format}")
        print(f"\nwrote     out/service-agreement.edited.html")
        print(f"wrote     out/service-agreement.{args.format} ({written / 1024:.1f} KB, export is free)")
    except SuperDocsError as exc:
        print(f"\nEdit succeeded, export did not: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SuperDocsError as exc:
        print(f"SuperDocs: {exc}", file=sys.stderr)
        raise SystemExit(1)
