"""When the drift arrived, and which commit brought it.

Every finding already names the file and the line that proves it. That answers
*what* the estate says. It does not answer the question the person reading the
finding asks next, which is **when did this stop being true** — because that is
what decides whether they are looking at a typo from last week or a rename from
two years ago that forty other pages also missed.

The change feed for that is already on disk. `INFRA_REPO_PATHS` are git
checkouts, and `git blame` on the evidence line names the commit that last
touched it. Nothing needs fetching, nothing needs configuring, and the answer is
as trustworthy as the repository the finding was read from.

## Why this is opt-in

One `git blame` per finding is one subprocess per finding. On thirteen findings
that is imperceptible; on a first sweep over a real estate finding four hundred
it is not, and the free layer's whole claim is that it costs nothing and runs in
a fraction of a second. So `rr check --blame` asks for it.

## Everything here fails soft

A path outside any repository, a file that was never committed, `git` not
installed, a shallow clone whose history does not reach back far enough: all of
them return `None`, and the finding prints exactly as it did before. Attribution
is a nicety on top of a finding that is already actionable, and a checker that
refused to report drift because it could not work out whose fault it was would
have its priorities exactly backwards.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

#: Long enough to be unambiguous in any repository a person will page through,
#: short enough to paste into a message.
_SHORT_SHA = 12

#: A blame that has not answered in this long is a blame nobody is waiting for.
#: A pathological history, or a repository on a slow network mount, must not
#: turn a free deterministic sweep into something that hangs.
_TIMEOUT = 5.0


@dataclass(frozen=True)
class Commit:
    """The commit that last touched one line, as much of it as is useful."""

    sha: str
    author: str
    date: str
    subject: str

    def describe(self) -> str:
        return f"{self.sha[:7]} · {self.author} · {self.date} · {self.subject}"


def blame(path: Path | str, line: int) -> Commit | None:
    """The commit that last changed `line` of `path`, or None for any reason."""
    target = Path(path)
    if line < 1 or not target.is_file():
        return None
    return _blame(str(target.resolve()), line)


@lru_cache(maxsize=2048)
def _blame(resolved: str, line: int) -> Commit | None:
    """Cached, because several findings routinely cite the same line.

    Three claims about one alert blame the same rules-file line three times, and
    a subprocess is far and away the most expensive thing in this module.

    `--` before the path so a file whose name looks like a revision is read as a
    file, and `-L n,n` so git reads one line rather than the whole history of a
    file that may be thousands of lines long.
    """
    path = Path(resolved)
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(path.parent),
                "blame",
                "-L",
                f"{line},{line}",
                "--porcelain",
                "--",
                path.name,
            ],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # git missing, not executable, or the repository unreadable. The finding
        # stands; only its attribution is lost.
        return None

    if result.returncode != 0 or not result.stdout:
        return None
    return _parse_porcelain(result.stdout)


def _parse_porcelain(output: str) -> Commit | None:
    """Porcelain, not the default format, because the default is not parseable.

    `git blame`'s human output puts the author and the date inside one
    parenthesised field with no delimiter an author's name cannot contain — an
    author called `Ana (Ana) Ruiz` is enough to break it. The porcelain format is
    one `key value` per line and is the documented interface.
    """
    fields: dict[str, str] = {}
    sha = ""
    for index, raw in enumerate(output.splitlines()):
        if index == 0:
            sha = raw.split(" ", 1)[0]
            continue
        if raw.startswith("\t"):
            break  # the line's own content: the header is over
        key, _, value = raw.partition(" ")
        fields.setdefault(key, value)

    if not sha or set(sha) == {"0"}:
        # All zeroes is git's way of saying "not committed yet". A finding about
        # an uncommitted line is a finding about somebody's working tree, and
        # naming a commit for it would be inventing one.
        return None

    return Commit(
        sha=sha[:_SHORT_SHA],
        author=fields.get("author", "unknown"),
        date=_date(fields.get("author-time", "")),
        subject=fields.get("summary", "").strip(),
    )


def _date(epoch: str) -> str:
    """The day, not the second. Nobody reading a finding needs the timezone."""
    from datetime import UTC, datetime

    try:
        return datetime.fromtimestamp(int(epoch), UTC).strftime("%Y-%m-%d")
    except (ValueError, OSError, OverflowError):
        return ""


__all__ = ["Commit", "blame"]
