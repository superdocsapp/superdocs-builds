from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcp_doctor.core import load_contract, scan  # noqa: I001
from mcp_doctor.repair import repair


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = load_contract(ROOT / "shared")


def cases(client_id: str) -> list[dict]:
    return json.loads((ROOT / "shared" / "fixtures" / f"{client_id}.cases.json").read_text())["cases"]


def run_case(tmp_path: Path, client_id: str, case: dict) -> dict:
    for relative, contents in case["raw_files"].items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
    env = {
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
        "CODEX_HOME": str(tmp_path / ".codex"),
        "XDG_CONFIG_HOME": str(tmp_path / ".config"),
    }
    for name, value in case.get("env", {}).items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    return scan(CONTRACT, cwd=tmp_path, env=env, os_name="darwin", client_filter=client_id, deterministic=True)


@pytest.mark.parametrize("client_id", ["claude-code", "vscode", "codex", "antigravity"])
def test_shared_scan_corpus(tmp_path: Path, client_id: str) -> None:
    for case in cases(client_id):
        report = run_case(tmp_path / case["name"], client_id, case)
        ids = [finding["id"] for finding in report["findings"]]
        expected = case["expect"]["scan"]
        for want in expected["findings"]:
            assert want["id"] in ids, f"{client_id}/{case['name']}: {ids}"
            got = next(finding for finding in report["findings"] if finding["id"] == want["id"])
            if "severity" in want:
                assert got["severity"] == want["severity"]
            if "auto_fixable" in want:
                assert got["auto_fixable"] == want["auto_fixable"]
        for unwanted in expected.get("must_not_contain_findings", []):
            assert unwanted not in ids, f"{client_id}/{case['name']}: {ids}"
        assert report["exit_code"] == expected["exit_code"], f"{client_id}/{case['name']}: {ids}"


def test_fixture_credentials_never_reach_report(tmp_path: Path) -> None:
    pattern = re.compile(r"\b(?:sk_|lce_|gw_)[A-Za-z0-9_-]{8,}")
    for client_id in ("claude-code", "vscode", "codex", "antigravity"):
        for case in cases(client_id):
            secrets = set(pattern.findall("\n".join(case["raw_files"].values())))
            output = json.dumps(run_case(tmp_path / client_id / case["name"], client_id, case))
            assert all(secret not in output for secret in secrets)


def test_fix_is_an_evidence_gated_refusal_not_a_usage_error(tmp_path: Path) -> None:
    case = next(case for case in cases("claude-code") if case["name"] == "scheme-insecure")
    run_case(tmp_path, "claude-code", case)
    _, lines, code = repair(CONTRACT, cwd=tmp_path, env={"HOME": str(tmp_path)}, os_name="darwin", client_filter="claude-code")
    assert code == 1
    assert "not write-capable" in lines[0]


def test_non_default_port_is_not_the_pinned_host(tmp_path: Path) -> None:
    source = '{"mcpServers":{"superdocs":{"type":"http","url":"https://api.superdocs.app:444/mcp","headers":{}}}}'
    report = run_case(
        tmp_path,
        "claude-code",
        {"raw_files": {".mcp.json": source}, "expect": {"scan": {"findings": [], "exit_code": 0}}},
    )
    assert [finding["id"] for finding in report["findings"]] == ["scope.non-canonical-host"]


def test_whitespace_environment_variable_is_unresolved(tmp_path: Path) -> None:
    source = '{"mcpServers":{"superdocs":{"type":"http","url":"https://api.superdocs.app/mcp","headers":{"Authorization":"Bearer ${SUPERDOCS_API_KEY}"}}}}'
    report = run_case(
        tmp_path,
        "claude-code",
        {"raw_files": {".mcp.json": source}, "env": {"SUPERDOCS_API_KEY": "   "}, "expect": {"scan": {"findings": [], "exit_code": 1}}},
    )
    assert "config.env-placeholder-unresolved" in [finding["id"] for finding in report["findings"]]


def test_strict_json_defaults_and_complete_url_validation(tmp_path: Path) -> None:
    strict = '{ // not legal JSON\n"mcpServers": {}}'
    report = run_case(tmp_path / "strict", "claude-code", {"raw_files": {".mcp.json": strict}})
    assert "config.invalid-syntax" in [item["id"] for item in report["findings"]]

    source = '{"mcpServers":{"superdocs":{"type":"http","url":"https://api.superdocs.app/mcp?x=y","headers":{"Authorization":"Bearer ${MISSING:-sk_fixture_default_0000}"}}}}'
    report = run_case(tmp_path / "url", "claude-code", {"raw_files": {".mcp.json": source}})
    ids = [item["id"] for item in report["findings"]]
    assert "config.url-query-or-fragment" in ids
    assert "config.env-placeholder-unresolved" not in ids

    missing = '{"mcpServers":{"superdocs":{"type":"http","headers":{}}}}'
    report = run_case(tmp_path / "missing", "claude-code", {"raw_files": {".mcp.json": missing}})
    assert "config.url-missing" in [item["id"] for item in report["findings"]]


def test_unparseable_url_omits_host_rather_than_emitting_null(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        '{"mcpServers":{"superdocs":{"type":"http","url":"::::","headers":{}}}}'
    )
    report = scan(
        CONTRACT,
        cwd=tmp_path,
        env={"HOME": str(tmp_path)},
        os_name="darwin",
        client_filter="claude-code",
    )
    entries = [e for f in report["clients"][0]["config_files"] for e in f.get("entries", [])]
    assert entries, report
    assert "host" not in entries[0]


def test_source_tree_wins_over_a_bundled_snapshot(tmp_path: Path, monkeypatch) -> None:
    import mcp_doctor.core as core

    module = Path(core.__file__).resolve()
    bundled = module.parent / "shared"
    assert not bundled.exists(), "a real bundle is present; this test would be meaningless"
    shutil.copytree(ROOT / "shared", bundled)
    try:
        chosen = core.shared_root({})
        assert chosen != bundled, "the stale bundled snapshot shadowed the source tree"
        assert (chosen.parent / "tools" / "validate_contract.py").is_file()
    finally:
        shutil.rmtree(bundled)
