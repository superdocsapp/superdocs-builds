"""
Compatibility report generator — the centerpiece.

Consumes oasdiff's JSON changelog for a (base -> revision) spec pair and produces:
  - reports/compat.md    a clean human-readable report
  - reports/compat.json  a structured summary (for machines / CI)

It classifies every change as BREAKING or SAFE using oasdiff's severity level
(3 = breaking/error, 2 = warning, 1 = info/additive) and, with --gate, exits
non-zero when any breaking change is present — so CI fails on an incompatible
spec bump.

Usage:
  python scripts/compat.py --changelog reports/changelog.json \
      --base specs/superdocs-old.json --revision specs/superdocs-new.json \
      --out reports [--gate]
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

LEVEL_BREAKING = 3
LEVEL_WARNING = 2


def _spec_meta(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
        return {
            "file": os.path.basename(path),
            "version": d.get("info", {}).get("version", "?"),
            "title": d.get("info", {}).get("title", "?"),
            "paths": len(d.get("paths", {})),
        }
    except Exception:
        return {"file": os.path.basename(path), "version": "?", "title": "?", "paths": 0}


def _row(c):
    ep = f"{c.get('operation', '')} {c.get('path', '')}".strip()
    return {"id": c.get("id", ""), "endpoint": ep, "detail": c.get("text", "")}


def build(changelog, base, revision):
    breaking = [_row(c) for c in changelog if c.get("level") == LEVEL_BREAKING]
    warnings = [_row(c) for c in changelog if c.get("level") == LEVEL_WARNING]
    safe = [_row(c) for c in changelog if c.get("level") not in (LEVEL_BREAKING, LEVEL_WARNING)]

    base_m, rev_m = _spec_meta(base), _spec_meta(revision)
    compatible = len(breaking) == 0

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base": base_m,
        "revision": rev_m,
        "compatible": compatible,
        "counts": {
            "breaking": len(breaking),
            "warnings": len(warnings),
            "safe": len(safe),
            "total": len(changelog),
        },
        "breaking": breaking,
        "warnings": warnings,
        "safe": safe,
    }
    return summary


def _table(rows):
    if not rows:
        return "_none_\n"
    out = ["| Change | Endpoint | Detail |", "|---|---|---|"]
    for r in rows:
        detail = r["detail"].replace("|", "\\|")
        out.append(f"| `{r['id']}` | `{r['endpoint']}` | {detail} |")
    return "\n".join(out) + "\n"


def to_markdown(s):
    b, r = s["base"], s["revision"]
    verdict = "✅ BACKWARD COMPATIBLE" if s["compatible"] else "❌ BREAKING CHANGES"
    c = s["counts"]
    same_version = b["version"] == r["version"]
    lines = [
        "# API Compatibility Report",
        "",
        f"**{verdict}**",
        "",
        f"- Base: `{b['file']}` — {b['title']} v{b['version']} ({b['paths']} paths)",
        f"- Revision: `{r['file']}` — {r['title']} v{r['version']} ({r['paths']} paths)",
        f"- Generated: {s['generated_at']}",
        "",
        f"**{c['breaking']} breaking**, {c['warnings']} warning, {c['safe']} safe "
        f"({c['total']} total changes).",
        "",
    ]
    if same_version and c["total"] > 0:
        lines += [
            f"> ⚠️ Both specs declare version **{b['version']}**, yet the contract changed "
            f"({c['total']} differences). The version string alone does not signal "
            "compatibility — this diff does.",
            "",
        ]
    lines += ["## Breaking changes", "", _table(s["breaking"]), ""]
    if s["warnings"]:
        lines += ["## Warnings", "", _table(s["warnings"]), ""]
    lines += ["## Safe / additive changes", "", _table(s["safe"]), ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--changelog", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--revision", required=True)
    ap.add_argument("--out", default="reports")
    ap.add_argument("--gate", action="store_true",
                    help="exit non-zero if any breaking change is present (for CI)")
    args = ap.parse_args()

    changelog = json.load(open(args.changelog, encoding="utf-8"))
    summary = build(changelog, args.base, args.revision)

    os.makedirs(args.out, exist_ok=True)
    json.dump(summary, open(os.path.join(args.out, "compat.json"), "w", encoding="utf-8"), indent=2)
    open(os.path.join(args.out, "compat.md"), "w", encoding="utf-8").write(to_markdown(summary))

    n = summary["counts"]["breaking"]
    verdict = "compatible" if n == 0 else f"{n} BREAKING change(s)"
    print(f"compat report: {verdict} — wrote {args.out}/compat.md and compat.json")

    if args.gate and n > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
