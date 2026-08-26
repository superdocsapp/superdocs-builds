"""
Orchestrates the benchmark: for each (doc_size, concurrency) cell, run N
full upload->processing->editing->export cycles and collect PhaseResults.

Budget guard (required by the assigned build card): small-sample mode is
the default. A full run only happens when explicitly requested, and the
caller must see the declared operation cap *before* it runs -- see
main.py, which prints the cap and asks for confirmation unless --yes is
passed.

Concurrency is real OS-thread concurrency (ThreadPoolExecutor), not
sequential calls labeled "concurrent" -- each request in a concurrency
cell is dispatched to fire close together, and per-request dispatch time
is measured separately (see stats.load_generator_overhead_check) to prove
the generator itself isn't the bottleneck.

Graceful degradation: client.py catches network-level exceptions per
request. run_one_cycle additionally wraps its entire body in a try/except
as a last-resort safety net -- confirmed necessary live, when an
unhandled exception on cycle 25/60 crashed the whole process and lost the
telemetry from the 24 cycles already completed (nothing is written to
disk until run_benchmark() returns). One bad cycle should degrade to "one
bad cycle's data point," not "the whole run is gone."
"""
from __future__ import annotations

import time
import uuid
import sys
import dataclasses
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from .client import SuperDocsClient, PhaseResult
from .fixtures import doc_bytes, SIZE_TIERS

EDIT_INSTRUCTION = "Add a new final section titled 'Amendments' with one paragraph."

SMALL_SAMPLE_SIZES = ["small"]
SMALL_SAMPLE_CONCURRENCY = [1, 2]
SMALL_SAMPLE_REPEATS = 2

FULL_SIZES = list(SIZE_TIERS.keys())
FULL_CONCURRENCY = [1, 2, 4, 8]
FULL_REPEATS = 5

EST_OPS_PER_CYCLE = 1


@dataclasses.dataclass
class CycleResult:
    tier: str
    concurrency: int
    dispatch_latency_s: float
    phases: list
    chunks_count: Optional[int] = None
    fatal_error: Optional[str] = None


def estimate_full_run_ops(sizes=FULL_SIZES, concurrency=FULL_CONCURRENCY, repeats=FULL_REPEATS) -> int:
    n_cells = len(sizes) * len(concurrency)
    return n_cells * repeats * EST_OPS_PER_CYCLE


def _log(session_id: str, msg: str) -> None:
    print(f"[bench:{session_id}] {msg}", file=sys.stderr)


def _run_one_cycle_inner(api_key: str, tier: str, concurrency: int, session_id: str) -> CycleResult:
    phases: list[PhaseResult] = []

    dispatch_t0 = time.perf_counter()
    with SuperDocsClient(api_key) as client:
        dispatch_latency = time.perf_counter() - dispatch_t0

        up = client.upload_document(f"{tier}.txt", doc_bytes(tier), session_id)
        phases.append(up)
        chunks_count = None
        if up.body and isinstance(up.body, dict):
            chunks_count = up.body.get("chunks_count")
        if up.rate_limited or up.error or up.status_code >= 400:
            _log(session_id, f"STOPPED after upload: status={up.status_code} "
                              f"rate_limited={up.rate_limited} error={up.error} body={up.body}")
            return CycleResult(tier, concurrency, dispatch_latency, phases, chunks_count)

        submit = client.submit_edit_async(session_id, EDIT_INSTRUCTION)
        phases.append(submit)
        if submit.rate_limited or submit.error or submit.status_code >= 400:
            _log(session_id, f"STOPPED after submit: status={submit.status_code} "
                              f"rate_limited={submit.rate_limited} error={submit.error} body={submit.body}")
            return CycleResult(tier, concurrency, dispatch_latency, phases, chunks_count)
        job_id = (submit.body or {}).get("job_id")
        if not job_id:
            _log(session_id, f"STOPPED: no job_id in submit response body={submit.body}")
            return CycleResult(tier, concurrency, dispatch_latency, phases, chunks_count)

        poll1 = client.poll_job(job_id, until_status={"awaiting_approval", "completed"},
                                 phase_label="processing")
        phases.append(poll1)
        if poll1.rate_limited or poll1.error or poll1.status_code >= 400:
            _log(session_id, f"STOPPED after processing poll: status={poll1.status_code} "
                              f"rate_limited={poll1.rate_limited} error={poll1.error} body={poll1.body}")
            return CycleResult(tier, concurrency, dispatch_latency, phases, chunks_count)

        status = (poll1.body or {}).get("status")
        _log(session_id, f"processing poll resolved with job status={status!r}")
        if status == "awaiting_approval":
            pending = (poll1.body or {}).get("metadata", {}).get("pending_changes", [])
            _log(session_id, f"{len(pending)} pending change(s) to approve")
            approve = client.approve_all(session_id, job_id, pending)
            phases.append(approve)
            _log(session_id, f"approve response: status={approve.status_code} body={approve.body}")
            if approve.rate_limited or approve.error or approve.status_code >= 400:
                _log(session_id, f"STOPPED after approve: status={approve.status_code} "
                                  f"rate_limited={approve.rate_limited} error={approve.error} "
                                  f"body={approve.body}")
                return CycleResult(tier, concurrency, dispatch_latency, phases, chunks_count)

            poll2 = client.poll_job(job_id, until_status={"completed"}, phase_label="editing",
                                     timeout_s=30.0)
            phases.append(poll2)
            if poll2.rate_limited or poll2.error or poll2.status_code >= 400:
                _log(session_id, f"STOPPED after editing poll: status={poll2.status_code} "
                                  f"rate_limited={poll2.rate_limited} error={poll2.error} "
                                  f"body={poll2.body}")
                return CycleResult(tier, concurrency, dispatch_latency, phases, chunks_count)

        exp = client.export_document(session_id, fmt="docx")
        phases.append(exp)
        if exp.rate_limited or exp.error or exp.status_code >= 400:
            _log(session_id, f"export non-success: status={exp.status_code} "
                              f"rate_limited={exp.rate_limited} error={exp.error}")
        else:
            _log(session_id, f"export OK: status={exp.status_code}")

    return CycleResult(tier, concurrency, dispatch_latency, phases, chunks_count)


def run_one_cycle(api_key: str, tier: str, concurrency: int) -> CycleResult:
    """
    One full upload -> processing -> editing -> export cycle. Wrapped in a
    try/except as a last-resort safety net: client.py already catches
    network exceptions per-request, but this guards against anything else
    (a malformed response body, an unexpected KeyError) so ONE bad cycle
    never takes down the other 59.
    """
    session_id = f"bench-{tier}-{uuid.uuid4().hex[:8]}"
    try:
        return _run_one_cycle_inner(api_key, tier, concurrency, session_id)
    except Exception as e:
        _log(session_id, f"FATAL (unhandled): {type(e).__name__}: {e}")
        return CycleResult(tier, concurrency, 0.0, [], None, fatal_error=f"{type(e).__name__}: {e}")


def run_cell(api_key: str, tier: str, concurrency: int, repeats: int) -> list[CycleResult]:
    results: list[CycleResult] = []
    print(f"  [{tier}, concurrency={concurrency}] starting {repeats} cycle(s)...", flush=True)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(run_one_cycle, api_key, tier, concurrency) for _ in range(repeats)]
        done_count = 0
        for f in as_completed(futures):
            result = f.result()  # run_one_cycle never raises -- always returns a CycleResult
            results.append(result)
            done_count += 1
            if result.fatal_error:
                print(f"  [{tier}, concurrency={concurrency}] cycle {done_count}/{repeats} "
                      f"FAILED: {result.fatal_error}", flush=True)
                continue
            total_latency = sum(p.latency_s for p in result.phases)
            phases_str = "->".join(p.phase for p in result.phases)
            print(f"  [{tier}, concurrency={concurrency}] cycle {done_count}/{repeats} done "
                  f"in {total_latency:.1f}s ({phases_str})", flush=True)
    return results


def run_benchmark(api_key: str, small_sample: bool = True) -> dict:
    sizes = SMALL_SAMPLE_SIZES if small_sample else FULL_SIZES
    concurrency_levels = SMALL_SAMPLE_CONCURRENCY if small_sample else FULL_CONCURRENCY
    repeats = SMALL_SAMPLE_REPEATS if small_sample else FULL_REPEATS

    all_results: dict[tuple, list[CycleResult]] = {}
    for tier in sizes:
        for conc in concurrency_levels:
            all_results[(tier, conc)] = run_cell(api_key, tier, conc, repeats)
    return all_results
