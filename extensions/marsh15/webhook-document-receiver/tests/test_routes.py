from pathlib import Path

import pytest
from pydantic import ValidationError

from app.routes import load_routes

ROUTES_PATH = Path(__file__).parents[1] / "routes" / "routes.yaml"


def test_loads_enabled_routes_and_stable_version() -> None:
    first = load_routes(ROUTES_PATH, environment={})
    second = load_routes(ROUTES_PATH, environment={})

    incident = first.resolve(provider="generic-hmac", event_type="incident.resolved")
    assert incident is not None
    assert incident.approval.mode == "manual"
    assert incident.export.format == "docx"
    assert first.version == second.version


def test_rejects_arbitrary_url_document_source(tmp_path: Path) -> None:
    path = tmp_path / "routes.yaml"
    path.write_text(
        """
routes:
  - id: unsafe
    provider: generic-hmac
    event_type: unsafe.event
    payload_fields: [type]
    workflow:
      mode: edit
      target:
        source: event_url
        file_id_env: TARGET_FILE_ID
    template: {name: unsafe}
    instruction: Unsafe
    approval: {mode: manual, policy: ask_every_time}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="configured_file"):
        load_routes(path, environment={"TARGET_FILE_ID": "file_1"})


def test_edit_route_requires_configured_target_environment(tmp_path: Path) -> None:
    path = tmp_path / "routes.yaml"
    path.write_text(
        """
routes:
  - id: edit-status
    provider: generic-hmac
    event_type: project.changed
    payload_fields: [type]
    workflow:
      mode: edit
      target:
        source: configured_file
        file_id_env: PROJECT_STATUS_FILE_ID
    template: {name: project-status}
    instruction: Update status
    approval: {mode: manual, policy: ask_every_time}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="PROJECT_STATUS_FILE_ID"):
        load_routes(path, environment={})
