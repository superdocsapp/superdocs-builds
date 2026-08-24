#!/usr/bin/env bash
# Render docs/architecture.mmd (committed mermaid source) to SVG + PNG.
#
# One-time setup: fetch mermaid.js once into tools/vendor/ (network needed
# only for this fetch; rendering itself is offline):
#   mkdir -p tools/vendor && curl -L -o tools/vendor/mermaid.min.js \
#     https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js
#
# Usage: scripts/render_diagram.sh [outdir]
#   writes <outdir>/architecture.svg and <outdir>/architecture.png
#
# How it works: headless Chrome loads a wrapper page that runs the EXACT
# bytes of docs/architecture.mmd through mermaid.render, we dump the DOM to
# extract the <svg>, then screenshot the SVG at 2x for the PNG.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$(cd "$(dirname "${1:-out/task4-bundle}")" && pwd)/$(basename "${1:-out/task4-bundle}")"
SRC="$REPO/docs/architecture.mmd"
VENDOR="$REPO/tools/vendor/mermaid.min.js"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

[ -f "$VENDOR" ] || { echo "missing $VENDOR — run the curl in this file's header" >&2; exit 1; }
mkdir -p "$OUT"

{
  echo '<!doctype html><meta charset="utf-8"><body><div id="graph"></div>'
  echo '<script src="'"$VENDOR"'"></script><script>'
  echo 'const src = `'
  # escape backticks/backslashes so the .mmd embeds verbatim inside a template literal
  sed -e 's/\\/\\\\/g' -e 's/`/\\`/g' -e 's/\$/\\$/g' "$SRC"
  echo '`;'
  echo 'mermaid.initialize({startOnLoad:false, theme:"base", themeVariables:{'
  echo '  primaryColor:"#f5f7fa", primaryBorderColor:"#334155", primaryTextColor:"#0f172a",'
  echo '  lineColor:"#475569", fontSize:"15px"}, flowchart:{htmlLabels:false}});'
  echo 'mermaid.render("arch", src).then(r => { document.getElementById("graph").innerHTML = r.svg; });'
  echo '</script></body>'
} > "$TMP/page.html"

"$CHROME" --headless --disable-gpu --virtual-time-budget=8000 \
  --dump-dom "file://$TMP/page.html" > "$TMP/dom.html" 2>/dev/null
python3 - "$TMP/dom.html" "$OUT/architecture.svg" <<'EOF'
import re, sys
dom = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r"<svg[^>]*id=\"arch\".*?</svg>", dom, re.S)
if not m:
    sys.exit("no rendered <svg id=arch> found in DOM dump")
svg = m.group(0)
if svg.startswith("<svg"):  # ensure xmlns survives the round-trip
    svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1) \
        if "xmlns=" not in svg[:200] else svg
open(sys.argv[2], "w", encoding="utf-8").write(svg)
EOF

"$CHROME" --headless --disable-gpu --window-size=2400,1400 \
  --screenshot="$OUT/architecture.png" \
  "--screenshot-background=#ffffff" "file://$OUT/architecture.svg" 2>/dev/null

echo "wrote $OUT/architecture.svg and $OUT/architecture.png"
