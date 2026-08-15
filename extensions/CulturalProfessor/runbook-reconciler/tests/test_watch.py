"""The watcher: debounce, coalesce, and never chasing its own tail.

Every test here drives a fake clock. A watcher tested against the real one is a
test suite that sleeps, and the debounce is precisely the behaviour worth many
assertions — so the clock is a parameter and the whole file runs in
milliseconds.

The test that matters most is `test_our_own_write_does_not_trigger_a_sweep`.
Rule 6 is the difference between a watcher and an infinite loop: a sweep can end
in a write, a write bumps a page version, and a version bump looks exactly like
a change worth sweeping for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reconciler.config import Config
from reconciler.confluence.local import LocalSource, PageRef
from reconciler.register import Register
from reconciler.watch import Trigger, Watcher


class FakeClock:
    """Time, as something the test moves on purpose."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept += seconds
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def estate(tmp_path: Path, infra_dir: Path) -> Path:
    """A writable copy of the corpus, because these tests change files."""
    target = tmp_path / "infra"
    target.mkdir()
    for path in infra_dir.rglob("*"):
        if path.is_file():
            destination = target / path.relative_to(infra_dir)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return target


@pytest.fixture
def register(tmp_path: Path) -> Register:
    with Register(tmp_path / "register.db") as reg:
        yield reg


def watcher(
    estate: Path,
    register: Register,
    runbooks: Path,
    clock: FakeClock,
    quiet: float = 2.0,
    watch_pages: bool = True,
) -> Watcher:
    import dataclasses

    config = dataclasses.replace(Config.load(), infra_repo_paths=(estate,), runbook_source=runbooks)
    return Watcher(
        config,
        register,
        LocalSource(runbooks),
        interval=10.0,
        quiet=quiet,
        clock=clock,
        sleep=clock.sleep,
        output=lambda _: None,
        watch_pages=watch_pages,
    )


def touch(path: Path, text: str = "\n# nudged\n") -> None:
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


# --------------------------------------------------------------- baseline --


def test_the_first_poll_is_a_baseline_and_not_a_change(
    estate: Path, register: Register, runbooks_dir: Path
) -> None:
    """Otherwise the watcher opens by sweeping an estate nobody touched."""
    clock = FakeClock()
    watch = watcher(estate, register, runbooks_dir, clock)

    assert not watch.poll()
    assert watch.state.files, "the baseline should still have been recorded"


def test_a_changed_file_is_noticed(estate: Path, register: Register, runbooks_dir: Path) -> None:
    clock = FakeClock()
    watch = watcher(estate, register, runbooks_dir, clock)
    watch.poll()

    target = next(estate.rglob("*.yml"))
    touch(target)
    trigger = watch.poll()

    assert str(target) in trigger.paths


def test_a_file_outside_the_watched_kinds_is_ignored(
    estate: Path, register: Register, runbooks_dir: Path
) -> None:
    """A README changing is not a change to the infrastructure."""
    clock = FakeClock()
    watch = watcher(estate, register, runbooks_dir, clock)
    watch.poll()

    (estate / "NOTES.md").write_text("nothing to do with the estate\n", encoding="utf-8")

    assert not watch.poll()


def test_a_deleted_file_counts_as_a_change(
    estate: Path, register: Register, runbooks_dir: Path
) -> None:
    clock = FakeClock()
    watch = watcher(estate, register, runbooks_dir, clock)
    watch.poll()

    target = next(estate.rglob("*.yml"))
    target.unlink()

    assert str(target) in watch.poll().paths


# --------------------------------------------------------------- debounce --


def test_a_change_does_not_sweep_until_everything_holds_still(
    estate: Path, register: Register, runbooks_dir: Path
) -> None:
    """A branch checkout rewriting forty files is one sweep, not forty."""
    clock = FakeClock()
    watch = watcher(estate, register, runbooks_dir, clock, watch_pages=False)
    watch.poll()

    touch(next(estate.rglob("*.yml")))
    assert watch.tick() is None, "swept while the estate was still moving"

    clock.advance(0.5)
    touch(next(estate.rglob("*.tf")))
    assert watch.tick() is None, "the quiet period should have restarted"

    clock.advance(5.0)
    assert watch.tick() is not None, "settled, so it should have swept"
    assert watch.state.sweeps == 1


def test_many_changes_coalesce_into_one_sweep(
    estate: Path, register: Register, runbooks_dir: Path
) -> None:
    clock = FakeClock()
    watch = watcher(estate, register, runbooks_dir, clock, watch_pages=False)
    watch.poll()

    for path in list(estate.rglob("*.yml"))[:5]:
        touch(path)
    watch.tick()
    clock.advance(5.0)
    watch.tick()

    assert watch.state.sweeps == 1


def test_nothing_changing_never_sweeps(
    estate: Path, register: Register, runbooks_dir: Path
) -> None:
    """The quiet estate case, which is most of the time."""
    clock = FakeClock()
    watch = watcher(estate, register, runbooks_dir, clock)
    watch.poll()

    for _ in range(5):
        clock.advance(10.0)
        assert watch.tick() is None

    assert watch.state.sweeps == 0
    assert watch.state.operations == 0


def test_a_sweep_drains_the_pending_set(
    estate: Path, register: Register, runbooks_dir: Path
) -> None:
    """Otherwise the same change sweeps again on every later tick."""
    clock = FakeClock()
    watch = watcher(estate, register, runbooks_dir, clock, watch_pages=False)
    watch.poll()
    touch(next(estate.rglob("*.yml")))
    watch.tick()
    clock.advance(5.0)
    watch.tick()

    clock.advance(60.0)
    assert watch.tick() is None
    assert watch.state.sweeps == 1


# ------------------------------------------------------------------ rule 6 --


def test_our_own_write_does_not_trigger_a_sweep(
    estate: Path, register: Register, tmp_path: Path, runbooks_dir: Path
) -> None:
    """The infinite loop this project would otherwise ship.

    A sweep ends in a write, the write bumps the version, and the bump looks
    exactly like somebody editing the page. The version ledger is what tells
    them apart.
    """
    runbooks = tmp_path / "runbooks"
    runbooks.mkdir()
    for path in runbooks_dir.iterdir():
        if path.is_file():
            (runbooks / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    clock = FakeClock()
    watch = watcher(estate, register, runbooks, clock)
    watch.poll()

    source = LocalSource(runbooks)
    document = source.read("1001")
    new_version = source.write("1001", document.body + "<p>ours</p>", document.version)
    register.record_page_write("1001", new_version)

    assert not watch.poll().pages


def test_somebody_else_editing_a_page_does_trigger(
    estate: Path, register: Register, tmp_path: Path, runbooks_dir: Path
) -> None:
    """The other half of rule 6: it must still notice real edits."""
    runbooks = tmp_path / "runbooks"
    runbooks.mkdir()
    for path in runbooks_dir.iterdir():
        if path.is_file():
            (runbooks / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    clock = FakeClock()
    watch = watcher(estate, register, runbooks, clock)
    watch.poll()

    source = LocalSource(runbooks)
    document = source.read("1001")
    source.write("1001", document.body + "<p>theirs</p>", document.version)

    assert "1001" in watch.poll().pages


def test_an_author_id_matching_ours_is_ignored_when_the_token_can_say(
    estate: Path, register: Register, runbooks_dir: Path
) -> None:
    """The second filter, for the classic-token case where account_id works."""

    class WithAccount(LocalSource):
        def account_id(self) -> str:
            return "acct-us"

        def pages(self) -> list[PageRef]:
            return [
                PageRef(
                    page_id="1001", title="t", version=9, labels=("runbook",), author_id="acct-us"
                )
            ]

    clock = FakeClock()
    watch = watcher(estate, register, runbooks_dir, clock)
    watch.source = WithAccount(runbooks_dir)
    watch.state.pages = {"1001": PageRef(page_id="1001", title="t", version=8, labels=("runbook",))}

    assert not watch.poll().pages


def test_an_unknown_author_is_treated_as_somebody_else(
    estate: Path, register: Register, runbooks_dir: Path
) -> None:
    """Unknown means sweep. One free sweep beats one silent miss."""

    class NoAccount(LocalSource):
        def account_id(self) -> None:
            return None

        def pages(self) -> list[PageRef]:
            return [PageRef(page_id="1001", title="t", version=9, labels=("runbook",))]

    clock = FakeClock()
    watch = watcher(estate, register, runbooks_dir, clock)
    watch.source = NoAccount(runbooks_dir)
    watch.state.pages = {"1001": PageRef(page_id="1001", title="t", version=8, labels=("runbook",))}

    assert "1001" in watch.poll().pages


# -------------------------------------------------------------- reporting --


def test_every_sweep_reports_its_cost_including_zero(
    estate: Path, register: Register, runbooks_dir: Path
) -> None:
    """Behaviour ten. The zero is the number people do not believe."""
    clock = FakeClock()
    lines: list[str] = []
    watch = watcher(estate, register, runbooks_dir, clock, watch_pages=False)
    watch.output = lines.append
    watch.poll()

    touch(next(estate.rglob("*.yml")))
    watch.tick()
    clock.advance(5.0)
    watch.tick()

    assert any("0 paid operation(s) spent" in line for line in lines)


def test_the_loop_takes_a_baseline_before_its_first_tick(
    estate: Path, register: Register, runbooks_dir: Path
) -> None:
    clock = FakeClock()
    lines: list[str] = []
    watch = watcher(estate, register, runbooks_dir, clock)
    watch.output = lines.append

    state = watch.loop(ticks=2)

    assert state.sweeps == 0
    assert any("baseline taken" in line for line in lines)


def test_a_trigger_describes_itself_without_flooding_the_terminal() -> None:
    trigger = Trigger(paths=tuple(f"/infra/file{n}.yaml" for n in range(40)))
    text = trigger.describe()

    assert "40 infra file(s)" in text
    assert "+37 more" in text
    assert len(text) < 200
