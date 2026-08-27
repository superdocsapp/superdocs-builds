"""The observational-language rail.

The card is explicit: keep the language observational, *"never framed as a certification of
the property's condition"*. That requirement is enforced here, in code, and not in a prompt —
because a prompt is a request and this is a rule.

It is not hypothetical. On the first live sample of this build, asked only to draft a report,
SuperDocs' AI produced "is not functioning correctly … recommend replacement **for safety**",
"HVAC unit is older but **operational**", and "settling crack …, **typical for the home's
age**": a safety assurance, a functional verdict, and a reassurance the inspector never gave.
Every one of those is caught below.

Two design decisions worth stating:

* **The rail runs on the AI's output, never on the inspector's own words.** An inspector may
  write whatever they judge correct; they are the licensed professional and the report is
  theirs. What the rail governs is text *this system generated* and is about to put in their
  name.
* **Refusing valid work is a failure too.** A rail that flags "safety glazing" or "no leaks
  were observed" would be switched off within a week, so real inspection vocabulary is
  allow-listed first, and terms that are fine when scoped to the moment of observation are
  checked for that scope rather than banned outright.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import yaml

from inspection_report.domain.catalogue import config_dir


class RailError(Exception):
    """The rail configuration could not be loaded."""


@dataclass(frozen=True)
class Breach:
    """One reason a piece of text may not be used, in terms a reviewer can act on."""

    rule_id: str
    category: str
    matched: str
    why: str
    suggest: str


@dataclass(frozen=True)
class Verdict:
    """The result of checking one piece of text."""

    text: str
    breaches: tuple[Breach, ...]

    @property
    def clean(self) -> bool:
        return not self.breaches

    def summary(self) -> str:
        if self.clean:
            return "observational"
        return "; ".join(f"{b.matched!r} ({b.category})" for b in self.breaches)


@dataclass(frozen=True)
class _Rule:
    id: str
    pattern: re.Pattern[str]
    category: str
    why: str
    suggest: str
    requires_any: tuple[re.Pattern[str], ...] = ()


@dataclass(frozen=True)
class _Rail:
    allow: tuple[re.Pattern[str], ...]
    banned: tuple[_Rule, ...]
    scoped: tuple[_Rule, ...]


def _compile(p: str) -> re.Pattern[str]:
    return re.compile(p, re.IGNORECASE)


def _rules(rows: list[dict[str, object]], scoped: bool) -> tuple[_Rule, ...]:
    out = []
    for r in rows:
        raw_scope = r.get("requires_any")
        scopes = raw_scope if scoped and isinstance(raw_scope, list) else []
        out.append(
            _Rule(
                id=str(r["id"]),
                pattern=_compile(str(r["pattern"])),
                category=str(r.get("category", "")),
                why=str(r.get("why", "")).strip(),
                suggest=str(r.get("suggest", "")).strip(),
                requires_any=tuple(_compile(str(x)) for x in scopes),
            )
        )
    return tuple(out)


@lru_cache(maxsize=1)
def load_rail() -> _Rail:
    path = config_dir() / "language_rail.yaml"
    if not path.exists():
        raise RailError(
            f"{path} not found. The language rail is required — this build will not generate "
            f"report prose without it. Set INSPECTION_CONFIG_DIR if config/ lives elsewhere."
        )
    data = yaml.safe_load(path.read_text()) or {}
    return _Rail(
        allow=tuple(_compile(str(p)) for p in (data.get("allow") or [])),
        banned=_rules(list(data.get("banned") or []), scoped=False),
        scoped=_rules(list(data.get("scoped_terms") or []), scoped=True),
    )


def reset_cache() -> None:
    load_rail.cache_clear()


def _mask_allowed(text: str, rail: _Rail) -> str:
    """Blank out allow-listed vocabulary so it cannot trigger a rule.

    Replaced with same-length spaces rather than deleted, so every match offset reported
    later still lines up with the original string.
    """
    for pattern in rail.allow:
        text = pattern.sub(lambda m: " " * len(m.group(0)), text)
    return text


def check(text: str) -> Verdict:
    """Check one piece of generated prose against the rail."""
    rail = load_rail()
    if not text.strip():
        return Verdict(text=text, breaches=())

    haystack = _mask_allowed(text, rail)
    breaches: list[Breach] = []

    for rule in rail.banned:
        for m in rule.pattern.finditer(haystack):
            breaches.append(
                Breach(rule.id, rule.category, text[m.start() : m.end()], rule.why, rule.suggest)
            )

    for rule in rail.scoped:
        matches = list(rule.pattern.finditer(haystack))
        if not matches:
            continue
        if any(scope.search(haystack) for scope in rule.requires_any):
            continue  # tied to the moment of observation — an observation, not a claim
        m = matches[0]
        breaches.append(
            Breach(rule.id, rule.category, text[m.start() : m.end()], rule.why, rule.suggest)
        )

    return Verdict(text=text, breaches=tuple(breaches))


def gate(*, original: str, proposed: str) -> tuple[str, Verdict]:
    """Decide what text may actually be used.

    Returns the text to use and the verdict on the *proposal*. A proposal that breaches the
    rail is refused and the inspector's original words stand — the report is never blocked by
    a bad rewrite, it simply keeps the words the licensed professional wrote.
    """
    verdict = check(proposed)
    return (proposed if verdict.clean else original), verdict


def describe_rules() -> list[dict[str, str]]:
    """Every rule, for the UI's "why was this refused" panel and for the README."""
    rail = load_rail()
    return [
        {"id": r.id, "category": r.category, "why": r.why, "suggest": r.suggest}
        for r in (*rail.banned, *rail.scoped)
    ]
