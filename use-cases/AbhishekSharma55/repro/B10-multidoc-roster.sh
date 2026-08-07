#!/usr/bin/env bash
# Repro for bugs.md B10:
#   three documents opened into one session return a roster of ONE,
#   every entry carries document_id "doc_primary",
#   and identical successive GETs return different documents.
#
# Usage:  SUPERDOCS_API_KEY=sk_... ./B10-multidoc-roster.sh
# Costs:  zero billable operations. Uploads, session init and roster reads are free.

set -euo pipefail
: "${SUPERDOCS_API_KEY:?set SUPERDOCS_API_KEY}"
API=https://api.superdocs.app
AUTH="Authorization: Bearer ${SUPERDOCS_API_KEY}"
JSON="Content-Type: application/json"
STAMP=$(date +%s)

b64() { printf '%s' "$1" | base64 | tr -d '\n'; }

echo "1. upload three documents, each into its own session"
for pair in "gdd:<h1>GDD</h1><h2>Overview</h2><p>ov</p>" \
            "mechanics:<h1>Mechanics</h1><h2>Dash</h2><p>d</p>" \
            "narrative:<h1>Narrative</h1><h2>Act I</h2><p>a</p>"; do
  name="${pair%%:*}"; html="${pair#*:}"
  curl -s -X POST "$API/v1/documents/upload-base64" -H "$AUTH" -H "$JSON" \
    -d "{\"filename\":\"b10-$name-$STAMP.html\",\"file_base64\":\"$(b64 "$html")\",\"session_id\":\"b10-$STAMP-$name\"}" \
    > /dev/null
  echo "   uploaded b10-$name-$STAMP"
done

echo
echo "2. collect their durable document ids from GET /v1/documents"
IDS=$(curl -s "$API/v1/documents" -H "$AUTH" \
  | jq -c "[.documents[] | select(.title | startswith(\"b10-\") and endswith(\"$STAMP\")) | .document_id]")
echo "   $IDS"
test "$(echo "$IDS" | jq 'length')" -eq 3 || { echo "expected 3 ids"; exit 1; }

echo
echo "3. each id resolves individually (so they exist):"
for id in $(echo "$IDS" | jq -r '.[]'); do
  printf '   %s -> HTTP %s\n' "${id:0:8}" \
    "$(curl -s -o /dev/null -w '%{http_code}' "$API/v1/documents/$id" -H "$AUTH")"
done

echo
echo "4. open all three into ONE session"
SID="b10-session-$STAMP"
curl -s -X POST "$API/v1/sessions/init" -H "$AUTH" -H "$JSON" \
  -d "{\"session_id\":\"$SID\",\"document_ids\":$IDS}" \
  | jq -c '{opened:(.opened|length), roster_size:(.documents|length),
            roster:[.documents[]|{document_id,title}]}'

echo
echo "5. EXPECTED: three documents, three distinct document_ids, stable across reads."
echo "   ACTUAL:"
for i in 1 2 3 4; do
  printf '   read %d: ' "$i"
  curl -s "$API/v1/sessions/$SID/documents" -H "$AUTH" \
    | jq -c '[.documents[]|{document_id, durable:(.durable_document_id[0:8]), title}]'
done

echo
echo "Roster returns one of three documents, document_id is the constant string"
echo "\"doc_primary\", and which document you get changes between identical reads."
