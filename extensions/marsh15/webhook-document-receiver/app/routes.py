import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowTarget(StrictModel):
    source: Literal["configured_file"]
    file_id_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")


class WorkflowConfig(StrictModel):
    mode: Literal["generate", "edit"]
    target: WorkflowTarget | None = None

    @model_validator(mode="after")
    def validate_target(self) -> "WorkflowConfig":
        if self.mode == "edit" and self.target is None:
            raise ValueError("Edit workflows require a configured_file target")
        if self.mode == "generate" and self.target is not None:
            raise ValueError("Generate workflows cannot define an edit target")
        return self


class TemplateConfig(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    required: bool = True


class ApprovalConfig(StrictModel):
    mode: Literal["manual", "automatic"] = "manual"
    policy: Literal["ask_every_time", "approve_all"] = "ask_every_time"

    @model_validator(mode="after")
    def validate_policy(self) -> "ApprovalConfig":
        expected = "ask_every_time" if self.mode == "manual" else "approve_all"
        if self.policy != expected:
            raise ValueError(f"{self.mode} approval requires policy={expected}")
        return self


class ModelConfig(StrictModel):
    tier: Literal["turbo", "core", "pro", "max"] = "core"
    thinking_depth: Literal["fast", "balanced", "deep"] = "balanced"


class ExportConfig(StrictModel):
    format: Literal["doc", "docx"] = "docx"


class Route(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
    enabled: bool = True
    provider: Literal["generic-hmac", "github"]
    event_type: str = Field(min_length=1, max_length=128)
    payload_fields: list[str] = Field(min_length=1, max_length=100)
    workflow: WorkflowConfig
    template: TemplateConfig
    instruction: str = Field(min_length=1, max_length=10_000)
    approval: ApprovalConfig
    model: ModelConfig = Field(default_factory=ModelConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)


class RoutesFile(StrictModel):
    routes: list[Route] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_route_ids(self) -> "RoutesFile":
        ids = [route.id for route in self.routes]
        if len(ids) != len(set(ids)):
            raise ValueError("Route IDs must be unique")
        return self


class RouteRegistry:
    def __init__(self, routes: RoutesFile, version: str):
        self.routes = routes
        self.version = version

    def resolve(self, *, provider: str, event_type: str) -> Route | None:
        matches = [
            route
            for route in self.routes.routes
            if route.enabled and route.provider == provider and route.event_type == event_type
        ]
        if len(matches) > 1:
            raise RuntimeError("Multiple enabled routes match the same provider event")
        return matches[0] if matches else None


def load_routes(
    path: str | Path, *, environment: Mapping[str, str] | None = None
) -> RouteRegistry:
    route_path = Path(path)
    raw = route_path.read_bytes()
    value = yaml.safe_load(raw)
    routes = RoutesFile.model_validate(value)
    active_environment = os.environ if environment is None else environment
    for route in routes.routes:
        if route.enabled and route.workflow.target is not None:
            variable = route.workflow.target.file_id_env
            if not active_environment.get(variable):
                raise ValueError(f"Route {route.id} requires environment variable {variable}")
    return RouteRegistry(routes, hashlib.sha256(raw).hexdigest())
