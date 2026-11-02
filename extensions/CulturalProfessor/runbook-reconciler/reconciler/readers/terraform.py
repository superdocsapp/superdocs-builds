"""Terraform: resource names, regions, retention, backup schedules.

There is no HCL parser in the standard library and adding a dependency for one
buys less than it looks. What a runbook claims about Terraform is nearly always
a literal — a retention period, an identifier, a region, a cron schedule — and a
literal is exactly what a small scanner can read reliably. Anything computed,
interpolated or referenced is recorded as *unresolved* and produces an
`unverifiable` claim, never a guess.

That boundary is the design. `backup_retention_period = 14` is ground truth.
`backup_retention_period = var.retention` is not ground truth this tool has, and
saying so is the honest answer; resolving variables properly means implementing
Terraform's evaluation, including modules, workspaces and `.tfvars` precedence,
and a half-implementation of that is a checker that is confidently wrong about
production.

## How the scanner works

Strings, comments and heredocs are blanked out first — replaced by spaces of the
same length, so every offset still lines up with the original text. Brace
matching and identifier scanning then run over that blanked copy, where a `{`
inside a string cannot be mistaken for the start of a block, while values are
sliced out of the original. It is about thirty lines and it does not pretend to
be a parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from reconciler.config import display_path
from reconciler.readers._source import SourceRef, iter_files

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
_QUOTED = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')
_HEREDOC = re.compile(r"<<-?([A-Za-z_][A-Za-z0-9_]*)")
#: A bare reference such as `aws_db_instance.payments.identifier`, or `var.x`.
_REFERENCE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\[\]\"-]*$")


@dataclass(frozen=True)
class Block:
    """One HCL block: `resource "aws_db_instance" "payments" { … }`."""

    type: str
    labels: tuple[str, ...]
    source: SourceRef
    attributes: dict[str, str] = field(default_factory=dict)
    unresolved: frozenset[str] = frozenset()
    blocks: tuple[Block, ...] = ()

    @property
    def address(self) -> str:
        """`aws_db_instance.payments`, the way Terraform itself names it."""
        return ".".join([*self.labels]) if self.type == "resource" else self.type

    @property
    def resource_type(self) -> str | None:
        return self.labels[0] if self.type == "resource" and self.labels else None

    def get(self, key: str) -> str | None:
        return self.attributes.get(key)

    def nested(self, block_type: str) -> list[Block]:
        return [b for b in self.blocks if b.type == block_type]

    def find_attribute(self, key: str) -> tuple[str, Block] | None:
        """The attribute wherever it is, including one level down.

        `delete_after` lives inside `rule { lifecycle { … } }` and a caller
        asking for it should not have to know that.
        """
        if key in self.attributes:
            return self.attributes[key], self
        for child in self.blocks:
            found = child.find_attribute(key)
            if found:
                return found
        return None


def read_terraform(paths: tuple[Path, ...]) -> list[Block]:
    out: list[Block] = []
    for path in iter_files(paths, "*.tf"):
        out.extend(read_terraform_file(path))
    return out


def read_terraform_file(path: Path) -> list[Block]:
    text = path.read_text(encoding="utf-8")
    code = _blank_literals(text)
    return _parse_body(text, code, 0, len(text), path)


def resources(blocks: list[Block], resource_type: str | None = None) -> list[Block]:
    return [
        b
        for b in blocks
        if b.type == "resource" and (resource_type is None or b.resource_type == resource_type)
    ]


def find_resource(blocks: list[Block], resource_type: str, name: str) -> Block | None:
    return next(
        (b for b in resources(blocks, resource_type) if len(b.labels) > 1 and b.labels[1] == name),
        None,
    )


# --------------------------------------------------------------- scanning --


def _blank_literals(text: str) -> str:
    """A copy of the source with strings, comments and heredocs spaced out.

    Same length, same offsets, no content. Everything downstream can then treat
    braces and identifiers as structure without wondering whether it is looking
    at the inside of a string.

    The quote characters themselves survive, and that is not cosmetic. Blanking
    them too made a block's labels indistinguishable from the whitespace between
    them, so `resource "aws_db_instance" "payments"` scanned as a block with no
    labels at all and every lookup by name came back empty.
    """
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        char = text[i]
        if char == '"':
            match = _QUOTED.match(text, i)
            if not match:
                i += 1
                continue
            for j in range(match.start() + 1, match.end() - 1):
                if out[j] != "\n":
                    out[j] = " "
            i = match.end()
            continue
        if char == "#" or text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end == -1 else end
            for j in range(i, end):
                out[j] = " "
            i = end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i)
            end = n if end == -1 else end + 2
            for j in range(i, end):
                if out[j] != "\n":
                    out[j] = " "
            i = end
            continue
        heredoc = _HEREDOC.match(text, i)
        if heredoc:
            marker = f"\n{heredoc.group(1)}"
            end = text.find(marker, heredoc.end())
            end = n if end == -1 else end + len(marker)
            for j in range(i, end):
                if out[j] != "\n":
                    out[j] = " "
            i = end
            continue
        i += 1
    return "".join(out)


def _parse_body(text: str, code: str, start: int, end: int, path: Path) -> list[Block]:
    """The blocks of a file.

    Attributes at file scope are dropped: `locals` and `variable` are by
    definition not the literals this reader is for.
    """
    _, _, blocks = _parse_scope(text, code, start, end, path)
    return blocks


def _parse_scope(
    text: str, code: str, start: int, end: int, path: Path
) -> tuple[dict[str, str], set[str], list[Block]]:
    attributes: dict[str, str] = {}
    unresolved: set[str] = set()
    blocks: list[Block] = []
    i = start
    while i < end:
        match = _IDENT.match(code, i)
        if not match:
            i += 1
            continue
        name, j = match.group(0), _skip_space(code, match.end(), end)

        if j < end and code[j] == "=" and code[j : j + 2] != "==":
            value_end = _value_end(code, j + 1, end)
            raw = text[j + 1 : value_end].strip()
            cleaned, resolved = _clean_value(raw)
            attributes[name] = cleaned
            if not resolved:
                unresolved.add(name)
            i = value_end
            continue

        labels, j = _read_labels(text, code, j, end)
        if j < end and code[j] == "{":
            close = _match_brace(code, j, end)
            child_attributes, child_unresolved, child_blocks = _parse_scope(
                text, code, j + 1, close, path
            )
            blocks.append(
                Block(
                    type=name,
                    labels=labels,
                    source=SourceRef(display_path(path), _line_at(text, match.start())),
                    attributes=child_attributes,
                    unresolved=frozenset(child_unresolved),
                    blocks=tuple(child_blocks),
                )
            )
            i = close + 1
            continue
        i = max(j, match.end())
    return attributes, unresolved, blocks


def _read_labels(text: str, code: str, i: int, end: int) -> tuple[tuple[str, ...], int]:
    labels: list[str] = []
    while i < end:
        i = _skip_space(code, i, end)
        if i >= end or code[i] == "{":
            break
        if text[i] == '"':
            match = _QUOTED.match(text, i)
            if not match:
                break
            labels.append(match.group(1))
            i = match.end()
            continue
        match = _IDENT.match(code, i)
        if not match:
            break
        labels.append(match.group(0))
        i = match.end()
    return tuple(labels), _skip_space(code, i, end)


def _skip_space(code: str, i: int, end: int) -> int:
    while i < end and code[i] in " \t\r\n":
        i += 1
    return i


def _match_brace(code: str, open_at: int, end: int) -> int:
    depth = 0
    for i in range(open_at, end):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return end


def _value_end(code: str, i: int, end: int) -> int:
    """The end of one attribute's value.

    End of line, unless brackets are still open — a list or an object spanning
    several lines is one value, and stopping at the first newline would leave
    the rest of it to be misread as more attributes.
    """
    depth = 0
    while i < end:
        char = code[i]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                return i
            depth -= 1
        elif char == "\n" and depth == 0:
            return i
        i += 1
    return end


def _clean_value(raw: str) -> tuple[str, bool]:
    """The literal, and whether it is one.

    `False` means this tool does not know the value: an interpolation, a
    variable, a reference to another resource. The caller turns that into
    `unverifiable`, which is the only honest verdict available.
    """
    value = raw.strip().rstrip(",")
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        inner = value[1:-1]
        return inner, "${" not in inner
    if value in ("true", "false"):
        return value, True
    try:
        float(value)
    except ValueError:
        pass
    else:
        return value, True
    if _REFERENCE.match(value):
        return value, False
    return value, False


def _line_at(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


__all__ = ["Block", "find_resource", "read_terraform", "read_terraform_file", "resources"]
