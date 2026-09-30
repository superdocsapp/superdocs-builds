"""Byte-preserving Python repair engine.

The parser records source spans for JSON and JSONC values; TOML is deliberately
narrow and changes only a quoted value in a named table.  No operation ever
serialises a whole configuration file.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .core import Contract, matches_entry, parse_config, render, scan


@dataclass
class Node:
    value: object
    start: int
    end: int
    properties: dict[str, Node] = field(default_factory=dict)
    property_starts: dict[str, int] = field(default_factory=dict)


class JsoncParser:
    def __init__(self, text: str):
        self.text = text.removeprefix("\ufeff")
        self.offset = len(text) - len(self.text)
        self.i = 0
        self.decoder = json.JSONDecoder()

    def skip(self) -> None:
        while self.i < len(self.text):
            if self.text[self.i].isspace():
                self.i += 1
            elif self.text.startswith("//", self.i):
                end = self.text.find("\n", self.i)
                self.i = len(self.text) if end < 0 else end + 1
            elif self.text.startswith("/*", self.i):
                end = self.text.find("*/", self.i + 2)
                if end < 0:
                    raise ValueError("unterminated block comment")
                self.i = end + 2
            else:
                return

    def value(self) -> Node:
        self.skip()
        start = self.i
        if self.i >= len(self.text):
            raise ValueError("missing value")
        if self.text[self.i] == "{":
            self.i += 1
            value: dict[str, object] = {}
            props: dict[str, Node] = {}
            prop_starts: dict[str, int] = {}
            self.skip()
            while self.i < len(self.text) and self.text[self.i] != "}":
                prop_start = self.i
                key, self.i = self.decoder.raw_decode(self.text, self.i)
                if not isinstance(key, str):
                    raise ValueError("object key is not string")
                self.skip()
                if self.i >= len(self.text) or self.text[self.i] != ":":
                    raise ValueError("missing colon")
                self.i += 1
                child = self.value()
                value[key], props[key], prop_starts[key] = child.value, child, prop_start
                self.skip()
                if self.i < len(self.text) and self.text[self.i] == ",":
                    self.i += 1
                    self.skip()
                elif self.i < len(self.text) and self.text[self.i] != "}":
                    raise ValueError("missing comma")
            if self.i >= len(self.text):
                raise ValueError("unterminated object")
            self.i += 1
            return Node(value, start + self.offset, self.i + self.offset, props, prop_starts)
        if self.text[self.i] == "[":
            self.i += 1
            items = []
            self.skip()
            while self.i < len(self.text) and self.text[self.i] != "]":
                items.append(self.value().value)
                self.skip()
                if self.i < len(self.text) and self.text[self.i] == ",":
                    self.i += 1
                    self.skip()
                elif self.i < len(self.text) and self.text[self.i] != "]":
                    raise ValueError("missing comma")
            if self.i >= len(self.text):
                raise ValueError("unterminated array")
            self.i += 1
            return Node(items, start + self.offset, self.i + self.offset)
        value, self.i = self.decoder.raw_decode(self.text, self.i)
        return Node(value, start + self.offset, self.i + self.offset)


def json_tree(text: str) -> Node:
    parser = JsoncParser(text)
    root = parser.value()
    parser.skip()
    if parser.i != len(parser.text):
        raise ValueError("trailing data")
    return root


def indent_of(text: str, offset: int) -> str:
    line = text.rfind("\n", 0, offset) + 1
    return re.match(r"[ \t]*", text[line:]).group(0)


def apply(text: str, start: int, end: int, replacement: str) -> str:
    # Exactly one declared span may change. Keep this intentionally tiny: an
    # error message has no source excerpt, so a failed repair cannot leak a key.
    if not 0 <= start <= end <= len(text):
        raise ValueError("invalid source span")
    after = text[:start] + replacement + text[end:]
    assert_only_span_changed(text, after, start, end, replacement)
    return after


def assert_only_span_changed(before: str, after: str, start: int, end: int, replacement: str) -> None:
    """Prove a repair changed only its declared source span.

    Deliberately never include source excerpts in an exception: either side can
    contain an Authorization value and the exception reaches CLI output.
    """
    expected_length = len(before) - (end - start) + len(replacement)
    if len(after) != expected_length or before[:start] != after[:start] or before[end:] != after[start + len(replacement) :]:
        raise ValueError(f"bytes outside the edited span changed near offset {start}")


def replace_value(text: str, node: Node, value: object) -> str:
    return apply(text, node.start, node.end, json.dumps(value, ensure_ascii=False))


def insert_property(text: str, obj: Node, name: str, value: object) -> str:
    if not isinstance(obj.value, dict) or name in obj.properties:
        raise ValueError("ambiguous property insertion")
    closing = obj.end - 1
    parent_indent = indent_of(text, closing)
    existing = list(obj.properties)
    child_indent = indent_of(text, obj.property_starts[existing[-1]]) if existing else parent_indent + "  "
    rendered = json.dumps(value, ensure_ascii=False, indent=2)
    if "\n" in rendered:
        rendered = rendered.replace("\n", "\n" + child_indent)
    if not existing:
        insertion = f"\n{child_indent}{json.dumps(name)}: {rendered}\n{parent_indent}"
        return apply(text, closing, closing, insertion)
    # A last property ending in a comma is already valid; otherwise add one.
    last = obj.properties[existing[-1]]
    # Always terminate the existing final property. If it already has a
    # trailing comma (possibly followed by a comment), that comma naturally
    # becomes the trailing comma of the newly inserted final property. This
    # leaves the comment bytes exactly where the author put them.
    insertion = f",\n{child_indent}{json.dumps(name)}: {rendered}"
    return apply(text, last.end, last.end, insertion)


def toml_edit(text: str, table: str, key: str, value: str) -> str | None:
    header = re.search(rf"^\[\s*{re.escape(table)}\s*\]\s*(?:#.*)?$", text, re.M)
    if not header:
        return None
    next_header = re.search(r"^\[", text[header.end() :], re.M)
    end = header.end() + next_header.start() if next_header else len(text)
    match = re.search(rf"(^[ \t]*{re.escape(key)}[ \t]*=[ \t]*)(\".*?\")", text[header.end() : end], re.M)
    if not match:
        return None
    return apply(text, header.end() + match.start(2), header.end() + match.end(2), json.dumps(value))


def permitted(client: dict, defect: dict, os_name: str) -> str | None:
    if not client["write_capable"].get(os_name, False):
        return f"{client['name']} is not write-capable on {os_name}: its configuration knowledge is '{client['evidence']['schema']['status']}', not captured from a real installation"
    if defect.get("fix_kind") not in client["repairs"]["allowed"]:
        return f"{client['name']} does not permit the '{defect.get('fix_kind')}' repair"
    return None


def entry_node(root: Node, client: dict, location: dict) -> tuple[Node, dict] | None:
    if not isinstance(root.value, dict):
        return None
    candidates: list[Node] = []
    paths = [item["json_path"] for item in location.get("containers", [])] or [f"$.{client['server_map']['container_key']}"]
    for path in paths:
        simple = re.fullmatch(r"\$\.([A-Za-z0-9_]+)", path)
        wildcard = re.fullmatch(r"\$\.([A-Za-z0-9_]+)\[\*\]\.([A-Za-z0-9_]+)", path)
        containers: list[Node] = []
        if simple and (container := root.properties.get(simple.group(1))) and isinstance(container.value, dict):
            containers.append(container)
        elif wildcard and (outer := root.properties.get(wildcard.group(1))) and isinstance(outer.value, dict):
            containers.extend(child.properties[wildcard.group(2)] for child in outer.properties.values() if isinstance(child.value, dict) and wildcard.group(2) in child.properties and isinstance(child.properties[wildcard.group(2)].value, dict))
        for container in containers:
            candidates.extend(node for name, node in container.properties.items() if isinstance(node.value, dict) and matches_entry(name, node.value, client))
    return (candidates[0], candidates[0].value) if len(candidates) == 1 else None


def add_container(root: Node, client: dict, location: dict) -> tuple[Node | None, str] | None:
    if not isinstance(root.value, dict):
        return None
    paths = [item["json_path"] for item in location.get("containers", [])] or [f"$.{client['server_map']['container_key']}"]
    simple = [match.group(1) for path in paths if (match := re.fullmatch(r"\$\.([A-Za-z0-9_]+)", path))]
    if len(simple) != 1:
        return None
    key = simple[0]
    container = root.properties.get(key)
    if container is None:
        return None, key
    return (container, key) if isinstance(container.value, dict) else None


def toml_entry(parsed: dict, client: dict) -> tuple[str, dict] | None:
    container = parsed.get(client["server_map"]["container_key"])
    if not isinstance(container, dict):
        return None
    matches = [(name, raw) for name, raw in container.items() if isinstance(raw, dict) and matches_entry(name, raw, client)]
    return matches[0] if len(matches) == 1 else None


def target(entry: dict, client: dict, contract: Contract, finding_id: str) -> tuple[list[str], object, str] | None:
    schema, profile = client["http_server_schema"], contract.profile
    url_field, headers_field = schema["url"]["field"], schema["headers"].get("field", "headers")
    auth, accept = schema["headers"].get("authorization_header", "Authorization"), schema["headers"].get("accept_header", "Accept")
    if finding_id in {"config.scheme-insecure", "config.path-wrong"}:
        url = entry.get(url_field)
        if not isinstance(url, str):
            return None
        parsed = urlsplit(url)
        if finding_id == "config.scheme-insecure":
            next_url = urlunsplit((profile["canonical"]["scheme"], parsed.netloc, parsed.path, parsed.query, parsed.fragment))
            return [url_field], next_url, "use https://"
        next_url = urlunsplit((parsed.scheme, parsed.netloc, profile["canonical"]["path"], parsed.query, parsed.fragment))
        return [url_field], next_url, f"set the path to {profile['canonical']['path']}"
    if finding_id == "config.transport-not-http" and schema["transport"].get("field"):
        return [schema["transport"]["field"]], schema["transport"]["preferred"], f"set {schema['transport']['field']} to {schema['transport']['preferred']}"
    headers = entry.get(headers_field) if isinstance(entry.get(headers_field), dict) else {}
    def key_for(wanted: str) -> str:
        return next((key for key in headers if key.lower() == wanted.lower()), wanted)
    if finding_id == "config.auth-header-no-bearer":
        key = key_for(auth)
        return [headers_field, key], f"{profile['credential']['header_scheme']} {str(headers.get(key, '')).strip()}", f"prefix the {auth} value with {profile['credential']['header_scheme']}"
    if finding_id == "config.auth-header-doubled-bearer":
        key = key_for(auth)
        value = re.sub(rf"^(?:{re.escape(profile['credential']['header_scheme'])}\s+)+", f"{profile['credential']['header_scheme']} ", str(headers.get(key, '')).strip(), flags=re.I)
        return [headers_field, key], value, f"write {profile['credential']['header_scheme']} once"
    if finding_id == "config.auth-header-missing":
        return [headers_field, auth], None, f"add the {auth} header"
    if finding_id == "config.accept-header-incompatible":
        key = key_for(accept)
        return [headers_field, key], profile["accept_header"]["must_include"], f"set {accept} to {profile['accept_header']['must_include']}"
    return None


def backup(path: Path, text: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = path.with_name(f"{path.name}.mcp-doctor-{stamp}.bak")
    for suffix in range(1000):
        candidate = destination if suffix == 0 else path.with_name(f"{path.name}.mcp-doctor-{stamp}-{suffix}.bak")
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            destination = candidate
            break
        except FileExistsError:
            continue
    else:
        raise OSError("could not allocate a unique backup name")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as file:
        file.write(text)
        file.flush()
        os.fsync(file.fileno())
    return destination


def read_source(path: Path) -> str:
    """Read without universal-newline conversion; CRLF is part of the promise."""
    with path.open(encoding="utf-8", newline="") as file:
        return file.read()


def atomic_replace(path: Path, text: str) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.mcp-doctor-", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        if os.name != "nt":
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def repair(contract: Contract, *, cwd: Path, env: dict[str, str], os_name: str, client_filter: str | None = None, single_file: Path | None = None, key_env: str = "SUPERDOCS_API_KEY", deterministic: bool = False) -> tuple[dict, list[str], int]:
    """Repair supported existing entries; every unsupported case is a refusal."""
    before = scan(contract, cwd=cwd, env=env, os_name=os_name, client_filter=client_filter, single_file=single_file, key_env=key_env, deterministic=False)
    lines, fixed_findings = [], []
    for client in (item for item in contract.clients if not client_filter or item["id"] == client_filter):
        seen: set[Path] = set()
        for location in sorted(client["locations"], key=lambda item: item["precedence"]):
            target_path = single_file if single_file and single_file.name == location["path"].split("/")[-1] else None
            if single_file is None:
                from .core import resolve_location
                target_path = resolve_location(location, contract.bases, cwd, env, os_name)
            if not target_path or not target_path.is_file():
                continue
            if target_path in seen:
                continue
            seen.add(target_path)
            source = str(target_path)
            applicable = [f for f in before["findings"] if f.get("client") == client["name"] and f.get("location", {}).get("path") == source and f.get("auto_fixable")]
            if not applicable:
                continue
            try:
                text = read_source(target_path)
                root = json_tree(text) if location["format"] != "toml" else None
                parsed, duplicates, failure = parse_config(text, location["format"])
                if failure or not isinstance(parsed, dict):
                    lines.append(f"✗ {client['name']}: not repaired: the file could not be parsed")
                    continue
                if duplicates:
                    # JSON/JSONC chooses the last duplicated key. Editing that
                    # silent winner is not safe: it leaves a shadowed config
                    # behind and makes a successful-looking repair ambiguous.
                    lines.append(f"i {client['name']}: not repaired: repeated keys make this configuration ambiguous")
                    continue
                located = entry_node(root, client, location) if root else toml_entry(parsed, client)
                if not located:
                    no_entry = next((finding for finding in applicable if finding["id"] == "config.no-entry"), None)
                    container = add_container(root, client, location) if root else None
                    if no_entry and container and location["format"] != "toml":
                        defect = contract.defect("config.no-entry")
                        if reason := permitted(client, defect, os_name):
                            lines.append(f"i {client['name']}: config.no-entry not repaired — {reason}")
                            continue
                        key = env.get(key_env, "").strip()
                        if not key:
                            lines.append(f"i {client['name']}: config.no-entry not repaired — no key available — set {key_env}")
                            continue
                        schema = client["http_server_schema"]
                        headers_field = schema["headers"].get("field")
                        if not schema["headers"].get("supported") or not headers_field:
                            lines.append(f"i {client['name']}: config.no-entry not repaired — this client has no verified request-header field")
                            continue
                        entry = {schema["url"]["field"]: contract.profile["canonical"]["url"], headers_field: {schema["headers"].get("authorization_header", "Authorization"): f"{contract.profile['credential']['header_scheme']} {key}"}}
                        if schema["transport"].get("field") and schema["transport"].get("preferred"):
                            entry = {schema["transport"]["field"]: schema["transport"]["preferred"], **entry}
                        destination, container_key = container
                        working = (
                            insert_property(text, destination, "superdocs", entry)
                            if destination is not None
                            else insert_property(text, root, container_key, {"superdocs": entry})
                        )
                        if parse_config(working, location["format"])[2]:
                            raise ValueError("repair produced invalid syntax")
                        backup_path = backup(target_path, text)
                        atomic_replace(target_path, working)
                        lines.extend([f"✓ {client['name']}: backed up → {backup_path}", f"✓ {client['name']}: add a SuperDocs entry"])
                        fixed_findings.append(("config.no-entry", source))
                        continue
                    lines.append(f"✗ {client['name']}: not repaired: no unambiguous SuperDocs entry to act on")
                    continue
                entry_name, entry = located
                working, applied = text, []
                for finding in applicable:
                    node = None
                    if location["format"] == "toml":
                        current, _, current_failure = parse_config(working, "toml")
                        refreshed = toml_entry(current, client) if isinstance(current, dict) and not current_failure else None
                        if not refreshed:
                            raise ValueError("entry moved while repairing")
                        entry_name, entry = refreshed
                    else:
                        located = entry_node(json_tree(working), client, location)
                        if not located:
                            raise ValueError("entry moved while repairing")
                        node, entry = located
                    defect = contract.defect(finding["id"])
                    if reason := permitted(client, defect, os_name):
                        lines.append(f"i {client['name']}: {finding['id']} not repaired — {reason}")
                        continue
                    change = target(entry, client, contract, finding["id"])
                    if not change:
                        lines.append(f"i {client['name']}: {finding['id']} not repaired — this repair could not be expressed as a single value change")
                        continue
                    path, value, description = change
                    if finding["id"] == "config.auth-header-missing":
                        key = env.get(key_env, "").strip()
                        if not key:
                            lines.append(f"i {client['name']}: {finding['id']} not repaired — no key available — set {key_env}")
                            continue
                        value = f"{contract.profile['credential']['header_scheme']} {key}"
                    if location["format"] == "toml":
                        table = ".".join([client["server_map"]["container_key"], entry_name, *path[:-1]])
                        next_text = toml_edit(working, table, path[-1], str(value))
                        if next_text is None:
                            lines.append(f"i {client['name']}: {finding['id']} not repaired — could not locate the TOML value unambiguously")
                            continue
                        working = next_text
                    else:

                        if len(path) == 2 and path[0] not in node.properties:
                            working = insert_property(working, node, path[0], {path[1]: value})
                            _, _, reparsed_failure = parse_config(working, location["format"])
                            if reparsed_failure:
                                raise ValueError("repair produced invalid syntax")
                            applied.append((finding["id"], description))
                            continue
                        parent = node
                        for segment in path[:-1]:
                            if segment not in parent.properties:
                                parent = None
                                break
                            parent = parent.properties[segment]
                        working = replace_value(working, parent.properties[path[-1]], value) if parent and path[-1] in parent.properties else insert_property(working, parent or node, path[-1], value)
                        _, _, reparsed_failure = parse_config(working, location["format"])
                        if reparsed_failure:
                            raise ValueError("repair produced invalid syntax")
                    applied.append((finding["id"], description))
                if applied:
                    backup_path = backup(target_path, text)
                    atomic_replace(target_path, working)
                    lines.append(f"✓ {client['name']}: backed up → {backup_path}")
                    lines.extend(f"✓ {client['name']}: {description}" for _, description in applied)
                    fixed_findings.extend((finding_id, source) for finding_id, _ in applied)
            except (OSError, ValueError) as err:
                lines.append(f"✗ {client['name']}: could not repair safely ({type(err).__name__})")
    after = scan(contract, cwd=cwd, env=env, os_name=os_name, client_filter=client_filter, single_file=single_file, key_env=key_env, deterministic=deterministic)
    after["summary"]["fixed"] = len(fixed_findings)
    for finding in before["findings"]:
        if (finding["id"], finding.get("location", {}).get("path")) in fixed_findings:
            historic = dict(finding)
            historic["fixed"] = True
            historic["location"] = dict(finding.get("location", {}))
            historic["data"] = dict(finding.get("data", {}))
            if deterministic:
                def relative(path: str) -> str:
                    return Path(os.path.relpath(path, cwd)).as_posix()

                if historic["location"].get("path"):
                    historic["location"]["path"] = relative(historic["location"]["path"])
                if isinstance(historic["data"].get("path"), str):
                    historic["data"]["path"] = relative(historic["data"]["path"])
                defect = contract.defect(historic["id"])
                historic["message"] = render(defect["message"], historic["data"])
                historic["remediation"] = render(defect.get("remediation"), historic["data"])
            after["findings"].append(historic)
    after["findings"].sort(key=lambda item: ({"error": 0, "warn": 1, "info": 2}[item["severity"]], item["id"], item.get("location", {}).get("path", "")))
    return after, lines, 1 if any(line.startswith(("i", "✗")) for line in lines) or after["summary"]["errors"] else 0
