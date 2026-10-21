"""Wrap a one-page SVG in an HTML page sized to A4, ready for a browser to print."""
import io
import os
import sys

TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
  @page {{ size: 210mm 297mm; margin: 0; }}
  html, body {{ margin: 0; padding: 0; background: #fff; }}
  svg {{ display: block; width: 210mm; height: 297mm; }}
</style></head><body>
{svg}
</body></html>
"""


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: wrap-svg.py <name-without-extension> <output.html>", file=sys.stderr)
        return 2
    name, out_path = sys.argv[1], sys.argv[2]
    here = os.path.dirname(os.path.abspath(__file__))
    svg = io.open(os.path.join(here, f"{name}.svg"), encoding="utf-8").read()
    io.open(out_path, "w", encoding="utf-8").write(
        TEMPLATE.format(title=name.replace("-", " "), svg=svg)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
