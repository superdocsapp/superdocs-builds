"""The command line.

`check` and `build` need no key and no network, which is deliberate: everything
this project actually guarantees -- the card matching the manual, the diagrams
being reproducible, a translation keeping its shape -- is checkable before
anything is uploaded. `publish` and `edit` are the two commands that spend
quota.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from manualbuilder import localize as lz, projections as pj, session
from manualbuilder.spec import SpecError, load_spec

DEFAULT_SPEC = Path("spec/halyard_m1.yaml")
LOCALES = Path("locales")
OUT = Path("out")


def _spec(args):
    return load_spec(args.spec)


def _locales(spec):
    """Every locale file next to the spec, keyed by language."""
    if not LOCALES.is_dir():
        return {}
    out = {}
    for path in sorted(LOCALES.glob("*.yaml")):
        locale = lz.load_locale(path)
        out[locale["language"]] = lz.localised_spec(spec, locale)
    return out


# ------------------------------------------------------------- offline --

def cmd_check(args) -> int:
    """Validate the spec and every locale. No network, no key."""
    spec = _spec(args)
    print(f"spec        {spec.name} rev {spec.revision} — "
          f"{len(spec.parts)} parts, {len(spec.steps)} steps, "
          f"{len(spec.warnings)} warnings")

    manual = pj.manual_html(spec)
    card = pj.quick_start_html(spec)

    # The consistency claim, checked rather than trusted.
    for step in spec.quick_start():
        if step.body not in manual or step.body not in card:
            print(f"  FAIL  step {step.id!r} differs between the two documents")
            return 1
    print(f"card        {len(spec.quick_start_steps)} of {len(spec.steps)} steps, "
          f"every instruction identical to the manual")

    failures = 0
    for language, localised in _locales(spec).items():
        try:
            lz.assert_same_structure(manual, pj.manual_html(localised), language)
            lz.assert_same_structure(card, pj.quick_start_html(localised), language)
        except lz.LocaleError as exc:
            print(f"  FAIL  {exc}")
            failures += 1
            continue
        ratio = len(pj.manual_html(localised)) / len(manual)
        print(f"locale {language}    structure identical, text {ratio:.0%} of source length")

    print("ok" if not failures else f"{failures} locale(s) would repaginate")
    return 1 if failures else 0


def cmd_build(args) -> int:
    """Render everything to `out/`. No network, no key."""
    spec = _spec(args)
    OUT.mkdir(exist_ok=True)

    diagrams = session.render_diagrams(spec)
    for image_id, svg in diagrams.items():
        (OUT / f"{image_id.replace(':', '_')}.svg").write_text(svg, encoding="utf-8")

    # Local files rather than uploaded URLs, so `out/` opens in a browser.
    images = {image_id: f"{image_id.replace(':', '_')}.svg" for image_id in diagrams}
    written = [("manual.html", pj.manual_html(spec, images)),
               ("quickstart.html", pj.quick_start_html(spec, images))]
    for language, localised in _locales(spec).items():
        written.append((f"manual.{language}.html", pj.manual_html(localised, images)))
        written.append((f"quickstart.{language}.html",
                        pj.quick_start_html(localised, images)))

    for name, html in written:
        (OUT / name).write_text(html, encoding="utf-8")

    print(f"{len(diagrams)} diagrams and {len(written)} documents in {OUT}/")
    return 0


# ------------------------------------------------------------- online --

def _client():
    from manualbuilder.superdocs import SuperDocs, load_dotenv

    load_dotenv()
    return SuperDocs()


def cmd_publish(args) -> int:
    spec = _spec(args)
    with _client() as client:
        published = session.publish(client, spec)
    print(f"manual  {published.manual_id}")
    print(f"card    {published.card_id}")
    print(f"images  {len(published.images)} uploaded")
    print("\nkeep those ids; `edit` needs them.")
    return 0


def cmd_edit(args) -> int:
    """One instruction, both documents, nothing applied without a look."""
    from manualbuilder.superdocs import SuperDocsError

    published = session.Publication(manual_id=args.manual, card_id=args.card)
    with _client() as client:
        changes, _ = session.edit_both(client, published, args.instruction)

        if not changes:
            print("the turn proposed no changes.")
            return 0

        grouped = session.changes_by_document(published, changes)
        for document_id, items in grouped.items():
            print(f"\n{published.name_for(document_id)} — {len(items)} change(s)")
            for change in items:
                print(f"  [{change.operation}] chunk {change.chunk_id}")
                print(f"    - {change.old_html[:100]}")
                print(f"    + {change.new_html[:100]}")
                if change.explanation:
                    print(f"    why: {change.explanation[:150]}")

        try:
            session.assert_touched_both(published, changes)
        except SuperDocsError as exc:
            print(f"\nREFUSED: {exc}")
            return 1

        if not args.yes:
            print("\nnothing approved. Re-run with --yes to apply.")
            return 0

        result = session.approve_all(client, published, changes)
        print(f"\napproved {len(changes)} change(s): {result.get('status', 'ok')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="manualbuilder", description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="validate the spec and every locale (offline)")
    sub.add_parser("build", help="render documents and diagrams to out/ (offline)")
    sub.add_parser("publish", help="upload both documents and their diagrams")

    edit = sub.add_parser("edit", help="one instruction, both documents")
    edit.add_argument("instruction")
    edit.add_argument("--manual", required=True, help="manual document id")
    edit.add_argument("--card", required=True, help="quick-start document id")
    edit.add_argument("--yes", action="store_true",
                      help="approve the proposed changes; without it, nothing is applied")

    args = parser.parse_args(argv)
    handler = {"check": cmd_check, "build": cmd_build,
               "publish": cmd_publish, "edit": cmd_edit}[args.command]
    try:
        return handler(args)
    except SpecError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
