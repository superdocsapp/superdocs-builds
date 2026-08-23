"""Direct vs proxied latency against the real SuperDocs API.

    SUPERDOCS_API_KEY=... uv run python bench/benchmark.py -n 60

Measures `tools/call health`, which is free — the benchmark costs nothing to
run. What it reports is what a client actually feels: one hop to SuperDocs
versus one hop to the gateway plus the gateway's hop to SuperDocs.

Two things make a live-only measurement defensible rather than flattering:

  * **Interleaving.** Direct and proxied calls alternate, so a slow minute on
    the network lands on both arms instead of on whichever ran second.
  * **Production settings.** The audit log runs with fsync ON, because that is
    how it runs in production and the fsync is a real part of the cost. Pass
    --no-fsync to see what it is worth.

The gateway under test is a real uvicorn server on loopback, not an in-process
ASGI shortcut, so the client→gateway hop is an actual socket.

What this does NOT isolate is the gateway's own compute: wide-area latency to
SuperDocs dominates, so the delta reported here is the honest end-user answer
("what does putting this in the path cost me?") and not a profile of the gate
chain. Treat a delta near zero as "lost in the noise", not as "free".
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import sys
import threading
import time
from pathlib import Path

import httpx
import uvicorn

from gateway.app import create_app
from gateway.audit import AuditLog
from gateway.policy import Policy, TeamPolicy, hash_token
from gateway.proxy import Proxy

UPSTREAM = "https://api.superdocs.app/mcp"
TOKEN = "gw_bench_token"
CT = "application/json"

HEALTH_CALL = json.dumps(
    {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": 1,
        "params": {"name": "health", "arguments": {}},
    }
).encode()


def api_key() -> str:
    key = os.environ.get("SUPERDOCS_API_KEY", "").strip()
    if key:
        return key
    here = Path(__file__).resolve()
    for candidate in (here.parents[1] / ".env", here.parents[3] / ".env"):
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                name, _, value = line.partition("=")
                if name.strip() == "SUPERDOCS_API_KEY":
                    return value.strip().strip("\"'")
    return ""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def build_app(key: str, audit_path: Path, fsync: bool):
    policy = Policy(
        upstream_url=UPSTREAM,
        upstream_key=key,
        teams=(
            TeamPolicy(
                name="bench",
                token_hash=hash_token(TOKEN),
                allow_tools=frozenset({"health"}),
            ),
        ),
    )
    proxy = Proxy(
        upstream_url=UPSTREAM,
        policy=policy,
        audit_log=AuditLog(audit_path, fsync=fsync),
    )
    return create_app(proxy=proxy)


def start_server(app, port: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 20
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("gateway did not start")
    return server


def summarise(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "n": len(ordered),
        "p50": statistics.median(ordered),
        "p95": ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))],
        "mean": statistics.fmean(ordered),
        "min": ordered[0],
        "max": ordered[-1],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", "--requests", type=int, default=40, help="paired samples")
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--no-fsync", action="store_true", help="audit without fsync")
    args = parser.parse_args()

    key = api_key()
    if not key:
        print("SUPERDOCS_API_KEY is not set", file=sys.stderr)
        return 2

    audit_path = Path(__file__).resolve().parent / ".bench-audit.jsonl"
    audit_path.unlink(missing_ok=True)

    port = free_port()
    server = start_server(build_app(key, audit_path, not args.no_fsync), port)

    direct_headers = {"Content-Type": CT, "Accept": CT, "Authorization": f"Bearer {key}"}
    proxied_headers = {"Content-Type": CT, "Accept": CT, "Authorization": f"Bearer {TOKEN}"}
    proxied_url = f"http://127.0.0.1:{port}/mcp"

    direct: list[float] = []
    proxied: list[float] = []

    try:
        with httpx.Client(timeout=60.0) as client:

            def one(url: str, headers: dict[str, str]) -> float:
                start = time.perf_counter()
                r = client.post(url, content=HEALTH_CALL, headers=headers)
                elapsed = (time.perf_counter() - start) * 1000
                if r.status_code != 200:
                    raise RuntimeError(f"{url} returned {r.status_code}: {r.text[:200]}")
                return elapsed

            print(f"warming up ({args.warmup} each) …")
            for _ in range(args.warmup):
                one(UPSTREAM, direct_headers)
                one(proxied_url, proxied_headers)

            print(f"measuring {args.requests} interleaved pairs against {UPSTREAM} …")
            for i in range(args.requests):
                # Alternate which arm goes first, so neither systematically
                # benefits from a warm connection within the pair.
                if i % 2 == 0:
                    direct.append(one(UPSTREAM, direct_headers))
                    proxied.append(one(proxied_url, proxied_headers))
                else:
                    proxied.append(one(proxied_url, proxied_headers))
                    direct.append(one(UPSTREAM, direct_headers))
    finally:
        server.should_exit = True

    d = summarise(direct)
    p = summarise(proxied)
    deltas = sorted(pr - di for pr, di in zip(proxied, direct, strict=True))
    paired = summarise(deltas)

    fsync_note = "off" if args.no_fsync else "on"
    print(f"\n  n={d['n']} paired samples · tool=health (free) · audit fsync={fsync_note}\n")
    print(f"  {'':<10}{'p50':>10}{'p95':>10}{'mean':>10}{'min':>10}{'max':>10}")
    print(
        f"  {'direct':<10}{d['p50']:>9.1f}{d['p95']:>10.1f}{d['mean']:>10.1f}"
        f"{d['min']:>10.1f}{d['max']:>10.1f}"
    )
    print(
        f"  {'proxied':<10}{p['p50']:>9.1f}{p['p95']:>10.1f}{p['mean']:>10.1f}"
        f"{p['min']:>10.1f}{p['max']:>10.1f}"
    )
    print(f"\n  overhead   p50 {p['p50'] - d['p50']:+.1f} ms    p95 {p['p95'] - d['p95']:+.1f} ms")
    print(f"  per-pair delta: p50 {paired['p50']:+.1f} ms, p95 {paired['p95']:+.1f} ms")
    print("\n  All times in milliseconds. Wide-area latency to SuperDocs dominates;")
    print("  see the module docstring for what this does and does not isolate.")

    audit_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
