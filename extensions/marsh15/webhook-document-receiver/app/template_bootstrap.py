import mimetypes
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings
from app.routes import load_routes


class TemplateBootstrapError(RuntimeError):
    """A safe, actionable template bootstrap failure."""


def _template_entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
        return payload
    if isinstance(payload, dict):
        for key in ("templates", "items", "data"):
            candidate = payload.get(key)
            if isinstance(candidate, list) and all(
                isinstance(item, dict) for item in candidate
            ):
                return candidate
            if isinstance(candidate, dict):
                for nested_key in ("templates", "items"):
                    nested = candidate.get(nested_key)
                    if isinstance(nested, list) and all(
                        isinstance(item, dict) for item in nested
                    ):
                        return nested
    raise TemplateBootstrapError("SuperDocs returned an unrecognized template-list response")


def _known_template_names(entries: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for entry in entries:
        for key in ("name", "title", "filename", "original_filename", "originalFilename"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                path = Path(value.strip())
                names.add(path.name.casefold())
                names.add(path.stem.casefold())
    return names


def required_template_files(settings: Settings) -> dict[str, Path]:
    registry = load_routes(settings.routes_path)
    required_names = {
        route.template.name
        for route in registry.routes.routes
        if route.enabled and route.template.required
    }
    template_dir = Path(settings.templates_path)
    files: dict[str, Path] = {}
    for name in sorted(required_names):
        matches = [path for path in template_dir.glob(f"{name}.*") if path.is_file()]
        if len(matches) != 1:
            raise TemplateBootstrapError(
                f"Template {name!r} must have exactly one local file in {template_dir}"
            )
        files[name] = matches[0]
    return files


def bootstrap_templates(
    settings: Settings, *, client: httpx.Client | None = None
) -> list[str]:
    """Upload required route templates that are not already present.

    Returns the names uploaded during this invocation.
    """

    files = required_template_files(settings)
    owns_client = client is None
    active_client = client or httpx.Client(
        base_url=settings.superdocs_base_url,
        timeout=settings.superdocs_timeout_seconds,
        headers={"Authorization": f"Bearer {settings.superdocs_api_key.get_secret_value()}"},
    )
    try:
        response = active_client.get("/v1/templates")
        try:
            response.raise_for_status()
            entries = _template_entries(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise TemplateBootstrapError("Unable to list SuperDocs templates") from exc

        known = _known_template_names(entries)
        uploaded: list[str] = []
        for name, path in files.items():
            if name.casefold() in known or path.name.casefold() in known:
                continue
            media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            with path.open("rb") as handle:
                upload = active_client.post(
                    "/v1/templates/upload",
                    files={"file": (path.name, handle, media_type)},
                )
            try:
                upload.raise_for_status()
            except httpx.HTTPError as exc:
                raise TemplateBootstrapError(f"Unable to upload template {name!r}") from exc
            uploaded.append(name)
            known.update({name.casefold(), path.name.casefold()})
        return uploaded
    finally:
        if owns_client:
            active_client.close()
