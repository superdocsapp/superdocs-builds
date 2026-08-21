#!/usr/bin/env bash
# The whole build, narrated. Needs SUPERDOCS_API_KEY.
#
#   ./demo.sh              full run (~26 operations)
#   ./demo.sh --dry-run    the same walkthrough, costing nothing
#
# The order record ships at 1 Gbps single path with a February date, and the
# change applied halfway through is the one that actually happens: the customer
# upgrades to 10 Gbps with route diversity and the date moves out.
set -euo pipefail

DRY=""
[ "${1:-}" = "--dry-run" ] && DRY="--dry-run"

bold() { printf "\n\033[1m%s\033[0m\n" "$*"; }
dim()  { printf "\033[2m%s\033[0m\n" "$*"; }
py()   { python3 -m packet "$@"; }

if [ -z "$DRY" ] && [ -z "${SUPERDOCS_API_KEY:-}" ] && [ ! -f .env ]; then
  echo "SUPERDOCS_API_KEY is not set. Either export it, copy .env.example to .env,"
  echo "or run ./demo.sh --dry-run to see the whole walkthrough without spending anything."
  exit 1
fi

bold "1. Check the templates before trusting them (offline, free)"
py audit

bold "2. Build both packs from one order record"
dim "   twelve documents: six for delivery, six for the customer"
py build $DRY

bold "3. What the two packs actually differ by"
if [ -d out/internal ]; then
  for f in out/internal/*.html; do
    name=$(basename "$f")
    lines=$(diff <(sed 's/internal pack/PACK/' "$f") \
                 <(sed 's/customer pack/PACK/' "out/customer/$name") \
             | grep -c '^<' || true)
    printf "   %-36s %s line(s) internal-only\n" "$name" "$lines"
  done
fi

bold "4. The change: 1 Gbps single path → 10 Gbps dual path, date moves out"
dim "   every document that carries one of those values gets a targeted edit;"
dim "   the ones that do not are never contacted"
py change \
  --set service.bandwidth_mbps=10000 \
  --set service.diversity=dual \
  --set 'service.protection=1+1 path protection' \
  --set delivery.rfs_date=2026-04-30 \
  --set delivery.install_date=2026-04-13 \
  --write-back \
  ${DRY:---yes}

bold "5. Prove it"
py verify ${DRY:+} || true

bold "6. Export what you would actually send"
if [ -z "$DRY" ]; then
  py export --format docx
  py export --format pdf --audience customer
else
  dim "   skipped in a dry run"
fi

bold "Done."
echo "   out/internal/   the delivery team's pack"
echo "   out/customer/   the customer's pack"
echo "   out/manifest.json  session and document ids, for the next change"
