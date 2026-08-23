"""Direct unit coverage of ManualTranscriptProvider — previously only
exercised indirectly through test_session.py's drafting-pipeline tests.
Milestone 4 backfill: this provider is one half of the "provider contract
is solid" claim (see test_provider_contract.py for the shared half)."""

import asyncio

import pytest

from app.transcript.manual_provider import ManualTranscriptProvider
from app.transcript.provider import STATUS_LIVE, STATUS_NOT_STARTED, STATUS_STOPPED


def test_status_starts_not_started():
    p = ManualTranscriptProvider()
    assert p.status() == STATUS_NOT_STARTED


def test_start_moves_straight_to_live():
    async def run():
        p = ManualTranscriptProvider()
        await p.start({"meeting_uuid": "u1"})
        return p

    p = asyncio.run(run())
    assert p.status() == STATUS_LIVE


def test_stop_moves_to_stopped():
    async def run():
        p = ManualTranscriptProvider()
        await p.start({"meeting_uuid": "u1"})
        await p.stop()
        return p

    p = asyncio.run(run())
    assert p.status() == STATUS_STOPPED


def test_submit_rejects_blank_text():
    async def run():
        p = ManualTranscriptProvider()
        with pytest.raises(ValueError):
            await p.submit("   ")

    asyncio.run(run())


def test_submit_sequence_numbers_increase_and_events_come_back_in_order():
    async def run():
        p = ManualTranscriptProvider()
        await p.start({"meeting_uuid": "u1"})
        first = await p.submit("first thing said")
        second = await p.submit("second thing said", speaker="Alice")

        stream = p.events()
        yielded_first = await anext(stream)
        yielded_second = await anext(stream)
        return first, second, yielded_first, yielded_second

    first, second, yielded_first, yielded_second = asyncio.run(run())
    assert first.sequence == 1
    assert second.sequence == 2
    assert yielded_first.text == "first thing said"
    assert yielded_second.text == "second thing said"
    assert yielded_second.speaker == "Alice"
    assert yielded_first.is_final and yielded_second.is_final
