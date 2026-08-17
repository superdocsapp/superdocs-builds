from dataclasses import dataclass
from pathlib import Path

import yaml

from app.gateway.config import gateway_settings


@dataclass(frozen=True)
class ToolPolicy:
    allowed_tools: frozenset[str]

    def is_allowed(self, tool: str) -> bool:
        return tool in self.allowed_tools


@dataclass(frozen=True)
class SensitivePolicy:
    enabled: bool
    action: str


@dataclass(frozen=True)
class GatewayPolicyConfig:
    version: int
    tool_policy: ToolPolicy
    sensitive_policy: SensitivePolicy
    quotas: dict[str, int]
    audit_enabled: bool
    audit_include_cost: bool
    audit_store_document_content: bool


def load_gateway_policy(path: Path | None = None) -> GatewayPolicyConfig:
    policy_path = path or gateway_settings.gateway_policy_file
    if not policy_path.is_file():
        raise FileNotFoundError(f"Gateway policy file not found: {policy_path}")

    with policy_path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file)

    if not isinstance(raw, dict):
        raise ValueError("Gateway policy must contain a YAML object.")

    version = raw.get("version")
    if not isinstance(version, int):
        raise ValueError("Gateway policy 'version' must be an integer.")

    gateway = raw.get("gateway", {})
    if not isinstance(gateway, dict):
        raise ValueError("Gateway policy 'gateway' must be an object.")

    tools = gateway.get("tools", {})
    if not isinstance(tools, dict):
        raise ValueError("Gateway policy 'tools' must be an object.")

    allowed = tools.get("allowed", [])
    if not isinstance(allowed, list) or not allowed:
        raise ValueError("Gateway policy must allow at least one tool.")

    sensitive = gateway.get("sensitive_content", {})
    if not isinstance(sensitive, dict):
        raise ValueError("Gateway policy 'sensitive_content' must be an object.")

    sensitive_enabled = bool(sensitive.get("enabled", False))
    sensitive_action = str(sensitive.get("action", "block")).lower()
    if sensitive_action not in {"block", "mask"}:
        raise ValueError("Sensitive-content action must be 'block' or 'mask'.")

    quotas_config = gateway.get("quotas", {})
    if not isinstance(quotas_config, dict):
        raise ValueError("Gateway policy 'quotas' must be an object.")

    quotas: dict[str, int] = {}
    for team, config in quotas_config.items():
        if not isinstance(config, dict):
            raise ValueError(f"Quota configuration for team '{team}' must be an object.")
        limit = config.get("limit")
        if not isinstance(limit, int) or limit < 0:
            raise ValueError(f"Quota limit for team '{team}' must be a non-negative integer.")
        quotas[str(team)] = limit

    audit = gateway.get("audit", {})
    if not isinstance(audit, dict):
        raise ValueError("Gateway policy 'audit' must be an object.")

    return GatewayPolicyConfig(
        version=version,
        tool_policy=ToolPolicy(frozenset(str(tool) for tool in allowed)),
        sensitive_policy=SensitivePolicy(sensitive_enabled, sensitive_action),
        quotas=quotas,
        audit_enabled=bool(audit.get("enabled", True)),
        audit_include_cost=bool(audit.get("include_cost", True)),
        audit_store_document_content=bool(audit.get("store_document_content", False)),
    )


DEFAULT_GATEWAY_POLICY = load_gateway_policy()
