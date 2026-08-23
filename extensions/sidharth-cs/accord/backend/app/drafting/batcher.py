"""The batching engine (design doc §14) — turns a stream of TranscriptEvents
into well-timed SuperDocs chat calls. A call per utterance is noisy and
burns operations; a call once a minute feels laggy. Any one trigger fires a
flush of the current buffer:

  silence gap   — no new event for SILENCE_GAP_SECONDS
  size ceiling  — buffered text has reached SIZE_CEILING_CHARS
  hard max-wait — MAX_WAIT_SECONDS since the buffer's first event
  correction cue — flushes immediately, pre-empting the other triggers

Thresholds are constructor parameters, not hardcoded, specifically so tests
can use small values instead of waiting on real 3-4s/20s timers — the
scheduling logic under test is identical either way.

Note on manual entry specifically: the plan's "0-1s debounce, to catch a
same-breath continuation" for the correction trigger is an RTMS-era nuance
for continuous speech. A manual Submit is already one complete, deliberate
utterance — there's no continuation to wait for — so this flushes
immediately on a detected correction cue, no extra debounce. Everything
else (silence gap, size ceiling, max-wait) applies identically regardless
of where events came from, which is the point: the Batcher never branches
on transcript origin.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Awaitable, Callable

from app.drafting.classifier import has_flush_cue
from app.transcript.provider import TranscriptEvent

logger = logging.getLogger("batcher")

OnFlush = Callable[[list[TranscriptEvent]], Awaitable[None]]

# A sentence terminator followed by whitespace or end-of-text. Audio arrives
# in fixed-length chunks that cut wherever the clock lands, routinely
# mid-clause ("...where customers can" | "browse products, and complete" |
# "payments online."). Flushing on that boundary sends half a clause to
# SuperDocs as if it were a fact: unwritable as prose, so it burns the full
# retry budget and lands in the wrong section (a fragment has no topic to
# route on). Splitting on real sentence ends instead is what keeps one
# spoken sentence in one batch.
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")


def _split_trailing_fragment(
    batch: list[TranscriptEvent], ceiling: int
) -> tuple[list[TranscriptEvent], TranscriptEvent | None]:
    """Split a batch at its last sentence terminator: (events to flush,
    continuation to carry forward). Carries nothing when the batch already
    ends on a sentence boundary, or when the dangling fragment has itself
    grown past `ceiling` — an unpunctuated monologue must still reach the
    document rather than buffer forever."""
    # A correction is one deliberate, complete utterance and pre-empts every
    # other trigger — never hold part of it back.
    if any(e.is_correction or has_flush_cue(e.text) for e in batch):
        return batch, None

    # The dangling tail can span several events ("...customers can" +
    # "browse products, and complete"), so the split point is the last
    # terminator anywhere in the batch, not just inside the final event.
    idx = next(
        (i for i in range(len(batch) - 1, -1, -1) if _SENTENCE_END_RE.search(batch[i].text)),
        None,
    )
    if idx is None:
        # Nothing complete to deliver alongside it. Holding here would buy
        # nothing and would silently void the max-wait guarantee for speech
        # ASR returned without terminal punctuation, so ship it as-is.
        return batch, None

    text = batch[idx].text.rstrip()
    cut = list(_SENTENCE_END_RE.finditer(text))[-1].end()
    tail = [text[cut:].strip()] + [e.text.strip() for e in batch[idx + 1 :]]
    remainder = " ".join(p for p in tail if p).strip()
    if not remainder or len(remainder) >= ceiling:
        return batch, None
    flush_events = batch[:idx] + [batch[idx].model_copy(update={"text": text[:cut]})]
    return flush_events, batch[-1].model_copy(update={"text": remainder})


class Batcher:
    def __init__(
        self,
        on_flush: OnFlush,
        *,
        silence_gap_seconds: float = 3.5,
        size_ceiling_chars: int = 400,
        max_wait_seconds: float = 20.0,
        fragment_wait_seconds: float = 8.0,
    ) -> None:
        self._on_flush = on_flush
        self._silence_gap_seconds = silence_gap_seconds
        self._size_ceiling_chars = size_ceiling_chars
        self._max_wait_seconds = max_wait_seconds
        # How long a held-back sentence fragment waits for the continuation
        # that completes it. Must exceed the audio chunk interval (6s) or the
        # deadline expires before the next chunk can possibly arrive. This is
        # the ONLY deadline the fragment path uses — max_wait stays untouched,
        # so normal batching keeps its proven timing.
        self._fragment_wait_seconds = fragment_wait_seconds

        self._buffer: list[TranscriptEvent] = []
        self._lock = asyncio.Lock()
        self._silence_task: asyncio.Task | None = None
        self._maxwait_task: asyncio.Task | None = None
        # Strong references to dispatched flushes. asyncio only holds a weak
        # reference to a running task, so without this the garbage collector
        # is free to cancel a batch mid-flight.
        self._flush_tasks: set[asyncio.Task] = set()

    async def add(self, event: TranscriptEvent) -> None:
        if not event.is_final:
            return  # interim ASR results are ignored for batching, per design

        flush_now = False
        async with self._lock:
            self._buffer.append(event)
            if len(self._buffer) == 1:
                self._maxwait_task = asyncio.create_task(
                    self._flush_after(self._max_wait_seconds)
                )

            if self._silence_task is not None:
                self._silence_task.cancel()

            buffered_chars = sum(len(e.text) for e in self._buffer)
            if has_flush_cue(event.text) or event.is_correction or buffered_chars >= self._size_ceiling_chars:
                flush_now = True
            else:
                self._silence_task = asyncio.create_task(
                    self._flush_after(self._silence_gap_seconds)
                )

        if flush_now:
            # Dispatched, never awaited. `add()` runs on the transcript
            # consumer loop, and _flush() ultimately runs the entire drafting
            # pipeline — every SuperDocs round trip for the batch, 30-60s.
            # Awaiting it here stopped the consumer pulling events for that
            # whole time: confirmed live, the backend logged nothing after
            # the utterance carrying the cue (seq=9, "Actually, no make it.")
            # until drafting finished, and the panel sat frozen mid-meeting
            # while the speaker kept talking.
            #
            # Ordering is still guaranteed without the await: _handle_batch
            # serialises on MeetingSession._inflight_lock, and asyncio locks
            # grant in FIFO order, so batches are drafted in the order they
            # were flushed regardless of who awaits them.
            batch = await self._take_batch()
            if batch:
                self._dispatch_flush(batch)

    def _dispatch_flush(self, batch: list[TranscriptEvent]) -> None:
        task = asyncio.create_task(self._on_flush(batch))
        self._flush_tasks.add(task)

        def _done(finished: asyncio.Task) -> None:
            self._flush_tasks.discard(finished)
            if finished.cancelled():
                return
            exc = finished.exception()
            if exc is not None:
                # Nothing awaits this task, so an exception here would
                # otherwise surface only as "Task exception was never
                # retrieved" at interpreter shutdown, long after the batch
                # it lost.
                logger.error("dispatched flush failed: %r", exc, exc_info=exc)

        task.add_done_callback(_done)

    async def _flush_after(self, delay: float, *, allow_carry: bool = True) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        await self._flush(allow_carry=allow_carry)

    async def _flush(self, *, allow_carry: bool = True) -> None:
        """Take the buffer and hand it to the flush callback, awaiting it."""
        batch = await self._take_batch(allow_carry=allow_carry)
        if batch:
            await self._on_flush(batch)

    async def _take_batch(self, *, allow_carry: bool = True) -> list[TranscriptEvent]:
        """Detach the current buffer and return it as a batch.

        Split out from _flush so a caller can claim the batch under the lock
        and hand the SLOW part off separately. Dispatching the whole of
        _flush() instead let the next add() reach the buffer first, and two
        utterances that should have been two batches were silently merged
        into one — content preserved, but batch boundaries no longer the
        ones the batching rules decided. `allow_carry=False` ships
        the buffer as-is: it is how the fragment deadline gives up waiting
        for a continuation that never came (the speaker stopped mid-
        sentence), so a trailing fragment is never held forever."""
        async with self._lock:
            if not self._buffer:
                return
            batch = self._buffer
            self._buffer = []
            # Cancel the sibling timer, never the task currently running this
            # _flush() call itself — when a timer fires, _flush() runs *as*
            # _silence_task or _maxwait_task, and both were still referenced
            # here (cleared only below). Cancelling one's own task schedules
            # a CancelledError for the next await — which, on a real
            # SuperDocs call, lands inside httpx and silently kills the
            # batch with no exception `_handle_batch` ever sees (BaseException,
            # not Exception). Found via live verification; every mocked test
            # passed because fakes have no real await for the cancellation
            # to interrupt.
            current = asyncio.current_task()
            for task in (self._silence_task, self._maxwait_task):
                if task is not None and task is not current:
                    task.cancel()
            self._silence_task = None
            self._maxwait_task = None

            if allow_carry:
                batch, carry = _split_trailing_fragment(batch, self._size_ceiling_chars)
                if carry is not None:
                    # Hold the dangling clause for its continuation. The
                    # fragment deadline is the buffer's only timer now; it
                    # ships the fragment as-is if nothing follows.
                    self._buffer.insert(0, carry)
                    self._maxwait_task = asyncio.create_task(
                        self._flush_after(self._fragment_wait_seconds, allow_carry=False)
                    )
        return batch

    # A pause only closes a batch that has enough in it to be worth drafting.
    # Without this, every gap between phrases became its own batch: a live run
    # produced "We need" / "payments online." / "The deliverables should
    # include the website." as three separate drafting operations, and the
    # document came back with Deliverables truncated to one clause, the budget
    # correction split across two batches so it never applied, and Assumptions
    # content duplicated into Next Steps. Speaking deliberately made it worse,
    # which is exactly backwards.
    _PAUSE_MIN_CHARS = 180

    async def flush_on_pause(self) -> None:
        """Close the current batch because the speaker actually paused.

        The silence-gap timer measures time between chunk ARRIVALS, which on
        the audio path is a fixed 6s clock — so a real pause never opens it and
        batches close on the 15s ceiling instead, cutting mid-topic. The pause
        is only detectable in the samples, so the audio route calls this when
        it sees one. Same dispatch as any other flush: ingestion never waits on
        drafting.
        """
        async with self._lock:
            buffered = sum(len(e.text) for e in self._buffer)
        if buffered < self._PAUSE_MIN_CHARS:
            # Too little to draft. Let the silence gap, the ceiling or the next
            # pause close it once there is a real unit of meaning here.
            return
        batch = await self._take_batch()
        if batch:
            self._dispatch_flush(batch)

    async def drain(self) -> None:
        """Wait for every dispatched flush to finish.

        Flushes are fire-and-forget so that ingestion never blocks on
        drafting, which leaves callers that genuinely need completion — a
        clean shutdown, and any test asserting on the result — with nothing
        to await. This is that handle.
        """
        while self._flush_tasks:
            await asyncio.gather(*tuple(self._flush_tasks), return_exceptions=True)

    async def clear(self) -> None:
        """Cancel all pending timers and discard the buffer.  Used by
        MeetingSession.reset() — must be called under _inflight_lock so
        no flush races with the clear.  Reuses the same self-cancellation-
        safe pattern as _flush."""
        async with self._lock:
            current = asyncio.current_task()
            for task in (self._silence_task, self._maxwait_task):
                if task is not None and task is not current:
                    task.cancel()
            self._silence_task = None
            self._maxwait_task = None
            self._buffer = []
