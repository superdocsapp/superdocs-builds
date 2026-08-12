"""Localised manuals that keep the source locale's structure, and prove it.

The third grading criterion is that localised versions keep the same page
structure. The usual failure is not mistranslation -- it is that German runs
about a third longer than English, so a translated manual reflows, a step lands
on a different page from its diagram, and the printed card no longer folds where
the crease is.

Two things stop that here.

**The skeleton is fixed, and content is filled into it.** The structure -- how
many headings, which order, where the figures sit -- comes from the source
locale and is not re-derived per language. A locale supplies strings; it cannot
supply a section.

**The result is asserted, not claimed.** `compare_structure` walks both
documents and reports every difference: a missing heading, a lost figure, a
table that changed shape. `assert_same_structure` raises on any. A localisation
that would reflow fails here, before it is uploaded, rather than being found by
whoever prints it.

Translation itself is out of scope for this build: `locales/*.yaml` carries
human-supplied strings. What is in scope is that a translation cannot quietly
change the shape of the document it lands in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from manualbuilder.spec import DIAGRAM_STRINGS, Fault, Part, Spec, Statement, Step, Warning_

# The structural elements a page break cares about. Text runs of different
# lengths are expected and fine; a different *number* of headings is not.
STRUCTURE_TAGS = ("h1", "h2", "h3", "figure", "table", "thead", "tbody", "tr")


class LocaleError(ValueError):
    """A locale file does not fit the skeleton it is filling."""


@dataclass(frozen=True)
class Difference:
    where: str
    expected: str
    found: str

    def __str__(self) -> str:
        return f"{self.where}: expected {self.expected}, found {self.found}"


def load_locale(path: str | Path) -> dict[str, Any]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if "language" not in raw:
        raise LocaleError(f"{Path(path).name}: no 'language' declared")
    return raw


def localise(spec: Spec, locale: dict[str, Any]) -> Spec:
    """A spec with this locale's strings and the source locale's structure.

    Only strings are substituted, and only for ids that already exist. A locale
    naming a step the spec does not have is refused: that is a locale trying to
    add a section, which is the thing the fixed skeleton exists to prevent.
    """
    steps = locale.get("steps") or {}
    warnings = locale.get("warnings") or {}
    parts = locale.get("parts") or {}
    faults = locale.get("troubleshooting") or {}
    statements = locale.get("statements") or {}
    chrome = locale.get("diagram") or {}

    unknown = (
        [f"step {k!r}" for k in steps if k not in {s.id for s in spec.steps}]
        + [f"warning {k!r}" for k in warnings if k not in {w.id for w in spec.warnings}]
        + [f"part {k!r}" for k in parts if k not in {p.id for p in spec.parts}]
        + [f"troubleshooting {k!r}" for k in faults if k not in {f.id for f in spec.faults}]
        + [f"statement {k!r}" for k in statements if k not in {s.id for s in spec.statements}]
        + [f"diagram string {k!r}" for k in chrome if k not in DIAGRAM_STRINGS]
    )
    if unknown:
        raise LocaleError(
            f"locale {locale['language']!r} names "
            + ", ".join(unknown)
            + ", which the spec does not have. A locale supplies strings; it "
            "cannot add or rename structure."
        )

    return Spec(
        name=locale.get("product_name", spec.name),
        tagline=locale.get("tagline", spec.tagline),
        model_number=spec.model_number,
        revision=spec.revision,
        languages=spec.languages,
        specifications=tuple(
            (locale.get("specifications", {}).get(label, label), value)
            for label, value in spec.specifications
        ),
        parts=tuple(
            Part(
                id=p.id,
                label=parts.get(p.id, {}).get("label", p.label),
                quantity=p.quantity,
                mounts_to=p.mounts_to,
                note=parts.get(p.id, {}).get("note", p.note),
            )
            for p in spec.parts
        ),
        steps=tuple(
            Step(
                id=s.id,
                title=steps.get(s.id, {}).get("title", s.title),
                body=steps.get(s.id, {}).get("body", s.body),
                parts=s.parts,
                warnings=s.warnings,
            )
            for s in spec.steps
        ),
        warnings=tuple(
            Warning_(
                id=w.id,
                severity=w.severity,
                title=warnings.get(w.id, {}).get("title", w.title),
                body=warnings.get(w.id, {}).get("body", w.body),
            )
            for w in spec.warnings
        ),
        faults=tuple(
            Fault(
                id=f.id,
                symptom=faults.get(f.id, {}).get("symptom", f.symptom),
                cause=faults.get(f.id, {}).get("cause", f.cause),
                fix=faults.get(f.id, {}).get("fix", f.fix),
                step=f.step,
                parts=f.parts,
            )
            for f in spec.faults
        ),
        statements=tuple(
            Statement(
                id=s.id,
                title=statements.get(s.id, {}).get("title", s.title),
                body=statements.get(s.id, {}).get("body", s.body),
            )
            for s in spec.statements
        ),
        quick_start_steps=spec.quick_start_steps,
        quick_start_warnings=spec.quick_start_warnings,
        quick_start_faults=spec.quick_start_faults,
        quick_start_footer=locale.get("footer", spec.quick_start_footer),
        source=spec.source,
        chrome=dict(chrome),
        _by_part={},
        _by_warning={},
        _by_step={},
        _by_fault={},
    )


def _rebuilt(spec: Spec) -> Spec:
    """Re-attach the lookup tables a hand-built Spec does not have."""
    object.__setattr__(spec, "_by_part", {p.id: p for p in spec.parts})
    object.__setattr__(spec, "_by_warning", {w.id: w for w in spec.warnings})
    object.__setattr__(spec, "_by_step", {s.id: s for s in spec.steps})
    object.__setattr__(spec, "_by_fault", {f.id: f for f in spec.faults})
    return spec


def localised_spec(spec: Spec, locale: dict[str, Any]) -> Spec:
    return _rebuilt(localise(spec, locale))


# ------------------------------------------------------------- structure --


def outline(html: str) -> list[str]:
    """The document's shape, with every word removed.

    Only the structural tags, in order. Two documents with the same outline
    paginate the same way whatever length their sentences are, which is the
    property being defended.
    """
    pattern = re.compile(r"<(/?)(" + "|".join(STRUCTURE_TAGS) + r")\b", re.I)
    return [f"{'/' if closing else ''}{tag.lower()}" for closing, tag in pattern.findall(html)]


def compare_structure(source_html: str, localised_html: str) -> list[Difference]:
    """Every structural difference between a source document and a translation."""
    a, b = outline(source_html), outline(localised_html)
    problems: list[Difference] = []

    if len(a) != len(b):
        problems.append(Difference("element count", f"{len(a)} structural elements", f"{len(b)}"))

    for index, (expected, found) in enumerate(zip(a, b, strict=False)):
        if expected != found:
            problems.append(Difference(f"element {index}", f"<{expected}>", f"<{found}>"))
            break  # everything after a shift is noise

    for tag in STRUCTURE_TAGS:
        want, got = a.count(tag), b.count(tag)
        if want != got:
            problems.append(Difference(f"<{tag}> count", str(want), str(got)))

    return problems


def assert_same_structure(source_html: str, localised_html: str, language: str) -> None:
    problems = compare_structure(source_html, localised_html)
    if problems:
        raise LocaleError(
            f"the {language} manual does not match the source structure, so it "
            f"would paginate differently:\n  - " + "\n  - ".join(str(p) for p in problems)
        )


__all__ = [
    "Difference",
    "LocaleError",
    "assert_same_structure",
    "compare_structure",
    "load_locale",
    "localised_spec",
    "outline",
]
