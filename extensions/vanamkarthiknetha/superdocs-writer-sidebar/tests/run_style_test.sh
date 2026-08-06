#!/bin/bash
# Style-respect test harness (Linux).
# Starts a throwaway headless LibreOffice on an ISOLATED profile (does not
# touch your normal LibreOffice or its profile) and runs the UNO test on it.
# Needs: libreoffice-writer, python3-uno, and SUPERDOCS_API_KEY (or
# ~/.superdocs/agent_credentials.json). Costs 1 SuperDocs operation.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PROFILE=/tmp/lotest-superdocs
rm -rf "$PROFILE"
soffice --headless --invisible --norestore \
  "-env:UserInstallation=file://$PROFILE" \
  --accept="socket,host=localhost,port=2002;urp;" &
LOPID=$!
PYTHONPATH=/usr/lib/libreoffice/program timeout 240 python3 "$HERE/style_respect_test.py"
RC=$?
kill "$LOPID" 2>/dev/null
exit "$RC"
