#!/usr/bin/env python3
"""Measure how long the mock takes to start, and commit the raw data.

**Method, stated before the result**, because a benchmark whose method arrives after its
number is a claim rather than a measurement:

* What is measured: wall-clock from `subprocess.Popen` of a cold `sdmock serve` process to
  the first TCP connection the socket accepts. That is the number a CI job actually waits
  for, and it includes interpreter start and every import.
* A second measurement takes it to the first successful HTTP `200 /health`, which adds the
  ASGI round trip.
* A third takes it to the first successful MCP `tools/list`, which additionally loads and
  serves the 280 KB pinned tool surface.
* N = 20 by default. A fresh process and a fresh port each time; nothing is reused.
* Reported as median, p95 and max -- the tail, not just the average, because a CI job
  waits for the slow run, not the typical one.
* Every sample is written to `docs/benchmarks/startup.csv` so the numbers can be
  re-derived, disagreed with, or re-run on other hardware.

It also measures the same thing with FastAPI imported, to substantiate the decision to
build on Starlette rather than assert it.

    python scripts/benchmark_startup.py
    python scripts/benchmark_startup.py --runs 5      # quick pass while iterating
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import socket
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "benchmarks"
PYTHON = str(ROOT / ".venv" / "bin" / "python")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def one_run(timeout: float = 30.0) -> dict[str, float]:
    """Start a cold process and time three successive readiness signals."""
    port = free_port()
    began = time.perf_counter()
    process = subprocess.Popen(
        [PYTHON, "-m", "sdmock.cli", "serve", "--port", str(port), "--quiet"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    marks: dict[str, float] = {}
    try:
        while "accept" not in marks:
            if time.perf_counter() - began > timeout:
                raise TimeoutError("socket never accepted")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.05):
                    marks["accept"] = time.perf_counter() - began
            except OSError:
                time.sleep(0.002)

        while "health" not in marks:
            if time.perf_counter() - began > timeout:
                raise TimeoutError("/health never answered")
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/health", timeout=1) as response:
                    if response.status == 200:
                        marks["health"] = time.perf_counter() - began
            except (urllib.error.URLError, OSError):
                time.sleep(0.002)

        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/mcp/",
            data=json.dumps({"jsonrpc": "2.0", "id": 1,
                             "method": "tools/list", "params": {}}).encode(),
            headers={"Authorization": "Bearer sk_test", "Content-Type": "application/json"},
        )
        while "mcp" not in marks:
            if time.perf_counter() - began > timeout:
                raise TimeoutError("MCP never answered")
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    if response.status == 200:
                        marks["mcp"] = time.perf_counter() - began
            except (urllib.error.URLError, OSError):
                time.sleep(0.002)
    finally:
        process.terminate()
        process.wait(timeout=10)
    return marks


def import_cost(module: str, runs: int = 5) -> float:
    """Median cost of importing a module in a cold interpreter."""
    samples = []
    for _ in range(runs):
        began = time.perf_counter()
        subprocess.run([PYTHON, "-c", f"import {module}"], cwd=ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        samples.append(time.perf_counter() - began)
    return statistics.median(samples)


def summarise(name: str, samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    index = max(0, int(round(0.95 * len(ordered))) - 1)
    return {
        "measurement": name,
        "n": len(ordered),
        "median_ms": round(statistics.median(ordered) * 1000, 1),
        "p95_ms": round(ordered[index] * 1000, 1),
        "max_ms": round(max(ordered) * 1000, 1),
        "min_ms": round(min(ordered) * 1000, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=20)
    args = ap.parse_args()

    print(f"method: cold `sdmock serve` process, fresh port, N={args.runs}")
    print("        timing to socket-accept, then to HTTP 200 /health, then to MCP "
          "tools/list\n")

    collected: dict[str, list[float]] = {"accept": [], "health": [], "mcp": []}
    rows: list[dict] = []
    for index in range(args.runs):
        marks = one_run()
        for key, value in marks.items():
            collected[key].append(value)
        rows.append({"run": index + 1, **{k: round(v * 1000, 2) for k, v in marks.items()}})
        print(f"  run {index + 1:2d}: accept {marks['accept']*1000:6.0f} ms   "
              f"health {marks['health']*1000:6.0f} ms   mcp {marks['mcp']*1000:6.0f} ms")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "startup.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["run", "accept", "health", "mcp"])
        writer.writeheader()
        writer.writerows(rows)

    summaries = [
        summarise("process start -> socket accepts", collected["accept"]),
        summarise("process start -> HTTP 200 /health", collected["health"]),
        summarise("process start -> MCP tools/list", collected["mcp"]),
    ]

    print("\n  measurement                              median     p95     max")
    for row in summaries:
        print(f"  {row['measurement']:38s} {row['median_ms']:7.0f} "
              f"{row['p95_ms']:7.0f} {row['max_ms']:7.0f}   (ms)")

    print("\nimport cost, median of 5 cold interpreters:")
    baseline = import_cost("sys")
    costs = {}
    for module in ("starlette.applications", "fastapi"):
        try:
            costs[module] = import_cost(module) - baseline
            print(f"  {module:24s} {costs[module]*1000:6.0f} ms above a bare interpreter")
        except Exception:
            print(f"  {module:24s} not installed")

    meta = {
        "generated": time.strftime("%Y-%m-%d"),
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
        "runs": args.runs,
        "summaries": summaries,
        "import_cost_ms": {k: round(v * 1000, 1) for k, v in costs.items()},
        "note": "Measured on the author's machine. Raw per-run samples are in "
                "startup.csv so the numbers can be re-derived or disputed.",
    }
    (OUT_DIR / "startup.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    worst = max(collected["mcp"])
    print(f"\nslowest full readiness across all runs: {worst*1000:.0f} ms")
    print(f"one-second bar: {'MET' if worst < 1.0 else 'NOT MET'}")
    print(f"raw data: {(OUT_DIR / 'startup.csv').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
