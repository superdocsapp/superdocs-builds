import os

from .engine import repair, Result
from .docx import Block, read_blocks, write_docx, blocks_to_html

__all__ = ["repair", "Result", "Block", "read_blocks", "write_docx", "blocks_to_html"]


def _load_dotenv() -> None:
    """Read this build's `.env`, so `cp .env.example .env` is the whole setup.

    Dependency-free on purpose: a fresh checkout may not have `python-dotenv`
    installed, and the relay defaults have to be configuration rather than
    documentation.

    **It does not walk up the tree.** It used to, six directories deep, and that
    is safe only for a build that owns its whole repository. This one sits in a
    tree beside other projects, and the walk reached a sibling's `.env` holding a
    real `sk_` SuperDocs key: an import from the wrong working directory handed
    this build credentials nobody gave it, and a live run would have spent
    somebody else's allowance. The precedence rule exists to stop a key going
    where its owner did not send it, and a loader reaching two directories too
    far defeats that rule from underneath. Reproduced 2026-08-27.

    One place: this build's own root, where its `.env.example` sits, so the
    documented `cp` works no matter which directory the command is run from. The
    working directory is deliberately not a second source — cwd is ambient, and
    "I happened to be standing in a project that has a `.env`" is not the same
    act as choosing that file. An existing environment variable always wins, so
    an `export` still beats the file, and a test that deliberately empties a
    variable stays emptied.
    """
    from pathlib import Path

    candidate = Path(__file__).resolve().parents[2] / ".env"
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
