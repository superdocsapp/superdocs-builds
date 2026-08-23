from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcp_doctor.core import load_contract  # noqa: I001
from mcp_doctor.repair import assert_only_span_changed, backup, insert_property, json_tree, repair, toml_edit


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = load_contract(ROOT / "shared")


def fixture(client_id: str, name: str) -> dict:
    cases = json.loads((ROOT / "shared" / "fixtures" / f"{client_id}.cases.json").read_text())["cases"]
    return next(case for case in cases if case["name"] == name)


def writable(client_id: str):
    contract = copy.deepcopy(CONTRACT)
    client = next(client for client in contract.clients if client["id"] == client_id)
    client["write_capable"] = {"darwin": True, "linux": True, "win32": True}
    client["repairs"]["allowed"] = client["repairs"].get("planned", [])
    return contract


def execute(tmp_path: Path, client_id: str, case: dict):
    for relative, source in case["raw_files"].items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    env = {"HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "CODEX_HOME": str(tmp_path / ".codex")}
    env.update({name: value for name, value in case.get("env", {}).items() if value is not None})
    return repair(writable(client_id), cwd=tmp_path, env=env, os_name="darwin", client_filter=client_id, deterministic=True)


def test_json_scheme_repair_is_exact_and_backed_up(tmp_path: Path) -> None:
    case = fixture("claude-code", "scheme-insecure")
    report, lines, code = execute(tmp_path, "claude-code", case)
    assert code == 0
    assert report["summary"]["fixed"] == 1
    assert "config.scheme-insecure" in [finding["id"] for finding in report["findings"] if finding.get("fixed")]
    assert (tmp_path / ".mcp.json").read_bytes().decode() == case["expect"]["fix"]["files"][".mcp.json"]
    assert any(path.suffix == ".bak" for path in tmp_path.iterdir())
    assert any("backed up" in line for line in lines)
    again, again_lines, again_code = repair(
        writable("claude-code"),
        cwd=tmp_path,
        env={"HOME": str(tmp_path)},
        os_name="darwin",
        client_filter="claude-code",
        deterministic=True,
    )
    assert again_code == 0
    assert again["summary"]["fixed"] == 0
    assert again_lines == []


def test_jsonc_comment_is_byte_preserved(tmp_path: Path) -> None:
    case = fixture("vscode", "jsonc-line-comments-preserved")
    _, _, code = execute(tmp_path, "vscode", case)
    assert code == 0
    assert (tmp_path / ".vscode" / "mcp.json").read_bytes().decode() == case["expect"]["fix"]["files"][".vscode/mcp.json"]


def test_toml_scheme_repair_is_exact(tmp_path: Path) -> None:
    case = fixture("codex", "scheme-insecure")
    _, _, code = execute(tmp_path, "codex", case)
    assert code == 0
    assert (tmp_path / ".codex" / "config.toml").read_bytes().decode() == case["expect"]["fix"]["files"][".codex/config.toml"]


def test_shipped_gate_never_creates_a_backup(tmp_path: Path) -> None:
    case = fixture("claude-code", "scheme-insecure")
    source = next(iter(case["raw_files"].values()))
    path = tmp_path / ".mcp.json"
    path.write_text(source)
    report, lines, code = repair(CONTRACT, cwd=tmp_path, env={"HOME": str(tmp_path)}, os_name="darwin", client_filter="claude-code")
    assert code == 1
    assert path.read_text() == source
    assert not list(tmp_path.glob("*.bak"))
    assert "not write-capable" in "\n".join(lines)
    assert report["summary"]["fixed"] == 0


def test_add_entry_requires_a_key_and_preserves_json_source(tmp_path: Path) -> None:
    case = {
        "raw_files": {".mcp.json": '{\n  "mcpServers": {}\n}\n'},
        "env": {"SUPERDOCS_API_KEY": "sk_fixture_python_add_0000"},
    }
    report, _, code = execute(tmp_path, "claude-code", case)
    assert code == 0
    assert report["summary"]["fixed"] == 1
    content = (tmp_path / ".mcp.json").read_text()
    assert '"superdocs"' in content
    assert "Bearer sk_fixture_python_add_0000" in content


def test_duplicate_keys_are_never_repaired(tmp_path: Path) -> None:
    source = '{"mcpServers":{"superdocs":{"url":"http://api.superdocs.app/mcp","headers":{}},"superdocs":{"url":"http://api.superdocs.app/mcp","headers":{}}}}\n'
    path = tmp_path / ".mcp.json"
    path.write_text(source)
    _, lines, code = repair(writable("claude-code"), cwd=tmp_path, env={"HOME": str(tmp_path)}, os_name="darwin", client_filter="claude-code")
    assert code == 1
    assert path.read_text() == source
    assert not list(tmp_path.glob("*.bak"))
    assert "repeated keys" in "\n".join(lines)


def test_backup_collision_uses_a_second_unique_name(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text("{}")
    first = backup(target, "{}")
    second = backup(target, "{}")
    assert first != second
    assert first.read_text() == second.read_text() == "{}"
    if os.name != "nt":
        assert first.stat().st_mode & 0o777 == 0o600
        assert second.stat().st_mode & 0o777 == 0o600


def test_span_assertion_never_leaks_source_text() -> None:
    secret = "sk_fixture_span_secret_0000"
    with pytest.raises(ValueError) as error:
        assert_only_span_changed(f"Bearer {secret}", "changed", 0, 0, "")
    assert secret not in str(error.value)


def test_jsonc_insertion_keeps_trailing_comma_and_comment_valid() -> None:
    source = '{\n  "server": {\n    "url": "https://api.superdocs.app/mcp", // managed\n  },\n}\n'
    root = json_tree(source)
    server = root.properties["server"]
    repaired = insert_property(source, server, "headers", {"Authorization": "Bearer sk_fixture_comment_0000"})
    assert "// managed" in repaired
    assert '"headers"' in repaired
    # Parsing through the normal JSONC path proves the comment/trailing-comma
    # combination remains client-loadable.
    assert json_tree(repaired).properties["server"].value["headers"]


def test_toml_table_header_comment_does_not_block_value_edit() -> None:
    source = '[mcp_servers.superdocs] # managed\nurl = "http://api.superdocs.app/mcp"\n'
    repaired = toml_edit(source, "mcp_servers.superdocs", "url", "https://api.superdocs.app/mcp")
    assert repaired == '[mcp_servers.superdocs] # managed\nurl = "https://api.superdocs.app/mcp"\n'


def test_shared_repair_bytes_for_supported_cases(tmp_path: Path) -> None:
    for client_id in ("claude-code", "vscode", "codex", "antigravity"):
        cases = json.loads((ROOT / "shared" / "fixtures" / f"{client_id}.cases.json").read_text())["cases"]
        for case in cases:
            expected = case.get("expect", {}).get("fix", {}).get("files")
            if not expected:
                continue
            root = tmp_path / client_id / case["name"]
            _, _, code = execute(root, client_id, case)
            assert code == case["expect"]["fix"]["exit_code"], f"{client_id}/{case['name']}"
            for relative, wanted in expected.items():
                assert (root / relative).read_bytes().decode() == wanted, f"{client_id}/{case['name']} → {relative}"


# ── regressions found by differential testing against the TypeScript CLI ──


def test_two_repairs_on_one_field_compose(tmp_path: Path) -> None:
    case = {
        "raw_files": {
            ".mcp.json": '{\n  "mcpServers": {\n    "superdocs": {\n      "type": "http",\n'
            '      "url": "http://api.superdocs.app/v1/mcp",\n'
            '      "headers": { "Authorization": "Bearer sk_fixture_compose_0000" }\n'
            "    }\n  }\n}\n"
        }
    }
    report, lines, code = execute(tmp_path, "claude-code", case)
    content = (tmp_path / ".mcp.json").read_text()
    assert '"url": "https://api.superdocs.app/mcp"' in content, "\n".join(lines)
    assert "/v1/mcp" not in content
    assert "http://" not in content
    assert code == 0
    assert report["summary"]["fixed"] == 2


def test_missing_container_key_is_created(tmp_path: Path) -> None:
    """A file of `{}` still has one unambiguous destination.

    Refusing left the user with no way forward while TypeScript wrote the entry
    happily — a divergence on the write path, which is the worst kind.
    """
    case = {
        "raw_files": {".mcp.json": "{}\n"},
        "env": {"SUPERDOCS_API_KEY": "sk_fixture_create_00000000"},
    }
    _, lines, code = execute(tmp_path, "claude-code", case)
    content = (tmp_path / ".mcp.json").read_text()
    assert '"mcpServers"' in content, "\n".join(lines)
    assert '"superdocs"' in content
    assert "Bearer sk_fixture_create_00000000" in content
    assert code == 0


def test_added_entry_orders_transport_first(tmp_path: Path) -> None:
    """Insertion order is written byte order, so it is part of the contract."""
    case = {
        "raw_files": {".mcp.json": '{\n  "mcpServers": {}\n}\n'},
        "env": {"SUPERDOCS_API_KEY": "sk_fixture_order_000000000"},
    }
    execute(tmp_path, "claude-code", case)
    content = (tmp_path / ".mcp.json").read_text()
    assert content.index('"type"') < content.index('"url"') < content.index('"headers"')


def test_one_file_is_repaired_once_when_locations_collide(tmp_path: Path) -> None:
    """VS Code declares two locations that both end in `mcp.json`."""
    target = tmp_path / ".vscode" / "mcp.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        '{\n  "servers": {\n    "superdocs": {\n      "type": "http",\n'
        '      "url": "http://api.superdocs.app/mcp",\n'
        '      "headers": { "Authorization": "Bearer sk_fixture_once_00000000" }\n'
        "    }\n  }\n}\n"
    )
    report, _, _ = repair(
        writable("vscode"),
        cwd=tmp_path,
        env={"HOME": str(tmp_path)},
        os_name="darwin",
        client_filter="vscode",
        single_file=target,
    )
    assert report["summary"]["fixed"] == 1
    assert len(list(tmp_path.rglob("*.mcp-doctor-*.bak"))) == 1
