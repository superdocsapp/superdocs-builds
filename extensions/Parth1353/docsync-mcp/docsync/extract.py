"""Extractors — the only place that turns source code into a fact.

Everything downstream (the diff, the impact set, the instruction sent to
SuperDocs, the verification) is a function of the values produced here, so
these are deliberately dull: no heuristics, no inference, no "best guess". An
extractor either finds exactly the thing it was told to find, or it raises.

That matters more than it sounds. The failure mode this whole build exists to
prevent is a document that looks updated and is wrong. An extractor that
silently returns ``None``, or falls back to a nearby match, manufactures
exactly that: a confident instruction built on a value nobody checked. So a
missing constant is an error that stops the run, not a warning.

Five kinds, chosen because between them they cover what documentation actually
quotes about a codebase:

``python_constant:NAME``  a module-level literal
``json_path:a.b.c``       a value in a JSON file (config, package manifest)
``yaml_path:a.b.c``       the same for YAML
``regex:<pattern>``       one capture, for everything the above cannot reach
``regex_list:<pattern>``  every capture — a *set* fact, like a route table
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

import yaml

Scalar = str | int | float | bool
Value = Scalar | list[str]


class ExtractError(RuntimeError):
    """An extractor could not produce a value.

    Always fatal to the fact it describes. Carries the fix where there is one,
    because "python_constant:MAX_ATTEMPTS not found" is only useful if it also
    says where it looked.
    """

    def __init__(self, message: str, *, fix: str | None = None) -> None:
        super().__init__(message if not fix else f"{message}\n  → {fix}")
        self.fix = fix


# ---------------------------------------------------------------------------
# The extractor spec string
# ---------------------------------------------------------------------------

KINDS = ("python_constant", "json_path", "yaml_path", "regex", "regex_list")

LIST_KINDS = ("regex_list",)


def parse_extractor(spec: str) -> tuple[str, str]:
    """``"regex:timeout = (\\d+)"`` → ``("regex", "timeout = (\\d+)")``.

    Split on the *first* colon only. Regex patterns contain colons routinely
    and a naive ``split(":")`` truncates them into something that still
    compiles and matches the wrong thing — a silent corruption rather than an
    error, which is the category this module refuses to be in.
    """
    if not isinstance(spec, str) or ":" not in spec:
        raise ExtractError(
            f"extractor {spec!r} is not in 'kind:argument' form",
            fix=f"use one of {', '.join(k + ':...' for k in KINDS)}",
        )
    kind, argument = spec.split(":", 1)
    kind = kind.strip()
    if kind not in KINDS:
        raise ExtractError(
            f"unknown extractor kind {kind!r}",
            fix=f"supported kinds are {', '.join(KINDS)}",
        )
    if not argument:
        raise ExtractError(f"extractor {kind!r} needs an argument after the colon")
    return kind, argument


def is_list_kind(kind: str) -> bool:
    return kind in LIST_KINDS


# ---------------------------------------------------------------------------
# The extractors
# ---------------------------------------------------------------------------


def extract(kind: str, argument: str, text: str, *, source: str = "") -> Value:
    """Run one extractor over one file's text. Raises ``ExtractError``."""
    fn = {
        "python_constant": _python_constant,
        "json_path": _json_path,
        "yaml_path": _yaml_path,
        "regex": _regex,
        "regex_list": _regex_list,
    }[kind]
    return fn(argument, text, source)


def _python_constant(name: str, text: str, source: str) -> Scalar:
    """A module-level ``NAME = <literal>``.

    Deliberately narrow. Only the top level of the module is scanned, and only
    literals are accepted: ``TIMEOUT = 30`` yes, ``TIMEOUT = compute()`` no.
    A constant that is computed at import time is not a fact this tool can
    quote into a document truthfully, and guessing at it is worse than saying
    so.

    Where a name is assigned more than once at the top level the last
    assignment wins, which is what the module itself would end up with for
    straight-line code.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise ExtractError(
            f"{source or 'file'} is not valid Python: {exc.msg} (line {exc.lineno})"
        ) from exc

    found: ast.expr | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    found = node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name and node.value:
                found = node.value

    if found is None:
        raise ExtractError(
            f"no module-level assignment to {name!r} in {source or 'the file'}",
            fix="only top-level assignments are read — a constant defined inside a "
            "function, class or `if` block cannot be extracted",
        )
    try:
        value = ast.literal_eval(found)
    except (ValueError, SyntaxError) as exc:
        raise ExtractError(
            f"{name} in {source or 'the file'} is not a literal, so it has no value "
            f"that can be quoted into a document",
            fix="point the fact at a literal constant, or use regex: to capture the "
            "text you actually want to appear in the documentation",
        ) from exc
    if not isinstance(value, str | int | float | bool):
        raise ExtractError(
            f"{name} in {source or 'the file'} is a {type(value).__name__}; "
            f"only strings, numbers and booleans can be quoted into a document"
        )
    return value


def _walk_path(data: Any, path: str, source: str, what: str) -> Any:
    cursor: Any = data
    walked: list[str] = []
    for segment in path.split("."):
        walked.append(segment)
        here = ".".join(walked)
        if isinstance(cursor, list):
            if not segment.lstrip("-").isdigit():
                raise ExtractError(
                    f"{what} {here!r} in {source or 'the file'}: {'.'.join(walked[:-1]) or 'the root'} "
                    f"is a list, so {segment!r} must be an index"
                )
            index = int(segment)
            if not -len(cursor) <= index < len(cursor):
                raise ExtractError(
                    f"{what} {here!r} in {source or 'the file'}: index {index} is out of "
                    f"range (the list has {len(cursor)} item(s))"
                )
            cursor = cursor[index]
            continue
        if not isinstance(cursor, dict) or segment not in cursor:
            raise ExtractError(
                f"{what} {here!r} not found in {source or 'the file'}",
                fix=f"available at {'.'.join(walked[:-1]) or 'the root'}: "
                + (", ".join(map(str, cursor)) if isinstance(cursor, dict) else "not an object"),
            )
        cursor = cursor[segment]

    if not isinstance(cursor, str | int | float | bool):
        raise ExtractError(
            f"{what} {path!r} in {source or 'the file'} is a "
            f"{'list' if isinstance(cursor, list) else type(cursor).__name__}; only "
            f"scalars can be quoted into a document"
        )
    return cursor


def _json_path(path: str, text: str, source: str) -> Scalar:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExtractError(f"{source or 'file'} is not valid JSON: {exc}") from exc
    return _walk_path(data, path, source, "json_path")


def _yaml_path(path: str, text: str, source: str) -> Scalar:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ExtractError(f"{source or 'file'} is not valid YAML: {exc}") from exc
    return _walk_path(data, path, source, "yaml_path")


def _compile(pattern: str) -> re.Pattern[str]:
    try:
        compiled = re.compile(pattern, re.MULTILINE)
    except re.error as exc:
        raise ExtractError(f"regex {pattern!r} does not compile: {exc}") from exc
    if compiled.groups < 1 and "value" not in (compiled.groupindex or {}):
        raise ExtractError(
            f"regex {pattern!r} has no capture group, so there is nothing to extract",
            fix="wrap the part you want in parentheses, e.g. r'TIMEOUT = (\\d+)', or "
            "name it (?P<value>...)",
        )
    return compiled


def _captured(match: re.Match[str]) -> str:
    if "value" in (match.re.groupindex or {}):
        return match.group("value")
    return match.group(1)


def _regex(pattern: str, text: str, source: str) -> str:
    compiled = _compile(pattern)
    match = compiled.search(text)
    if match is None:
        raise ExtractError(f"regex {pattern!r} matched nothing in {source or 'the file'}")
    captured = _captured(match)
    if captured is None:
        raise ExtractError(
            f"regex {pattern!r} matched in {source or 'the file'} but its capture group "
            f"is empty — an optional group cannot carry a fact"
        )
    return captured


def _regex_list(pattern: str, text: str, source: str) -> list[str]:
    """Every capture, deduplicated and sorted.

    Sorted on purpose: a set fact is about membership, so moving a route from
    the top of a file to the bottom is not a documentation change and must not
    produce one. Reordering being invisible is a deliberate trade — see the
    README's limitations.

    An empty result is allowed here where the scalar version raises. A list
    that legitimately becomes empty (every endpoint removed) is a real state,
    and the diff will report it as a removal rather than as a broken extractor.
    """
    compiled = _compile(pattern)
    seen = {_captured(m) for m in compiled.finditer(text) if _captured(m) is not None}
    return sorted(seen)


# ---------------------------------------------------------------------------
# Rendering — the canonical string form a document is expected to contain
# ---------------------------------------------------------------------------


def render_scalar(value: Scalar) -> str:
    """One spelling per value, decided above the extractors.

    Task 2 of this round taught this the expensive way: normalisation that
    lives inside a provider lets ``99.95`` and ``99.95%`` reach the comparison
    as different facts and manufactures a conflict between documents that
    agree. One canonical spelling, chosen here, is what makes "did the edit
    land" answerable.

    ``30.0`` renders as ``30`` because that is what a document says.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value)


def apply_format(rendered: str, fmt: str) -> str:
    try:
        return fmt.format(value=rendered)
    except (KeyError, IndexError, ValueError) as exc:
        raise ExtractError(
            f"format {fmt!r} could not be applied: {exc}",
            fix="a format is a Python format string whose only placeholder is {value}",
        ) from exc


def render(value: Value, fmt: str = "{value}") -> str | list[str]:
    """Render a fact for the page. Lists render item by item."""
    if isinstance(value, list):
        return [apply_format(render_scalar(item), fmt) for item in value]
    return apply_format(render_scalar(value), fmt)
