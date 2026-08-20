import argparse
import sys

from .pipeline import adapt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="adapt",
        description="Adapt a Western-typeset HTML/Markdown document to CJK typography "
                    "conventions (or the reverse), with side-by-side comparison and a checklist report.",
    )
    parser.add_argument("input", help="input document (.html or .md)")
    parser.add_argument("--locale", default="ja", choices=["ja", "zh-CN", "zh-TW", "ko"],
                        help="target CJK locale (default: ja)")
    parser.add_argument("--reverse", action="store_true",
                        help="reverse direction: CJK typography back to Western (Latin) conventions")
    parser.add_argument("--out-dir", default="out", help="output directory (default: out)")
    parser.add_argument("--format", default="both", choices=["html", "docx", "both"],
                        help="which adapted outputs to write (default: both)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    formats = ("html", "docx") if args.format == "both" else (args.format,)
    try:
        result = adapt(args.input, locale=args.locale, out_dir=args.out_dir,
                       formats=formats, reverse=args.reverse)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    p = result.profile
    rule_counts = ", ".join(f"{k}={v['count']}" for k, v in result.stats.items())
    print(f"Adapted {result.title!r} to {p.label} ({p.lang}, {p.direction})")
    print(f"  rules applied: {rule_counts}")
    print(f"  wrote: {result.out_html}")
    if result.out_docx:
        print(f"  wrote: {result.out_docx}")
    print(f"  wrote: {result.comparison_html}")
    print(f"  wrote: {result.checklist_json}")
    print(f"  wrote: {result.checklist_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
