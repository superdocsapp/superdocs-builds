from __future__ import annotations

import os
import threading

import pytest

from notion_review.domain import (
    BlockMapEntry,
    ChangeOperation,
    ProposalStatus,
    ProposedChange,
    ReviewRound,
    RoundStatus,
)
from notion_review.store import PostgresStore, RoundConflictError, SQLiteStore, Store, open_store


def _sample_round() -> ReviewRound:
    return ReviewRound(
        notion_page_id="page_1",
        status=RoundStatus.AWAITING_APPROVAL,
        block_map=[
            BlockMapEntry(
                notion_block_id="blk_1",
                block_type="paragraph",
                anchor="a1",
                chunk_id="chunk_0001",
                original_text="The quick brown fox.",
            )
        ],
        proposals=[
            ProposedChange(
                chunk_id="chunk_0001",
                notion_block_id="blk_1",
                operation=ChangeOperation.REPLACE,
                new_html="<p>The quick red fox.</p>",
                reviewer_name="Dana Reviewer",
                status=ProposalStatus.APPROVED,
            )
        ],
    )


def test_open_store_defaults_to_sqlite() -> None:
    store = open_store(None)
    assert isinstance(store, SQLiteStore)
    assert isinstance(store, Store)
    store.close()


def test_save_and_reload_preserves_the_whole_round() -> None:
    store = SQLiteStore()
    rnd = _sample_round()
    store.save(rnd)

    loaded = store.get(rnd.id)
    assert loaded is not None
    assert loaded.id == rnd.id
    assert loaded.status == RoundStatus.AWAITING_APPROVAL
    assert len(loaded.block_map) == 1
    assert loaded.block_map[0].chunk_id == "chunk_0001"
    assert len(loaded.proposals) == 1
    assert loaded.proposals[0].reviewer_name == "Dana Reviewer"
    assert loaded.proposals[0].status == ProposalStatus.APPROVED
    assert loaded.proposals[0].new_html == "<p>The quick red fox.</p>"
    store.close()


def test_save_is_an_upsert() -> None:
    store = SQLiteStore()
    rnd = _sample_round()
    store.save(rnd)
    rnd.status = RoundStatus.COMPLETED
    store.save(rnd)
    reloaded = store.get(rnd.id)
    assert reloaded is not None
    assert reloaded.status == RoundStatus.COMPLETED
    assert store.list_ids() == [rnd.id]  # updated in place, not duplicated
    store.close()


def test_missing_round_returns_none() -> None:
    store = SQLiteStore()
    assert store.get("round_missing") is None
    store.close()


def test_delete_removes_the_round() -> None:
    store = SQLiteStore()
    rnd = _sample_round()
    store.save(rnd)
    store.delete(rnd.id)
    assert store.get(rnd.id) is None
    assert store.list_ids() == []
    store.close()


def test_concurrent_rounds_stay_isolated() -> None:
    # Two runs at once must not corrupt state. Each round is its own row; hammer both.
    store = SQLiteStore()
    errors: list[Exception] = []

    def worker(tag: str) -> None:
        try:
            for _ in range(50):
                rnd = ReviewRound(notion_page_id=f"page_{tag}")
                store.save(rnd)
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(store.list_ids()) == 100
    store.close()


def test_a_stale_write_to_one_round_is_rejected_not_lost() -> None:
    # Two workers read the same round, then both try to write it. The first wins; the second is
    # working from a stale copy and must be refused rather than silently clobbering the first.
    store = SQLiteStore()
    rnd = _sample_round()
    store.save(rnd)

    first = store.get(rnd.id)
    second = store.get(rnd.id)
    assert first is not None and second is not None

    first.status = RoundStatus.APPLYING
    store.save(first)  # wins

    second.status = RoundStatus.FAILED
    with pytest.raises(RoundConflictError):
        store.save(second)  # stale — refused

    winner = store.get(rnd.id)
    assert winner is not None and winner.status == RoundStatus.APPLYING  # first writer's value
    store.close()


@pytest.mark.postgres
def test_postgres_store_round_trips() -> None:
    if not os.environ.get("RUN_POSTGRES_TESTS"):
        pytest.skip("Postgres tests run only in `make test-postgres` (needs the db service)")
    dsn = os.environ["DATABASE_URL"]
    store = PostgresStore(dsn)
    try:
        rnd = _sample_round()
        store.save(rnd)
        loaded = store.get(rnd.id)
        assert loaded is not None
        assert loaded.proposals[0].reviewer_name == "Dana Reviewer"
        rnd.status = RoundStatus.COMPLETED
        store.save(rnd)
        again = store.get(rnd.id)
        assert again is not None and again.status == RoundStatus.COMPLETED
        store.delete(rnd.id)
        assert store.get(rnd.id) is None
    finally:
        store.close()


def test_a_store_creates_the_directory_it_was_pointed_at(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # The default state path lives under a mounted data/ directory so a round outlives its
    # container. A missing directory must not surface as "unable to open database file".
    target = tmp_path / "data" / "nested" / "state.db"
    assert not target.parent.exists()

    store = SQLiteStore(str(target))
    round_ = ReviewRound(notion_page_id="page-1")
    store.save(round_)

    assert target.exists()
    assert store.get(round_.id) is not None
    store.close()


def test_a_round_survives_the_process_that_created_it(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # `watch` runs in a throwaway container: the store has to be the thing that remembers, or a
    # returned file comes back to a service that has never heard of its round.
    path = str(tmp_path / "data" / "state.db")
    first = SQLiteStore(path)
    round_ = ReviewRound(notion_page_id="page-1")
    first.save(round_)
    first.close()

    reopened = SQLiteStore(path)

    assert [r for r in reopened.list_ids()] == [round_.id]
    assert reopened.get(round_.id) is not None
    reopened.close()


def test_a_file_store_keeps_its_data_in_the_database_not_a_side_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # Write-ahead logging keeps committed rows in a -wal coordinated through shared memory, and
    # that coordination is not reliable on a bind mount: a second connection can decide it is the
    # last one and delete the -wal out from under a live writer, losing committed rounds silently.
    # No side files means there is nothing to lose that way.
    path = tmp_path / "state.db"
    store = SQLiteStore(str(path))
    store.save(ReviewRound(notion_page_id="page-1"))

    mode = store._conn.execute("pragma journal_mode").fetchone()[0]
    assert mode != "wal"
    assert not (tmp_path / "state.db-wal").exists()
    assert not (tmp_path / "state.db-shm").exists()

    # And the row is readable by an unrelated connection the moment it is committed.
    other = SQLiteStore(str(path))
    assert len(other.list_ids()) == 1
    other.close()
    store.close()
