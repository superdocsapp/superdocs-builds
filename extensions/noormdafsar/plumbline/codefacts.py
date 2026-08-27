"""The truth side of Plumbline: what the code actually says.

Read with Python's own `ast` module, never with a model. A function signature is
not a matter of opinion, and asking a language model to report one introduces a
chance of being wrong about something that can simply be looked up.

This is the whole basis for the tool being trustworthy: when a document and the
code disagree, the code is the fact and the document is the claim.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Param:
    name: str
    annotation: str | None = None
    default: str | None = None      # source text of the default, or None
    kind: str = "positional"        # positional | keyword_only | var_args | var_kwargs

    def render(self) -> str:
        s = self.name
        if self.annotation:
            s += f": {self.annotation}"
        if self.default is not None:
            s += f" = {self.default}"
        return s


@dataclass
class FuncFact:
    qualname: str
    file: str
    line: int
    params: list[Param] = field(default_factory=list)
    returns: str | None = None
    raises: list[str] = field(default_factory=list)
    is_async: bool = False
    docstring_first_line: str = ""

    @property
    def param_names(self) -> list[str]:
        return [p.name for p in self.params if p.name not in ("self", "cls")]

    def signature(self) -> str:
        inner = ", ".join(p.render() for p in self.params)
        arrow = f" -> {self.returns}" if self.returns else ""
        return f"{'async ' if self.is_async else ''}def {self.qualname}({inner}){arrow}"

    def default_for(self, param: str) -> str | None:
        for p in self.params:
            if p.name == param:
                return p.default
        return None


@dataclass
class ConstFact:
    qualname: str
    file: str
    line: int
    value: str          # source text of the assigned value


@dataclass
class CodeFacts:
    functions: dict[str, FuncFact] = field(default_factory=dict)
    constants: dict[str, ConstFact] = field(default_factory=dict)

    def get_function(self, name: str) -> FuncFact | None:
        if name in self.functions:
            return self.functions[name]
        # allow referring to a method by its bare name when unambiguous
        hits = [f for k, f in self.functions.items() if k.rsplit(".", 1)[-1] == name]
        return hits[0] if len(hits) == 1 else None

    def get_constant(self, name: str) -> ConstFact | None:
        if name in self.constants:
            return self.constants[name]
        hits = [c for k, c in self.constants.items() if k.rsplit(".", 1)[-1] == name]
        return hits[0] if len(hits) == 1 else None

    def symbols(self) -> list[str]:
        return sorted(list(self.functions) + list(self.constants))


def _src(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 - unparse is best-effort on odd nodes
        return None


def _params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[Param]:
    a = node.args
    out: list[Param] = []

    # positional-only and positional-or-keyword, defaults align to the right
    positional = list(a.posonlyargs) + list(a.args)
    pad = len(positional) - len(a.defaults)
    for i, arg in enumerate(positional):
        out.append(Param(
            name=arg.arg,
            annotation=_src(arg.annotation),
            default=_src(a.defaults[i - pad]) if i >= pad else None,
        ))

    if a.vararg:
        out.append(Param(name="*" + a.vararg.arg,
                         annotation=_src(a.vararg.annotation), kind="var_args"))

    for arg, dflt in zip(a.kwonlyargs, a.kw_defaults):
        out.append(Param(name=arg.arg, annotation=_src(arg.annotation),
                         default=_src(dflt), kind="keyword_only"))

    if a.kwarg:
        out.append(Param(name="**" + a.kwarg.arg,
                         annotation=_src(a.kwarg.annotation), kind="var_kwargs"))
    return out


def _raises(node: ast.AST) -> list[str]:
    """Exception types raised directly in a function body.

    Deliberately shallow: it reports what this function raises itself, not what
    anything it calls might raise. Claiming more than that would be guessing,
    and a drift report built on a guess is worse than no report.
    """
    # Sorted by line, because ast.walk is breadth-first and would otherwise
    # report a function's exceptions in an order that matches nothing a reader
    # can see. A drift report is read next to the file it describes.
    found: list[tuple[int, str]] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Raise) and sub.exc is not None:
            exc = sub.exc
            if isinstance(exc, ast.Call):
                exc = exc.func
            name = _src(exc)
            if name:
                found.append((getattr(sub, "lineno", 0), name.split(".")[-1]))
    seen: set[str] = set()
    return [n for _, n in sorted(found) if not (n in seen or seen.add(n))]


class _Visitor(ast.NodeVisitor):
    def __init__(self, facts: CodeFacts, file: str):
        self.facts = facts
        self.file = file
        self.stack: list[str] = []

    def _qual(self, name: str) -> str:
        return ".".join(self.stack + [name])

    def visit_ClassDef(self, node: ast.ClassDef):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def _function(self, node, is_async: bool):
        qual = self._qual(node.name)
        doc = ast.get_docstring(node) or ""
        self.facts.functions[qual] = FuncFact(
            qualname=qual,
            file=self.file,
            line=node.lineno,
            params=_params(node),
            returns=_src(node.returns),
            raises=_raises(node),
            is_async=is_async,
            docstring_first_line=doc.strip().splitlines()[0] if doc.strip() else "",
        )
        # nested functions are implementation detail, not public surface
        self.stack.append(node.name)
        for child in node.body:
            if isinstance(child, ast.ClassDef):
                self.visit(child)
        self.stack.pop()

    def visit_FunctionDef(self, node):
        self._function(node, False)

    def visit_AsyncFunctionDef(self, node):
        self._function(node, True)

    def visit_Assign(self, node: ast.Assign):
        # module- and class-level constants only: UPPER_SNAKE at depth <= 1
        if len(self.stack) > 1:
            return
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                val = _src(node.value)
                if val is not None:
                    qual = self._qual(target.id)
                    self.facts.constants[qual] = ConstFact(qual, self.file, node.lineno, val)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        if len(self.stack) > 1 or node.value is None:
            return
        if isinstance(node.target, ast.Name) and node.target.id.isupper():
            val = _src(node.value)
            if val is not None:
                qual = self._qual(node.target.id)
                self.facts.constants[qual] = ConstFact(qual, self.file, node.lineno, val)


def read_source(paths: list[Path], root: Path | None = None) -> CodeFacts:
    """Every public symbol in the given files, as facts."""
    facts = CodeFacts()
    for p in paths:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError as exc:
            raise ValueError(f"{p}: cannot parse ({exc})") from exc
        rel = str(p.relative_to(root)) if root else str(p)
        _Visitor(facts, rel.replace("\\", "/")).visit(tree)
    return facts


def read_tree(root: Path, include: list[str] | None = None) -> CodeFacts:
    globs = include or ["**/*.py"]
    files: list[Path] = []
    for g in globs:
        files += [p for p in sorted(root.glob(g))
                  if p.is_file() and "__pycache__" not in p.parts]
    return read_source(files, root=root)
