#!/usr/bin/env bash
# The whole of docsync's free half, in about twenty seconds.
#
# No API key, no network, no operations spent. It copies the example service to
# a temporary directory so nothing in this repository is touched, changes the
# code the way a real commit would, and shows what docsync works out from that.
#
# Run `docsync apply` yourself afterwards if you want to see the paid half.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp -R "$HERE/example/." "$WORK/"
cd "$WORK"

rule() { printf '\n\033[1m%s\033[0m\n' "$1"; }

rule "1. What the code says right now"
python3 -m docsync facts --registry .

rule "2. Does each document actually contain what it claims to carry?"
python3 -m docsync audit --registry . || true

rule "3. Record where the documents currently stand"
python3 -m docsync snapshot --registry .

rule "4. Now change the code, the way a commit would"
python3 - <<'PY'
import pathlib
retry = pathlib.Path("src/provisioning/retry.py")
text = retry.read_text()
retry.write_text(
    text.replace("MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")
        .replace("BACKOFF_SECONDS = 30", "BACKOFF_SECONDS = 45")
)
api = pathlib.Path("src/provisioning/api.py")
text = api.read_text()
old = '    "POST /v1/circuits/{circuit_id}/provision": "provision_circuit",'
api.write_text(
    text.replace(old, old + '\n    "POST /v1/circuits/{circuit_id}/activate": "activate_circuit",')
)
print("  retry attempts 3 -> 5, backoff 30s -> 45s, one new endpoint")
PY

rule "5. What drifted, who carries it, and what it would cost"
python3 -m docsync plan --registry .

rule "6. The exact message that would be sent to one document"
python3 -m docsync plan --registry . --show-instruction docs/adr/0007-retry-policy.md \
  | sed -n '/--- instruction/,$p'

rule "Nothing was sent and nothing was billed."
echo "  To do it for real:  cd example && docsync apply --registry ."
echo "  Add --dry-run first if you want the cost without the call."
