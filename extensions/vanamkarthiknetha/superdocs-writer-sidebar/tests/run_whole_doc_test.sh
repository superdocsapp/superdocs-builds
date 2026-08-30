#!/bin/bash
# Whole-document write-back test harness (Linux). OFFLINE: no API key needed,
# costs 0 operations. Starts a throwaway headless LibreOffice on an ISOLATED
# profile (port 2003, so it can run alongside run_style_test.sh) and drives
# writeback.apply_changes against a real Writer document.
# Needs: libreoffice-writer, python3-uno.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PROFILE=/tmp/lotest-superdocs-wholedoc
rm -rf "$PROFILE"
soffice --headless --invisible --norestore \
  "-env:UserInstallation=file://$PROFILE" \
  --accept="socket,host=localhost,port=2003;urp;" &
LOPID=$!
PYTHONPATH=/usr/lib/libreoffice/program timeout 240 python3 "$HERE/whole_doc_test.py"
RC=$?
kill "$LOPID" 2>/dev/null
exit "$RC"
