#!/usr/bin/env bash
# Exact demo sequence referenced by README.md "Demo steps".
# Requires SUPERDOCS_API_KEY to be set (real operations are spent by this script).
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -z "${SUPERDOCS_API_KEY:-}" ]; then
  echo "SUPERDOCS_API_KEY is not set. See .env.example. Aborting demo." >&2
  exit 1
fi

echo "== 1. Create four Q4 debriefs (auto-approve for a smooth recorded demo) =="
winloss debrief create --transcript data/transcripts/2025q4_nimbus_freight_win.txt \
  --deal-code DEAL-2025Q4-001 --quarter 2025Q4 --segment Mid-Market --outcome win \
  --customer-name "Nimbus Freight Systems" --auto-approve

winloss debrief create --transcript data/transcripts/2025q4_solstice_retail_loss.txt \
  --deal-code DEAL-2025Q4-002 --quarter 2025Q4 --segment Enterprise --outcome loss \
  --customer-name "Solstice Retail Group" --auto-approve

winloss debrief create --transcript data/transcripts/2025q4_harbor_point_win.txt \
  --deal-code DEAL-2025Q4-003 --quarter 2025Q4 --segment SMB --outcome win \
  --customer-name "Harbor Point Clinics" --auto-approve

winloss debrief create --transcript data/transcripts/2025q4_ferrous_metalworks_loss.txt \
  --deal-code DEAL-2025Q4-004 --quarter 2025Q4 --segment Enterprise --outcome loss \
  --customer-name "Ferrous Metalworks Co" --auto-approve

echo
echo "== 2. List what's indexed for the quarter =="
winloss debrief list --quarter 2025Q4

echo
echo "== 3. Search the local index by competitor =="
winloss search --competitor "Comp Corp"

echo
echo "== 4. Synthesize the Quarterly Competitive Brief (redaction-gated) =="
winloss brief quarterly --quarter 2025Q4 --auto-approve

echo
echo "== 5. Verify the shared brief is clean of customer identifiers (independent, manual re-check) =="
winloss redact-check outputs/briefs/2025Q4.docx

echo
echo "Demo complete. See outputs/debriefs/ and outputs/briefs/."
