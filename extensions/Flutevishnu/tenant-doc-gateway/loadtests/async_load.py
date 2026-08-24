"""Minimal dependency-free async load test.

Fires N concurrent requests at a RUNNING gateway and reports p50/p95/p99 latency
and error rate. Defaults to read-heavy endpoints (health + list documents) so it
measures the GATEWAY and does NOT burn SuperDocs operations.

Usage:
    python loadtests/async_load.py --base-url http://localhost:8000 \
        --admin-key change-me-admin-key --requests 500 --concurrency 50
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx


async def _provision_tenant(base_url: str, admin_key: str) -> dict:
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as c:
        r = await c.post(
            "/v1/admin/tenants",
            json={"name": "loadtest"},
            headers={"Authorization": f"Bearer {admin_key}"},
        )
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['api_key']}"}


async def _worker(
    client: httpx.AsyncClient, headers: dict, latencies: list[float], errors: list[int]
):
    start = time.perf_counter()
    try:
        resp = await client.get("/v1/documents", headers=headers)
        if resp.status_code >= 400:
            errors.append(1)
    except httpx.HTTPError:
        errors.append(1)
    latencies.append((time.perf_counter() - start) * 1000)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--admin-key", default="change-me-admin-key")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=50)
    args = parser.parse_args()

    headers = await _provision_tenant(args.base_url, args.admin_key)
    latencies: list[float] = []
    errors: list[int] = []

    sem = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=30) as client:

        async def bounded():
            async with sem:
                await _worker(client, headers, latencies, errors)

        wall_start = time.perf_counter()
        await asyncio.gather(*(bounded() for _ in range(args.requests)))
        wall = time.perf_counter() - wall_start

    latencies.sort()

    def pct(p: float) -> float:
        idx = min(len(latencies) - 1, int(p / 100 * len(latencies)))
        return round(latencies[idx], 2)

    print("=== async load test ===")
    print(f"requests={args.requests} concurrency={args.concurrency}")
    print(f"wall_time_s={round(wall, 2)} throughput_rps={round(args.requests / wall, 1)}")
    print(f"errors={len(errors)} error_rate={round(len(errors) / args.requests * 100, 2)}%")
    print(f"p50_ms={pct(50)} p95_ms={pct(95)} p99_ms={pct(99)} max_ms={round(max(latencies), 2)}")
    print(f"mean_ms={round(statistics.mean(latencies), 2)}")


if __name__ == "__main__":
    asyncio.run(main())
