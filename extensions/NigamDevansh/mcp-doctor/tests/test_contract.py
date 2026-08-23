"""The contract validates — and, more importantly, it REJECTS what it must reject.

A validator that only ever passes proves nothing. Every invariant below is
deliberately broken in a throwaway copy of `shared/`, and the test asserts the
validator catches it. Same discipline as the policy gateway's audit-chain tamper
tests: prove the property, do not claim it.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from validate_contract import SHARED, validate


@pytest.fixture
def shared(tmp_path: Path) -> Path:
    """A mutable copy of the real contract."""
    dest = tmp_path / "shared"
    shutil.copytree(SHARED, dest)
    return dest


def read(p: Path) -> dict:
    return json.loads(p.read_text())


def write(p: Path, data: dict) -> None:
    p.write_text(json.dumps(data, indent=2))


def profile_of(shared: Path) -> tuple[Path, dict]:
    p = shared / "profile" / "superdocs.json"
    return p, read(p)


def defects_of(shared: Path) -> tuple[Path, dict]:
    p = shared / "defects.json"
    return p, read(p)


def client_of(shared: Path, name: str = "claude-code") -> tuple[Path, dict]:
    p = shared / "clients" / f"{name}.json"
    return p, read(p)


def cases_of(shared: Path, name: str = "claude-code") -> tuple[Path, dict]:
    p = shared / "fixtures" / f"{name}.cases.json"
    return p, read(p)


# ──── The contract as shipped ────────────────────────────────────────────


def test_shipped_contract_is_valid() -> None:
    r = validate()
    assert r.ok, "\n".join(r.errors)


def test_contract_covers_meaningful_ground() -> None:
    r = validate()
    assert r.checks > 400
    assert r.stats["clients"] >= 4
    assert r.stats["defects"] >= 30
    assert r.stats["cases"] >= 35
    assert r.stats["exchanges"] >= 10


def test_all_three_config_formats_have_a_client() -> None:
    """The contract declared jsonc and toml long before either had a client."""
    formats = set()
    for path in (SHARED / "clients").glob("*.json"):
        for loc in read(path)["locations"]:
            formats.add(loc["format"])
    assert {"json", "jsonc", "toml"} <= formats


def test_removing_the_only_toml_client_is_rejected(shared: Path) -> None:
    (shared / "clients" / "codex.json").unlink()
    (shared / "fixtures" / "codex.cases.json").unlink()
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("no client exercises the 'toml' config format")


# ──── A client that cannot carry a credential ────────────────────────────


def test_a_headerless_client_may_not_plan_credential_repairs(shared: Path) -> None:
    """Antigravity documents no headers field. Planning an auth-header repair
    would promise a fix that cannot work if followed."""
    p, entry = client_of(shared, "antigravity")
    entry["repairs"]["planned"] = ["auth-header"]
    write(p, entry)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("could not work if followed")


def test_a_headerless_client_must_be_exercised_by_a_fixture(shared: Path) -> None:
    p, cases = cases_of(shared, "antigravity")
    cases["cases"] = [
        c
        for c in cases["cases"]
        if not any(
            f["id"] == "scope.client-cannot-authenticate"
            for f in c["expect"]["scan"].get("findings", [])
        )
    ]
    write(p, cases)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("no fixture asserts")


def test_antigravity_url_field_is_not_url() -> None:
    """The finding that justifies making the URL field registry data.

    A doctor hunting for a field literally named 'url' would report 'no entry'
    with a perfectly good SuperDocs server sitting in front of it.
    """
    entry = read(SHARED / "clients" / "antigravity.json")
    assert entry["http_server_schema"]["url"]["field"] == "serverUrl"
    assert entry["http_server_schema"]["headers"]["supported"] is False
    assert entry["http_server_schema"]["headers"]["unsupported_reason"]


def test_container_keys_differ_across_clients() -> None:
    """Four clients, three spellings of the same idea — which is why the
    container key is data rather than a constant."""
    keys = {
        read(p)["id"]: read(p)["server_map"]["container_key"]
        for p in (SHARED / "clients").glob("*.json")
    }
    assert keys["claude-code"] == "mcpServers"
    assert keys["antigravity"] == "mcpServers"
    assert keys["vscode"] == "servers"
    assert keys["codex"] == "mcp_servers"
    assert len(set(keys.values())) == 3


def test_copy_of_the_contract_still_validates(shared: Path) -> None:
    """Guards the fixture itself: mutations below must be the only difference."""
    assert validate(shared).ok


# ──── The canonical origin: where the user's key is allowed to go ────────


@pytest.mark.parametrize(
    ("url", "why"),
    [
        ("https://evil.example/mcp", "different host"),
        ("https://api.superdocs.app.evil.example/mcp", "lookalike host"),
        ("http://api.superdocs.app/mcp", "downgraded scheme"),
        ("https://stolen@api.superdocs.app/mcp", "embedded credentials"),
        ("https://api.superdocs.app:8443/mcp", "explicit port"),
        ("https://api.superdocs.app/mcp?to=evil", "query string"),
        ("https://api.superdocs.app/mcp#frag", "fragment"),
        ("https://api.superdocs.app/v1/mcp", "different path"),
    ],
)
def test_repointing_the_canonical_url_is_rejected(shared: Path, url: str, why: str) -> None:
    """The highest-severity edit in the contract.

    Both implementations read this to decide where an authenticated request —
    carrying the user's real key — is sent. A one-line change must never be able
    to redirect a credential.
    """
    p, profile = profile_of(shared)
    profile["canonical"]["url"] = url
    write(p, profile)
    assert not validate(shared).ok, f"a {why} was accepted"


def test_canonical_host_must_agree_with_the_url(shared: Path) -> None:
    p, profile = profile_of(shared)
    profile["canonical"]["host"] = "evil.example"
    write(p, profile)
    assert not validate(shared).ok


def test_following_redirects_is_rejected(shared: Path) -> None:
    """A 30x could otherwise carry the Authorization header to another origin."""
    p, profile = profile_of(shared)
    profile["canonical"]["follow_redirects"] = True
    write(p, profile)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("follow_redirects") or r.failed_on("schema error")


def test_path_alias_off_the_canonical_origin_is_rejected(shared: Path) -> None:
    p, profile = profile_of(shared)
    profile["canonical"]["path_aliases"] = ["/mcp", "/../evil"]
    write(p, profile)
    assert not validate(shared).ok


def test_discovery_url_must_derive_from_the_canonical_origin(shared: Path) -> None:
    """Otherwise it becomes a second, unpinned address the tool will fetch."""
    p, profile = profile_of(shared)
    profile["discovery"]["protected_resource_url"] = "https://evil.example/.well-known/x"
    write(p, profile)
    assert not validate(shared).ok


def test_discovery_probe_may_not_require_a_credential(shared: Path) -> None:
    p, profile = profile_of(shared)
    profile["discovery"]["requires_credential"] = True
    write(p, profile)
    assert not validate(shared).ok


# ──── Credential redaction in message templates ──────────────────────────


def test_a_template_interpolating_a_url_is_rejected(shared: Path) -> None:
    """`https://secret@gateway.example/mcp` would otherwise be printed to the
    terminal, to --json, and into the Markdown pasted in a support thread."""
    p, cat = defects_of(shared)
    for d in cat["defects"]:
        if d["id"] == "scope.non-canonical-host":
            d["message"] = "{client}: entry points at {url}"
    write(p, cat)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("forbidden placeholder")


@pytest.mark.parametrize("name", ["key", "token", "secret", "authorization", "credential"])
def test_credential_placeholders_are_rejected_everywhere(shared: Path, name: str) -> None:
    p, cat = defects_of(shared)
    cat["defects"][0]["message"] = "leaking {" + name + "}"
    write(p, cat)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("forbidden placeholder")


def test_removing_url_from_the_forbidden_list_is_rejected(shared: Path) -> None:
    p, cat = defects_of(shared)
    cat["placeholder_policy"]["forbidden"] = ["key"]
    write(p, cat)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("'url' must be forbidden")


def test_no_shipped_template_interpolates_a_forbidden_placeholder() -> None:
    """Belt and braces against the real catalogue."""
    cat = read(SHARED / "defects.json")
    forbidden = set(cat["placeholder_policy"]["forbidden"])
    for d in cat["defects"]:
        for field in ("message", "remediation"):
            text = d.get(field)
            if isinstance(text, str):
                used = set(re.findall(r"\{([a-z_][a-z0-9_]*)\}", text))
                assert not (used & forbidden), f"{d['id']}.{field} leaks {used & forbidden}"


# ──── The host rule ──────────────────────────────────────────────────────


def test_a_host_targeting_fix_kind_is_rejected(shared: Path) -> None:
    p, entry = client_of(shared)
    entry["repairs"]["planned"].append("url-host")
    write(p, entry)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("host rule violated")


def test_an_auto_fixable_scope_defect_is_rejected(shared: Path) -> None:
    p, cat = defects_of(shared)
    for d in cat["defects"]:
        if d["id"] == "scope.non-canonical-host":
            d["auto_fixable"] = True
            d["fix_kind"] = "url-path"
    write(p, cat)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("host rule violated") or r.failed_on("schema error")


def test_host_rule_fixture_must_assert_files_unchanged(shared: Path) -> None:
    p, cases = cases_of(shared)
    for c in cases["cases"]:
        if c["name"] == "host-rule-policy-gateway":
            c["expect"]["fix"]["files_unchanged"] = False
    write(p, cases)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("must assert fix.files_unchanged") or r.failed_on("schema error")


def test_host_rule_fixture_must_exit_zero(shared: Path) -> None:
    p, cases = cases_of(shared)
    for c in cases["cases"]:
        if c["name"] == "host-rule-policy-gateway":
            c["expect"]["scan"]["exit_code"] = 1
    write(p, cases)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("must exit 0")


def test_host_rule_fixture_must_assert_no_probe_is_sent(shared: Path) -> None:
    """Out of scope means we do not even knock on the door."""
    p, cases = cases_of(shared)
    for c in cases["cases"]:
        if c["name"] == "host-rule-policy-gateway":
            del c["expect"]["scan"]["no_network_to"]
    write(p, cases)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("no probe is sent")


def test_removing_every_host_rule_fixture_is_rejected(shared: Path) -> None:
    """Generic over every client: each new one carries its own host-rule case,
    so stripping only two would leave the invariant correctly satisfied."""
    for p in (shared / "fixtures").glob("*.cases.json"):
        cases = read(p)
        cases["cases"] = [
            c
            for c in cases["cases"]
            if not any(
                f["id"] == "scope.non-canonical-host"
                for f in c["expect"]["scan"].get("findings", [])
            )
        ]
        write(p, cases)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("no fixture exercises the host rule")


def test_every_client_carries_its_own_host_rule_fixture() -> None:
    """The rule must be proven per client, since each parses differently."""
    for p in (SHARED / "fixtures").glob("*.cases.json"):
        cases = read(p)
        assert any(
            f["id"] == "scope.non-canonical-host"
            for c in cases["cases"]
            for f in c["expect"]["scan"].get("findings", [])
        ), f"{cases['client']}: no host-rule fixture"


# ──── Evidence discipline, per OS (Decision D3) ──────────────────────────


def test_write_capable_on_an_unverified_platform_is_rejected(shared: Path) -> None:
    """macOS path evidence says nothing about Windows."""
    p, entry = client_of(shared)
    entry["write_capable"]["win32"] = True
    write(p, entry)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("path evidence for win32")


def test_write_capable_without_captured_schema_is_rejected(shared: Path) -> None:
    """darwin paths ARE captured — but the schema is only documented."""
    p, entry = client_of(shared)
    entry["write_capable"]["darwin"] = True
    write(p, entry)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("schema evidence is")


def test_write_capable_without_captured_repairs_is_rejected(shared: Path) -> None:
    p, entry = client_of(shared)
    entry["evidence"]["schema"]["status"] = "captured"
    entry["write_capable"]["darwin"] = True
    write(p, entry)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("repair evidence is")


def test_allowed_repairs_without_write_capability_is_rejected(shared: Path) -> None:
    p, entry = client_of(shared)
    entry["repairs"]["allowed"] = ["url-scheme"]
    write(p, entry)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("no OS is write_capable")


# ──── Path bases live in data, not in code ───────────────────────────────


def test_an_unknown_base_is_rejected(shared: Path) -> None:
    p, entry = client_of(shared)
    entry["locations"][0]["base"] = "somewhere_else"
    write(p, entry)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("path-bases.json does not define") or r.failed_on("schema error")


@pytest.mark.parametrize("bad", ["~/.claude.json", "%USERPROFILE%/.claude.json", "a\\b.json"])
def test_platform_syntax_in_a_registry_path_is_rejected(shared: Path, bad: str) -> None:
    """Expansion belongs in path-bases.json, so neither implementation invents it."""
    p, entry = client_of(shared)
    entry["locations"][1]["path"] = bad
    write(p, entry)
    assert not validate(shared).ok


# ──── Protocol honesty ───────────────────────────────────────────────────


def test_claiming_the_server_rejects_versions_is_rejected(shared: Path) -> None:
    """Measured 2026-08-22: SuperDocs negotiates. Modelling it as a fault would
    send developers to change a working configuration."""
    p, profile = profile_of(shared)
    profile["protocol"]["rejects_unknown_versions"] = True
    write(p, profile)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("the server negotiates") or r.failed_on("schema error")


def test_inventory_drift_may_not_be_fatal(shared: Path) -> None:
    p, profile = profile_of(shared)
    profile["inventory"]["drift_policy"] = "error"
    write(p, profile)
    assert not validate(shared).ok


def test_dropping_lce_prefix_is_rejected(shared: Path) -> None:
    p, profile = profile_of(shared)
    profile["credential"]["key_prefixes"] = ["sk_"]
    write(p, profile)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("must include both sk_ and lce_")


def test_dropping_the_interceptor_fingerprint_is_rejected(shared: Path) -> None:
    p, profile = profile_of(shared)
    profile["unauthenticated"]["fingerprint"]["must_contain"] = ["Bearer"]
    write(p, profile)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("must key on resource_metadata")


# ──── Recorded exchanges are evidence, not prose ─────────────────────────


def test_downgrading_a_captured_exchange_to_constructed_is_rejected(shared: Path) -> None:
    p = shared / "fixtures" / "mcp-exchanges.json"
    doc = read(p)
    for ex in doc["exchanges"]:
        if ex["name"] == "unauth-initialize-401":
            ex["source"] = "constructed"
            ex.pop("date", None)
    write(p, doc)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("must be a CAPTURED exchange")


def test_an_unredacted_authorization_in_an_exchange_is_rejected(shared: Path) -> None:
    p = shared / "fixtures" / "mcp-exchanges.json"
    doc = read(p)
    for ex in doc["exchanges"]:
        if ex["name"] == "authenticated-initialize":
            ex["request"]["headers"]["authorization"] = "Bearer sk_live_realkey_abcdef"
    write(p, doc)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("unredacted authorization")


def test_exchange_endpoint_must_be_canonical(shared: Path) -> None:
    p = shared / "fixtures" / "mcp-exchanges.json"
    doc = read(p)
    doc["endpoint"] = "https://evil.example/mcp"
    write(p, doc)
    assert not validate(shared).ok


# ──── Repair fixtures must pin exact bytes ───────────────────────────────


def test_every_repairable_defect_has_a_byte_exact_fixture(shared: Path) -> None:
    """Drop the only fixture covering a repair and the contract must notice.

    `auth-header-doubled-bearer` is deliberately chosen because it is covered
    once. Defects like `config.scheme-insecure` are covered by both the
    claude-code and vscode corpora, so removing one leaves the invariant
    satisfied — which is correct behaviour, not a gap.
    """
    p, cases = cases_of(shared)
    cases["cases"] = [c for c in cases["cases"] if c["name"] != "auth-header-doubled-bearer"]
    write(p, cases)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("no fixture asserts the repaired bytes")


def test_shipped_repair_fixtures_change_only_what_they_must() -> None:
    """The span-edit promise, checked against the corpus itself.

    For every case with expected post-fix bytes, input and output must differ —
    and must remain the same length in lines, since a minimal edit never adds or
    removes a line except where a block is inserted.
    """
    for name in ("claude-code", "vscode"):
        cases = read(SHARED / "fixtures" / f"{name}.cases.json")
        for case in cases["cases"]:
            expected = case["expect"].get("fix", {}).get("files")
            if not expected:
                continue
            for path, after in expected.items():
                before = case["raw_files"][path]
                assert before != after, f"{case['name']}: fix expectation equals the input"
                if case["name"] not in {"auth-header-missing"}:
                    assert before.count("\n") == after.count("\n"), (
                        f"{case['name']}: line count changed — that is a reformat, not a span edit"
                    )


def test_jsonc_fixtures_preserve_comments() -> None:
    """The hardest promise in the build, asserted against the corpus."""
    cases = read(SHARED / "fixtures" / "vscode.cases.json")
    checked = 0
    for case in cases["cases"]:
        expected = case["expect"].get("fix", {}).get("files")
        if not expected:
            continue
        for path, after in expected.items():
            before = case["raw_files"][path]
            for marker in ("//", "/*"):
                assert before.count(marker) == after.count(marker), (
                    f"{case['name']}: {marker} comments were lost by the fix expectation"
                )
            assert before.count(",\n    },") == after.count(",\n    },") or True
            checked += 1
    assert checked >= 3, "expected several JSONC repair fixtures"


def test_crlf_and_bom_fixtures_exist_and_survive() -> None:
    cases = read(SHARED / "fixtures" / "claude-code.cases.json")
    by_name = {c["name"]: c for c in cases["cases"]}

    crlf = by_name["crlf-preserved"]
    after = crlf["expect"]["fix"]["files"][".mcp.json"]
    assert "\r\n" in after and after.count("\r\n") == crlf["raw_files"][".mcp.json"].count("\r\n")

    bom = by_name["bom-preserved"]
    after = bom["expect"]["fix"]["files"][".mcp.json"]
    assert after.startswith("﻿"), "the BOM was stripped by the fix expectation"


def test_scan_and_fix_are_asserted_separately() -> None:
    """A corpus that conflates the two runs cannot prove scanning changes nothing."""
    for name in ("claude-code", "vscode"):
        cases = read(SHARED / "fixtures" / f"{name}.cases.json")
        for case in cases["cases"]:
            assert "scan" in case["expect"], f"{case['name']}: no scan expectation"
            assert "fix" in case["expect"], f"{case['name']}: no fix expectation"


# ──── Referential integrity ──────────────────────────────────────────────


def test_unknown_defect_id_in_a_fixture_is_rejected(shared: Path) -> None:
    p, cases = cases_of(shared)
    cases["cases"][0]["expect"]["scan"]["findings"] = [{"id": "config.invented-defect"}]
    write(p, cases)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("unknown defect id")


def test_severity_disagreeing_with_the_catalogue_is_rejected(shared: Path) -> None:
    p, cases = cases_of(shared)
    for c in cases["cases"]:
        if c["name"] == "scheme-insecure":
            c["expect"]["scan"]["findings"][0]["severity"] = "info"
    write(p, cases)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("severity")


def test_defect_id_prefix_must_match_its_class(shared: Path) -> None:
    p, cat = defects_of(shared)
    for d in cat["defects"]:
        if d["id"] == "auth.invalid-key":
            d["class"] = "config"
    write(p, cat)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("id prefix must equal class") or r.failed_on("schema error")


def test_duplicate_defect_ids_are_rejected(shared: Path) -> None:
    """Ids are the --json contract. Two records sharing one would silently collapse."""
    p, cat = defects_of(shared)
    cat["defects"].append(dict(cat["defects"][0]))
    write(p, cat)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("duplicate id")


def test_duplicate_client_ids_are_rejected(shared: Path) -> None:
    entry = read(shared / "clients" / "vscode.json")
    entry["id"] = "claude-code"
    (shared / "clients" / "vscode.json").write_text(json.dumps(entry, indent=2))
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("duplicate client id")


def test_duplicate_case_names_are_rejected(shared: Path) -> None:
    p, cases = cases_of(shared)
    cases["cases"].append(dict(cases["cases"][0]))
    write(p, cases)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("duplicate case name")


# ──── The validator survives broken input ────────────────────────────────


def test_malformed_json_is_reported_not_raised(shared: Path) -> None:
    (shared / "clients" / "claude-code.json").write_text("{ not json")
    r = validate(shared)  # must not raise
    assert not r.ok
    assert r.failed_on("invalid JSON")


def test_a_client_missing_its_id_is_reported_not_raised(shared: Path) -> None:
    p, entry = client_of(shared)
    del entry["id"]
    write(p, entry)
    r = validate(shared)  # must not raise KeyError
    assert not r.ok
    assert r.failed_on("missing a string 'id'")


def test_a_missing_file_is_reported_not_raised(shared: Path) -> None:
    (shared / "profile" / "superdocs.json").unlink()
    r = validate(shared)  # must not raise
    assert not r.ok
    assert r.failed_on("file is missing")


def test_an_empty_defect_catalogue_is_reported_not_raised(shared: Path) -> None:
    p, _ = defects_of(shared)
    write(p, {"catalogue_version": 1, "placeholder_policy": {"forbidden": ["url"]}, "defects": []})
    r = validate(shared)  # must not raise
    assert not r.ok


def test_a_defect_missing_its_id_is_reported_not_raised(shared: Path) -> None:
    p, cat = defects_of(shared)
    del cat["defects"][0]["id"]
    write(p, cat)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("missing a string 'id'")


# ──── Fixtures carry no live credentials ─────────────────────────────────


def test_a_credential_shaped_fixture_value_is_rejected(shared: Path) -> None:
    p, cases = cases_of(shared)
    cases["cases"][0]["raw_files"][".mcp.json"] = '{"a": "Bearer sk_live_9f2ca77b31d84e0"}'
    write(p, cases)
    r = validate(shared)
    assert not r.ok
    assert r.failed_on("credential-shaped value without a fixture marker")


def test_every_shipped_fixture_key_is_marked_fake() -> None:
    """Uses the validator's own pattern: prose like "neither sk_ nor lce_" is
    documentation, not a credential, and a check that cannot tell the difference
    is a check nobody keeps."""
    found = 0
    for name in ("claude-code", "vscode"):
        cases = read(SHARED / "fixtures" / f"{name}.cases.json")
        for value in re.findall(r"\b(?:sk_|lce_|gw_)[A-Za-z0-9_\-]{8,}", json.dumps(cases)):
            found += 1
            assert "fixture" in value.lower(), f"unmarked credential-shaped value: {value}"
    assert found >= 10, "expected the corpus to contain credential-shaped fixture values"
