"""Unit tests for the publication-ready PDF Card Renderer."""

import pytest
from pathlib import Path
from src.pdf_renderer import PDFCardRenderer


def test_pdf_renderer_produces_valid_pdf_binary():
    manifest = {
        "model_name": "Nexus-70B-Instruct",
        "version": "v1.2.0",
        "release_date": "2026-08-15",
        "license": "Apache-2.0",
        "model_type": "Dense Decoder-Only Transformer",
        "description": "State of the art instruction-tuned generative model.",
        "intended_purpose": ["General reasoning", "Code synthesis", "Mathematical problem solving"],
        "limitations": ["Potential hallucinations on fringe topics", "English-centric reasoning bias"],
        "out_of_scope_uses": ["High-risk autonomous decision making without human review"],
        "maintenance_contact": {"team": "Nexus Core Alignment", "email": "nexus-dev@superdocs.app"},
        "model_architecture": {"parameters": "70 Billion", "context_window": "128k tokens"},
        "training_data_summary": "Trained on 15T tokens of curated multilingual web text and code.",
        "ethical_considerations": ["RLHF applied for harmlessness and truthfulness alignment."],
        "citation": "@article{nexus70b2026,\n  title={Nexus-70B},\n  year={2026}\n}"
    }

    eval_records = [
        {
            "name": "MMLU (Massive Multitask Language Understanding)",
            "domain": "General Reasoning & Knowledge",
            "metric": "5-shot Accuracy",
            "shots": "5-shot",
            "score": 86.4,
            "score_str": "86.4%",
            "baseline": 82.1,
            "baseline_str": "82.1%",
            "delta_val": 4.3,
            "delta_str": "+4.3% ▲",
            "description": "Multi-subject exam questions across humanities, STEM, and social sciences."
        },
        {
            "name": "HumanEval (Python Code Generation)",
            "domain": "Coding & Syntactic Synthesis",
            "metric": "Pass@1",
            "shots": "0-shot",
            "score": 81.2,
            "score_str": "81.2%",
            "baseline": 74.0,
            "baseline_str": "74.0%",
            "delta_val": 7.2,
            "delta_str": "+7.2% ▲",
            "description": "Hand-crafted Python programming problems with unit test verification."
        }
    ]

    eval_meta = {
        "timestamp": "2026-08-17 14:30:00 UTC",
        "run_id": "run-20260817-prod",
        "baseline_model": "Llama-3-70B-Instruct"
    }

    pdf_bytes = PDFCardRenderer.render(
        manifest=manifest,
        evaluation_records=eval_records,
        evaluation_metadata=eval_meta
    )

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 500
    assert pdf_bytes.startswith(b"%PDF-")


def test_pdf_renderer_fallback_and_markdown_render():
    md_content = """# Model Card: TestModel
## Executive Summary
This is a test model description.

```bibtex
@article{test2026}
```
"""
    pdf_bytes = PDFCardRenderer.render_from_markdown(md_content, title="TestModel")
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 200
    assert pdf_bytes.startswith(b"%PDF-")
