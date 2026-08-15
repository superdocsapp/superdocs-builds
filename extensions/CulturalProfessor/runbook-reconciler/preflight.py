#!/usr/bin/env python3
"""Setup diagnostic. Reports what is configured and what actually works.

Prints key names and status only - never a value. Run it before anything else:

    python3 preflight.py
"""

import base64
import contextlib
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).parent
OK, BAD, WARN = "ok  ", "FAIL", "warn"
QUOTED = set()


def load(name):
    """Parse a dotenv file.

    Values wrapped in quotes are unwrapped. This matters more than it looks: a quoted
    token produces a malformed Basic auth header, Confluence falls back to anonymous,
    and the resulting 403 says "Current user not permitted to use Confluence" - which
    reads like a licensing problem and sends you looking in entirely the wrong place.
    """
    path = HERE / name
    if not path.exists():
        return None
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            unwrapped = v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v
            if unwrapped != v and name == ".env":
                QUOTED.add(k)
            out[k] = unwrapped
    return out


def http(url, auth_header=None, method="GET"):
    headers = {"Accept": "application/json"}
    if auth_header:
        headers["Authorization"] = auth_header
    req = urllib.request.Request(url, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        # Deliberately bare. A diagnostic that dies on an unexpected exception
        # tells you nothing; this one reports the exception as the finding.
        return None, f"{type(e).__name__}: {e}".encode()


def basic(email, token):
    return "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()


def discover(site, email, token):
    """Find the (api_base, auth_header) combination that actually works.

    Confluence Cloud has two front doors and they accept different credentials:

      - the site host serves classic API tokens over Basic auth
      - the gateway, api.atlassian.com/ex/confluence/{cloudId}, serves scoped
        (granular) tokens over either Basic or Bearer

    A scoped token sent to the site host returns 401, which is indistinguishable from a
    revoked credential and costs an hour if you trust it. So probe rather than assume,
    and keep working when the token type changes underneath us.
    """
    candidates = []
    code, raw = http(f"{site}/_edge/tenant_info")
    cloud_id = None
    if code == 200:
        with contextlib.suppress(ValueError, KeyError):
            cloud_id = json.loads(raw)["cloudId"]
    if cloud_id:
        gw = f"https://api.atlassian.com/ex/confluence/{cloud_id}"
        candidates.append((gw, basic(email, token), "gateway + basic (scoped token)"))
        candidates.append((gw, "Bearer " + token, "gateway + bearer (scoped token)"))
    candidates.append((site, basic(email, token), "site + basic (classic token)"))

    last = None
    for base, auth, label in candidates:
        code, _ = http(f"{base}/wiki/api/v2/spaces?limit=1", auth)
        if code == 200:
            return base, auth, label, cloud_id, None
        last = code
    return None, None, None, cloud_id, last


def check_keys(env, example):
    print("\nconfiguration")
    missing = 0
    for k, placeholder in example.items():
        if k not in env:
            print(f"  {BAD}  {k}: missing")
            missing += 1
        elif env[k] == "":
            print(f"  {WARN}  {k}: empty")
        elif env[k] == placeholder:
            print(f"  {WARN}  {k}: still the placeholder")
        else:
            print(f"  {OK}  {k}: set ({len(env[k])} chars)")
    return missing


def check_confluence(env):
    print("\nconfluence")
    site = env.get("CONFLUENCE_BASE_URL", "").rstrip("/")
    if not site:
        print(f"  {BAD}  CONFLUENCE_BASE_URL not set")
        return False
    parsed = urllib.parse.urlparse(site)
    if parsed.path:
        print(f"  {WARN}  base URL has a path ({parsed.path!r}); use the bare site origin")
        site = f"{parsed.scheme}://{parsed.netloc}"

    email = env.get("CONFLUENCE_EMAIL", "")
    token = env.get("CONFLUENCE_API_TOKEN", "")
    api, auth, how, cloud_id, failed_code = discover(site, email, token)

    if not api:
        print(f"  {BAD}  no working host/credential combination (last HTTP {failed_code})")
        if cloud_id:
            print("        The site resolves, so the credential is the problem: check the token")
            print("        is not revoked, and that its scopes include read:page:confluence.")
        else:
            print("        The site itself did not resolve. Check CONFLUENCE_BASE_URL.")
        return False

    print(f"  {OK}  authenticated via {how}")
    print(f"  {OK}  API base resolved (cloudId {'found' if cloud_id else 'n/a'})")

    space = env.get("CONFLUENCE_SPACE_KEY", "")
    if space and space != "RUNBOOKS":
        code, raw = http(f"{api}/wiki/api/v2/spaces?keys={space}&limit=1", auth)
        found = code == 200 and json.loads(raw).get("results")
        print(
            f"  {OK if found else BAD}  space {space}: {'found' if found else 'not found or not visible'}"
        )
    else:
        code, raw = http(f"{api}/wiki/api/v2/spaces?limit=25", auth)
        if code == 200:
            keys = [s.get("key") for s in json.loads(raw).get("results", [])]
            print(f"  {WARN}  CONFLUENCE_SPACE_KEY not set. Visible spaces: {keys}")

    code, raw = http(f"{api}/wiki/api/v2/pages?limit=25", auth)
    if code == 200:
        pages = json.loads(raw).get("results", [])
        print(f"  {OK}  {len(pages)} page(s) readable via the pages API")
        if not pages:
            print("        Zero pages usually means the content is a live doc, which the")
            print("        pages API does not return. Create a standard page instead.")
    else:
        print(f"  {BAD}  pages unreadable: HTTP {code}")
    return True


def main():
    example = load(".env.example")
    env = load(".env")
    if example is None:
        print("no .env.example found")
        return 1
    if env is None:
        print("no .env found - copy .env.example to .env and fill it in")
        return 1

    print("runbook-reconciler preflight")
    missing = check_keys(env, example)
    if QUOTED:
        print(f"\n  {WARN}  quoted values unwrapped: {', '.join(sorted(QUOTED))}")
        print("        dotenv does not strip quotes. Remove them from .env - other tools will not.")
    ok = check_confluence(env)

    print("\nsuperdocs")
    if not env.get("SUPERDOCS_BASE_URL"):
        print(f"  {OK}  SUPERDOCS_BASE_URL empty - the client defaults to api.superdocs.app")
    if not env.get("SUPERDOCS_API_KEY") or env["SUPERDOCS_API_KEY"] == example["SUPERDOCS_API_KEY"]:
        print(f"  {WARN}  SUPERDOCS_API_KEY not set")
    else:
        print(f"  {OK}  SUPERDOCS_API_KEY set (not yet exercised)")

    print()
    return 0 if ok and not missing else 1


if __name__ == "__main__":
    sys.exit(main())
