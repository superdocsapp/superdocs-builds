"""Shared-contract configuration discovery and diagnosis."""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from . import VERSION

SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}
CANONICAL_URL = "https://api.superdocs.app/mcp"


@dataclass
class PairObject:
    pairs: list[tuple[str, object]]


def shared_root(env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if override := env.get("MCP_DOCTOR_SHARED"):
        root = Path(override).resolve()
    else:
        bundled = Path(__file__).resolve().parent / "shared"
        source = Path(__file__).resolve().parents[3] / "shared"
        if (source.parent / "tools" / "validate_contract.py").is_file():
            root = source
        elif bundled.is_dir():
            root = bundled
        else:
            root = source
    if not (root / "defects.json").is_file() or not (root / "clients").is_dir():
        raise RuntimeError(f"MCP_DOCTOR_SHARED is not a contract: {root}")
    return root


@dataclass
class Contract:
    root: Path
    profile: dict
    bases: dict
    clients: list[dict]
    defects: dict[str, dict]

    def defect(self, finding_id: str) -> dict:
        try:
            return self.defects[finding_id]
        except KeyError as err:
            raise RuntimeError(f"defect '{finding_id}' is not in the shared catalogue") from err


def load_contract(root: Path | None = None, env: dict[str, str] | None = None) -> Contract:
    root = shared_root(env) if root is None else root
    profile = json.loads((root / "profile" / "superdocs.json").read_text())
    canonical = profile.get("canonical", {})
    if canonical.get("url") != CANONICAL_URL or canonical.get("follow_redirects") is not False:
        raise RuntimeError("refusing to run: loaded profile is not the pinned SuperDocs endpoint")
    parsed = urlsplit(CANONICAL_URL)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
        raise RuntimeError("refusing to run: canonical URL is not bare HTTPS")
    catalogue = json.loads((root / "defects.json").read_text())
    clients = sorted(
        (json.loads(path.read_text()) for path in (root / "clients").glob("*.json")),
        key=lambda client: client["id"],
    )
    return Contract(
        root=root,
        profile=profile,
        bases=json.loads((root / "path-bases.json").read_text()),
        clients=clients,
        defects={defect["id"]: defect for defect in catalogue["defects"]},
    )


def strip_jsonc(text: str) -> str:
    """Remove comments and trailing commas without touching quoted strings."""
    output: list[str] = []
    i = 0
    quoted = False
    escaped = False
    while i < len(text):
        char = text[i]
        if quoted:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            i += 1
            continue
        if char == '"':
            quoted = True
            output.append(char)
            i += 1
        elif char == "/" and i + 1 < len(text) and text[i + 1] == "/":
            end = text.find("\n", i)
            if end == -1:
                break
            output.append("\n")
            i = end + 1
        elif char == "/" and i + 1 < len(text) and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end == -1:
                raise ValueError("unterminated block comment")
            output.extend("\n" for c in text[i : end + 2] if c == "\n")
            i = end + 2
        else:
            output.append(char)
            i += 1

    no_comments = "".join(output)
    output = []
    quoted = escaped = False
    i = 0
    while i < len(no_comments):
        char = no_comments[i]
        if quoted:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            i += 1
            continue
        if char == '"':
            quoted = True
            output.append(char)
        elif char == ",":
            lookahead = i + 1
            while lookahead < len(no_comments) and no_comments[lookahead].isspace():
                lookahead += 1
            if lookahead < len(no_comments) and no_comments[lookahead] in "}]":
                i += 1
                continue
            output.append(char)
        else:
            output.append(char)
        i += 1
    return "".join(output)


def line_col(text: str, offset: int) -> tuple[int, int]:
    return text.count("\n", 0, offset) + 1, offset - text.rfind("\n", 0, offset)


def parse_config(text: str, fmt: str) -> tuple[object | None, list[tuple[str, str]], dict | None]:
    """Return value, duplicate keys, and parse error metadata."""
    body = text.removeprefix("\ufeff")
    if not body.strip():
        return None, [], {"empty": True}
    if fmt == "toml":
        try:
            return tomllib.loads(body), [], None
        except tomllib.TOMLDecodeError as err:
            match = re.search(r"line (\d+), column (\d+)", str(err))
            return None, [], {
                "reason": "invalid TOML",
                "line": int(match.group(1)) if match else 1,
                "column": int(match.group(2)) if match else 1,
            }
    try:
        decoded = json.loads(
            strip_jsonc(body) if fmt == "jsonc" else body,
            object_pairs_hook=lambda pairs: PairObject(pairs),
        )
    except (json.JSONDecodeError, ValueError) as err:
        offset = getattr(err, "pos", 0)
        line, column = line_col(body, offset)
        return None, [], {"reason": "invalid JSON", "line": line, "column": column}

    duplicates: list[tuple[str, str]] = []

    def convert(value: object, path: str = "") -> object:
        if isinstance(value, PairObject):
            result: dict[str, object] = {}
            for key, child in value.pairs:
                if key in result:
                    duplicates.append((path or "(root)", key))
                result[key] = convert(child, f"{path}.{key}" if path else key)
            return result
        if isinstance(value, list):
            return [convert(child, f"{path}[{index}]") for index, child in enumerate(value)]
        return value

    return convert(decoded), duplicates, None


def expand_fallback(fallback: str, env: dict[str, str]) -> str | None:
    if fallback == "~":
        return env.get("HOME")
    value = re.sub(r"\$([A-Z_][A-Z0-9_]*)", lambda match: env.get(match.group(1), match.group(0)), fallback)
    return None if "$" in value else value


def project_root(cwd: Path, markers: list[str], env: dict[str, str]) -> Path:
    home = Path(env.get("HOME") or env.get("USERPROFILE") or "/__not_home__").resolve()
    current = cwd.resolve()
    while True:
        if any((current / marker).exists() for marker in markers):
            return current
        if current == current.parent or current == home:
            return cwd.resolve()
        current = current.parent


def resolve_location(location: dict, bases: dict, cwd: Path, env: dict[str, str], os_name: str) -> Path | None:
    if os_name not in location["os"]:
        return None
    base_name = location["base"]
    base = bases["bases"].get(base_name)
    if not base:
        return None
    if base_name == "project_root":
        base_path = project_root(cwd, base.get("markers", []), env) if base.get("ascend") else cwd
    else:
        rule = base.get(os_name)
        if not rule:
            return None
        base_path = next((env[name] for name in rule.get("from_env", []) if env.get(name)), None)
        if not base_path:
            fallback = rule.get("fallback")
            base_path = expand_fallback(fallback, env) if fallback else None
        if not base_path:
            return None
    return Path(base_path).joinpath(*location["path"].split("/"))


def render(template: str | None, data: dict) -> str | None:
    if template is None:
        return None
    return re.sub(r"\{([a-z_][a-z0-9_]*)\}", lambda match: str(data.get(match.group(1), match.group(0))), template)


def make_finding(contract: Contract, finding_id: str, data: dict, **extra: object) -> dict:
    defect = contract.defect(finding_id)
    return {
        "id": finding_id,
        "class": defect["class"],
        "severity": defect["severity"],
        "message": render(defect["message"], data),
        "remediation": render(defect.get("remediation"), data),
        "auto_fixable": defect["auto_fixable"],
        **extra,
        "data": data,
    }


def host_of(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname.lower() if parsed.hostname else None
        if not host:
            return None
        # WHATWG URL.host (used by TypeScript) includes a non-default port.
        # Comparing hostname alone would incorrectly regard :444 as the pinned
        # direct endpoint and could lead the two doctors to opposite advice.
        port = parsed.port
        if port is not None and port != (443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else None):
            return f"{host}:{port}"
        return host
    except ValueError:
        return None


def is_stdio(entry: dict, client: dict) -> bool:
    return any(field in entry for field in client["http_server_schema"]["transport"].get("stdio_indicator_fields", []))


def containers_of(root: object, client: dict, location: dict) -> list[tuple[dict, str]]:
    if not isinstance(root, dict):
        return []
    declared = [item["json_path"] for item in location.get("containers", [])] or [f"$.{client['server_map']['container_key']}"]
    output: list[tuple[dict, str]] = []
    for path in declared:
        simple = re.fullmatch(r"\$\.([A-Za-z0-9_]+)", path)
        wildcard = re.fullmatch(r"\$\.([A-Za-z0-9_]+)\[\*\]\.([A-Za-z0-9_]+)", path)
        if simple and isinstance(root.get(simple.group(1)), dict):
            output.append((root[simple.group(1)], path))
        elif wildcard and isinstance(root.get(wildcard.group(1)), dict):
            for name, outer in root[wildcard.group(1)].items():
                if isinstance(outer, dict) and isinstance(outer.get(wildcard.group(2)), dict):
                    output.append((outer[wildcard.group(2)], f'$.{wildcard.group(1)}["{name}"].{wildcard.group(2)}'))
    return output


def matches_entry(name: str, entry: dict, client: dict) -> bool:
    url_field = client["http_server_schema"]["url"]["field"]
    for rule in client["identification"]["rules"]:
        if rule["by"] == "url_host" and rule.get("equals") and isinstance(entry.get(url_field), str):
            if host_of(entry[url_field]) == rule["equals"].lower():
                return True
        elif rule["by"] == "name" and rule.get("matches"):
            flags = re.IGNORECASE if "i" in rule.get("flags", "") else 0
            if re.search(rule["matches"], name, flags):
                return True
    return False


def identify(root: object, client: dict, location: dict) -> list[tuple[str, dict, str]]:
    output = []
    for container, path in containers_of(root, client, location):
        for name, raw in container.items():
            if isinstance(raw, dict) and matches_entry(name, raw, client):
                output.append((name, raw, f"{path}.{name}"))
    return output


def header(entry: dict, field: str | None, wanted: str) -> tuple[bool, str | None]:
    headers = entry.get(field or "")
    if not isinstance(headers, dict):
        return False, None
    for name, value in headers.items():
        if name.lower() == wanted.lower():
            return True, str(value)
    return False, None


def summary_entry(name: str, entry: dict, client: dict, profile: dict) -> dict:
    if is_stdio(entry, client):
        return {"name": name, "kind": "stdio", "in_scope": False}
    url = entry.get(client["http_server_schema"]["url"]["field"])
    if not isinstance(url, str):
        return {"name": name, "kind": "unknown", "in_scope": False}
    host = host_of(url)
    canonical = host == profile["canonical"]["host"].lower()
    summary = {"name": name, "kind": "http", "canonical": canonical, "in_scope": canonical}
    if host is not None:
        summary["host"] = host
    return summary


def diagnose(contract: Contract, client: dict, path: Path, name: str, entry: dict, json_path: str, env: dict[str, str], key_env: str) -> list[dict]:
    profile, schema = contract.profile, client["http_server_schema"]
    data = {"client": client["name"], "path": str(path)}
    location = {"path": str(path), "json_path": json_path}
    extra = {"client": client["name"], "location": location}
    if is_stdio(entry, client):
        return [make_finding(contract, "scope.stdio-server", data, **extra)]
    raw_url = entry.get(schema["url"]["field"])
    if not isinstance(raw_url, str) or not raw_url:
        return [make_finding(contract, "config.url-missing", data, **extra)]
    host = host_of(raw_url)
    if host != profile["canonical"]["host"].lower():
        return [make_finding(contract, "scope.non-canonical-host", {**data, "host": host or "(unparseable)", "canonical_host": profile["canonical"]["host"]}, **extra)]
    if not schema["headers"]["supported"]:
        return [make_finding(contract, "scope.client-cannot-authenticate", {**data, "reason": schema["headers"].get("unsupported_reason", "no headers field")}, **extra)]
    parsed = urlsplit(raw_url)
    findings: list[dict] = []
    if parsed.username or parsed.password:
        findings.append(make_finding(contract, "config.url-embedded-credentials", data, **extra))
    if parsed.scheme != profile["canonical"]["scheme"]:
        findings.append(make_finding(contract, "config.scheme-insecure", data, **extra))
    if parsed.path not in profile["canonical"].get("path_aliases", [profile["canonical"]["path"]]):
        findings.append(make_finding(contract, "config.path-wrong", {**data, "found": parsed.path, "expected": profile["canonical"]["path"]}, **extra))
    # urlsplit normalises a bare trailing `?` / `#` to empty components, but
    # the canonical endpoint forbids the delimiters themselves as well.
    if parsed.query or parsed.fragment or "?" in raw_url or "#" in raw_url:
        findings.append(make_finding(contract, "config.url-query-or-fragment", data, **extra))
    transport = schema["transport"]
    if transport["detected_by"] == "type-field" and transport.get("field") and transport["field"] in entry and str(entry[transport["field"]]) not in transport["http_values"]:
        findings.append(make_finding(contract, "config.transport-not-http", {**data, "found": str(entry[transport["field"]]), "expected": transport.get("preferred") or "http"}, **extra))
    auth_name = schema["headers"].get("authorization_header", "Authorization")
    present, value = header(entry, schema["headers"].get("field"), auth_name)
    scheme = profile["credential"]["header_scheme"]
    if not present:
        findings.append(make_finding(contract, "config.auth-header-missing", data, **extra))
    else:
        value = (value or "").strip()
        if re.match(rf"^(?:{re.escape(scheme)}\s+){{2}}", value, re.I):
            findings.append(make_finding(contract, "config.auth-header-doubled-bearer", data, **extra))
        elif not re.match(rf"^{re.escape(scheme)}\s+", value, re.I):
            findings.append(make_finding(contract, "config.auth-header-no-bearer", data, **extra))
        else:
            token = value[len(scheme) :].strip()
            placeholder = re.fullmatch(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)(:-[^}]*)?\}?|\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}", token)
            fallback = placeholder.group(2)[2:] if placeholder and placeholder.group(2) else None
            resolved = env.get(placeholder.group(1) or placeholder.group(3) or "") if placeholder else None
            resolved = resolved if resolved and resolved.strip() else fallback
            if placeholder and (not resolved or not resolved.strip()):
                findings.append(make_finding(contract, "config.env-placeholder-unresolved", {**data, "variable": placeholder.group(1) or placeholder.group(3) or ""}, **extra))
            elif not placeholder and not any(token.startswith(prefix) for prefix in profile["credential"]["key_prefixes"]):
                findings.append(make_finding(contract, "config.key-shape-unexpected", {**data, "expected_prefixes": " or ".join(profile["credential"]["key_prefixes"])}, **extra))
    accept_name = schema["headers"].get("accept_header", "Accept")
    accept_present, accept = header(entry, schema["headers"].get("field"), accept_name)
    if accept_present and profile["accept_header"]["must_include"].lower() not in (accept or "").lower():
        findings.append(make_finding(contract, "config.accept-header-incompatible", {**data, "found": accept or ""}, **extra))
    return findings


def evidence_tier(client: dict, os_name: str) -> str:
    order = ["unverified", "documented", "captured"]
    path = client["evidence"]["paths"].get(os_name, {}).get("status", "unverified")
    schema = client["evidence"]["schema"]["status"]
    return order[min(order.index(path), order.index(schema))]


def scan(contract: Contract, *, cwd: Path, env: dict[str, str], os_name: str, client_filter: str | None = None, single_file: Path | None = None, key_env: str = "SUPERDOCS_API_KEY", deterministic: bool = False) -> dict:
    clients, findings = [], []
    files_read = entries_found = 0
    selected = [client for client in contract.clients if not client_filter or client["id"] == client_filter]
    for client in selected:
        reports = []
        seen: set[Path] = set()
        for location in sorted(client["locations"], key=lambda item: item["precedence"]):
            leaf = location["path"].split("/")[-1]
            target = single_file if single_file and str(single_file).endswith(leaf) else (None if single_file else resolve_location(location, contract.bases, cwd, env, os_name))
            if target is None:
                continue
            if target in seen:
                continue
            seen.add(target)
            base = {"path": str(target), "scope": location["scope"], "format": location["format"]}
            try:
                text = target.read_text(encoding="utf-8")
            except FileNotFoundError:
                reports.append({**base, "status": "absent"})
                continue
            except (OSError, UnicodeError) as err:
                findings.append(make_finding(contract, "config.file-unreadable", {"client": client["name"], "path": str(target), "reason": getattr(err, "errno", "unreadable")}, client=client["name"], location={"path": str(target)}))
                reports.append({**base, "status": "unreadable"})
                continue
            files_read += 1
            root, duplicates, failure = parse_config(text, location["format"])
            if failure:
                if failure.get("empty"):
                    findings.append(make_finding(contract, "config.file-empty", {"client": client["name"], "path": str(target)}, client=client["name"], location={"path": str(target)}))
                    reports.append({**base, "status": "ok", "entries": []})
                else:
                    findings.append(make_finding(contract, "config.invalid-syntax", {"client": client["name"], "path": str(target), "format": location["format"].upper(), "line": failure.get("line", 1), "column": failure.get("column", 1), "reason": failure["reason"]}, client=client["name"], location={"path": str(target), "line": failure.get("line", 1), "column": failure.get("column", 1)}))
                    reports.append({**base, "status": "invalid"})
                continue
            for container, key in duplicates:
                findings.append(make_finding(contract, "config.duplicate-keys", {"client": client["name"], "path": str(target), "field_name": key, "container": container}, client=client["name"], location={"path": str(target), "json_path": f"$.{container}"}))
            entries = identify(root, client, location)
            entries_found += len(entries)
            if not entries:
                findings.append(make_finding(contract, "config.no-entry", {"client": client["name"], "path": str(target), "key_env": key_env}, client=client["name"], location={"path": str(target)}))
            elif len(entries) > 1:
                findings.append(make_finding(contract, "config.duplicate-entries", {"client": client["name"], "path": str(target), "count": len(entries), "names": ", ".join(item[0] for item in entries)}, client=client["name"], location={"path": str(target)}))
            else:
                name, entry, json_path = entries[0]
                findings.extend(diagnose(contract, client, target, name, entry, json_path, env, key_env))
            reports.append({**base, "status": "ok", "entries": [summary_entry(name, entry, client, contract.profile) for name, entry, _ in entries]})
        # `locations` was sorted by precedence above. Do not sort by scope here:
        # the shared wire contract requires precedence, then path, not an
        # alphabetic scope order that happens to look stable.
        clients.append({"id": client["id"], "name": client["name"], "write_capable": client["write_capable"].get(os_name, False), "evidence_tier": evidence_tier(client, os_name), "config_files": reports})
    if deterministic:
        def relative(path: str) -> str:
            return Path(os.path.relpath(path, cwd)).as_posix()
        for client in clients:
            for item in client["config_files"]:
                item["path"] = relative(item["path"])
        for finding in findings:
            if finding.get("location", {}).get("path"):
                finding["location"]["path"] = relative(finding["location"]["path"])
            if isinstance(finding.get("data", {}).get("path"), str):
                finding["data"]["path"] = relative(finding["data"]["path"])
            defect = contract.defect(finding["id"])
            finding["message"] = render(defect["message"], finding["data"])
            finding["remediation"] = render(defect.get("remediation"), finding["data"])
    findings.sort(key=lambda item: (SEVERITY_ORDER[item["severity"]], item["id"], item.get("location", {}).get("path", "")))
    errors = sum(item["severity"] == "error" for item in findings)
    warnings = sum(item["severity"] == "warn" for item in findings)
    report = {"schema_version": 1, "tool": {"name": "mcp-doctor", "version": "deterministic" if deterministic else VERSION, "implementation": "python"}, "summary": {"clients_scanned": len(clients), "config_files_read": files_read, "entries_found": entries_found, "errors": errors, "warnings": warnings, "fixed": 0, "connection": "not-attempted"}, "clients": clients, "findings": findings, "exit_code": 1 if errors else 0}
    if not deterministic:
        report["generated_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return report


def platform_name(platform: str | None = None) -> str:
    platform = sys.platform if platform is None else platform
    return {"darwin": "darwin", "linux": "linux", "win32": "win32"}.get(platform, "")
