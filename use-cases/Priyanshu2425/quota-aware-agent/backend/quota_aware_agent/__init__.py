import os

from .agent import QuotaAwareAgent, Report, Step
from .budget import Balance, BudgetGuard, Change, Plan, estimate
from .client import (Endpoint, HttpTransport, QuotaExhausted, RationExhausted,
                     RelayRefused, SuperDocsClient, parse_proposed_changes,
                     resolve)

__all__ = [
    "QuotaAwareAgent", "Report", "Step",
    "Balance", "BudgetGuard", "Change", "Plan", "estimate",
    "Endpoint", "HttpTransport", "QuotaExhausted", "RationExhausted",
    "RelayRefused", "SuperDocsClient", "parse_proposed_changes", "resolve",
]


def _load_dotenv() -> None:
    """Read this build's `.env`, so `cp .env.example .env` is the whole setup.

    Dependency-free on purpose, and the same parser as the neighbouring
    `word-doc-repair` build (`docrepair/__init__.py`) rather than a second
    dialect of the same file: this package declares `dependencies = []` and a
    fresh checkout will not have `python-dotenv`, but the relay defaults have to
    be configuration and not documentation.

    **It does not walk up the tree, and that is a deliberate difference from the
    neighbouring copy.** That one walks up six directories, which is right for a
    build that owns its whole repository and wrong here: this one sits in a tree
    alongside other projects, and walking up found a sibling's `.env` holding a
    real `sk_` SuperDocs key. A `--live` run then went to the origin on somebody
    else's credentials, having been given none — the precedence rule in
    `client.resolve` exists precisely to stop a key going somewhere its owner
    did not choose, and an over-eager loader handing one over underneath it
    defeats the rule from below. Verified 2026-08-27, which is why this looks
    only where this build's own configuration can be.

    One place: this build's root, where `.env.example` sits, so the documented
    `cp` works from whatever directory the command is run from. The working
    directory was a second source and is not any more — the same sibling `.env`
    is still reachable through it, since cwd is ambient and standing in a project
    that has a `.env` is not the act of choosing that file. Existing environment
    variables are never overridden, so an `export` still wins — and a test that
    deliberately empties a variable stays emptied.
    """
    from pathlib import Path

    candidate = Path(__file__).resolve().parents[2] / ".env"   # .../quota-aware-agent
    if candidate.is_file():
        _read_env_file(candidate)


def _read_env_file(path) -> None:
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = val.strip().strip('"').strip("'")


_load_dotenv()
