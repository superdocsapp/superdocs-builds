"""CI workflows: job names, environments, and which jobs gate on approval.

Runbooks name CI jobs constantly — "re-run the deploy job", "trigger the
rollback job" — and job names are renamed more often than almost anything else
in an estate, because renaming one is a one-line diff nobody thinks of as a
breaking change. It is a breaking change to every document that named it.

Two formats, because infrastructure repositories are rarely all one thing:

- **GitHub Actions**, `.github/workflows/*.yml`: jobs are the keys of the
  top-level `jobs` mapping.
- **GitLab CI**, `.gitlab-ci.yml`: jobs are top-level keys that are *not* one of
  the reserved words. That inversion is why `_GITLAB_RESERVED` exists and why it
  is a set of data rather than a chain of `if`s — GitLab adds keywords, and
  adding one here is a one-line change to a list.

`environment` is read because it is the closest thing in either format to "this
step needs a human to approve it", and a runbook that says a deploy is gated
when it is not is telling an engineer they have a safety net they do not have.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reconciler.readers._source import SourceRef, iter_files, line_of, load_yaml

#: Top-level keys in a GitLab CI file that configure the pipeline rather than
#: declare a job. Everything else at that level is a job.
_GITLAB_RESERVED = frozenset(
    {
        "default",
        "image",
        "include",
        "services",
        "stages",
        "variables",
        "workflow",
        "before_script",
        "after_script",
        "cache",
        "pages",
    }
)


@dataclass(frozen=True)
class Job:
    name: str
    environment: str | None
    needs: tuple[str, ...]
    source: SourceRef

    @property
    def gated(self) -> bool:
        return self.environment is not None


@dataclass(frozen=True)
class Workflow:
    name: str
    repo: str
    platform: str  # github | gitlab
    source: SourceRef
    jobs: tuple[Job, ...] = ()

    def job(self, name: str) -> Job | None:
        return next((j for j in self.jobs if j.name == name), None)


def read_workflows(paths: tuple[Path, ...]) -> list[Workflow]:
    out: list[Workflow] = []
    for path in iter_files(paths, "*.yml", "*.yaml"):
        if ".github/workflows" in str(path):
            workflow = read_github_workflow(path)
        elif path.name == ".gitlab-ci.yml":
            workflow = read_gitlab_workflow(path)
        else:
            continue
        if workflow:
            out.append(workflow)
    return out


def read_github_workflow(path: Path) -> Workflow | None:
    document = load_yaml(path)
    if not isinstance(document, dict) or "jobs" not in document:
        return None
    jobs = []
    for name, body in (document.get("jobs") or {}).items():
        body = body if isinstance(body, dict) else {}
        jobs.append(
            Job(
                name=str(name),
                environment=_environment(body.get("environment")),
                needs=_needs(body.get("needs")),
                source=SourceRef.of(path, body, line_of(document, 1)),
            )
        )
    return Workflow(
        name=str(document.get("name") or path.stem),
        repo=_repo_of(path),
        platform="github",
        source=SourceRef.of(path, document),
        jobs=tuple(jobs),
    )


def read_gitlab_workflow(path: Path) -> Workflow | None:
    document = load_yaml(path)
    if not isinstance(document, dict):
        return None
    jobs = []
    for name, body in document.items():
        name = str(name)
        # `.hidden` keys are templates to be extended, not jobs that run.
        if name in _GITLAB_RESERVED or name.startswith(".") or not isinstance(body, dict):
            continue
        jobs.append(
            Job(
                name=name,
                environment=_environment(body.get("environment")),
                needs=_needs(body.get("needs")),
                source=SourceRef.of(path, body, line_of(document, 1)),
            )
        )
    return Workflow(
        name=path.stem or "gitlab-ci",
        repo=_repo_of(path),
        platform="gitlab",
        source=SourceRef.of(path, document),
        jobs=tuple(jobs),
    )


def _environment(value: object) -> str | None:
    """`environment: production` and `environment: {name: production}` both count."""
    if isinstance(value, dict):
        name = value.get("name")
        return str(name) if name else None
    return str(value) if value else None


def _needs(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(v.get("job", v)) if isinstance(v, dict) else str(v) for v in value)
    return ()


def _repo_of(path: Path) -> str:
    """The repository a workflow belongs to, by convention rather than by git.

    For `<repo>/.github/workflows/deploy.yml` that is two levels up; for a
    GitLab file at the repository root it is the parent. Reading `.git/config`
    would be more correct and would also mean this reader needs a real checkout
    rather than a directory of files, which the tests would then need too.
    """
    if ".github" in path.parts:
        index = path.parts.index(".github")
        return path.parts[index - 1] if index else path.parent.name
    return path.parent.name


__all__ = ["Job", "Workflow", "read_github_workflow", "read_gitlab_workflow", "read_workflows"]
