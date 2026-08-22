"""
Diffs two versions of a Python source file at the FUNCTION level, using the `ast` module rather than text
diffing. This is deliberate: a text/line diff would flag a reformatted docstring or a renamed local variable
as "changed", which would make DocSync propose doc updates for things nobody actually needs documented
differently. Comparing normalized function signatures (and only signatures + docstrings, not full bodies)
means an internal implementation refactor with an unchanged public signature produces NO proposed change --
which is the whole point: only propose doc updates when something a reader of the docs would actually need
to know about has changed.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Literal, Optional

ChangeType = Literal["added", "removed", "signature_changed", "docstring_changed"]


@dataclass
class FunctionSnapshot:
    name: str
    signature: str  # normalized: "def name(arg1: type1, arg2: type2 = default) -> return_type"
    docstring: Optional[str]
    lineno: int


@dataclass
class FunctionChange:
    name: str
    change_type: ChangeType
    old: Optional[FunctionSnapshot]
    new: Optional[FunctionSnapshot]
    file_path: str

    def citation(self) -> str:
        line = self.new.lineno if self.new else (self.old.lineno if self.old else 0)
        return f"{self.file_path}:{line}"

    def describe(self) -> str:
        if self.change_type == "added":
            return f"New function `{self.name}` added: `{self.new.signature}`"
        if self.change_type == "removed":
            return f"Function `{self.name}` was removed (was: `{self.old.signature}`)"
        if self.change_type == "signature_changed":
            return f"`{self.name}` signature changed from `{self.old.signature}` to `{self.new.signature}`"
        if self.change_type == "docstring_changed":
            return f"`{self.name}`'s docstring changed (signature unchanged)"
        return f"`{self.name}` changed"


def _normalize_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = []
    defaults_offset = len(node.args.args) - len(node.args.defaults)
    for i, arg in enumerate(node.args.args):
        piece = arg.arg
        if arg.annotation is not None:
            piece += f": {ast.unparse(arg.annotation)}"
        default_index = i - defaults_offset
        if default_index >= 0:
            piece += f" = {ast.unparse(node.args.defaults[default_index])}"
        args.append(piece)
    ret = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(args)}){ret}"


def _extract_functions(source: str) -> dict[str, FunctionSnapshot]:
    tree = ast.parse(source)
    functions = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = FunctionSnapshot(
                name=node.name,
                signature=_normalize_signature(node),
                docstring=ast.get_docstring(node),
                lineno=node.lineno,
            )
    return functions


def diff_functions(old_source: str, new_source: str, file_path: str = "unknown") -> list[FunctionChange]:
    old_funcs = _extract_functions(old_source) if old_source else {}
    new_funcs = _extract_functions(new_source)

    changes: list[FunctionChange] = []
    all_names = set(old_funcs) | set(new_funcs)

    for name in sorted(all_names):
        old_f = old_funcs.get(name)
        new_f = new_funcs.get(name)

        if old_f is None and new_f is not None:
            changes.append(FunctionChange(name=name, change_type="added", old=None, new=new_f, file_path=file_path))
        elif old_f is not None and new_f is None:
            changes.append(FunctionChange(name=name, change_type="removed", old=old_f, new=None, file_path=file_path))
        elif old_f.signature != new_f.signature:
            changes.append(FunctionChange(name=name, change_type="signature_changed", old=old_f, new=new_f, file_path=file_path))
        elif old_f.docstring != new_f.docstring:
            changes.append(FunctionChange(name=name, change_type="docstring_changed", old=old_f, new=new_f, file_path=file_path))
        # else: signature AND docstring both identical -- genuinely nothing doc-relevant changed, even if
        # the function body was completely rewritten. No FunctionChange is emitted. This is the core
        # guarantee: internal refactors never trigger a proposed doc update.

    return changes
