#!/usr/bin/env bash
#
# Build the plugin and install it into an Obsidian vault.
#
#   ./install-into-vault.sh ~/Desktop/DemoVault
#
# Real files are copied rather than symlinked. A symlinked plugin folder usually
# works, but when it does not the failure is silent — the plugin simply never
# appears in the installed list — and that is a bad thing to be debugging with a
# screen recorder running.
#
# Re-run this after every rebuild, then use "Reload app without saving" in Obsidian
# (Cmd+P) to pick up the new bundle.
set -euo pipefail
cd "$(dirname "$0")"

VAULT="${1:-}"
if [ -z "$VAULT" ]; then
  echo "usage: ./install-into-vault.sh /path/to/YourVault" >&2
  exit 2
fi
if [ ! -d "$VAULT" ]; then
  echo "No such folder: $VAULT" >&2
  exit 2
fi

ID="$(python3 -c 'import json;print(json.load(open("manifest.json"))["id"])')"
DEST="$VAULT/.obsidian/plugins/$ID"

npm run build --silent

mkdir -p "$DEST"
cp main.js manifest.json styles.css "$DEST/"

# Make sure the vault has this plugin in its enabled list, without clobbering any
# other plugins the vault already uses.
PLUGINS_JSON="$VAULT/.obsidian/community-plugins.json"
python3 - "$PLUGINS_JSON" "$ID" <<'PY'
import json, os, sys
path, plugin_id = sys.argv[1], sys.argv[2]
try:
    enabled = json.load(open(path))
    if not isinstance(enabled, list):
        enabled = []
except Exception:
    enabled = []
if plugin_id not in enabled:
    enabled.append(plugin_id)
os.makedirs(os.path.dirname(path), exist_ok=True)
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(enabled, f, indent=2)
    f.write("\n")
os.replace(tmp, path)
print("enabled:", ", ".join(enabled))
PY

echo "installed $ID -> $DEST"
echo "In Obsidian: Cmd+P -> \"Reload app without saving\""
