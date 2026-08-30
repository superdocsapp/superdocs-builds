#!/bin/bash
# Whole-document LIVE round-trip harness (Linux). Costs 1 SuperDocs operation.
# Needs: libreoffice-writer, python3-uno, and SUPERDOCS_API_KEY (or
# ~/.superdocs/agent_credentials.json). Isolated profile, port 2004.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PROFILE=/tmp/lotest-superdocs-wholedoc-live
rm -rf "$PROFILE"
soffice --headless --invisible --norestore \
  "-env:UserInstallation=file://$PROFILE" \
  --accept="socket,host=localhost,port=2004;urp;" &
LOPID=$!
PYTHONPATH=/usr/lib/libreoffice/program timeout 600 python3 "$HERE/whole_doc_live_test.py"
RC=$?
kill "$LOPID" 2>/dev/null
exit "$RC"
