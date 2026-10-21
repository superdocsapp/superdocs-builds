#!/usr/bin/env bash
#
# Render the two one-page documents to PDF — exactly A4, exactly one page each.
#
#   docs/make-diagram.py  -> docs/architecture-diagram.svg
#   docs/make-writeup.py  -> docs/one-page-writeup.svg
#   this script           -> docs/*.pdf
#
# The SVGs are the source of truth. Chrome is used only as a printer: it is the one
# renderer on a stock Mac that honours @page and emits a true vector PDF rather
# than a rasterised one. Set CHROME to override the path.
set -euo pipefail
cd "$(dirname "$0")/.."

CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
if [ ! -x "$CHROME" ]; then
  echo "Chrome not found at: $CHROME" >&2
  echo "Set CHROME=/path/to/chrome and re-run. The SVGs in docs/ are already usable as-is." >&2
  exit 1
fi

python3 docs/make-diagram.py
python3 docs/make-writeup.py

for name in architecture-diagram one-page-writeup; do
  python3 docs/wrap-svg.py "$name" "/tmp/mc-$name.html"
  "$CHROME" --headless=new --disable-gpu --no-pdf-header-footer \
    --virtual-time-budget=6000 --print-to-pdf="docs/$name.pdf" \
    "file:///tmp/mc-$name.html" 2>/dev/null
  echo "wrote docs/$name.pdf"
done
