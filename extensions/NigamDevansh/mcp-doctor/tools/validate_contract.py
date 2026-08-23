# The gate on shared/. No implementation exists yet, so this script is what makes
# delivery step 1 a verifiable artifact rather than a folder of hopeful JSON.
#
# Three jobs:
#   1. schema validation      — every data file matches its JSON Schema
#   2. referential integrity  — ids, fix kinds and bases resolve to something real
#   3. INVARIANTS             — the rules that would otherwise live only in prose
#
# The third earns its keep. "--fix never changes a host", "the key only ever goes
# to one pinned origin", "write access is earned per OS" are exactly the sort of
# rule that rots quietly in a document. Here they fail a build.
#
# This script must also FAIL GRACEFULLY. It runs against data that may be broken
# in arbitrary ways, so it never assumes a field survived schema validation: a
# malformed file produces a readable finding, never a traceback.

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

SHARED = Path(__file__).resolve().parents[1] / "shared"

# The single address that ever receives a user's key.
CANONICAL_URL = "https://api.superdocs.app/mcp"
CANONICAL_HOST = "api.superdocs.app"
CANONICAL_PATH = "/mcp"

# The host rule (PLAN §6): --fix may repair a URL's scheme, path or trailing
# slash but NEVER its host. Enforced by forbidding such a fix kind from existing.
FORBIDDEN_FIX_KINDS = {"url-host", "host", "url-authority", "url-origin"}

FIXTURE_KEY_MARKERS = ("fixture", "example", "placeholder", "redacted")
KEY_LIKE = re.compile(r"\b(?:sk_|lce_|gw_)[A-Za-z0-9_\-]{8,}")
PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")

OSES = ("darwin", "linux", "win32")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.checks = 0
        self.stats: dict[str, int] = {}

    def check(self, ok: bool, message: str) -> bool:
        self.checks += 1
        if not ok:
            self.errors.append(message)
        return bool(ok)

    @property
    def ok(self) -> bool:
        return not self.errors

    def failed_on(self, needle: str) -> bool:
        """Did any failure mention this? Used by the negative tests."""
        return any(needle in e for e in self.errors)


def load(r: Report, path: Path, label: str) -> Any:
    """Read JSON without ever raising: a broken file is a finding, not a crash."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        r.check(False, f"{label}: file is missing")
    except UnicodeDecodeError as exc:
        r.check(False, f"{label}: not valid UTF-8 ({exc})")
    except json.JSONDecodeError as exc:
        r.check(False, f"{label}: invalid JSON at line {exc.lineno}, column {exc.colno}")
    return None


def validate_schema(r: Report, data: Any, schema_path: Path, label: str) -> bool:
    if data is None:
        return False
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        r.check(False, f"{label}: its schema {schema_path.name} could not be read ({exc})")
        return False
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
    ok = r.check(not errors, f"{label}: {len(errors)} schema error(s)")
    for e in errors[:10]:
        loc = "/".join(str(p) for p in e.path) or "(root)"
        r.errors.append(f"    {label} at {loc}: {e.message}")
    return ok


def dig(node: Any, *keys: str, default: Any = None) -> Any:
    """Fetch a nested value without assuming any level exists."""
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def index_unique(r: Report, items: Any, key: str, label: str) -> dict[str, Any]:
    """Index by a stable id, REPORTING duplicates instead of silently overwriting.

    Ids here are part of the --json contract. Two records sharing one would
    collapse into a single entry and quietly change what the tool can emit.
    """
    out: dict[str, Any] = {}
    if not isinstance(items, list):
        r.check(False, f"{label}: expected a list")
        return out
    for i, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get(key), str):
            r.check(False, f"{label}[{i}]: missing a string '{key}'")
            continue
        ident = item[key]
        if ident in out:
            r.check(False, f"{label}: duplicate {key} '{ident}' — ids must be unique")
            continue
        out[ident] = item
    return out


def walk_strings(node: Any) -> list[str]:
    out: list[str] = []
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for v in node.values():
            out.extend(walk_strings(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(walk_strings(v))
    return out


def validate(shared: Path = SHARED) -> Report:
    r = Report()
    sd = shared / "schema"

    # ── 1 · load and schema-validate ─────────────────────────────────────
    profile = load(r, shared / "profile" / "superdocs.json", "profile/superdocs.json")
    validate_schema(r, profile, sd / "endpoint-profile.schema.json", "profile/superdocs.json")

    catalogue = load(r, shared / "defects.json", "defects.json")
    validate_schema(r, catalogue, sd / "defect-catalogue.schema.json", "defects.json")

    bases_doc = load(r, shared / "path-bases.json", "path-bases.json")
    validate_schema(r, bases_doc, sd / "path-bases.schema.json", "path-bases.json")

    clients: dict[str, Any] = {}
    for path in sorted((shared / "clients").glob("*.json")):
        label = f"clients/{path.name}"
        entry = load(r, path, label)
        validate_schema(r, entry, sd / "client-registry.schema.json", label)
        cid = dig(entry, "id")
        if not isinstance(cid, str):
            r.check(False, f"{label}: missing a string 'id'")
            continue
        if cid in clients:
            r.check(False, f"{label}: duplicate client id '{cid}'")
            continue
        clients[cid] = entry

    fixtures: dict[str, Any] = {}
    for path in sorted((shared / "fixtures").glob("*.cases.json")):
        label = f"fixtures/{path.name}"
        cases = load(r, path, label)
        if validate_schema(r, cases, sd / "fixture-cases.schema.json", label):
            fixtures[path.name] = cases

    exchanges_doc = load(
        r, shared / "fixtures" / "mcp-exchanges.json", "fixtures/mcp-exchanges.json"
    )
    validate_schema(
        r, exchanges_doc, sd / "mcp-exchanges.schema.json", "fixtures/mcp-exchanges.json"
    )

    r.check(bool(clients), "at least one client registry entry must exist")
    r.check(bool(fixtures), "at least one fixture case file must exist")

    defects = index_unique(r, dig(catalogue, "defects", default=[]), "id", "defects.json/defects")
    exchanges = index_unique(
        r, dig(exchanges_doc, "exchanges", default=[]), "name", "mcp-exchanges/exchanges"
    )

    # ── 2 · the canonical origin ─────────────────────────────────────────
    # The highest-severity object in the contract: both implementations read it
    # to decide where an authenticated request goes. A silent edit here would
    # redirect every user's credential, so it is pinned and then re-parsed.
    canon = dig(profile, "canonical", default={})
    url = canon.get("url")
    if r.check(isinstance(url, str), "profile: canonical.url must be a string"):
        r.check(url == CANONICAL_URL, f"profile: canonical.url must be exactly {CANONICAL_URL}")
        parts = urlsplit(url)
        r.check(parts.scheme == "https", "profile: canonical URL must be https")
        r.check("@" not in parts.netloc, "profile: canonical URL must not embed credentials")
        r.check(parts.netloc == CANONICAL_HOST, f"profile: canonical host must be {CANONICAL_HOST}")
        try:
            r.check(parts.port is None, "profile: canonical URL must not specify a port")
        except ValueError:
            r.check(False, "profile: canonical URL has an invalid port")
        r.check(parts.path == CANONICAL_PATH, f"profile: canonical path must be {CANONICAL_PATH}")
        r.check(not parts.query, "profile: canonical URL must not carry a query string")
        r.check(not parts.fragment, "profile: canonical URL must not carry a fragment")

    r.check(
        canon.get("host") == CANONICAL_HOST and canon.get("path") == CANONICAL_PATH,
        "profile: canonical host/path must agree with canonical.url",
    )
    r.check(
        canon.get("follow_redirects") is False,
        "profile: follow_redirects must be false — a 30x could carry the key to another origin",
    )
    for alias in canon.get("path_aliases", []) or []:
        r.check(
            isinstance(alias, str) and alias.rstrip("/") == CANONICAL_PATH.rstrip("/"),
            f"profile: path alias '{alias}' is not a path on the canonical origin",
        )

    # The discovery URL is DERIVED, never a second independent address.
    disco = dig(profile, "discovery", default={})
    suffix = disco.get("path_suffix")
    if isinstance(url, str) and isinstance(suffix, str):
        r.check(
            disco.get("protected_resource_url") == url + suffix,
            "profile: discovery URL must be canonical.url + path_suffix",
        )
    r.check(
        disco.get("requires_credential") is False,
        "profile: the discovery probe must never carry a credential",
    )

    # ── 3 · referential integrity ────────────────────────────────────────
    for did, d in defects.items():
        r.check(
            did.split(".")[0] == d.get("class"),
            f"defect {did}: id prefix must equal class '{d.get('class')}'",
        )

    forbidden_names = set(dig(catalogue, "placeholder_policy", "forbidden", default=[]))
    r.check(bool(forbidden_names), "defects.json: placeholder_policy.forbidden must be populated")
    r.check(
        "url" in forbidden_names,
        "defects.json: 'url' must be forbidden — a URL can carry a credential in its userinfo",
    )
    for did, d in defects.items():
        for field in ("message", "remediation"):
            text = d.get(field)
            if not isinstance(text, str):
                continue
            for name in PLACEHOLDER.findall(text):
                r.check(
                    name not in forbidden_names,
                    f"defect {did}: {field} interpolates forbidden placeholder "
                    f"'{{{name}}}' — it can leak a credential into the terminal, --json "
                    f"and the shareable report",
                )

    known_bases = set(dig(bases_doc, "bases", default={}).keys())
    for cid, entry in clients.items():
        for i, loc in enumerate(entry.get("locations", []) or []):
            base = loc.get("base")
            r.check(
                base in known_bases,
                f"clients/{cid}: location[{i}] uses base '{base}' which path-bases.json "
                f"does not define",
            )
            path_value = loc.get("path", "")
            r.check(
                isinstance(path_value, str)
                and "~" not in path_value
                and "%" not in path_value
                and "\\" not in path_value,
                f"clients/{cid}: location[{i}] path '{path_value}' embeds platform syntax; "
                f"expansion belongs in path-bases.json",
            )
            for os_name in loc.get("os", []) or []:
                r.check(
                    os_name in OSES, f"clients/{cid}: location[{i}] names unknown OS '{os_name}'"
                )

    for name, cases in fixtures.items():
        r.check(
            cases.get("client") in clients,
            f"{name}: client '{cases.get('client')}' has no registry entry",
        )
        seen: set[str] = set()
        for case in cases.get("cases", []):
            cname = case.get("name", "?")
            if cname in seen:
                r.check(False, f"{name}: duplicate case name '{cname}'")
            seen.add(cname)

            for phase in ("scan", "fix"):
                block = dig(case, "expect", phase)
                if not isinstance(block, dict):
                    continue
                for f in block.get("findings", []) or []:
                    fid = f.get("id")
                    if not r.check(
                        fid in defects, f"{name}/{cname}.{phase}: unknown defect id '{fid}'"
                    ):
                        continue
                    d = defects[fid]
                    if "severity" in f:
                        r.check(
                            f["severity"] == d.get("severity"),
                            f"{name}/{cname}.{phase}: '{fid}' severity {f['severity']} "
                            f"!= catalogue {d.get('severity')}",
                        )
                    if "auto_fixable" in f:
                        r.check(
                            f["auto_fixable"] == d.get("auto_fixable"),
                            f"{name}/{cname}.{phase}: '{fid}' auto_fixable "
                            f"{f['auto_fixable']} != catalogue {d.get('auto_fixable')}",
                        )
                for fid in block.get("must_not_contain_findings", []) or []:
                    r.check(
                        fid in defects,
                        f"{name}/{cname}.{phase}: must_not_contain unknown defect '{fid}'",
                    )

    # ── 4 · invariants ───────────────────────────────────────────────────

    # 4a · The host rule: no fix kind may target a host, anywhere.
    all_fix_kinds = {d["fix_kind"] for d in defects.values() if d.get("fix_kind")}
    for entry in clients.values():
        repairs = entry.get("repairs", {}) or {}
        all_fix_kinds |= set(repairs.get("allowed", []) or [])
        all_fix_kinds |= set(repairs.get("planned", []) or [])
    leaked = all_fix_kinds & FORBIDDEN_FIX_KINDS
    r.check(not leaked, f"host rule violated: fix kind(s) targeting a host exist: {sorted(leaked)}")

    # 4b · Nothing out-of-scope may ever be auto-fixed.
    for did, d in defects.items():
        if d.get("class") == "scope":
            r.check(
                d.get("auto_fixable") is False,
                f"host rule violated: scope defect {did} is marked auto_fixable",
            )

    # 4c · write_capable is DERIVED, per OS, never asserted alone.
    for cid, entry in clients.items():
        ev = entry.get("evidence", {}) or {}
        schema_ok = dig(ev, "schema", "status") == "captured"
        repairs_ok = dig(ev, "repairs", "status") == "captured"
        wc = entry.get("write_capable", {}) or {}
        for os_name in OSES:
            if wc.get(os_name) is not True:
                continue
            r.check(
                dig(ev, "paths", os_name, "status") == "captured",
                f"clients/{cid}: write_capable.{os_name} is true but path evidence for "
                f"{os_name} is '{dig(ev, 'paths', os_name, 'status')}' (must be 'captured')",
            )
            r.check(
                schema_ok,
                f"clients/{cid}: write_capable.{os_name} is true but schema evidence is "
                f"'{dig(ev, 'schema', 'status')}'",
            )
            r.check(
                repairs_ok,
                f"clients/{cid}: write_capable.{os_name} is true but repair evidence is "
                f"'{dig(ev, 'repairs', 'status')}'",
            )
        if (entry.get("repairs", {}) or {}).get("allowed"):
            r.check(
                any(wc.get(o) is True for o in OSES),
                f"clients/{cid}: repairs.allowed is non-empty while no OS is write_capable",
            )

    # 4c-bis · A client that cannot carry a credential must not plan credential
    #          repairs, and must be exercised by a fixture that says so.
    cannot_auth = {
        cid
        for cid, e in clients.items()
        if dig(e, "http_server_schema", "headers", "supported") is False
    }
    for cid in cannot_auth:
        planned = set(dig(clients[cid], "repairs", "planned", default=[]) or [])
        impossible = planned & {"auth-header", "accept-header", "add-entry"}
        r.check(
            not impossible,
            f"clients/{cid}: has no header mechanism yet plans {sorted(impossible)} — "
            f"a repair that could not work if followed",
        )
        exercised_here = any(
            f.get("id") == "scope.client-cannot-authenticate"
            for cases in fixtures.values()
            if cases.get("client") == cid
            for c in cases.get("cases", [])
            for f in dig(c, "expect", "scan", "findings", default=[])
        )
        r.check(
            exercised_here,
            f"clients/{cid}: cannot authenticate, but no fixture asserts "
            f"scope.client-cannot-authenticate",
        )

    # 4c-quater · Regexes in the contract must compile in BOTH languages.
    #
    # Found the hard way: `(?i)^superdocs` is valid Python and throws
    # "Invalid group" in JavaScript. Inline flag groups are Python-only, so
    # flags live in a `flags` field and the pattern stays portable.
    inline_flags = re.compile(r"\(\?[aiLmsux]+\)")
    for cid, entry in clients.items():
        for i, rule in enumerate(dig(entry, "identification", "rules", default=[]) or []):
            pattern = rule.get("matches")
            if not isinstance(pattern, str):
                continue
            r.check(
                not inline_flags.search(pattern),
                f"clients/{cid}: identification rule {i} uses an inline flag group in "
                f"'{pattern}' — Python-only syntax that throws in JavaScript. Use `flags`.",
            )
            try:
                re.compile(pattern)
            except re.error as exc:
                r.check(False, f"clients/{cid}: identification rule {i} will not compile ({exc})")
            for flag in rule.get("flags", "") or "":
                r.check(
                    flag in "imsu",
                    f"clients/{cid}: identification rule {i} uses flag '{flag}', which is "
                    f"not portable between Python and JavaScript",
                )

    # 4c-ter · Every declared config format must have a client behind it.
    #          The contract named jsonc and toml long before either had one.
    declared_formats = {
        loc.get("format") for e in clients.values() for loc in e.get("locations", []) or []
    }
    for fmt in ("json", "jsonc", "toml"):
        r.check(fmt in declared_formats, f"no client exercises the '{fmt}' config format")

    # 4d · Every fixable defect names a fix kind some client could actually run.
    for did, d in defects.items():
        if d.get("auto_fixable"):
            known = any(
                d.get("fix_kind")
                in ((e.get("repairs", {}) or {}).get("allowed", []) or [])
                + ((e.get("repairs", {}) or {}).get("planned", []) or [])
                for e in clients.values()
            )
            r.check(
                known, f"defect {did}: fix_kind '{d.get('fix_kind')}' is not planned by any client"
            )

    # 4e · Protocol negotiation must never be modelled as a fault.
    r.check(
        dig(profile, "protocol", "rejects_unknown_versions") is False,
        "profile: rejects_unknown_versions must stay false — the server negotiates",
    )
    r.check(
        not any(d.get("class") == "config" and "version" in did for did, d in defects.items()),
        "a protocol version must never be a config defect; drift.protocol-version is its only home",
    )
    r.check(
        dig(profile, "inventory", "drift_policy") == "warn",
        "profile: inventory drift must warn, never fail a working connection",
    )

    # 4f · Both key prefixes are real. Accepting only sk_ rejects valid keys.
    r.check(
        set(dig(profile, "credential", "key_prefixes", default=[])) >= {"sk_", "lce_"},
        "profile: key_prefixes must include both sk_ and lce_",
    )

    # 4g · The fingerprint separating a real 401 from an interceptor.
    r.check(
        any(
            "resource_metadata" in s
            for s in dig(profile, "unauthenticated", "fingerprint", "must_contain", default=[])
        ),
        "profile: the 401 fingerprint must key on resource_metadata",
    )
    r.check(
        "network.interceptor" in defects, "a defect must exist for a 401 lacking the fingerprint"
    )

    # 4h · The host rule must be proven by fixtures, not asserted in prose.
    host_cases = [
        (name, c)
        for name, cases in fixtures.items()
        for c in cases.get("cases", [])
        if any(
            f.get("id") == "scope.non-canonical-host"
            for f in dig(c, "expect", "scan", "findings", default=[])
        )
    ]
    r.check(bool(host_cases), "no fixture exercises the host rule")
    for name, c in host_cases:
        cname = c.get("name", "?")
        fix = dig(c, "expect", "fix", default={})
        r.check(
            fix.get("files_unchanged") is True,
            f"{name}/{cname}: a host-rule fixture must assert fix.files_unchanged",
        )
        r.check(
            dig(c, "expect", "scan", "exit_code") == 0,
            f"{name}/{cname}: a host-rule fixture must exit 0 — out of scope is not a fault",
        )
        r.check(
            bool(dig(c, "expect", "scan", "no_network_to")),
            f"{name}/{cname}: a host-rule fixture must assert no probe is sent to the host",
        )

    # 4i · A scan is read-only, so no scan block may claim to have changed a file.
    #      And every repairable defect must be exercised by at least one fixture.
    exercised: set[str] = set()
    for cases in fixtures.values():
        for c in cases.get("cases", []):
            for f in dig(c, "expect", "fix", "findings", default=[]):
                if f.get("fixed") is True:
                    exercised.add(f.get("id"))
    for did, d in defects.items():
        if d.get("auto_fixable") and d.get("fix_kind") != "add-entry":
            r.check(
                did in exercised,
                f"defect {did} is auto_fixable but no fixture asserts the repaired bytes",
            )

    # 4j · Fixtures carry no live credentials.
    for name, cases in fixtures.items():
        for s in walk_strings(cases):
            for m in KEY_LIKE.finditer(s):
                value = m.group(0)
                r.check(
                    any(mark in value.lower() for mark in FIXTURE_KEY_MARKERS),
                    f"{name}: credential-shaped value without a fixture marker: {value[:24]}…",
                )

    # 4k · Recorded exchanges: the evidence behind the profile.
    r.check(
        dig(exchanges_doc, "endpoint") == CANONICAL_URL,
        "mcp-exchanges: endpoint must be the canonical URL",
    )
    for required in (
        "unauth-initialize-401",
        "discovery-protected-resource",
        "accept-wildcard-406",
    ):
        r.check(
            exchanges.get(required, {}).get("source") == "captured",
            f"mcp-exchanges: '{required}' must be a CAPTURED exchange, not constructed",
        )
    r.check(
        "protocol-negotiation-downgrade" in exchanges,
        "mcp-exchanges: the negotiation correction must be recorded as evidence",
    )
    for ex_name, ex in exchanges.items():
        auth = dig(ex, "request", "headers", "authorization")
        if isinstance(auth, str):
            r.check(
                "redacted" in auth.lower() or "fixture" in auth.lower(),
                f"mcp-exchanges/{ex_name}: request carries an unredacted authorization value",
            )

    r.stats = {
        "clients": len(clients),
        "defects": len(defects),
        "cases": sum(len(c.get("cases", [])) for c in fixtures.values()),
        "exchanges": len(exchanges),
    }
    return r


def main() -> int:
    r = validate()
    print(
        f"shared contract: {r.checks} checks over {r.stats.get('clients', 0)} client(s), "
        f"{r.stats.get('defects', 0)} defect(s), {r.stats.get('cases', 0)} fixture case(s), "
        f"{r.stats.get('exchanges', 0)} recorded exchange(s)"
    )
    if not r.ok:
        print("\nFAILED:\n")
        for e in r.errors:
            print(f"  ✗ {e}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
