"""Where the mock finds the data it serves.

Three ways this project gets run, and the fixtures have to be found in all of them:

* from a checkout, where `spec/` and `cassettes/` sit beside `src/`
* from an installed wheel, where they are packaged inside `sdmock/_data/`
* from the container, where they are mounted or copied to a known path

So resolution is explicit and ordered rather than a relative path that happens to work in
whichever layout was tried first. An environment variable always wins, because the whole
point of the container is that someone can mount their own recordings over the baked-in
ones.
"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent

# Inside an installed wheel: sdmock/_data/{spec,cassettes}
PACKAGED = PACKAGE / "_data"

# From a checkout: <repo>/{spec,cassettes}
CHECKOUT = PACKAGE.parent.parent


def _resolve(name: str, env_var: str) -> Path:
    override = os.environ.get(env_var)
    if override:
        path = Path(override).expanduser()
        if not path.is_dir():
            raise SystemExit(
                f"{env_var} points at {path}, which is not a directory. Unset it to use "
                f"the {name} bundled with this install."
            )
        return path

    for candidate in (PACKAGED / name, CHECKOUT / name, Path.cwd() / name):
        if candidate.is_dir():
            return candidate

    raise SystemExit(
        f"Could not find a {name}/ directory. Looked in {PACKAGED / name}, "
        f"{CHECKOUT / name} and {Path.cwd() / name}. Set {env_var} to point at one."
    )


def cassettes_dir() -> Path:
    """Where the recorded scenarios live. Override with SDMOCK_CASSETTES."""
    return _resolve("cassettes", "SDMOCK_CASSETTES")


def spec_dir() -> Path:
    """Where the pinned OpenAPI document and MCP surface live. Override: SDMOCK_SPEC."""
    return _resolve("spec", "SDMOCK_SPEC")
