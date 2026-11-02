"""Dashboards declared in the repository, so a link can be checked without one.

A runbook's dashboard links rot faster than almost anything else on the page,
and the obvious way to check them — fetch the URL — is the wrong one here. It
makes the checker's output depend on VPN state, on whoever's Grafana is up, and
on network reachability inside a stage that is otherwise deterministic and
offline. A check that reports differently depending on where it runs is a check
nobody trusts.

So: a link is resolved against the dashboards *declared in the repository*, by
uid. A link whose uid is declared passes. A link whose uid is not declared is
reported as unresolvable, with the honest wording — this tool cannot see
dashboards that live only in the Grafana database, and that limitation is in the
README rather than hidden behind a confident "dead link" verdict.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from reconciler.config import display_path
from reconciler.readers._source import SourceRef, iter_files

#: Grafana's own URL shape: `/d/<uid>/<slug>`.
DASHBOARD_URL = re.compile(r"/d/([A-Za-z0-9_-]+)")


@dataclass(frozen=True)
class Dashboard:
    uid: str
    title: str
    source: SourceRef
    tags: tuple[str, ...] = ()


def read_dashboards(paths: tuple[Path, ...]) -> list[Dashboard]:
    out: list[Dashboard] = []
    for path in iter_files(paths, "*.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(document, dict) or not document.get("uid"):
            continue
        out.append(
            Dashboard(
                uid=str(document["uid"]),
                title=str(document.get("title", "")),
                source=SourceRef(display_path(path), 1),
                tags=tuple(str(t) for t in document.get("tags") or ()),
            )
        )
    return out


def uid_in(url: str) -> str | None:
    match = DASHBOARD_URL.search(url)
    return match.group(1) if match else None


__all__ = ["DASHBOARD_URL", "Dashboard", "read_dashboards", "uid_in"]
