"""Agent self-signup for the SuperDocs API — no human in the loop.

Follows the documented flow:

  1. If ``~/.superdocs/agent_credentials.json`` exists, reuse that account:
     ``GET /v1/agents/whoami`` confirms it still works and reports quota.
  2. Otherwise ``POST /v1/agents/signup`` (solving the optional altcha
     proof-of-work challenge if the gate is enabled) and save the whole
     response — including the key — to ``~/.superdocs/agent_credentials.json``.

The API key is shown only once by the API and is never printed here. This tool
prints account status (tier, monthly operations used/remaining, adoption), and
the key is read straight from the credentials file by the CLI (see
``exhibit.cli._agent_key``). ``POST /v1/agents/handoff`` lets the human adopt
the account later.

Usage::

    python tools/superdocs_login.py [--agent-name exhibit-engine]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

import httpx

BASE_URL = "https://api.superdocs.app"
CREDS = Path.home() / ".superdocs" / "agent_credentials.json"


def _load_creds() -> dict | None:
    if CREDS.exists():
        return json.loads(CREDS.read_text(encoding="utf-8"))
    return None


def _whoami(key: str, base_url: str) -> dict:
    resp = httpx.get(
        f"{base_url}/v1/agents/whoami",
        headers={"Authorization": f"Bearer {key}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _solve_altcha(base_url: str) -> str | None:
    """Solve the optional proof-of-work challenge, if the gate is enabled."""
    resp = httpx.get(f"{base_url}/v1/agents/challenge", timeout=30)
    if resp.status_code != 200 or not resp.text:
        return None
    chal = resp.json()
    algorithm = chal["algorithm"]
    salt = chal["salt"]
    target = chal["challenge"]
    max_number = chal.get("maxNumber", 100_000)
    for n in range(max_number + 1):
        if hashlib.sha256(f"{salt}{n}".encode("utf-8")).hexdigest() == target:
            payload = {
                "algorithm": algorithm,
                "challenge": target,
                "number": n,
                "salt": salt,
                "signature": chal["signature"],
            }
            return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    raise RuntimeError("could not solve the signup challenge")


def _signup(agent_name: str, base_url: str) -> dict:
    body = {"terms_accepted": True, "agent_name": agent_name}
    altcha = _solve_altcha(base_url)
    if altcha:
        body["altcha"] = altcha
    resp = httpx.post(f"{base_url}/v1/agents/signup", json=body, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _handoff(email: str, key: str, base_url: str) -> dict:
    """Let the human adopt the agent account (links it to their login/credits)."""
    resp = httpx.post(
        f"{base_url}/v1/agents/handoff",
        headers={"Authorization": f"Bearer {key}"},
        json={"email": email},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def _print_status(me: dict) -> None:
    """Print account status with any credential-like field redacted."""
    redacted = {k: ("***" if "key" in k.lower() else v) for k, v in me.items()}
    print(json.dumps(redacted, indent=2))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--agent-name", default="exhibit-engine")
    ap.add_argument("--handoff", metavar="EMAIL",
                    help="hand the saved agent account to a human (they adopt "
                         "it and its credits merge under their login)")
    ap.add_argument("--base-url", default=BASE_URL)
    args = ap.parse_args(argv)

    creds = _load_creds()
    if args.handoff:
        if not (creds and creds.get("api_key")):
            print(f"no saved account at {CREDS}; sign up first", file=sys.stderr)
            return 1
        print(f"handing the agent account at {CREDS} to {args.handoff} ...")
        try:
            _print_status(_handoff(args.handoff, creds["api_key"], args.base_url))
        except httpx.HTTPError as exc:
            print(f"handoff failed: {exc}", file=sys.stderr)
            return 1
        return 0
    if creds and creds.get("api_key"):
        print(f"reusing account saved at {CREDS}")
        try:
            _print_status(_whoami(creds["api_key"], args.base_url))
        except httpx.HTTPError as exc:
            print(f"whoami failed: {exc}", file=sys.stderr)
            print(
                "The saved account may have been revoked. If it was handed to a "
                "human, adopt or re-create it (POST /v1/agents/handoff).",
                file=sys.stderr,
            )
            return 1
        return 0

    resp = _signup(args.agent_name, args.base_url)
    CREDS.parent.mkdir(parents=True, exist_ok=True)
    CREDS.write_text(json.dumps(resp, indent=2), encoding="utf-8")
    print(f"created account; key saved to {CREDS} (shown only once by the API)")
    _print_status(resp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
