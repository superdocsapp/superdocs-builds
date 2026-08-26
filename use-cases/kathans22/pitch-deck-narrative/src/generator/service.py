"""Single entry point: generate → guard → score for one vertical.

Idempotent for the current manifest version: if exports already exist and the
ledger has charged ``narrative:<vertical>:complete:v<N>``, SuperDocs is not
called again — the step is recorded SKIPPED and guard/score still run locally.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .divergence import write_divergence_report
from .format_guard import assert_not_deck
from .ledger import LEDGER_PATH, Ledger
from .manifest import load_validated, project_root
from .narrative import OUT_DIR, generate_narrative, parse_script_sections

logger = logging.getLogger(__name__)

EVIDENCE_DIR = project_root() / "evidence"
DIVERGENCE_REPORT_PATH = EVIDENCE_DIR / "divergence-report.json"


def manifest_version(bundle: dict[str, Any] | None = None) -> int:
    data = bundle or load_validated()
    return int((data["manifest"] or {}).get("manifest_version") or 1)


def complete_content_key(vertical_code: str, version: int | None = None) -> str:
    """Ledger key for a finished vertical at a given manifest version."""
    ver = version if version is not None else manifest_version()
    return f"narrative:{vertical_code}:complete:v{ver}"


def export_paths(
    vertical_code: str,
    product_name: str = "ClarityDocs",
    out_dir: Path | None = None,
) -> dict[str, Path]:
    dest = out_dir or OUT_DIR
    slug = product_name.lower().replace(" ", "")
    base = f"pitch-script-{vertical_code}-{slug}"
    return {
        "markdown": dest / f"{base}.md",
        "docx": dest / f"{base}.docx",
    }


def exports_exist(paths: dict[str, Path]) -> bool:
    return all(p.is_file() and p.stat().st_size > 0 for p in paths.values())


def guard_exports(
    paths: dict[str, Path],
    *,
    product_name: str = "ClarityDocs",
) -> None:
    """Re-assert format_guard on every export path. Raises FormatGuardError on fail."""
    title = f"{product_name} — Pitch Speaking Script"
    assert_not_deck(paths["markdown"], title, export_format="markdown")
    assert_not_deck(paths["docx"], title, export_format="docx")


def _product_name(bundle: dict[str, Any]) -> str:
    product = bundle["product"]
    block = product.get("product") or product
    return str(block.get("name") or "ClarityDocs")


def _section_weights(manifest: dict[str, Any]) -> dict[int, str]:
    return {
        int(section["number"]): str(section["weight"])
        for section in (manifest.get("sections") or [])
    }


def discover_exported_narratives(out_dir: Path | None = None) -> dict[str, dict[int, str]]:
    """Load section bodies from every ``pitch-script-<vertical>-*.md`` under out/."""
    dest = out_dir or OUT_DIR
    narratives: dict[str, dict[int, str]] = {}
    if not dest.is_dir():
        return narratives
    for path in sorted(dest.glob("pitch-script-*-*.md")):
        # pitch-script-<vertical>-<product>.md
        parts = path.stem.split("-")
        # ["pitch", "script", vertical, product...]
        if len(parts) < 4 or parts[0] != "pitch" or parts[1] != "script":
            continue
        vertical_code = parts[2]
        bodies = parse_script_sections(path.read_text(encoding="utf-8"))
        if bodies:
            narratives[vertical_code] = bodies
    return narratives


def score_available(
    out_dir: Path | None = None,
    *,
    report_path: Path | None = None,
    narratives_dir: Path | None = None,
) -> dict[str, Any]:
    """Pairwise divergence over exports on disk. 0 ops. Needs ≥2 verticals."""
    bundle = load_validated()
    if narratives_dir is not None:
        narratives: dict[str, dict[int, str]] = {}
        for path in sorted(Path(narratives_dir).glob("pitch-script-*-*.md")):
            parts = path.stem.split("-")
            if len(parts) < 4 or parts[0] != "pitch" or parts[1] != "script":
                continue
            bodies = parse_script_sections(path.read_text(encoding="utf-8"))
            if bodies:
                narratives[parts[2]] = bodies
    else:
        narratives = discover_exported_narratives(out_dir)
    weights = _section_weights(bundle["manifest"])
    dest = report_path or DIVERGENCE_REPORT_PATH

    if len(narratives) < 2:
        result = {
            "status": "deferred",
            "reason": "score_all requires at least two vertical exports on disk",
            "verticals_found": sorted(narratives.keys()),
            "report_path": None,
        }
        logger.info("divergence scoring deferred: %s", result["reason"])
        return result

    return write_divergence_report(
        narratives,
        weights,
        dest=dest,
        manifest_version=int((bundle["manifest"] or {}).get("manifest_version") or 1),
    )


async def run_vertical(
    vertical_code: str,
    *,
    out_dir: Path | None = None,
    ledger: Ledger | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Generate (unless idempotent skip), guard, and score for one vertical.

    Returns a result dict with ``skipped``, ``paths``, ``guard``, ``score``, and
    ``ops_total``. Never completes without format_guard passing on exports.
    """
    bundle = load_validated()
    if vertical_code not in bundle["verticals"]:
        raise KeyError(
            f"unknown vertical {vertical_code!r}; known: {sorted(bundle['verticals'])}"
        )

    version = manifest_version(bundle)
    product_name = _product_name(bundle)
    paths = export_paths(vertical_code, product_name=product_name, out_dir=out_dir)
    key = complete_content_key(vertical_code, version)
    ledger = ledger if ledger is not None else Ledger.load()

    already = (not force) and ledger.already_charged(key) and exports_exist(paths)
    generate_result: dict[str, Any] | None = None
    started = time.monotonic()

    if already:
        entry = ledger.record(
            step="generate",
            vertical=vertical_code,
            chat_calls=0,
            wall_time=time.monotonic() - started,
            content_key=key,
            output_exists=True,
        )
        assert entry.status == "SKIPPED"
        logger.info("idempotent skip for %s (%s)", vertical_code, key)
    else:
        generate_result = await generate_narrative(
            vertical_code,
            out_dir=out_dir,
            ledger=ledger,
        )
        # Mark the vertical complete for this manifest version (marker; batches
        # already charged their own keys inside generate_narrative).
        ledger.record(
            step="generate",
            vertical=vertical_code,
            chat_calls=0,
            wall_time=time.monotonic() - started,
            content_key=key,
            output_exists=False,
        )
        paths = {
            "markdown": Path(generate_result["paths"]["markdown"]),
            "docx": Path(generate_result["paths"]["docx"]),
        }

    # Guard — structural; blocks the run if exports look like a deck.
    guard_started = time.monotonic()
    guard_exports(paths, product_name=product_name)
    ledger.record(
        step="guard",
        vertical=vertical_code,
        chat_calls=0,
        wall_time=time.monotonic() - guard_started,
        content_key=f"guard:{vertical_code}:v{version}",
        output_exists=False,
    )

    # Score — local only; deferred until ≥2 verticals are on disk.
    score_started = time.monotonic()
    score = score_available(out_dir=out_dir or paths["markdown"].parent)
    ledger.record(
        step="score",
        vertical=vertical_code,
        chat_calls=0,
        wall_time=time.monotonic() - score_started,
        content_key=f"score:on-disk:v{version}",
        output_exists=False,
    )

    ledger.save()
    ledger.report()

    markdown_path = paths["markdown"]
    return {
        "vertical": vertical_code,
        "skipped": already,
        "manifest_version": version,
        "content_key": key,
        "paths": {k: str(v) for k, v in paths.items()},
        "guard": "passed",
        "score": score,
        "ready": True if already else bool(generate_result and generate_result.get("ready")),
        "generate": generate_result,
        "ops_total": ledger.total_operations,
        "ledger_status": "SKIPPED" if already else "CHARGED",
        "markdown_chars": markdown_path.stat().st_size if markdown_path.is_file() else 0,
    }


# Alias matching the module docstring / source-of-truth naming.
run = run_vertical


def list_verticals() -> dict[str, Any]:
    """Known verticals from config — adding a YAML is enough; no code change."""
    bundle = load_validated()
    codes = sorted(bundle["verticals"].keys())
    return {
        "verticals": codes,
        "manifest_version": manifest_version(bundle),
        "product": _product_name(bundle),
    }


def narrative_export_path(
    vertical_code: str,
    fmt: str = "markdown",
    *,
    out_dir: Path | None = None,
) -> Path:
    """Path to an exported speaking-script file (out/, then evidence/narratives)."""
    bundle = load_validated()
    if vertical_code not in bundle["verticals"]:
        raise KeyError(
            f"unknown vertical {vertical_code!r}; known: {sorted(bundle['verticals'])}"
        )
    fmt_n = fmt.lower()
    if fmt_n not in {"markdown", "md", "docx"}:
        raise ValueError(f"unsupported narrative format {fmt!r}; use markdown or docx")
    fmt_key = "markdown" if fmt_n in {"markdown", "md"} else "docx"
    product_name = _product_name(bundle)
    paths = export_paths(vertical_code, product_name=product_name, out_dir=out_dir)
    candidate = paths[fmt_key]
    if candidate.is_file() and candidate.stat().st_size > 0:
        return candidate
    evidence = EVIDENCE_DIR / "narratives" / candidate.name
    if evidence.is_file() and evidence.stat().st_size > 0:
        return evidence
    raise FileNotFoundError(
        f"no {fmt_key} export for vertical {vertical_code!r} at {candidate} "
        f"or {evidence}. Fix: generate the vertical first."
    )


async def run_verticals(
    vertical_code: str,
    *,
    out_dir: Path | None = None,
    ledger: Ledger | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Generate one vertical, or every configured vertical when code is ``all``."""
    bundle = load_validated()
    codes = sorted(bundle["verticals"].keys())
    if vertical_code != "all" and vertical_code not in bundle["verticals"]:
        raise KeyError(
            f"unknown vertical {vertical_code!r}; known: {codes} (or 'all')"
        )
    targets = codes if vertical_code == "all" else [vertical_code]
    results = [
        await run_vertical(code, out_dir=out_dir, ledger=ledger, force=force)
        for code in targets
    ]
    return {
        "requested": vertical_code,
        "verticals": targets,
        "results": results,
        "ops_total": results[-1]["ops_total"] if results else 0,
    }


def divergence_report(*, narratives_dir: Path | None = None) -> dict[str, Any]:
    """Return the on-disk divergence report, or score locally if none is stored."""
    import json

    path = DIVERGENCE_REPORT_PATH
    if narratives_dir is None and path.is_file() and path.stat().st_size > 0:
        return json.loads(path.read_text(encoding="utf-8"))
    return score_available(narratives_dir=narratives_dir, report_path=path)


def ledger_snapshot(*, ledger_path: Path | None = None) -> dict[str, Any]:
    """Live state ledger, falling back to the committed four-vertical snapshot."""
    path = ledger_path or LEDGER_PATH
    if path.is_file():
        ledger = Ledger.load(path)
        source = str(path)
    else:
        snapshot = EVIDENCE_DIR / "ledger-four-verticals.json"
        if snapshot.is_file():
            ledger = Ledger.load(snapshot)
            source = str(snapshot)
        else:
            ledger = Ledger()
            source = None
    return {
        "source": source,
        "total_operations": ledger.total_operations,
        "entries": [asdict(e) for e in ledger.entries],
    }
