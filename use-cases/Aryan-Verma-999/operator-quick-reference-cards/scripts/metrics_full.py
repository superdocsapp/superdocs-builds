"""Repeated offline metrics for every local pipeline stage."""
from __future__ import annotations
import json, statistics, time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
from linecard.m1 import page_map, evidence_pack, skeleton, verify
from linecard.ingest import ingest_pdf
from linecard.flow import hero_flow
from linecard.layout import LayoutBlock, solve_two_page
from linecard.retrieval import EvidenceIndex
from linecard.batch import run_offline_three_task_batch

def sample(name, fn, n=5):
    values=[]; failures=0
    for _ in range(n):
        start=time.perf_counter()
        try: fn()
        except Exception: failures += 1
        values.append((time.perf_counter()-start)*1000)
    ordered=sorted(values); return {"name":name,"N":n,"raw_ms":values,"median_ms":statistics.median(values),"p95_ms":ordered[max(0,min(n-1,int(n*.95)-1))],"maximum_ms":max(values),"failures":failures}

def main():
    mapping=page_map(); manifest={"pages":[{"pdf_index":p["pdf_index"],"text":p["text"]} for p in mapping["pages"]]}; idx=EvidenceIndex()
    second=Path("fixtures/generated/second-manual-60-pages.pdf")
    jobs=[
        sample("long_manual_generation",lambda: page_map()),
        sample("page_extraction",lambda: page_map()["pages"]),
        sample("pdf_ingest",lambda: ingest_pdf("fixtures/generated/scale-manual-400-pages.pdf")),
        sample("fts_indexing",lambda: idx.add_manifest(manifest)),
        sample("deterministic_retrieval",lambda: idx.search("energy infeed")),
        sample("gold_ledger_evaluation",lambda: evidence_pack(mapping)),
        sample("evidence_composition",lambda: skeleton()),
        sample("verification",lambda: verify(skeleton())),
        sample("flow_graph_generation",lambda: hero_flow().mermaid()),
        sample("page_budget_solve",lambda: solve_two_page([LayoutBlock(str(i),"x") for i in range(20)])),
        sample("three_card_batch",lambda: run_offline_three_task_batch("artifacts/metrics-batch")),
        sample("second_manual",lambda: ingest_pdf(second)),
    ]
    payload={"measurement_scope":"offline synthetic fixtures; milliseconds; no peak-memory measurement available","measurements":jobs,"live_operations":0,"fixtures":["fixtures/generated/scale-manual-400-pages.pdf","fixtures/generated/second-manual-60-pages.pdf"]}
    out=Path("artifacts/metrics"); out.mkdir(parents=True,exist_ok=True); (out/"raw.json").write_text(json.dumps(payload,indent=2)+"\n")
    rows=["# Offline metrics", "", "Synthetic/offline measurements only; no live provider operation or peak-memory measurement is included.", "", "| metric | N | median ms | p95 ms | maximum ms | failures |", "|---|---:|---:|---:|---:|---:|"]+[f"| {x['name']} | {x['N']} | {x['median_ms']:.3f} | {x['p95_ms']:.3f} | {x['maximum_ms']:.3f} | {x['failures']} |" for x in jobs]
    (out/"report.md").write_text("\n".join(rows)+"\n"); print(json.dumps(payload,indent=2))
if __name__ == "__main__": main()
