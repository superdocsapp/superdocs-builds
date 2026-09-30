from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any

import yaml

_TIER_ORDERINGS: dict[str, dict[str, int]] = {
    "model_tier": {"standard": 0, "pro": 1, "max": 2},
}


@dataclass(frozen=True)
class ArgRule:
    mode: str  # "force", "deny", "max"
    value: Any


@dataclass(frozen=True)
class ScanConfig:
    rules: tuple[str, ...] = ()
    on_match: str = "warn"
    egress: bool = False


@dataclass(frozen=True)
class TeamPolicy:
    name: str
    token_hash: str
    allow_tools: frozenset[str] = frozenset()
    deny_tools: frozenset[str] = frozenset()
    arg_rules: tuple[tuple[str, ArgRule], ...] = ()
    scan_on_match: str | None = None
    monthly_edits: int | None = None


@dataclass(frozen=True)
class Policy:
    upstream_url: str
    upstream_key: str
    default_deny_tools: frozenset[str] = frozenset()
    default_arg_rules: tuple[tuple[str, ArgRule], ...] = ()
    default_scan: ScanConfig | None = None
    teams: tuple[TeamPolicy, ...] = ()

    def identify(self, token: str) -> TeamPolicy | None:
        h = hash_token(token)
        for team in self.teams:
            if team.token_hash == h:
                return team
        return None

    def is_tool_allowed(self, team: TeamPolicy, tool_name: str) -> bool:
        if tool_name in (self.default_deny_tools | team.deny_tools):
            return False
        if "*" in team.allow_tools:
            return True
        return tool_name in team.allow_tools

    def permitted_tools(self, team: TeamPolicy, all_tool_names: list[str]) -> list[str]:
        return [n for n in all_tool_names if self.is_tool_allowed(team, n)]

    def apply_arg_rules(
        self, team: TeamPolicy, tool_name: str, arguments: dict
    ) -> tuple[list[str], str | None]:
        rules = dict(self.default_arg_rules)
        rules.update(dict(team.arg_rules))

        rewrites: list[str] = []
        for key, rule in rules.items():
            if "." in key:
                qtool, arg_name = key.split(".", 1)
                if qtool != tool_name:
                    continue
            else:
                arg_name = key

            if rule.mode == "deny":
                if arg_name in arguments and arguments[arg_name] == rule.value:
                    return [], f"argument '{arg_name}={rule.value}' is denied"

            elif rule.mode == "max":
                if arg_name in arguments and _exceeds_max(
                    arg_name, arguments[arg_name], rule.value
                ):
                    return [], (
                        f"argument '{arg_name}={arguments[arg_name]}' exceeds max '{rule.value}'"
                    )

            elif rule.mode == "force" and arguments.get(arg_name) != rule.value:
                arguments[arg_name] = rule.value
                rewrites.append(f"{arg_name}={rule.value}")

        return rewrites, None

    def get_scan_config(self, team: TeamPolicy) -> ScanConfig | None:
        if self.default_scan is None:
            return None
        if team.scan_on_match is not None:
            return ScanConfig(
                rules=self.default_scan.rules,
                on_match=team.scan_on_match,
                egress=self.default_scan.egress,
            )
        return self.default_scan


def _exceeds_max(arg_name: str, value: Any, max_value: Any) -> bool:
    ordering = _TIER_ORDERINGS.get(arg_name)
    if ordering is not None:
        v_rank = ordering.get(str(value))
        m_rank = ordering.get(str(max_value))
        if v_rank is None or m_rank is None:
            return True
        return v_rank > m_rank
    try:
        return float(value) > float(max_value)
    except (ValueError, TypeError):
        return True


def hash_token(token: str) -> str:
    return f"sha256:{hashlib.sha256(token.encode()).hexdigest()}"


def _parse_arg_rules(raw: dict) -> tuple[tuple[str, ArgRule], ...]:
    rules: list[tuple[str, ArgRule]] = []
    for key, cfg in raw.items():
        if "force" in cfg:
            rules.append((key, ArgRule(mode="force", value=cfg["force"])))
        elif "deny" in cfg:
            rules.append((key, ArgRule(mode="deny", value=cfg["deny"])))
        elif "max" in cfg:
            rules.append((key, ArgRule(mode="max", value=cfg["max"])))
    return tuple(rules)


def _parse_scan_config(raw: dict) -> ScanConfig:
    return ScanConfig(
        rules=tuple(raw.get("rules", [])),
        on_match=raw.get("on_match", "warn"),
        egress=raw.get("egress", False),
    )


def load_policy(path: str) -> Policy:
    with open(path) as f:
        raw = yaml.safe_load(f)

    upstream = raw.get("upstream", {})
    defaults = raw.get("defaults", {})

    default_arg_rules = _parse_arg_rules(defaults.get("arguments", {}))
    default_scan = _parse_scan_config(defaults["scan"]) if "scan" in defaults else None

    teams: list[TeamPolicy] = []
    for name, cfg in raw.get("teams", {}).items():
        team_scan = cfg.get("scan", {})
        teams.append(
            TeamPolicy(
                name=name,
                token_hash=cfg["token_hash"],
                allow_tools=frozenset(cfg.get("allow_tools", [])),
                deny_tools=frozenset(cfg.get("deny_tools", [])),
                arg_rules=_parse_arg_rules(cfg.get("arguments", {})),
                scan_on_match=team_scan.get("on_match"),
                monthly_edits=cfg.get("quota", {}).get("monthly_edits"),
            )
        )

    key_env = upstream.get("key_env", "SUPERDOCS_API_KEY")

    return Policy(
        upstream_url=upstream.get("url", "https://api.superdocs.app/mcp"),
        upstream_key=os.environ.get(key_env, ""),
        default_deny_tools=frozenset(defaults.get("deny_tools", [])),
        default_arg_rules=default_arg_rules,
        default_scan=default_scan,
        teams=tuple(teams),
    )
