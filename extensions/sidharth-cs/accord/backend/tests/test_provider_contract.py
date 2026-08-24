"""Parametrized across both concrete TranscriptProviders — this is what
actually demonstrates "the provider contract is solid" from the suite
itself (Milestone 4's own stated goal), not just prose asserting it.

Only exercises the shared TranscriptProvider Protocol shape plus the
submit()/sequence convention both concrete providers happen to share.
Provider-specific internals (RTMS's websocket handshake, Manual's lack of
one) are covered by test_rtms_provider.py and test_manual_provider.py."""

import asyncio

import pytest

from app.transcript.manual_provider import ManualTranscriptProvider
from app.transcript.provider import STATUS_NOT_STARTED, TranscriptEvent
from app.transcript.rtms_provider import RTMSTranscriptProvider
from app.transcript.vexa_provider import VexaTranscriptProvider

PROVIDER_FACTORIES = [
    ManualTranscriptProvider,
    lambda: RTMSTranscriptProvider("cid", "csecret"),
    lambda: VexaTranscriptProvider("https://vexa.example", "key"),
]
PROVIDER_IDS = ["manual", "rtms", "vexa"]


@pytest.mark.parametrize("make_provider", PROVIDER_FACTORIES, ids=PROVIDER_IDS)
def test_status_starts_not_started(make_provider):
    assert make_provider().status() == STATUS_NOT_STARTED


@pytest.mark.parametrize("make_provider", PROVIDER_FACTORIES, ids=PROVIDER_IDS)
def test_submit_yields_a_final_transcript_event(make_provider):
    async def run():
        provider = make_provider()
        await provider.start({"meeting_uuid": "u1"})
        return await provider.submit("hello from the meeting")

    event = asyncio.run(run())
    assert isinstance(event, TranscriptEvent)
    assert event.is_final is True
    assert event.text == "hello from the meeting"


@pytest.mark.parametrize("make_provider", PROVIDER_FACTORIES, ids=PROVIDER_IDS)
def test_events_stream_yields_submissions_in_order_with_increasing_sequence(make_provider):
    async def run():
        provider = make_provider()
        await provider.start({"meeting_uuid": "u1"})
        await provider.submit("first")
        await provider.submit("second")
        stream = provider.events()
        first = await anext(stream)
        second = await anext(stream)
        return first, second

    first, second = asyncio.run(run())
    assert first.text == "first"
    assert second.text == "second"
    assert second.sequence > first.sequence


@pytest.mark.parametrize("make_provider", PROVIDER_FACTORIES, ids=PROVIDER_IDS)
def test_submit_rejects_blank_text(make_provider):
    async def run():
        provider = make_provider()
        with pytest.raises(ValueError):
            await provider.submit("   ")

    asyncio.run(run())
