"""The trigger: notice a change, wait for it to stop, sweep once.

## Polling, not inotify

A watcher built on filesystem events is better on Linux and a separate
implementation on macOS, Windows and inside a container with a bind mount. This
one stats the declared paths on an interval. The estate is a few hundred config
files, the interval is measured in seconds, and the cost is a rounding error
next to being able to reason about it — and next to a dependency that behaves
differently on the machine the demo is recorded on.

The interval is also the demo's cadence. Ten seconds is short enough that a
recording does not have dead air and long enough that it is visibly polling
rather than reacting to a keystroke.

## Debounce and coalesce, which are two different things

**Debounce**: `git checkout` of a branch rewrites forty files over a couple of
hundred milliseconds. Sweeping on the first one reads an estate that is half one
branch and half the other, and reports drift that never existed. So a change
starts a quiet period, and the sweep runs only once nothing has moved for
`quiet` seconds.

**Coalesce**: changes that land *while a sweep is running* must produce exactly
one more sweep, not one per file. The pending set is drained before the sweep
starts and refilled by anything that arrives during it, so a busy repository
converges instead of queueing.

Both are the difference between a tool somebody leaves running and a tool
somebody kills on the first afternoon.

## Rule 6: never re-trigger on our own writes

A sweep can end in an approved fix being written to Confluence. That write bumps
the page's version, the watcher sees a changed page, and it sweeps again —
forever, on a loop it caused itself.

The plan's mechanism for this was `client.account_id()`: ignore the version
whose author is us. That endpoint is unreachable with a scoped API token (see
`ConfluenceSource.account_id`), so the mechanism here is the version ledger —
`apply.py` records the exact version number each of its PUTs produced, in the
same transaction that marks the finding applied, and a page version this tool
wrote is not a change. `account_id()` is still consulted when the token happens
to support it, as a second filter rather than the only one.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reconciler.config import Config
from reconciler.confluence import PageSource
from reconciler.confluence.local import PageRef
from reconciler.register import Register
from reconciler.sweep import Sweep, SweepResult

#: Distinguishes "not looked up yet" from "looked up, and there is no answer",
#: which for `account_id` is the common case rather than the exception.
_UNRESOLVED = object()

#: The demo cadence. Short enough to watch, long enough to be a poll.
DEFAULT_INTERVAL = 10.0
#: How long everything must hold still before a sweep starts.
DEFAULT_QUIET = 2.0
#: How often the runbook space is re-listed, which is a different question from
#: how often the estate is stat'ed and deserves a different answer.
#:
#: Statting a few hundred local files costs nothing. Listing a Confluence space
#: does not: it is a paginated crawl plus **one extra call per page**, because
#: CQL search is unreachable with a scoped token (BUGS.md item 2). At the file
#: interval that is a 400-call round trip every ten seconds against somebody's
#: production wiki, all to notice an edit that can wait.
#:
#: The two are not the same urgency either. An infra change is what makes a
#: runbook wrong and is worth reacting to promptly; a human editing a runbook is
#: worth re-checking, but nobody is paged over it arriving five minutes later.
DEFAULT_PAGE_INTERVAL = 300.0

#: Directories that are never estate config and change constantly.
IGNORED_DIRECTORIES = frozenset({".git", "__pycache__", ".venv", "node_modules", ".terraform"})
#: Files worth reading. Anything else changing is not ground truth.
WATCHED_SUFFIXES = frozenset({".yaml", ".yml", ".tf", ".tfvars", ".json", ".hcl"})


@dataclass
class Trigger:
    """What changed, and therefore why a sweep is about to run."""

    paths: tuple[str, ...] = ()
    pages: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.paths or self.pages)

    def describe(self) -> str:
        parts = []
        if self.paths:
            shown = ", ".join(self.paths[:3])
            more = f" (+{len(self.paths) - 3} more)" if len(self.paths) > 3 else ""
            parts.append(f"{len(self.paths)} infra file(s) changed: {shown}{more}")
        if self.pages:
            parts.append(f"{len(self.pages)} runbook page(s) changed: {', '.join(self.pages[:5])}")
        return " · ".join(parts)


@dataclass
class WatchState:
    """Everything the loop remembers between ticks."""

    files: dict[str, float] = field(default_factory=dict)
    pages: dict[str, PageRef] = field(default_factory=dict)
    pending: Trigger = field(default_factory=Trigger)
    #: Monotonic time of the most recent observed change, or None when settled.
    last_change: float | None = None
    sweeps: int = 0
    operations: int = 0


class Watcher:
    """The loop, with its clock injected so the tests need not sleep.

    `clock` and `sleep` are parameters rather than direct calls to `time`
    because otherwise every test of the debounce is a test that takes two real
    seconds, and a suite that sleeps is a suite people stop running.
    """

    def __init__(
        self,
        config: Config,
        register: Register,
        source: PageSource,
        interval: float = DEFAULT_INTERVAL,
        quiet: float = DEFAULT_QUIET,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        output: Callable[[str], None] = print,
        watch_pages: bool = True,
        page_interval: float = DEFAULT_PAGE_INTERVAL,
    ) -> None:
        self.config = config
        self.register = register
        self.source = source
        self.interval = interval
        self.quiet = quiet
        self.clock = clock
        self.sleep = sleep
        self.output = output
        self.watch_pages = watch_pages
        #: Zero means "every poll", which is what the tests want and what a
        #: local corpus can afford.
        self.page_interval = page_interval
        self.state = WatchState()
        self._me: Any = _UNRESOLVED
        self._last_page_scan: float | None = None

    # ------------------------------------------------------------ observing --

    def scan_files(self) -> dict[str, float]:
        """Modification times for every declared config file, by path."""
        out: dict[str, float] = {}
        for root in self.config.infra_repo_paths:
            for path in _walk(root):
                try:
                    out[str(path)] = path.stat().st_mtime
                except OSError:
                    # Vanished between the walk and the stat -- that is itself a
                    # change, and the next tick sees it as a removal.
                    continue
        return out

    def scan_pages(self) -> dict[str, PageRef]:
        if not self.watch_pages:
            return {}
        return {page.page_id: page for page in self.source.pages()}

    def _pages_due(self) -> bool:
        """Whether this tick re-lists the space. See `DEFAULT_PAGE_INTERVAL`."""
        if not self.watch_pages:
            return False
        if self.page_interval <= 0 or self._last_page_scan is None:
            return True
        return self.clock() - self._last_page_scan >= self.page_interval

    def poll(self) -> Trigger:
        """One tick: what moved since last time, our own writes excluded."""
        files = self.scan_files()
        changed_paths = tuple(sorted(_differences(self.state.files, files)))
        self.state.files = files

        if not self._pages_due():
            # The space was not re-listed this tick, so nothing is known to have
            # changed on it. Deliberately not "assume unchanged and carry on
            # comparing": leaving `state.pages` alone means the next scan that
            # does run compares against the last real listing rather than
            # against a stale snapshot it has been pretending to refresh.
            return Trigger(paths=changed_paths)

        pages = self.scan_pages()
        self._last_page_scan = self.clock()
        versions = {page_id: ref.version for page_id, ref in pages.items()}
        before = {page_id: ref.version for page_id, ref in self.state.pages.items()}
        changed_pages = tuple(
            page_id
            for page_id in sorted(_differences(before, versions))
            if page_id in pages and not self._is_our_own_write(pages[page_id])
        )
        self.state.pages = pages
        return Trigger(paths=changed_paths, pages=changed_pages)

    def _is_our_own_write(self, page: PageRef) -> bool:
        """Rule 6. The version ledger first, the account id only if it works.

        Unknown authorship is treated as somebody else's edit. The cost of
        being wrong that way is one unnecessary sweep, which is free; the cost
        of the other way is a real change to a runbook that nobody is told
        about.
        """
        if self.register.wrote_version(page.page_id, page.version):
            return True
        me = self._account_id()
        return bool(me and page.author_id and page.author_id == me)

    def _account_id(self) -> str | None:
        """Cached, and usually None. See `ConfluenceSource.account_id`."""
        if self._me is _UNRESOLVED:
            resolver = getattr(self.source, "account_id", None)
            self._me = resolver() if callable(resolver) else None
        return self._me

    # ---------------------------------------------------------------- ticks --

    def tick(self) -> SweepResult | None:
        """One interval. Returns the sweep it ran, or None if nothing was due.

        The whole debounce lives here rather than in the loop, so a test can
        drive it a tick at a time against a fake clock.
        """
        trigger = self.poll()
        if trigger:
            # Coalesced: whatever arrived joins what was already waiting, and
            # the quiet period restarts. A branch checkout is one sweep.
            self.state.pending = Trigger(
                paths=tuple(sorted({*self.state.pending.paths, *trigger.paths})),
                pages=tuple(sorted({*self.state.pending.pages, *trigger.pages})),
            )
            self.state.last_change = self.clock()
            self.output(f"  {trigger.describe()}")

        if not self.state.pending or self.state.last_change is None:
            return None
        if self.clock() - self.state.last_change < self.quiet:
            return None

        due = self.state.pending
        # Drained *before* the sweep, so anything landing during it is the next
        # sweep's trigger rather than being lost or re-running this one.
        self.state.pending = Trigger()
        self.state.last_change = None
        return self.sweep(due)

    def sweep(self, trigger: Trigger) -> SweepResult:
        result = Sweep(self.config, self.register, source=self.source).run(mode="watch")
        self.state.sweeps += 1
        self.state.operations += result.operations
        self.output(f"  → {result.summary_line()}")
        self.output(f"  → {self.cost_line()}")
        return result

    def cost_line(self) -> str:
        """Behaviour ten, per run, including when the answer is zero.

        The zero is the point. A watcher that only mentions cost when it spent
        something is a watcher nobody believes when it says it is cheap.
        """
        return (
            f"{self.state.sweeps} sweep(s) this session · "
            f"{self.state.operations} paid operation(s) spent"
        )

    def loop(self, ticks: int | None = None) -> WatchState:
        """Run until interrupted, or for a fixed number of ticks in tests."""
        pages = f" · runbook pages every {self.page_interval:g}s" if self.watch_pages else ""
        self.output(
            f"watching {len(self.config.infra_repo_paths)} infra path(s) every "
            f"{self.interval:g}s{pages} · debounce {self.quiet:g}s · ctrl-c to stop"
        )
        # The first poll establishes the baseline. Without it every file in the
        # estate looks new and the watcher opens by sweeping on nothing.
        self.poll()
        self.output("  baseline taken; waiting for changes")

        count = 0
        try:
            while ticks is None or count < ticks:
                self.sleep(self.interval)
                self.tick()
                count += 1
        except KeyboardInterrupt:
            self.output("\nstopped.")
        self.output(self.cost_line())
        return self.state


def _walk(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    if not root.is_dir():
        return
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in WATCHED_SUFFIXES:
            continue
        if IGNORED_DIRECTORIES.intersection(path.parts):
            continue
        yield path


def _differences(before: dict[str, float | int], after: dict[str, float | int]) -> set[str]:
    """Added, removed or modified. A first scan reports nothing, by convention.

    `before` empty means "no baseline yet", and treating every file in the
    estate as new would make the watcher sweep the moment it starts on an estate
    nobody touched.
    """
    if not before:
        return set()
    return {
        key
        for key in {*before, *after}
        if before.get(key) != after.get(key)  # covers added, removed and changed
    }


__all__ = [
    "DEFAULT_INTERVAL",
    "DEFAULT_PAGE_INTERVAL",
    "DEFAULT_QUIET",
    "Trigger",
    "WatchState",
    "Watcher",
]
