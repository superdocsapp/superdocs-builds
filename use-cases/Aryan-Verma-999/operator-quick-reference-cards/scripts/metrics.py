"""Offline measurement entry point; emits raw values and summary statistics."""
from __future__ import annotations
import json, statistics, time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
from linecard.m1 import page_map, evidence_pack

def main() -> int:
    samples=[]
    for _ in range(3):
        start=time.perf_counter(); mapping=page_map(); evidence_pack(mapping); samples.append((time.perf_counter()-start)*1000)
    ordered=sorted(samples); result={"method":"three repeated local hero-fixture runs","sample_count":len(samples),"raw_ms":samples,"median_ms":statistics.median(samples),"p95_ms":ordered[min(len(ordered)-1,int(len(ordered)*.95))],"max_ms":max(samples),"failures":0,"operations_used":0,"fixture_pages":len(mapping["pages"])}
    print(json.dumps(result,indent=2)); return 0
if __name__ == '__main__': raise SystemExit(main())
