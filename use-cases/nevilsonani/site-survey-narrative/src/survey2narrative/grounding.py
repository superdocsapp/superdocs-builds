"""Grounding verification - the app-side proof that the narrative only
claims what its evidence supports.

Parses the exported markdown; every observation line in an evidence-bearing
section must cite at least one evidence id that actually exists in the
bundle. Lines under 'Requires Second Visit' are the honest exceptions.
The check FAILS on fabricated citations (ids not in the bundle).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

EVIDENCE_SECTIONS = {
    "Roof Structure & Condition",
    "Shading Assessment",
    "Electrical Service",
    "Access & Safety",
    "Design Assumptions & Constraints",
}
EXEMPT_SECTIONS = {"Property & Visit", "Requires Second Visit", "Evidence Index"}

_TAG_RE = re.compile(r"\[([A-Za-z0-9_.\-]+)\]")
# models also cite by embedding the image or with parenthesised ids - a
# citation is a citation whatever the syntax, so accept all three forms
_IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
_PAREN_RE = re.compile(r"\(((?:IMG|vn)_[A-Za-z0-9_.\-]+|measurements\.csv)\)")


def _find_tags(line: str) -> list[str]:
    tags = _TAG_RE.findall(line)
    tags += [t.rsplit("/", 1)[-1] for t in _IMG_RE.findall(line)]
    tags += _PAREN_RE.findall(line)
    return list(dict.fromkeys(tags))


def known_evidence_ids(bundle_dir: Path) -> set[str]:
    manifest = yaml.safe_load((bundle_dir / "manifest.yaml").read_text(encoding="utf-8"))
    ids = {p.name for p in (bundle_dir / "photos").glob("*.png")}
    ids.add("measurements.csv")
    for n in manifest.get("voice_notes", []):
        ids.add(n)
        ids.add(n.removesuffix(".txt"))
    return ids


def verify(md_path: Path, bundle_dir: Path) -> dict:
    known = known_evidence_ids(bundle_dir)
    section = ""
    supported, unsupported, fabricated = [], [], []
    for raw in md_path.read_text(encoding="utf-8").splitlines():
        # the markdown exporter escapes underscores (IMG\_01...) - normalize
        line = raw.replace("\\_", "_").strip()
        if line.startswith("#"):
            section = line.lstrip("#").strip()
            continue
        if not line or line.startswith("|") or section in EXEMPT_SECTIONS:
            continue
        if section in EVIDENCE_SECTIONS and len(line) > 30:
            tags = _find_tags(line)
            if not tags:
                unsupported.append((section, line[:110]))
                continue
            bad = [t for t in tags if t not in known]
            if bad:
                fabricated.append((section, bad, line[:110]))
            else:
                supported.append((section, tags))
    return {
        "supported": len(supported),
        "unsupported": unsupported,
        "fabricated": fabricated,
        # an empty narrative must fail, not vacuously pass: a real assessment
        # of this bundle carries well over five cited observations
        "ok": not unsupported and not fabricated and len(supported) >= 5,
    }


def print_report(result: dict) -> None:
    print(f"grounding check: {result['supported']} observation(s) fully cited")
    for section, line in result["unsupported"]:
        print(f"  UNSUPPORTED [{section}]: {line}")
    for section, bad, line in result["fabricated"]:
        print(f"  FABRICATED CITATION {bad} [{section}]: {line}")
    print("grounding: PASS - every claim traces to bundle evidence"
          if result["ok"] else
          "grounding: FAIL - the narrative claims more than its evidence")
