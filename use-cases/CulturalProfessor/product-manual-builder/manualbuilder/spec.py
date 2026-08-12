"""The product spec: loaded, validated, and then trusted.

Everything downstream -- both documents, every diagram, every localised
variant -- is a projection of this one object. That is the whole design: two
documents cannot disagree about the torque figure if neither of them contains
the torque figure.

The validation here is not defensive tidiness. A spec that names a part no step
uses, or a warning no step references, or a quick-start step that is not a step,
produces documents that are individually well-formed and jointly wrong -- and
that is exactly the failure this project exists to make impossible. So it is
refused at load time, where one person reads one error, rather than at render
time in one of six locales.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SEVERITIES = ("danger", "warning", "caution")

# A manual that ships without these is not a shorter manual, it is a
# non-compliant one: a consumer product sold in the EU or the UK carries a
# warranty statement and a WEEE disposal statement, and the absence of either is
# a defect in the document rather than a stylistic choice. So the two ids are
# required by name. This is a deliberate hard-coded rule, not a missing feature:
# a spec is free to declare further statements, and they render alongside these.
REQUIRED_STATEMENTS = ("warranty", "disposal")

# The words the drawings put on themselves. They are not product content -- no
# spec author writes them -- but they are printed English inside a German
# manual if nobody owns them, which is the sort of thing that survives three
# revisions because it lives in a renderer rather than in a document. A locale
# overrides them by id under `diagram:`; anything it does not override falls
# back to these.
DIAGRAM_STRINGS = {
    "breakdown_title": "{name} — parts breakdown",
    "step_title": "{name} — step: {title}",
    "loose_parts": "SUPPLIED, NOT MOUNTED",
    "highlight_note": (
        "Outlined parts are the ones this step uses; the rest of "
        "the assembly is shown for position."
    ),
}


class SpecError(ValueError):
    """The spec is not internally consistent. Reported with what to fix."""


@dataclass(frozen=True)
class Part:
    id: str
    label: str
    quantity: int = 1
    mounts_to: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class Warning_:
    id: str
    severity: str
    title: str
    body: str


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    body: str
    parts: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Fault:
    """One row of the troubleshooting table.

    `step` and `parts` are what make it more than three strings: a fault that
    names the step it belongs to can be checked against a manual that still has
    that step, and one that names its parts is refused when a part is renamed
    out of the graph. A troubleshooting table that points at a step the manual
    no longer contains is the classic way this section rots.
    """

    id: str
    symptom: str
    cause: str
    fix: str
    step: str | None = None
    parts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Statement:
    """A warranty, disposal or other legal statement, worded once."""

    id: str
    title: str
    body: str


@dataclass(frozen=True)
class Spec:
    name: str
    tagline: str
    model_number: str
    revision: str
    languages: tuple[str, ...]
    specifications: tuple[tuple[str, str], ...]
    parts: tuple[Part, ...]
    steps: tuple[Step, ...]
    warnings: tuple[Warning_, ...]
    faults: tuple[Fault, ...]
    statements: tuple[Statement, ...]
    quick_start_steps: tuple[str, ...]
    quick_start_warnings: tuple[str, ...]
    quick_start_faults: tuple[str, ...]
    quick_start_footer: str
    source: Path | None = None
    chrome: dict[str, str] = field(default_factory=dict)

    # -- lookups, so no caller re-derives them -----------------------------

    _by_part: dict[str, Part] = field(default_factory=dict, compare=False, repr=False)
    _by_warning: dict[str, Warning_] = field(default_factory=dict, compare=False, repr=False)
    _by_step: dict[str, Step] = field(default_factory=dict, compare=False, repr=False)
    _by_fault: dict[str, Fault] = field(default_factory=dict, compare=False, repr=False)

    def part(self, part_id: str) -> Part:
        return self._by_part[part_id]

    def warning(self, warning_id: str) -> Warning_:
        return self._by_warning[warning_id]

    def step(self, step_id: str) -> Step:
        return self._by_step[step_id]

    def fault(self, fault_id: str) -> Fault:
        return self._by_fault[fault_id]

    def statement(self, statement_id: str) -> Statement:
        for statement in self.statements:
            if statement.id == statement_id:
                return statement
        raise KeyError(statement_id)

    def children_of(self, part_id: str | None) -> list[Part]:
        """The parts that mount directly onto this one, in declared order."""
        return [p for p in self.parts if p.mounts_to == part_id]

    def warnings_for(self, step: Step) -> list[Warning_]:
        return [self.warning(w) for w in step.warnings]

    def quick_start(self) -> list[Step]:
        return [self.step(s) for s in self.quick_start_steps]

    def text(self, key: str, **fmt: str) -> str:
        """A drawing's own words, in this spec's language.

        Falls back to English rather than to an empty string: a diagram with no
        caption is a diagram whose caption nobody notices is missing.
        """
        return self.chrome.get(key, DIAGRAM_STRINGS[key]).format(**fmt)

    def quick_start_troubleshooting(self) -> list[Fault]:
        return [self.fault(f) for f in self.quick_start_faults]


def load_spec(path: str | Path) -> Spec:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    spec = _build(raw, path)
    _validate(spec)
    return spec


# ------------------------------------------------------------------ build --


def _build(raw: dict[str, Any], path: Path) -> Spec:
    for section in (
        "product",
        "parts",
        "setup_steps",
        "warnings",
        "troubleshooting",
        "statements",
        "quick_start",
    ):
        if section not in raw:
            raise SpecError(f"{path.name}: missing required section {section!r}")

    product = raw["product"]
    quick = raw["quick_start"]

    parts = tuple(
        Part(
            id=str(p["id"]),
            label=str(p["label"]),
            quantity=int(p.get("quantity", 1)),
            mounts_to=p.get("mounts_to") or None,
            note=_text(p.get("note")),
        )
        for p in raw["parts"]
    )
    warnings = tuple(
        Warning_(
            id=str(w["id"]),
            severity=str(w["severity"]),
            title=str(w["title"]),
            body=_text(w["body"]) or "",
        )
        for w in raw["warnings"]
    )
    steps = tuple(
        Step(
            id=str(s["id"]),
            title=str(s["title"]),
            body=_text(s["body"]) or "",
            parts=tuple(str(x) for x in s.get("parts", [])),
            warnings=tuple(str(x) for x in s.get("warnings", [])),
        )
        for s in raw["setup_steps"]
    )
    faults = tuple(
        Fault(
            id=str(f["id"]),
            symptom=_text(f["symptom"]) or "",
            cause=_text(f["cause"]) or "",
            fix=_text(f["fix"]) or "",
            step=f.get("step") or None,
            parts=tuple(str(x) for x in f.get("parts", [])),
        )
        for f in raw["troubleshooting"]
    )
    statements = tuple(
        Statement(id=str(s["id"]), title=str(s["title"]), body=_text(s["body"]) or "")
        for s in raw["statements"]
    )

    return Spec(
        name=str(product["name"]),
        tagline=str(product.get("tagline", "")),
        model_number=str(product.get("model_number", "")),
        revision=str(product.get("revision", "")),
        languages=tuple(str(x) for x in product.get("languages_available", ["en"])),
        specifications=tuple(
            (str(row["label"]), str(row["value"])) for row in raw.get("specifications", [])
        ),
        parts=parts,
        steps=steps,
        warnings=warnings,
        faults=faults,
        statements=statements,
        quick_start_steps=tuple(str(x) for x in quick.get("steps", [])),
        quick_start_warnings=tuple(str(x) for x in quick.get("warnings", [])),
        quick_start_faults=tuple(str(x) for x in quick.get("troubleshooting", [])),
        quick_start_footer=_text(quick.get("footer")) or "",
        source=path,
        _by_part={p.id: p for p in parts},
        _by_warning={w.id: w for w in warnings},
        _by_step={s.id: s for s in steps},
        _by_fault={f.id: f for f in faults},
    )


def _text(value: Any) -> str | None:
    """YAML folded scalars arrive with trailing newlines and soft-wrap breaks."""
    if value is None:
        return None
    return " ".join(str(value).split())


# --------------------------------------------------------------- validate --


def _validate(spec: Spec) -> None:
    problems: list[str] = []

    problems += _duplicates("part", [p.id for p in spec.parts])
    problems += _duplicates("warning", [w.id for w in spec.warnings])
    problems += _duplicates("step", [s.id for s in spec.steps])
    problems += _duplicates("fault", [f.id for f in spec.faults])
    problems += _duplicates("statement", [s.id for s in spec.statements])

    for warning in spec.warnings:
        if warning.severity not in SEVERITIES:
            problems.append(
                f"warning {warning.id!r} has severity {warning.severity!r}; "
                f"expected one of {', '.join(SEVERITIES)}"
            )

    # Every reference resolves. A step naming a part that does not exist would
    # render a diagram highlighting nothing, silently.
    for step in spec.steps:
        for part_id in step.parts:
            if part_id not in spec._by_part:
                problems.append(f"step {step.id!r} names unknown part {part_id!r}")
        for warning_id in step.warnings:
            if warning_id not in spec._by_warning:
                problems.append(f"step {step.id!r} names unknown warning {warning_id!r}")

    for part in spec.parts:
        if part.mounts_to and part.mounts_to not in spec._by_part:
            problems.append(f"part {part.id!r} mounts to unknown part {part.mounts_to!r}")

    problems += _cycles(spec)

    # A troubleshooting row that points at a step or a part the manual no longer
    # has is how this section rots: the step is renamed during a revision, the
    # table keeps the old name, and the reader is sent to a section that is not
    # there. The reference is checked so the rot is a load error instead.
    for fault in spec.faults:
        if fault.step and fault.step not in spec._by_step:
            problems.append(
                f"troubleshooting {fault.id!r} refers to step {fault.step!r}, "
                f"which is not a setup step"
            )
        for part_id in fault.parts:
            if part_id not in spec._by_part:
                problems.append(f"troubleshooting {fault.id!r} names unknown part {part_id!r}")

    missing = [
        s for s in REQUIRED_STATEMENTS if s not in {statement.id for statement in spec.statements}
    ]
    if missing:
        problems.append(
            "statements is missing "
            + " and ".join(repr(m) for m in missing)
            + "; a shipped manual carries both, so a spec without them would "
            "render a document that is missing a section rather than one that "
            "chose not to have it"
        )

    # The quick-start card is a projection, not a second document. Every step it
    # carries has to be a step of the manual, or the card would contain an
    # instruction the manual does not -- which is the drift this project is
    # supposed to make structurally impossible.
    for step_id in spec.quick_start_steps:
        if step_id not in spec._by_step:
            problems.append(
                f"quick_start names {step_id!r}, which is not a setup step; the "
                f"card must be a projection of the manual, never a source of its own"
            )
    for warning_id in spec.quick_start_warnings:
        if warning_id not in spec._by_warning:
            problems.append(f"quick_start names unknown warning {warning_id!r}")
    for fault_id in spec.quick_start_faults:
        if fault_id not in spec._by_fault:
            problems.append(
                f"quick_start names {fault_id!r}, which is not a troubleshooting "
                f"entry; the card's few fixes are the manual's fixes, never a "
                f"shorter wording of them"
            )

    # A warning nobody references is a warning nobody reads. It is a spec bug,
    # not a stylistic one: someone wrote a safety notice believing it shipped.
    referenced = {w for step in spec.steps for w in step.warnings}
    referenced |= set(spec.quick_start_warnings)
    for warning in spec.warnings:
        if warning.id not in referenced:
            problems.append(
                f"warning {warning.id!r} is declared but no step or the card "
                f"references it, so it would never appear in any document"
            )

    if not spec.quick_start_steps:
        problems.append("quick_start declares no steps")

    if problems:
        raise SpecError(
            f"{(spec.source or Path('spec')).name} is not internally consistent:\n  - "
            + "\n  - ".join(problems)
        )


def _duplicates(kind: str, ids: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in ids:
        if value in seen:
            out.append(f"duplicate {kind} id {value!r}")
        seen.add(value)
    return out


def _cycles(spec: Spec) -> list[str]:
    """`mounts_to` has to be a forest. The exploded view walks it, and a cycle
    would recurse until the stack ran out rather than draw anything."""
    problems: list[str] = []
    for part in spec.parts:
        seen = {part.id}
        current = part.mounts_to
        while current:
            if current in seen:
                problems.append(f"part {part.id!r} is in a mounts_to cycle")
                break
            seen.add(current)
            parent = spec._by_part.get(current)
            current = parent.mounts_to if parent else None
    return problems


__all__ = [
    "REQUIRED_STATEMENTS",
    "SEVERITIES",
    "Fault",
    "Part",
    "Spec",
    "SpecError",
    "Statement",
    "Step",
    "Warning_",
    "load_spec",
]
