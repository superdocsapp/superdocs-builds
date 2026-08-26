# Token-Cost & Latency Benchmark 📊⚡

A benchmark study comparing **Whole-Document Regeneration** versus **SuperDocs Surgical Section Editing (`response_mode='compact'`)**.

## What This Measures
- **Input Token Reduction:** Measures payload token savings when sending targeted section edit instructions vs re-sending entire documents.
- **Output Token Reduction:** Measures token savings when receiving compact per-section diffs vs receiving full regenerated HTML.
- **Wall-Clock Latency:** Measures completion time per edit turn.

## Quickstart

### 1. Set Environment Variable
```bash
export SUPERDOCS_API_KEY=your-api-key-here
```

### 2. Run the Benchmark
```bash
../../venv/bin/python3 token_cost_benchmark.py
```

This will run both test scenarios, calculate exact token & latency variance, display the comparison table, and export `SuperDocs_Token_Cost_Benchmark.pdf`!
