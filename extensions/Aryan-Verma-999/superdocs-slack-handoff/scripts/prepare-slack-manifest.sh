#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 https://your-public-host.example" >&2
  exit 64
fi

origin="${1%/}"
if [[ ! "$origin" =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?$ ]]; then
  echo "Expected one HTTPS origin, for example https://your-tunnel.ngrok.app" >&2
  exit 64
fi

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sed "s#https://REPLACE_WITH_PUBLIC_HOST#$origin#g" "$project_dir/slack-app-manifest.yaml" > "$project_dir/slack-app-manifest.local.yaml"
echo "Wrote $project_dir/slack-app-manifest.local.yaml"
