from __future__ import annotations

from pathlib import Path

import pytest

from notion_review.clients import build_boards, build_channel
from notion_review.config import Config, ConfigError
from notion_review.notion import FakeNotionClient
from notion_review.roundtrip.delivery import FolderDelivery, NotionRowDelivery
from notion_review.roundtrip.intake import FolderIntake, NotionRowIntake
from notion_review.roundtrip.requests import create_request_database


def test_defaults_are_fake_and_frugal() -> None:
    cfg = Config.from_env({})
    assert cfg.provider == "fake"
    assert cfg.superdocs_base_url == "https://api.superdocs.app"
    assert cfg.sections_per_op == 25
    assert cfg.database_url is None


def test_live_requires_credentials() -> None:
    cfg = Config.from_env({"PROVIDER": "live"})
    with pytest.raises(ConfigError) as excinfo:
        cfg.require_live()
    assert "SUPERDOCS_API_KEY" in str(excinfo.value)
    assert "NOTION_TOKEN" in str(excinfo.value)


def test_live_with_credentials_validates() -> None:
    cfg = Config.from_env(
        {"PROVIDER": "live", "SUPERDOCS_API_KEY": "sk_x", "NOTION_TOKEN": "ntn_y"}
    )
    assert cfg.require_live() is cfg


def test_fake_never_requires_credentials() -> None:
    # require_live is a no-op for the fake provider, so a keyless run is always valid.
    assert Config.from_env({}).require_live().provider == "fake"


def test_invalid_provider_rejected() -> None:
    with pytest.raises(ConfigError):
        Config.from_env({"PROVIDER": "sqlite"})


def test_sample_size_parsed() -> None:
    assert Config.from_env({"SAMPLE_SIZE": "3"}).sample_size == 3
    assert Config.from_env({}).sample_size is None


def test_config_is_frozen() -> None:
    cfg = Config.from_env({})
    with pytest.raises(Exception):  # noqa: B017 - pydantic frozen raises ValidationError
        cfg.provider = "live"  # type: ignore[misc]


def test_the_handoff_defaults_to_notion_and_only_accepts_the_two_channels() -> None:
    assert Config.from_env({}).handoff == "notion"
    assert Config.from_env({"HANDOFF": "folder"}).handoff == "folder"
    with pytest.raises(ConfigError):
        Config.from_env({"HANDOFF": "email"})


def test_the_channel_is_a_pair_and_falls_back_to_folders_without_a_requests_database(
    tmp_path: Path,
) -> None:
    # Both halves come from one decision: a channel that sends but cannot receive is a promise
    # the round-trip cannot keep.
    notion, _ = FakeNotionClient.build_sample()
    inbox, outbox = str(tmp_path / "in"), str(tmp_path / "out")

    create_request_database(notion, parent_page_id="page")  # shared with the integration
    cfg = Config.from_env({})
    on_rows = build_channel(
        cfg, notion, inbox=inbox, outbox=outbox, boards=build_boards(cfg, notion)
    )
    assert isinstance(on_rows[0], NotionRowIntake) and isinstance(on_rows[1], NotionRowDelivery)

    # No board shared with the integration, so the folder channel is what is left.
    bare, _ = FakeNotionClient.build_sample()
    without_db = build_channel(
        cfg, bare, inbox=inbox, outbox=outbox, boards=build_boards(cfg, bare)
    )
    assert isinstance(without_db[0], FolderIntake) and isinstance(without_db[1], FolderDelivery)

    folders = Config.from_env({"HANDOFF": "folder"})
    asked_for_folders = build_channel(
        folders, notion, inbox=inbox, outbox=outbox, boards=build_boards(folders, notion)
    )
    assert isinstance(asked_for_folders[0], FolderIntake)
    assert isinstance(asked_for_folders[1], FolderDelivery)
