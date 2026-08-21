"""Where everything is, resolved once.

Two ideas hold this file together.

**Nothing reads `os.environ` except this module.** A checker that reaches for an
environment variable in the middle of a rule is a checker that behaves
differently under `rr sweep` and under pytest, and the difference surfaces as a
flaky test three stages later.

**Configuration over code.** Entity resolution — deciding that "the payments
service" in a sentence means `deploy/payments-api` in namespace `payments` — is
solved by Backstage where a `catalog-info.yaml` exists and by
`config/mappings.yaml` where one does not. Neither path involves editing Python.
The same applies to the check rules, which live in `config/checks.yaml` and are
read by one generic engine; adding "check the PagerDuty escalation policy name"
is a YAML entry, not a new function.

Multi-repo from the start, because infrastructure and service code do not live
in the same repository at any organisation large enough to want this tool.
`INFRA_REPO_PATHS` is comma-separated for that reason and the readers walk all
of them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from reconciler.superdocs import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = PROJECT_ROOT / "fixtures" / "infra"
DEFAULT_RUNBOOKS = PROJECT_ROOT / "fixtures" / "runbooks"
CONFIG_DIR = PROJECT_ROOT / "config"


def display_path(path: Path | str) -> str:
    """A path an engineer can paste into an editor.

    Project-relative where possible, absolute where the file lives in somebody
    else's checkout. Findings quote this, and a finding whose evidence path is
    `../../../var/folders/T/pytest-of-x/…` is a finding nobody checks.
    """
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(resolved)


@dataclass(frozen=True)
class Mappings:
    """Entity resolution that Backstage cannot supply.

    `aliases` maps a phrase as written in a runbook to a catalog entity name.
    `former_names` is the same idea from the other direction and is normally
    read out of `catalog-info.yaml`; this file is the fallback for estates
    without a catalog, which is most of them.

    `ignore_subjects` is the escape hatch that keeps this tool installable: a
    team that decides a particular claim is not worth checking says so here
    rather than turning the whole checker off.
    """

    aliases: dict[str, str] = field(default_factory=dict)
    former_names: dict[str, str] = field(default_factory=dict)
    ignore_subjects: tuple[str, ...] = ()
    #: Extra spellings of "put your own value here", added to the built-in
    #: conventions rather than replacing them. The README has always said a team
    #: writing placeholders another way should "say so in config"; this is where
    #: they say it.
    placeholder_patterns: tuple[str, ...] = ()

    @classmethod
    def load(cls, path: Path | None = None) -> Mappings:
        path = path or CONFIG_DIR / "mappings.yaml"
        if not path.is_file():
            return cls()
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            aliases={str(k).lower(): str(v) for k, v in (raw.get("aliases") or {}).items()},
            former_names={
                str(k).lower(): str(v) for k, v in (raw.get("former_names") or {}).items()
            },
            ignore_subjects=tuple(raw.get("ignore_subjects") or ()),
            placeholder_patterns=tuple(str(p) for p in (raw.get("placeholder_patterns") or ())),
        )


def mute_subject(subject: str, path: Path | None = None) -> bool:
    """Add a subject to `ignore_subjects`, editing the text rather than the YAML.

    Round-tripping through `yaml.safe_load`/`yaml.dump` would rewrite the file
    and throw away every comment in it. `config/mappings.yaml` is mostly
    comments — it is the file that explains to a platform team what each escape
    hatch is for — and a tool that silently strips them the first time somebody
    runs `rr mute` has made the config worse in exchange for saving itself
    twenty lines.

    So the two shapes the key can be in are handled literally: the empty inline
    list it ships as, and a block list once there is something in it. Anything
    else (a key that is not there, a file shaped unexpectedly) returns False and
    the caller tells the operator to add the line by hand, which is a worse
    outcome than doing it for them and a much better one than corrupting the
    file.

    Returns False when the subject is already muted, so the caller can say so
    rather than writing a duplicate.
    """
    path = path or CONFIG_DIR / "mappings.yaml"
    if not path.is_file():
        return False

    existing = Mappings.load(path).ignore_subjects
    if subject in existing:
        return False

    text = path.read_text(encoding="utf-8")
    entry = f"  - {subject!r}"

    if "\nignore_subjects: []" in text:
        updated = text.replace("\nignore_subjects: []", f"\nignore_subjects:\n{entry}", 1)
    elif "\nignore_subjects:\n" in text:
        head, _, tail = text.partition("\nignore_subjects:\n")
        updated = f"{head}\nignore_subjects:\n{entry}\n{tail}"
    else:
        return False

    path.write_text(updated, encoding="utf-8")
    return True


@dataclass(frozen=True)
class Config:
    infra_repo_paths: tuple[Path, ...]
    runbook_source: Path | None
    space_key: str
    runbook_label: str
    confluence_site: str
    confluence_email: str
    confluence_token: str
    superdocs_key: str
    register_path: Path
    checks_path: Path
    mappings: Mappings
    #: `auto` reads Confluence when it is configured and the corpus when it is
    #: not; `corpus` and `confluence` say so outright. See `wants_confluence`.
    source_mode: str = "auto"

    @property
    def has_confluence(self) -> bool:
        return bool(self.confluence_site and self.confluence_email and self.confluence_token)

    @property
    def wants_confluence(self) -> bool:
        """Whether to read the live site, asked as one question in one place.

        `auto` exists because a stranger with no `.env` has to get output from
        their first command, and an operator who filled one in expects it to be
        used. The other two modes exist because `auto` is not good enough for
        two cases where guessing wrong is expensive:

        - **The test suite.** Left on `auto`, every test that calls
          `Config.load()` reads whatever `.env` the developer happens to have,
          so the suite passes on one machine and makes live HTTP calls on
          another. `conftest.py` pins `RR_SOURCE=corpus` for exactly this
          reason -- it was not hypothetical, it turned `rr check` into a network
          round-trip and a green suite into a slow one.
        - **The demo.** `RR_SOURCE=corpus` guarantees the offline half of the
          recording is offline even with credentials sitting in the environment.
        """
        if self.source_mode == "corpus":
            return False
        if self.source_mode == "confluence":
            return True
        return self.has_confluence

    @property
    def has_superdocs(self) -> bool:
        return bool(self.superdocs_key)

    @classmethod
    def load(cls, env_file: Path | None = None) -> Config:
        load_dotenv(env_file or PROJECT_ROOT / ".env")

        raw_paths = os.environ.get("INFRA_REPO_PATHS", "").strip()
        if raw_paths and not raw_paths.startswith("/path/to"):
            paths = tuple(Path(p.strip()).expanduser() for p in raw_paths.split(",") if p.strip())
        else:
            # The corpus is the default rather than an error. A stranger's first
            # command has to do something, and "point this at your estate" is a
            # worse first five minutes than "here is what it found on the
            # example estate; now point it at yours".
            paths = (DEFAULT_CORPUS,)

        return cls(
            infra_repo_paths=paths,
            runbook_source=DEFAULT_RUNBOOKS if DEFAULT_RUNBOOKS.is_dir() else None,
            space_key=os.environ.get("CONFLUENCE_SPACE_KEY", ""),
            runbook_label=os.environ.get("CONFLUENCE_RUNBOOK_LABEL", "runbook"),
            confluence_site=os.environ.get("CONFLUENCE_BASE_URL", "").rstrip("/"),
            confluence_email=os.environ.get("CONFLUENCE_EMAIL", ""),
            confluence_token=os.environ.get("CONFLUENCE_API_TOKEN", ""),
            superdocs_key=os.environ.get("SUPERDOCS_API_KEY", ""),
            register_path=Path(os.environ.get("RR_REGISTER", PROJECT_ROOT / "register.db")),
            checks_path=Path(os.environ.get("RR_CHECKS", CONFIG_DIR / "checks.yaml")),
            mappings=Mappings.load(),
            source_mode=os.environ.get("RR_SOURCE", "auto").strip().lower() or "auto",
        )


__all__ = [
    "CONFIG_DIR",
    "DEFAULT_CORPUS",
    "PROJECT_ROOT",
    "Config",
    "Mappings",
    "display_path",
    "mute_subject",
]
