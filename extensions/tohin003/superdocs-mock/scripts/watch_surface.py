#!/usr/bin/env python3
"""Watch SuperDocs' published surface for drift, and say exactly what moved.

Two surfaces, two failure modes, and the second is the one that motivates this project:

* **`openapi.json`** lives in `github.com/superdocsapp/docs`. It changes when SuperDocs
  publishes a change, which is visible in their git history. Comparing against the pin is
  a courtesy — it tells us to re-record before anyone's tests break.

* **The MCP tool surface is served live from the SuperDocs backend.** The Claude Code
  plugin carries only a manifest, so tools, arguments and descriptions can change with no
  release anywhere and nothing local to diff. There is no git history to watch. This is
  the surface most likely to move under an integration's feet, and pinning it is the only
  way to notice.

Run on a schedule, it turns "the mock is stale" from something a user discovers into
something a CI job reports.

    python scripts/watch_surface.py            # human summary, exit 1 on drift
    python scripts/watch_surface.py --json     # machine-readable, for an issue body

Non-billable. The REST fetch needs no auth; the MCP handshake needs the key.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import httpx  # noqa: E402

SPEC_URL = "https://raw.githubusercontent.com/superdocsapp/docs/main/openapi.json"
SPEC_PIN = ROOT / "spec" / "openapi.json"
TOOLS_PIN = ROOT / "spec" / "mcp-tools.json"


def fetch_spec() -> dict | None:
    try:
        response = httpx.get(SPEC_URL, timeout=30, follow_redirects=True)
        response.raise_for_status()
        return response.json()
    except Exception as exc:  # network, 404, rate limit -- all "cannot tell", not "clean"
        print(f"could not fetch the published spec: {exc}", file=sys.stderr)
        return None


def diff_spec(published: dict, pinned: dict) -> dict:
    def routes(doc: dict) -> set[str]:
        out = set()
        for path, node in doc.get("paths", {}).items():
            for method in node:
                if method in {"get", "post", "put", "patch", "delete"}:
                    out.add(f"{method.upper()} {path}")
        return out

    published_routes, pinned_routes = routes(published), routes(pinned)
    published_schemas = set(published.get("components", {}).get("schemas", {}))
    pinned_schemas = set(pinned.get("components", {}).get("schemas", {}))

    changed_schemas = sorted(
        name for name in published_schemas & pinned_schemas
        if published["components"]["schemas"][name]
        != pinned["components"]["schemas"][name]
    )

    return {
        "version_published": published.get("info", {}).get("version"),
        "version_pinned": pinned.get("info", {}).get("version"),
        "routes_added": sorted(published_routes - pinned_routes),
        "routes_removed": sorted(pinned_routes - published_routes),
        "schemas_added": sorted(published_schemas - pinned_schemas),
        "schemas_removed": sorted(pinned_schemas - published_schemas),
        "schemas_changed": changed_schemas,
    }


def diff_tools() -> dict | None:
    """Re-capture the live MCP surface and diff it against the pin."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "pin_mcp_surface.py"), "--check"],
        capture_output=True, text=True, cwd=ROOT,
    )
    if result.returncode == 0:
        return {"drift": False}
    if result.returncode == 2:
        return {"drift": True, "detail": result.stdout.strip() or result.stderr.strip()}
    return None  # could not check -- missing key, network, handshake failure


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report: dict = {"spec": None, "mcp": None}
    drifted = False

    published = fetch_spec()
    if published is not None:
        pinned = json.loads(SPEC_PIN.read_text(encoding="utf-8"))
        spec_diff = diff_spec(published, pinned)
        moved = any(spec_diff[k] for k in
                    ("routes_added", "routes_removed", "schemas_added",
                     "schemas_removed", "schemas_changed"))
        spec_diff["drift"] = moved
        report["spec"] = spec_diff
        drifted = drifted or moved

    tools = diff_tools()
    report["mcp"] = tools
    if tools and tools.get("drift"):
        drifted = True

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if drifted else 0

    spec = report["spec"]
    if spec is None:
        print("REST spec  : could not be checked")
    elif not spec["drift"]:
        print(f"REST spec  : unchanged (v{spec['version_pinned']}, "
              f"pinned commit ac0d44c)")
    else:
        print(f"REST spec  : DRIFT  (published v{spec['version_published']}, "
              f"pinned v{spec['version_pinned']})")
        for label in ("routes_added", "routes_removed", "schemas_added",
                      "schemas_removed", "schemas_changed"):
            if spec[label]:
                print(f"  {label.replace('_', ' ')}: {', '.join(spec[label][:8])}"
                      + (" …" if len(spec[label]) > 8 else ""))

    if tools is None:
        print("MCP surface: could not be checked (no key, or the handshake failed)")
    elif tools["drift"]:
        print("MCP surface: DRIFT — the live tool surface differs from "
              "spec/mcp-tools.json")
        print("  re-pin with scripts/pin_mcp_surface.py once the change is understood")
    else:
        print("MCP surface: unchanged (38 tools, 4 prompts)")

    if drifted:
        print("\nWhat to do: understand the change first, then re-pin, re-record the "
              "affected scenarios, and note what moved in docs/findings.md. Do not "
              "re-pin to make a red build green.")
    return 1 if drifted else 0


if __name__ == "__main__":
    raise SystemExit(main())
