"""Turn a job spec into a durable plan.

Planning is separate from running, and it happens exactly once per run. Everything the
runner needs afterwards — the ordered steps, each step's document, each step's
idempotency token — is in the ledger before the first network call is made. That is what
lets a resumed run be sure it is finishing the same plan and not inventing a new one.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .ledger import Ledger
from .model import (
    RUN_PLANNED,
    Document,
    Run,
    Step,
    sha256_text,
    step_token,
)

SUPPORTED_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".html", ".htm", ".docx", ".pdf", ".rtf"})


class SpecError(ValueError):
    """The spec is wrong in a way that names the fix."""


@dataclass(frozen=True)
class GateRule:
    description: str
    old_html_contains: str | None = None
    new_html_contains: str | None = None


@dataclass(frozen=True)
class GateSpec:
    mode: str = "policy"
    default: str = "approve"
    reject_when: tuple[GateRule, ...] = ()


@dataclass(frozen=True)
class JobSpec:
    name: str
    description: str
    session_prefix: str
    model_tier: str | None
    gate: GateSpec
    documents: tuple[dict[str, Any], ...]
    steps: tuple[dict[str, Any], ...]
    source_path: Path
    raw_text: str

    @property
    def spec_hash(self) -> str:
        return sha256_text(self.raw_text)


def load_spec(path: str | Path) -> JobSpec:
    p = Path(path)
    if not p.exists():
        raise SpecError(f"no job spec at {p}\n  fix: pass a path to a job YAML file")
    raw = p.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise SpecError(f"{p} is not a YAML mapping")

    for required in ("name", "documents", "steps"):
        if required not in data:
            raise SpecError(f"{p} is missing '{required}'")

    documents = data["documents"]
    if not documents:
        raise SpecError(f"{p} declares no documents")

    slugs = [d.get("slug") for d in documents]
    if len(set(slugs)) != len(slugs):
        dupes = sorted({s for s in slugs if slugs.count(s) > 1})
        raise SpecError(f"{p} has duplicate document slugs: {dupes}")

    gate_raw = data.get("gate") or {}
    gate = GateSpec(
        mode=gate_raw.get("mode", "policy"),
        default=gate_raw.get("default", "approve"),
        reject_when=tuple(
            GateRule(
                description=r.get("description", "").strip(),
                old_html_contains=r.get("old_html_contains"),
                new_html_contains=r.get("new_html_contains"),
            )
            for r in gate_raw.get("reject_when", []) or []
        ),
    )
    if gate.mode not in ("policy", "manual"):
        raise SpecError(f"gate.mode must be 'policy' or 'manual', not {gate.mode!r}")

    return JobSpec(
        name=data["name"],
        description=(data.get("description") or "").strip(),
        session_prefix=data.get("session_prefix", data["name"]),
        model_tier=data.get("model_tier"),
        gate=gate,
        documents=tuple(documents),
        steps=tuple(data["steps"]),
        source_path=p,
        raw_text=raw,
    )


def _resolve(spec_dir: Path, rel: str) -> Path:
    """Document paths are relative to the spec, so a spec can be moved with its corpus."""
    p = Path(rel)
    return p if p.is_absolute() else (spec_dir / p).resolve()


def expand_steps(spec: JobSpec) -> list[tuple[str, str, str]]:
    """Expand step templates into concrete ``(step_id, doc_slug, instruction)`` triples.

    Order is deterministic — template order, then document order as declared — because
    a resumed run must produce exactly the plan the original run was executing.
    """
    known = {d["slug"] for d in spec.documents}
    declared_order = [d["slug"] for d in spec.documents]
    out: list[tuple[str, str, str]] = []

    for template in spec.steps:
        step_id = template.get("id")
        if not step_id:
            raise SpecError("every step needs an 'id'")
        instruction = " ".join((template.get("instruction") or "").split())
        if not instruction:
            raise SpecError(f"step {step_id} has no instruction")

        if template.get("for_each_document"):
            targets = declared_order
        else:
            targets = template.get("documents") or []
            if not targets:
                raise SpecError(
                    f"step {step_id} targets no documents"
                    "\n  fix: set for_each_document: true, or list documents: [slug, ...]"
                )
        unknown = [t for t in targets if t not in known]
        if unknown:
            raise SpecError(f"step {step_id} targets undeclared documents: {unknown}")

        out.extend((step_id, slug, instruction) for slug in targets)

    if not out:
        raise SpecError("the plan expands to zero steps")
    return out


def plan_run(ledger: Ledger, spec: JobSpec, *, run_id: str | None = None) -> Run:
    """Write a complete, immutable plan to the ledger. One transaction, all or nothing."""
    spec_dir = spec.source_path.parent
    documents: list[Document] = []
    for entry in spec.documents:
        path = _resolve(spec_dir, entry["path"])
        if not path.exists():
            raise SpecError(
                f"document {entry['slug']} not found at {path}"
                "\n  fix: paths in a job spec are relative to the spec file"
            )
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise SpecError(
                f"{path.name}: unsupported format {path.suffix!r}"
                f"\n  fix: use one of {sorted(SUPPORTED_SUFFIXES)}"
            )
        documents.append(Document(
            run_id="",  # filled below once the run id is known
            slug=entry["slug"],
            source_path=str(path),
            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            title=entry.get("title") or entry["slug"],
        ))

    rid = run_id or _derive_run_id(spec, documents)
    documents = [Document(**{**d.__dict__, "run_id": rid}) for d in documents]

    steps = [
        Step(
            run_id=rid,
            step_index=i,
            step_id=step_id,
            doc_slug=slug,
            # The token rides inside the instruction. When this text reaches SuperDocs it
            # lands in the session transcript, which is how a crashed run later asks the
            # server "did this turn happen?" without trusting anything local.
            instruction=f"{instruction} {step_token(rid, i)}",
            token=step_token(rid, i),
        )
        for i, (step_id, slug, instruction) in enumerate(expand_steps(spec))
    ]

    run = Run(
        run_id=rid,
        spec_path=str(spec.source_path),
        spec_hash=spec.spec_hash,
        session_id=f"{spec.session_prefix}-{rid}",
        status=RUN_PLANNED,
        created_at=time.time(),
        meta={
            "job_name": spec.name,
            "model_tier": spec.model_tier,
            "gate_mode": spec.gate.mode,
            "document_count": len(documents),
            "step_count": len(steps),
        },
    )
    if ledger.get_run(rid) is not None:
        raise SpecError(
            f"run {rid} already exists"
            "\n  fix: resume it instead — a run id names one run for its whole life"
        )
    ledger.create_run(run, documents, steps)
    return run


def _derive_run_id(spec: JobSpec, documents: list[Document]) -> str:
    """A short id derived from the plan's content plus the wall clock.

    Content-derived so two different plans never collide; time-salted so deliberately
    running the same job twice gives two independent runs rather than colliding on one.
    """
    material = "\x00".join(
        [spec.name, spec.spec_hash, *(d.source_sha256 for d in documents), f"{time.time():.6f}"]
    )
    return hashlib.sha256(material.encode()).hexdigest()[:12]
