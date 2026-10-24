from pathlib import Path

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.config import Settings
from app.template_bootstrap import (
    TemplateBootstrapError,
    bootstrap_templates,
    required_template_files,
)


def settings(routes_path: Path, templates_path: Path) -> Settings:
    return Settings(
        superdocs_api_key=SecretStr("sk_test"),
        webhook_secret=SecretStr("s" * 32),
        github_webhook_secret=SecretStr("g" * 32),
        management_token=SecretStr("m" * 32),
        routes_path=str(routes_path),
        templates_path=str(templates_path),
    )


def write_routes(path: Path) -> None:
    path.write_text(
        """
routes:
  - id: incident-report
    provider: generic-hmac
    event_type: incident.resolved
    payload_fields: [type]
    workflow: {mode: generate}
    template: {name: incident-report, required: true}
    instruction: Create a report
    approval: {mode: manual, policy: ask_every_time}
  - id: release-notes
    provider: github
    event_type: release.published
    payload_fields: [action]
    workflow: {mode: generate}
    template: {name: release-notes, required: true}
    instruction: Create release notes
    approval: {mode: automatic, policy: approve_all}
""",
        encoding="utf-8",
    )


@respx.mock
def test_uploads_only_missing_required_templates(tmp_path: Path) -> None:
    routes_path = tmp_path / "routes.yaml"
    templates_path = tmp_path / "templates"
    templates_path.mkdir()
    write_routes(routes_path)
    (templates_path / "incident-report.html").write_text("<p>incident</p>", encoding="utf-8")
    (templates_path / "release-notes.html").write_text("<p>release</p>", encoding="utf-8")

    base = "https://api.superdocs.app"
    respx.get(f"{base}/v1/templates").mock(
        return_value=httpx.Response(
            200, json={"data": {"templates": [{"filename": "incident-report.html"}]}}
        )
    )
    upload = respx.post(f"{base}/v1/templates/upload").mock(
        return_value=httpx.Response(201, json={"id": "template_2"})
    )

    uploaded = bootstrap_templates(settings(routes_path, templates_path))

    assert uploaded == ["release-notes"]
    assert upload.call_count == 1
    request = upload.calls[0].request
    assert b'release-notes.html' in request.content
    assert request.headers["authorization"] == "Bearer sk_test"


@respx.mock
def test_is_idempotent_when_all_templates_exist(tmp_path: Path) -> None:
    routes_path = tmp_path / "routes.yaml"
    templates_path = tmp_path / "templates"
    templates_path.mkdir()
    write_routes(routes_path)
    (templates_path / "incident-report.html").write_text("<p>incident</p>", encoding="utf-8")
    (templates_path / "release-notes.html").write_text("<p>release</p>", encoding="utf-8")

    base = "https://api.superdocs.app"
    respx.get(f"{base}/v1/templates").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {"name": "incident-report"},
                    {"originalFilename": "release-notes.html"},
                ]
            },
        )
    )
    upload = respx.post(f"{base}/v1/templates/upload").mock(
        return_value=httpx.Response(201)
    )

    assert bootstrap_templates(settings(routes_path, templates_path)) == []
    assert upload.call_count == 0


def test_missing_or_ambiguous_local_template_fails_before_network(tmp_path: Path) -> None:
    routes_path = tmp_path / "routes.yaml"
    templates_path = tmp_path / "templates"
    templates_path.mkdir()
    write_routes(routes_path)
    (templates_path / "incident-report.html").write_text("<p>incident</p>", encoding="utf-8")

    with pytest.raises(TemplateBootstrapError, match="release-notes"):
        required_template_files(settings(routes_path, templates_path))


@respx.mock
def test_unknown_list_shape_fails_closed(tmp_path: Path) -> None:
    routes_path = tmp_path / "routes.yaml"
    templates_path = tmp_path / "templates"
    templates_path.mkdir()
    write_routes(routes_path)
    (templates_path / "incident-report.html").write_text("<p>incident</p>", encoding="utf-8")
    (templates_path / "release-notes.html").write_text("<p>release</p>", encoding="utf-8")
    respx.get("https://api.superdocs.app/v1/templates").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )

    with pytest.raises(TemplateBootstrapError, match="unrecognized"):
        bootstrap_templates(settings(routes_path, templates_path))
