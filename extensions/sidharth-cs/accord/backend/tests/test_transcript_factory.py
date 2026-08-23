"""Locks in provider selection — the one deliberate branch point Milestones
4/6 add (create_transcript_provider), and the config-level half of
"capability detection": rtms requested but not actually configured falls
back rather than ever attempting a connection that's guaranteed to fail;
vexa requested but not configured still constructs (the provider's own
begin_listening degrades honestly — see factory.py's comment)."""

from app.core.config import Settings
from app.transcript.factory import create_transcript_provider
from app.transcript.manual_provider import ManualTranscriptProvider
from app.transcript.rtms_provider import RTMSTranscriptProvider
from app.transcript.vexa_provider import VexaTranscriptProvider


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_default_is_vexa():
    provider = create_transcript_provider(_settings())
    assert isinstance(provider, VexaTranscriptProvider)


def test_explicit_vexa_is_vexa():
    provider = create_transcript_provider(
        _settings(transcript_provider="vexa", vexa_api_base_url="https://vexa.example", vexa_api_key="k")
    )
    assert isinstance(provider, VexaTranscriptProvider)


def test_vexa_missing_config_still_constructs_vexa():
    # Not a factory-time fallback: identity stays "vexa", and the provider
    # reports degraded at begin_listening while submit() stays open.
    provider = create_transcript_provider(_settings(transcript_provider="vexa"))
    assert isinstance(provider, VexaTranscriptProvider)


def test_explicit_manual_is_manual():
    provider = create_transcript_provider(_settings(transcript_provider="manual"))
    assert isinstance(provider, ManualTranscriptProvider)


def test_rtms_with_both_secrets_present_is_rtms():
    provider = create_transcript_provider(
        _settings(
            transcript_provider="rtms",
            zoom_client_id="cid",
            zoom_client_secret="csecret",
        )
    )
    assert isinstance(provider, RTMSTranscriptProvider)


def test_rtms_missing_client_id_falls_back_to_manual(caplog):
    provider = create_transcript_provider(
        _settings(transcript_provider="rtms", zoom_client_id="", zoom_client_secret="csecret")
    )
    assert isinstance(provider, ManualTranscriptProvider)
    assert "falling back to ManualTranscriptProvider" in caplog.text


def test_rtms_missing_client_secret_falls_back_to_manual(caplog):
    provider = create_transcript_provider(
        _settings(transcript_provider="rtms", zoom_client_id="cid", zoom_client_secret="")
    )
    assert isinstance(provider, ManualTranscriptProvider)
    assert "falling back to ManualTranscriptProvider" in caplog.text


def test_unrecognized_value_falls_back_to_manual_and_does_not_crash(caplog):
    provider = create_transcript_provider(_settings(transcript_provider="something-else"))
    assert isinstance(provider, ManualTranscriptProvider)
    assert "not recognized" in caplog.text
