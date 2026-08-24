"""Locks in the Batcher's flush triggers. Uses small real thresholds
(milliseconds, not the production 3.5s/20s) so these run fast without
mocking asyncio's clock — the scheduling logic under test is identical
either way."""

import asyncio

from app.drafting.batcher import Batcher
from app.transcript.provider import TranscriptEvent


def _event(text: str, sequence: int, is_final: bool = True) -> TranscriptEvent:
    return TranscriptEvent(text=text, timestamp=0.0, sequence=sequence, is_final=is_final)


class _Recorder:
    """A tiny async-callable spy — records each flushed batch.

    The `asyncio.sleep(0)` is load-bearing, not decoration: a coroutine with
    no real internal suspension point never gives the event loop a chance to
    deliver a pending cancellation into it, which is exactly how a self-
    cancellation bug in Batcher._flush hid behind this whole suite until a
    live SuperDocs call (a genuine suspension point) exposed it. This keeps
    the fake honest about that distinction instead of only real I/O being
    able to catch it."""

    def __init__(self) -> None:
        self.batches: list[list[TranscriptEvent]] = []

    async def __call__(self, batch: list[TranscriptEvent]) -> None:
        await asyncio.sleep(0)
        self.batches.append(batch)


def test_flushes_on_size_ceiling():
    recorder = _Recorder()

    async def run():
        batcher = Batcher(
            recorder, silence_gap_seconds=10, size_ceiling_chars=10, max_wait_seconds=10
        )
        await batcher.add(_event("x" * 11, sequence=1))
        # flushes are dispatched now, not awaited by add()
        await batcher.drain()

    asyncio.run(run())
    assert len(recorder.batches) == 1
    assert len(recorder.batches[0]) == 1


def test_flushes_immediately_on_correction_cue():
    recorder = _Recorder()

    async def run():
        batcher = Batcher(
            recorder, silence_gap_seconds=10, size_ceiling_chars=10_000, max_wait_seconds=10
        )
        await batcher.add(_event("No, the date should be the 15th.", sequence=1))
        # flushes are dispatched now, not awaited by add()
        await batcher.drain()

    asyncio.run(run())
    assert len(recorder.batches) == 1


def test_flushes_on_silence_gap():
    recorder = _Recorder()

    async def run():
        batcher = Batcher(
            recorder, silence_gap_seconds=0.05, size_ceiling_chars=10_000, max_wait_seconds=10
        )
        await batcher.add(_event("The client is Acme Corp.", sequence=1))
        assert recorder.batches == []  # not yet — waiting on the silence gap
        await asyncio.sleep(0.15)

    asyncio.run(run())
    assert len(recorder.batches) == 1


def test_flushes_on_max_wait_even_if_silence_gap_keeps_resetting():
    recorder = _Recorder()

    async def run():
        batcher = Batcher(
            recorder, silence_gap_seconds=0.05, size_ceiling_chars=10_000, max_wait_seconds=0.12
        )
        # Keep the silence timer from ever firing by adding a new event
        # faster than the silence gap, for longer than max_wait.
        for i in range(6):
            await batcher.add(_event("word ", sequence=i))
            await asyncio.sleep(0.03)

    asyncio.run(run())
    assert len(recorder.batches) >= 1  # max-wait forced a flush despite continuous input


def test_multiple_events_accumulate_into_one_batch():
    recorder = _Recorder()

    async def run():
        batcher = Batcher(
            recorder, silence_gap_seconds=0.05, size_ceiling_chars=10_000, max_wait_seconds=10
        )
        await batcher.add(_event("First sentence.", sequence=1))
        await batcher.add(_event("Second sentence.", sequence=2))
        await asyncio.sleep(0.15)

    asyncio.run(run())
    assert len(recorder.batches) == 1
    assert len(recorder.batches[0]) == 2


def test_interim_events_are_ignored():
    recorder = _Recorder()

    async def run():
        batcher = Batcher(
            recorder, silence_gap_seconds=0.05, size_ceiling_chars=10, max_wait_seconds=10
        )
        await batcher.add(_event("x" * 20, sequence=1, is_final=False))
        await asyncio.sleep(0.15)

    asyncio.run(run())
    assert recorder.batches == []


# --- a cue-triggered flush must not stall transcript ingestion -------------
#
# Batcher.add() runs on the transcript consumer loop and _flush() ultimately
# runs the whole drafting pipeline. Awaiting the flush inside add() stopped
# the consumer pulling events for the entire batch — confirmed live, the
# backend logged nothing after seq=9 ("Actually, no make it.") until drafting
# finished, and the panel sat frozen mid-meeting while the speaker kept going.

def test_a_cue_flush_does_not_block_the_caller():
    """add() must return promptly even when drafting takes a long time."""
    import asyncio, time
    from app.drafting.batcher import Batcher

    started = asyncio.Event()

    async def slow_draft(batch):
        started.set()
        await asyncio.sleep(0.6)          # stands in for SuperDocs round trips

    async def run():
        b = Batcher(slow_draft, silence_gap_seconds=30, max_wait_seconds=60,
                    size_ceiling_chars=10_000)
        t0 = time.monotonic()
        await b.add(_event("Actually, no make it $55,000.", 1))
        elapsed = time.monotonic() - t0
        # The consumer keeps going while drafting runs.
        await b.add(_event("The deliverables include analytics.", 2))
        await asyncio.wait_for(started.wait(), timeout=1.0)
        await asyncio.sleep(0.8)          # let the dispatched flush finish
        return elapsed

    elapsed = asyncio.run(run())
    assert elapsed < 0.3, f"add() blocked for {elapsed:.2f}s on the flush"


def test_a_failing_flush_is_logged_and_never_lost_silently():
    """Nothing awaits a dispatched flush, so its errors need a home."""
    import asyncio, logging
    from app.drafting.batcher import Batcher

    async def boom(batch):
        raise RuntimeError("SuperDocs exploded")

    async def run():
        b = Batcher(boom, silence_gap_seconds=30, max_wait_seconds=60,
                    size_ceiling_chars=10_000)
        await b.add(_event("Actually, no make it $55,000.", 1))
        await asyncio.sleep(0.2)

    logger = logging.getLogger("batcher")
    seen = []
    handler = logging.Handler()
    handler.emit = lambda record: seen.append(record.getMessage())
    logger.addHandler(handler)
    try:
        asyncio.run(run())          # must not raise
    finally:
        logger.removeHandler(handler)
    assert any("dispatched flush failed" in m for m in seen), seen
