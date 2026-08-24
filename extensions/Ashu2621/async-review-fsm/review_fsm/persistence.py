import asyncio
from collections.abc import Callable
from typing import Protocol

from pydantic import JsonValue

from review_fsm.models import Command, ReviewEvent, ReviewSnapshot, TransitionResult


class ReviewPersistenceError(RuntimeError):
    pass


class ReviewPersistenceConflict(ReviewPersistenceError):
    pass


class ReviewPersistence(Protocol):
    async def create(self, snapshot: ReviewSnapshot) -> None: ...

    async def load(self, batch_id: str) -> ReviewSnapshot | None: ...

    async def commit(
        self,
        event: ReviewEvent,
        result: TransitionResult,
        *,
        expected_version: int,
    ) -> bool: ...


class InMemoryReviewPersistence:
    """Concurrency-safe test/reference persistence with a durable-command view."""

    def __init__(self) -> None:
        self._snapshots: dict[str, ReviewSnapshot] = {}
        self._events: dict[str, ReviewEvent] = {}
        self._commands: dict[str, Command] = {}
        self._lock = asyncio.Lock()

    async def create(self, snapshot: ReviewSnapshot) -> None:
        async with self._lock:
            if snapshot.batch_id in self._snapshots:
                raise ReviewPersistenceConflict("review batch already exists")
            self._snapshots[snapshot.batch_id] = snapshot.model_copy(deep=True)

    async def load(self, batch_id: str) -> ReviewSnapshot | None:
        async with self._lock:
            snapshot = self._snapshots.get(batch_id)
            return snapshot.model_copy(deep=True) if snapshot is not None else None

    async def commit(
        self,
        event: ReviewEvent,
        result: TransitionResult,
        *,
        expected_version: int,
    ) -> bool:
        async with self._lock:
            current = self._snapshots.get(event.batch_id)
            if current is None:
                raise ReviewPersistenceError("review batch does not exist")
            if event.event_id in self._events:
                return False
            if current.version != expected_version:
                raise ReviewPersistenceConflict("review snapshot changed before commit")
            self._events[event.event_id] = event.model_copy(deep=True)
            for command in result.commands:
                self._commands.setdefault(command.idempotency_key, command.model_copy(deep=True))
            self._snapshots[event.batch_id] = result.snapshot.model_copy(deep=True)
            return True

    async def commands(self) -> tuple[Command, ...]:
        async with self._lock:
            return tuple(command.model_copy(deep=True) for command in self._commands.values())


class ReviewRuntime:
    """Loads, reduces and atomically persists before exposing side-effect commands."""

    def __init__(
        self,
        persistence: ReviewPersistence,
        *,
        after_commit: Callable[[TransitionResult], None] | None = None,
    ) -> None:
        self._persistence = persistence
        self._after_commit = after_commit

    async def create(
        self,
        batch_id: str,
        *,
        context: dict[str, JsonValue] | None = None,
    ) -> ReviewSnapshot:
        snapshot = ReviewSnapshot(batch_id=batch_id, context=context or {})
        await self._persistence.create(snapshot)
        return snapshot

    async def load(self, batch_id: str) -> ReviewSnapshot | None:
        return await self._persistence.load(batch_id)

    async def dispatch(self, event: ReviewEvent) -> TransitionResult:
        from review_fsm.reducer import reduce

        snapshot = await self._persistence.load(event.batch_id)
        if snapshot is None:
            raise ReviewPersistenceError("review batch does not exist")
        result = reduce(snapshot, event)
        if not result.duplicate:
            committed = await self._persistence.commit(
                event,
                result,
                expected_version=snapshot.version,
            )
            if committed and self._after_commit is not None:
                self._after_commit(result)
        return result
