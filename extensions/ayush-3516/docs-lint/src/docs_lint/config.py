"""Loading `docs-lint.toml`.

Everything a team needs to change lives here or in their style guide file: which files to check,
how severe each rule is, what gates the build, which words are banned, how much to spend. Adding a
banned term, retiring a rule, or swapping in a different house style is a data change. None of it
requires touching Python, which is the card's explicit requirement.

Unknown keys are reported rather than ignored. A rule name with a typo in it silently doing nothing
is exactly the failure that makes people stop trusting a linter.
"""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .model import Severity

CONFIG_FILENAME = "docs-lint.toml"

DEFAULT_INCLUDE = ("**/*.md", "**/*.mdx")
DEFAULT_EXCLUDE = (
    "**/node_modules/**",
    "**/.venv/**",
    "**/venv/**",
    "**/.git/**",
    "**/dist/**",
    "**/build/**",
    "**/site-packages/**",
)


class ConfigError(Exception):
    """The configuration is wrong in a way that must stop the run.

    Configuration errors are fatal rather than warnings: a linter running with a
    misunderstood config gives confident answers about the wrong thing.
    """


class StyleGuideConfig(BaseModel):
    """Where the house style lives, and which uploaded copy it corresponds to.

    `attachment_id` is pinned by `docs-lint init`. `content_sha256` is what makes the cache
    correct: edit the style guide and every cached verdict is invalidated, because a document
    judged against the old rules has not been judged against the new ones.
    """

    model_config = ConfigDict(frozen=True)

    path: str | None = None
    attachment_id: str | None = None
    content_sha256: str | None = None

    def resolve(self, root: Path) -> Path | None:
        return (root / self.path).resolve() if self.path else None

    def read(self, root: Path) -> bytes:
        resolved = self.resolve(root)
        if resolved is None:
            raise ConfigError(
                "No style guide configured. Set [styleguide] path in docs-lint.toml, "
                "or run: docs-lint init --styleguide path/to/your-guide.md"
            )
        if not resolved.is_file():
            raise ConfigError(f"Style guide not found: {resolved}")
        return resolved.read_bytes()

    def current_hash(self, root: Path) -> str:
        return hashlib.sha256(self.read(root)).hexdigest()

    def is_stale(self, root: Path) -> bool:
        """True when the file on disk differs from the copy that was uploaded."""
        if self.content_sha256 is None:
            return True
        try:
            return self.current_hash(root) != self.content_sha256
        except ConfigError:
            return True


class SuperDocsConfig(BaseModel):
    """Cost, latency and quality knobs for the model-driven pass."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    model_tier: str | None = None
    thinking_depth: str | None = None
    #: Hard ceiling on billed operations per run. Reached, the run stops and says what it skipped
    #: rather than quietly checking less than it was asked to.
    budget_operations: int = Field(default=100, ge=0)
    #: Check at most this many files in one run; 0 means no limit. The small-sample mode the
    #: integration notes recommend having on day one rather than day nine.
    sample: int = Field(default=0, ge=0)
    #: How long to wait on one document before giving up and recording its job for resumption.
    job_timeout_seconds: float = Field(default=600.0, gt=0)
    poll_interval_seconds: float = Field(default=2.0, gt=0)


class RuleConfig(BaseModel):
    """One rule's severity plus whatever options that rule understands."""

    model_config = ConfigDict(frozen=True)

    severity: Severity
    options: dict[str, Any] = Field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        return self.severity is not Severity.OFF


class Config(BaseModel):
    """A fully resolved configuration, rooted at the directory containing docs-lint.toml."""

    model_config = ConfigDict(frozen=True)

    root: Path
    include: tuple[str, ...] = DEFAULT_INCLUDE
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE
    error_on: frozenset[Severity] = frozenset({Severity.ERROR})
    styleguide: StyleGuideConfig = StyleGuideConfig()
    superdocs: SuperDocsConfig = SuperDocsConfig()
    rules: dict[str, RuleConfig] = Field(default_factory=dict)
    source_path: Path | None = None

    def severity_for(self, rule_id: str, default: Severity) -> Severity:
        entry = self.rules.get(rule_id)
        return entry.severity if entry else default

    def options_for(self, rule_id: str) -> dict[str, Any]:
        entry = self.rules.get(rule_id)
        return dict(entry.options) if entry else {}

    def is_enabled(self, rule_id: str, default: Severity) -> bool:
        return self.severity_for(rule_id, default) is not Severity.OFF

    def fingerprint(self) -> str:
        """Hash of every setting that could change a verdict.

        Part of the cache key. Change a severity or a banned term and yesterday's cached results
        stop being valid answers to today's question.
        """
        parts = [
            "|".join(sorted(self.include)),
            "|".join(sorted(self.exclude)),
            "|".join(sorted(s.value for s in self.error_on)),
            self.styleguide.content_sha256 or "no-styleguide",
            f"{self.superdocs.enabled}:{self.superdocs.model_tier}:{self.superdocs.thinking_depth}",
        ]
        for rule_id in sorted(self.rules):
            rule = self.rules[rule_id]
            options = ";".join(f"{k}={rule.options[k]!r}" for k in sorted(rule.options))
            parts.append(f"{rule_id}={rule.severity.value}({options})")
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def find_config_file(start: Path) -> Path | None:
    """Walk up from `start` looking for docs-lint.toml, the way git finds its root."""
    current = start.resolve()
    for directory in (current, *current.parents):
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_config(start: Path | None = None) -> Config:
    """Load the nearest config, or return defaults rooted at `start` if there is none.

    Running with no config file at all is legitimate — the built-in rules and default globs are a
    reasonable house style. The SuperDocs pass, though, needs a style guide, and says so clearly
    when one is missing rather than silently checking nothing.
    """
    start = (start or Path.cwd()).resolve()
    path = find_config_file(start)
    if path is None:
        return Config(root=start)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc
    return parse_config(raw, root=path.parent, source_path=path)


def parse_config(raw: dict[str, Any], *, root: Path, source_path: Path | None = None) -> Config:
    section = raw.get("docs-lint", raw.get("docs_lint", {}))
    if not isinstance(section, dict):
        raise ConfigError("[docs-lint] must be a table")

    _reject_unknown(section, {"include", "exclude", "error_on"}, "[docs-lint]")

    include = _string_tuple(section.get("include"), DEFAULT_INCLUDE, "[docs-lint] include")
    exclude = _string_tuple(section.get("exclude"), DEFAULT_EXCLUDE, "[docs-lint] exclude")

    error_on_raw = section.get("error_on", ["error"])
    if not isinstance(error_on_raw, list):
        raise ConfigError("[docs-lint] error_on must be a list of severities")
    error_on = frozenset(_severity(value, "[docs-lint] error_on") for value in error_on_raw)

    styleguide = _styleguide(raw.get("styleguide", {}))
    superdocs = _superdocs(raw.get("superdocs", {}))
    rules = _rules(raw.get("rules", {}))

    return Config(
        root=root,
        include=include,
        exclude=exclude,
        error_on=error_on,
        styleguide=styleguide,
        superdocs=superdocs,
        rules=rules,
        source_path=source_path,
    )


def _styleguide(raw: Any) -> StyleGuideConfig:
    if not isinstance(raw, dict):
        raise ConfigError("[styleguide] must be a table")
    _reject_unknown(raw, {"path", "attachment_id", "content_sha256"}, "[styleguide]")
    return StyleGuideConfig(
        path=_optional_str(raw.get("path"), "[styleguide] path"),
        attachment_id=_optional_str(raw.get("attachment_id"), "[styleguide] attachment_id"),
        content_sha256=_optional_str(raw.get("content_sha256"), "[styleguide] content_sha256"),
    )


def _superdocs(raw: Any) -> SuperDocsConfig:
    if not isinstance(raw, dict):
        raise ConfigError("[superdocs] must be a table")
    known = {
        "enabled",
        "model_tier",
        "thinking_depth",
        "budget_operations",
        "sample",
        "job_timeout_seconds",
        "poll_interval_seconds",
    }
    _reject_unknown(raw, known, "[superdocs]")
    try:
        return SuperDocsConfig(**raw)
    except Exception as exc:  # pydantic validation
        raise ConfigError(f"[superdocs] is invalid: {exc}") from exc


def _rules(raw: Any) -> dict[str, RuleConfig]:
    if not isinstance(raw, dict):
        raise ConfigError("[rules] must be a table")
    parsed: dict[str, RuleConfig] = {}
    for rule_id, body in raw.items():
        if not isinstance(body, dict):
            raise ConfigError(f"[rules.{rule_id}] must be a table")
        options = {k: v for k, v in body.items() if k != "severity"}
        parsed[rule_id] = RuleConfig(
            severity=_severity(body.get("severity", "warning"), f"[rules.{rule_id}] severity"),
            options=options,
        )
    return parsed


def _severity(value: Any, where: str) -> Severity:
    try:
        return Severity(str(value).strip().lower())
    except ValueError:
        valid = ", ".join(s.value for s in Severity)
        raise ConfigError(f"{where}: {value!r} is not a severity. Use one of: {valid}") from None


def _string_tuple(value: Any, default: tuple[str, ...], where: str) -> tuple[str, ...]:
    if value is None:
        return default
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where} must be a list of strings")
    return tuple(value)


def _optional_str(value: Any, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{where} must be a string")
    return value


def _reject_unknown(section: dict[str, Any], known: set[str], where: str) -> None:
    unknown = sorted(set(section) - known)
    if unknown:
        raise ConfigError(
            f"{where}: unknown setting(s) {', '.join(unknown)}. "
            f"Known settings: {', '.join(sorted(known))}"
        )
