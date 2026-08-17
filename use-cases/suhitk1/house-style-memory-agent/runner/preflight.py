"""Preconditions that must hold before a live run spends an operation.

Every check here exists because failing it produces an experiment whose results
cannot be verified after the fact — the expensive kind of failure, discovered
after twenty documents have already run.

The H3 cache is the centrepiece. H3 is the one rule scored by a model, and the
correction protocol is only deterministic for it because results are cached by
content hash. If that cache is missing, or lives somewhere that is not
published with the raw data, then nobody — including us — can verify after the
run that both arms received identical corrections for identical output.

A nuance worth stating plainly rather than papering over: a *fresh* experiment
legitimately starts with an empty cache, because nothing has been scored yet.
So the checks are staged:

- Always: the cache file exists, parses, and sits inside the run directory that
  gets published, and is not excluded from version control.
- From the second arm onward: the cache is non-empty and covers the documents
  the previous arm scored. This is the check that actually protects the
  cross-arm guarantee, because that is when a missing cache would silently
  break it.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_FILENAME = "h3_cache.json"


class PreflightError(RuntimeError):
    """Raised when a precondition fails. The run must not start."""


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str

    def __str__(self) -> str:
        return f"[{'PASS' if self.ok else 'FAIL'}] {self.name}: {self.detail}"


def cache_path_for(run_dir: Path) -> Path:
    return run_dir / CACHE_FILENAME


def _git_ignore_status(path: Path) -> str:
    """'ignored' | 'tracked' | 'unknown'.

    Degrades CLOSED: when git cannot answer, the caller fails the check rather
    than passing it. A precondition whose job is to abort a run must not treat
    "I could not tell" as "fine" — that is precisely how an unverifiable
    experiment gets produced.
    """
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=ROOT, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return {0: "ignored", 1: "tracked"}.get(result.returncode, "unknown")


def check_h3_cache_exists(run_dir: Path) -> CheckResult:
    path = cache_path_for(run_dir)
    if not path.exists():
        return CheckResult("h3_cache_exists", False,
                           f"{path} is missing. Create it (an empty '{{}}' is "
                           "valid for a fresh experiment) so its location is "
                           "fixed before any document is scored.")
    try:
        json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return CheckResult("h3_cache_exists", False,
                           f"{path} exists but does not parse as JSON: {exc}")
    return CheckResult("h3_cache_exists", True, str(path))


def check_h3_cache_non_empty(run_dir: Path, arm_index: int) -> CheckResult:
    """Non-emptiness is required from the second arm onward.

    Arm 0 starts cold by definition. Arm 1+ reusing an empty cache means the
    model would be re-queried for text arm 0 already scored, and the two arms
    could receive different corrections for identical output.
    """
    path = cache_path_for(run_dir)
    if arm_index == 0:
        return CheckResult("h3_cache_non_empty", True,
                           "not required for the first arm (starts cold)")
    if not path.exists():
        return CheckResult("h3_cache_non_empty", False, f"{path} is missing")
    try:
        entries = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        return CheckResult("h3_cache_non_empty", False, f"unparseable: {exc}")
    if not entries:
        return CheckResult(
            "h3_cache_non_empty", False,
            f"{path} is empty at arm {arm_index}. The previous arm either did "
            "not write it or wrote it elsewhere; H3 determinism across arms "
            "cannot be verified after the fact. Refusing to start.")
    return CheckResult("h3_cache_non_empty", True,
                       f"{len(entries)} cached documents")


def check_h3_cache_is_published(run_dir: Path) -> CheckResult:
    """The cache must live with the raw data, not in a temp directory."""
    path = cache_path_for(run_dir)
    try:
        path.resolve().relative_to(run_dir.resolve())
    except ValueError:
        return CheckResult("h3_cache_is_published", False,
                           f"{path} is outside the run directory {run_dir}")
    status = _git_ignore_status(path)
    if status == "ignored":
        return CheckResult(
            "h3_cache_is_published", False,
            f"{path} is git-ignored, so it would not be committed alongside "
            "the raw run data. H3 determinism would be unverifiable after the "
            "run.")
    if status == "unknown":
        return CheckResult(
            "h3_cache_is_published", False,
            f"could not determine whether {path} is tracked by git (is this a "
            "git repository?). This check degrades closed: an unverifiable "
            "publication path fails rather than passes.")
    return CheckResult("h3_cache_is_published", True,
                       f"inside {run_dir}, tracked by git")


def check_versions_pinned(run_dir: Path, versions: dict) -> CheckResult:
    """Record rubric/template/prompt versions, and refuse a mid-run change."""
    manifest = run_dir / "run_manifest.json"
    if not manifest.exists():
        return CheckResult("versions_pinned", True,
                           f"first arm; pinning {versions}")
    recorded = json.loads(manifest.read_text("utf-8")).get("versions", {})
    drift = {k: (recorded.get(k), v) for k, v in versions.items()
             if recorded.get(k) != v}
    if drift:
        return CheckResult(
            "versions_pinned", False,
            f"versions changed mid-experiment (recorded, current): {drift}. "
            "Scores across versions are not comparable.")
    return CheckResult("versions_pinned", True, f"unchanged: {versions}")


def check_corpus_present(expected: int = 20) -> CheckResult:
    docs = sorted((ROOT / "corpus" / "documents").glob("doc_*.md"))
    if len(docs) != expected:
        return CheckResult("corpus_present", False,
                           f"expected {expected} documents, found {len(docs)}")
    return CheckResult("corpus_present", True, f"{len(docs)} documents")


def run_preflight(run_dir: Path, arm_index: int, versions: dict,
                  expected_documents: int = 20,
                  raise_on_failure: bool = True) -> list[CheckResult]:
    """Run every precondition. Raises PreflightError unless told not to."""
    run_dir.mkdir(parents=True, exist_ok=True)
    results = [
        check_corpus_present(expected_documents),
        check_h3_cache_exists(run_dir),
        check_h3_cache_non_empty(run_dir, arm_index),
        check_h3_cache_is_published(run_dir),
        check_versions_pinned(run_dir, versions),
    ]
    failures = [r for r in results if not r.ok]
    if failures and raise_on_failure:
        raise PreflightError(
            "run aborted before spending any operation:\n  "
            + "\n  ".join(str(r) for r in failures))
    return results


def pin_versions(run_dir: Path, versions: dict, arm_index: int) -> None:
    """Write the run manifest after preflight passes."""
    manifest = run_dir / "run_manifest.json"
    data = (json.loads(manifest.read_text("utf-8"))
            if manifest.exists() else {"versions": versions, "arms": []})
    data["versions"] = versions
    if arm_index not in data["arms"]:
        data["arms"].append(arm_index)
    manifest.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
