"""Metric Table Compiler and Benchmark Tabulator.

Ingests machine-readable evaluation artifacts (JSON / CSV),
maps raw task IDs to human-readable capability domains,
standardizes units, and computes baseline deltas.
Supports --sample-mode for lightweight 3-row test slicing.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class BenchmarkTabulator:
    """Compiles raw benchmark evaluation logs into publication-ready markdown tables."""

    def __init__(self, mappings_path: Optional[Union[str, Path]] = None) -> None:
        """Initialize tabulator with benchmark mappings config."""
        if mappings_path is None:
            default_config = Path(__file__).resolve().parent.parent / "config" / "benchmark_mappings.json"
            if default_config.exists():
                mappings_path = default_config
        
        self.mappings_path = Path(mappings_path) if mappings_path else None
        self.task_mappings: Dict[str, Dict[str, Any]] = {}
        self.domains: List[str] = []
        self.default_domain: str = "Other Benchmarks"

        if self.mappings_path and self.mappings_path.exists():
            with open(self.mappings_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
                self.task_mappings = config_data.get("tasks", {})
                self.domains = config_data.get("domains", [])
                self.default_domain = config_data.get("default_domain", "Other Benchmarks")

    def load_eval_data(self, file_path_or_data: Union[str, Path, List[Dict[str, Any]], Dict[str, Any]]) -> Dict[str, Any]:
        """Load evaluation records from JSON file, CSV file, dict, or list.
        
        Returns standardized dict:
            {
                "run_id": str,
                "timestamp": str,
                "baseline_model": Optional[str],
                "model_name": Optional[str],
                "results": List[Dict[str, Any]]
            }
        """
        if isinstance(file_path_or_data, (str, Path)):
            path = Path(file_path_or_data)
            if not path.is_file():
                # Try parsing as raw JSON string
                try:
                    parsed = json.loads(str(file_path_or_data))
                    return self._standardize_payload(parsed)
                except Exception:
                    raise FileNotFoundError(f"Evaluation file not found: {file_path_or_data}")

            if path.suffix.lower() == ".csv":
                return self._load_csv(path)
            else:
                with open(path, "r", encoding="utf-8") as f:
                    parsed = json.load(f)
                return self._standardize_payload(parsed)

        return self._standardize_payload(file_path_or_data)

    def _load_csv(self, path: Path) -> Dict[str, Any]:
        """Parse CSV evaluation file into standardized structure."""
        results: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                task_id = row.get("task_id") or row.get("benchmark") or row.get("task") or "unknown"
                score_str = row.get("score") or row.get("value") or row.get("result") or "0"
                try:
                    score = float(score_str)
                except ValueError:
                    score = 0.0

                baseline_score = None
                raw_baseline = row.get("baseline_score") or row.get("baseline")
                if raw_baseline not in (None, "", "null", "N/A"):
                    try:
                        baseline_score = float(raw_baseline)
                    except ValueError:
                        baseline_score = None

                few_shot = None
                if row.get("few_shot") not in (None, "", "null"):
                    try:
                        few_shot = int(row.get("few_shot"))
                    except ValueError:
                        pass

                num_samples = None
                if row.get("num_samples") not in (None, "", "null", "samples"):
                    try:
                        num_samples = int(row.get("num_samples") or row.get("samples", 0))
                    except ValueError:
                        pass

                item = {
                    "task_id": task_id.strip().lower(),
                    "score": score,
                    "baseline_score": baseline_score,
                    "unit": row.get("unit"),
                    "metric": row.get("metric"),
                    "domain": row.get("domain"),
                    "task_name": row.get("task_name") or row.get("name"),
                    "few_shot": few_shot,
                    "num_samples": num_samples,
                    "notes": row.get("notes") or row.get("description"),
                }
                results.append(item)

        return {
            "run_id": path.stem,
            "timestamp": None,
            "baseline_model": None,
            "results": results
        }

    def _standardize_payload(self, data: Union[List[Any], Dict[str, Any]]) -> Dict[str, Any]:
        """Convert list or dictionary into unified evaluation structure."""
        if isinstance(data, list):
            return {
                "run_id": "eval-run",
                "timestamp": None,
                "baseline_model": None,
                "results": data
            }

        if isinstance(data, dict):
            records = data.get("results") or data.get("metrics") or []
            if not records and "task_id" in data:
                records = [data]

            return {
                "run_id": data.get("run_id", "eval-run"),
                "timestamp": data.get("timestamp"),
                "baseline_model": data.get("baseline_model"),
                "model_name": data.get("model_name"),
                "results": records
            }

        raise ValueError(f"Unrecognized evaluation data format: {type(data)}")

    def enrich_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich a raw benchmark record using mapping rules and calculate deltas."""
        raw_id = str(record.get("task_id", "")).strip().lower()
        mapping = self.task_mappings.get(raw_id, {})

        name = record.get("task_name") or mapping.get("name") or raw_id.upper().replace("_", " ")
        domain = record.get("domain") or mapping.get("domain") or self.default_domain
        metric = record.get("metric") or mapping.get("metric") or "Score"
        unit = record.get("unit") or mapping.get("unit") or "%"
        desc = record.get("notes") or mapping.get("description") or ""

        score = float(record.get("score", 0.0))
        baseline_score = record.get("baseline_score")
        if baseline_score not in (None, "", "N/A", "null"):
            try:
                baseline_score = float(baseline_score)
            except (ValueError, TypeError):
                baseline_score = None
        else:
            baseline_score = None

        # Calculate delta
        delta_val: Optional[float] = None
        delta_str = "—"
        if baseline_score is not None:
            delta_val = round(score - baseline_score, 2)
            if delta_val > 0:
                delta_str = f"▲ +{delta_val:.1f}{unit}"
            elif delta_val < 0:
                delta_str = f"▼ {delta_val:.1f}{unit}"
            else:
                delta_str = f"— 0.0{unit}"

        # Standardize score string
        if unit == "%":
            score_str = f"{score:.1f}%"
            baseline_str = f"{baseline_score:.1f}%" if baseline_score is not None else "—"
        else:
            score_str = f"{score:.2f} {unit}".strip()
            baseline_str = f"{baseline_score:.2f} {unit}".strip() if baseline_score is not None else "—"

        few_shot = record.get("few_shot")
        shot_str = f"{few_shot}-shot" if few_shot is not None else "0-shot"

        return {
            "task_id": raw_id,
            "name": name,
            "domain": domain,
            "metric": metric,
            "unit": unit,
            "score": score,
            "score_str": score_str,
            "baseline_score": baseline_score,
            "baseline_str": baseline_str,
            "delta_val": delta_val,
            "delta_str": delta_str,
            "shots": shot_str,
            "num_samples": record.get("num_samples"),
            "description": desc,
        }

    def process_records(
        self,
        records: List[Dict[str, Any]],
        sample_mode: bool = False
    ) -> List[Dict[str, Any]]:
        """Process and enrich all benchmark records. Slices to 3 rows if sample_mode is True."""
        enriched = [self.enrich_record(r) for r in records if r.get("task_id")]

        if sample_mode:
            enriched = enriched[:3]

        return enriched

    def render_markdown_tables(
        self,
        records: List[Dict[str, Any]],
        sample_mode: bool = False,
        baseline_model_name: Optional[str] = None
    ) -> str:
        """Render complete evaluation markdown section with summary and domain breakdown tables."""
        processed = self.process_records(records, sample_mode=sample_mode)

        if not processed:
            return "_No benchmark evaluation results recorded._\n"

        baseline_header = f"Baseline ({baseline_model_name})" if baseline_model_name else "Baseline"

        # Group by domain
        domain_groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in processed:
            d = item["domain"]
            domain_groups.setdefault(d, []).append(item)

        output_lines: List[str] = []

        if sample_mode:
            output_lines.append("> [!NOTE]\n> **Sample Mode Active:** Displaying a 3-row verification slice of evaluation metrics.\n")

        # Summary Master Table
        output_lines.append("### Key Benchmark Performance Summary\n")
        output_lines.append(f"| Benchmark | Domain | Metric | Current Score | {baseline_header} | Delta |")
        output_lines.append(f"| :--- | :--- | :--- | :---: | :---: | :---: |")

        for r in processed:
            metric_display = r['metric']
            if r['shots'] and r['shots'] not in metric_display and "shot" not in metric_display.lower():
                metric_display = f"{metric_display} ({r['shots']})"
            output_lines.append(
                f"| **{r['name']}** | {r['domain']} | {metric_display} | **{r['score_str']}** | {r['baseline_str']} | {r['delta_str']} |"
            )

        output_lines.append("\n---\n")

        # Capability Domain Breakdowns
        output_lines.append("### Domain-Specific Evaluation Breakdown\n")
        for domain, items in domain_groups.items():
            output_lines.append(f"#### {domain}\n")
            output_lines.append(f"| Task | Metric | Setting | Score | {baseline_header} | Delta | Details |")
            output_lines.append(f"| :--- | :--- | :---: | :---: | :---: | :---: | :--- |")
            for it in items:
                desc = it["description"] if it["description"] else "Standard test configuration"
                output_lines.append(
                    f"| **{it['name']}** | {it['metric']} | {it['shots']} | **{it['score_str']}** | {it['baseline_str']} | {it['delta_str']} | {desc} |"
                )
            output_lines.append("")

        return "\n".join(output_lines).strip()
