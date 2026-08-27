"""The ledger's own guarantees, tested without a server.

These are the properties everything else stands on: a transition that lost a race must
fail rather than overwrite, and a durable write must still be there in a process that
has never seen the one that wrote it.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from longhaul.ledger import ConcurrentTransition, Ledger, LeaseLost, new_owner_id
from longhaul.model import ISSUED, ISSUING, PLANNED, Commit, Document, Run, Step


def _seed(path: Path, steps: int = 3) -> Ledger:
    ledger = Ledger(path)
    run = Run(run_id="r1", spec_path="spec.yaml", spec_hash="h", session_id="s1")
    docs = [Document("r1", "doc-a", "/tmp/a.md", "sha", "Doc A")]
    plan = [
        Step("r1", i, f"step-{i}", "doc-a", f"do thing {i}", f"[tok:{i}]")
        for i in range(steps)
    ]
    ledger.create_run(run, docs, plan)
    return ledger


def test_transition_is_compare_and_swap(tmp_path: Path) -> None:
    ledger = _seed(tmp_path / "l.db")
    ledger.transition("r1", 0, expect=PLANNED, to=ISSUING)

    # The second caller expected PLANNED and reality has moved on. Overwriting here is
    # how two runners would both issue the same edit, so it must fail loudly.
    with pytest.raises(ConcurrentTransition) as exc:
        ledger.transition("r1", 0, expect=PLANNED, to=ISSUING)
    assert "found 'issuing'" in str(exc.value)
    assert ledger.get_step("r1", 0).state == ISSUING


def test_transition_rejects_unwritable_fields(tmp_path: Path) -> None:
    ledger = _seed(tmp_path / "l.db")
    with pytest.raises(Exception, match="not writable"):
        ledger.transition("r1", 0, expect=PLANNED, to=ISSUING, instruction="rewritten")


def test_commits_are_append_only_and_ordered(tmp_path: Path) -> None:
    ledger = _seed(tmp_path / "l.db")
    ledger.append_commits([
        Commit(0, "r1", 0, "ch_b", True, "doc", None, time.time()),
        Commit(0, "r1", 0, "ch_a", False, "doc", None, time.time()),
    ])
    ledger.append_commits([Commit(0, "r1", 1, "ch_c", True, "doc", None, time.time())])

    log = [c.identity() for c in ledger.get_commits("r1")]
    assert log == [(0, "ch_b", True, "doc"), (0, "ch_a", False, "doc"), (1, "ch_c", True, "doc")]

    conn = sqlite3.connect(str(tmp_path / "l.db"))
    try:
        assert conn.execute("SELECT COUNT(*) FROM commits").fetchone()[0] == 3
    finally:
        conn.close()


def test_lease_excludes_a_live_holder(tmp_path: Path) -> None:
    ledger = _seed(tmp_path / "l.db")
    # A live owner on this host: our own pid, which is definitely running.
    import os
    alive = f"{os.uname().nodename}:{os.getpid()}:deadbeef"
    ledger.acquire_lease("r1", alive, ttl=60)
    with pytest.raises(LeaseLost):
        ledger.acquire_lease("r1", new_owner_id(), ttl=60)


def test_lease_is_reclaimed_from_a_dead_holder(tmp_path: Path) -> None:
    """A killed runner never releases its lease. Waiting out a timer for a process that
    cannot come back is only downtime, so a provably dead holder is displaced at once."""
    ledger = _seed(tmp_path / "l.db")
    dead = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    dead.kill()
    dead.wait()

    import os
    ledger.acquire_lease("r1", f"{os.uname().nodename}:{dead.pid}:cafebabe", ttl=600)
    fence = ledger.acquire_lease("r1", new_owner_id(), ttl=60)
    assert fence == 2  # the fence advanced rather than the lease being silently shared


def test_stale_fence_cannot_write(tmp_path: Path) -> None:
    ledger = _seed(tmp_path / "l.db")
    old = ledger.acquire_lease("r1", "hostx:1:aaaa", ttl=0.01)
    time.sleep(0.05)
    ledger.acquire_lease("r1", new_owner_id(), ttl=60)
    with pytest.raises(LeaseLost):
        ledger.transition("r1", 0, expect=PLANNED, to=ISSUING, fence=old)


def test_state_survives_a_process_that_never_saw_it(tmp_path: Path) -> None:
    """Durability, proven the only way that means anything: read it back from a process
    that did not write it."""
    db = tmp_path / "l.db"
    ledger = _seed(db)
    ledger.transition("r1", 0, expect=PLANNED, to=ISSUING)
    ledger.transition("r1", 0, expect=ISSUING, to=ISSUED, job_id="job_42")
    ledger.close()

    script = (
        "import sys, json;"
        "sys.path.insert(0, %r);"
        "from longhaul.ledger import Ledger;"
        "l = Ledger(%r);"
        "s = l.get_step('r1', 0);"
        "print(json.dumps({'state': s.state, 'job': s.job_id}))"
        % (str(Path(__file__).resolve().parent.parent / "src"), str(db))
    )
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    import json

    assert json.loads(out.stdout) == {"state": ISSUED, "job": "job_42"}


def test_binding_a_document_twice_to_different_ids_is_refused(tmp_path: Path) -> None:
    ledger = _seed(tmp_path / "l.db")
    ledger.bind_document("r1", "doc-a", "doc_1")
    ledger.bind_document("r1", "doc-a", "doc_1")  # idempotent: same id is fine
    with pytest.raises(ConcurrentTransition):
        ledger.bind_document("r1", "doc-a", "doc_2")


def test_run_is_written_whole_or_not_at_all(tmp_path: Path) -> None:
    db = tmp_path / "l.db"
    ledger = Ledger(db)
    run = Run(run_id="r2", spec_path="s", spec_hash="h", session_id="s2")
    steps = [Step("r2", 0, "a", "doc", "i", "t"), Step("r2", 0, "dup", "doc", "i", "t")]
    with pytest.raises(sqlite3.IntegrityError):
        ledger.create_run(run, [Document("r2", "doc", "/p", "sha", "T")], steps)
    assert ledger.get_run("r2") is None
    assert ledger.get_steps("r2") == []


def test_a_hostname_containing_colons_does_not_break_liveness(tmp_path: Path) -> None:
    """Found the hard way: this machine started reporting its hostname as
    "Unknown_86:ae:73:f8:f0:67" after a network change. Splitting the owner id from the
    left made every owner unparseable, so every dead lease looked alive and no crashed
    run could be resumed — nine tests failed at once for one reason."""
    from longhaul.ledger import _owner_is_alive

    dead = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    dead.kill()
    dead.wait()

    import os

    host = os.uname().nodename
    assert _owner_is_alive(f"{host}:{dead.pid}:cafebabe") is False
    assert _owner_is_alive(f"Unknown_86:ae:73:f8:f0:67:{dead.pid}:cafebabe") in (False, None)
    assert _owner_is_alive(f"{host}:{os.getpid()}:cafebabe") is True
    # A remote host is never guessed dead, whatever its name looks like.
    assert _owner_is_alive(f"some:other:box:{dead.pid}:cafebabe") is None
    assert _owner_is_alive("nonsense") is None


def test_the_lease_is_reclaimed_whatever_this_host_is_called(tmp_path: Path) -> None:
    """The end-to-end consequence: a crashed runner's lease must be reclaimable on the
    machine it crashed on, regardless of what that machine calls itself today."""
    ledger = _seed(tmp_path / "l.db")
    import os

    dead = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    dead.kill()
    dead.wait()
    ledger.acquire_lease("r1", f"{os.uname().nodename}:{dead.pid}:cafebabe", ttl=600)
    assert ledger.acquire_lease("r1", new_owner_id(), ttl=60) == 2
