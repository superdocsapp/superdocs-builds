"""Tests for HTMLCardRenderer."""

import pytest
from src.html_renderer import HTMLCardRenderer


def test_html_card_renderer_produces_complete_page():
    manifest = {
        "model_name": "Nexus-70B-Instruct",
        "version": "v1.2.0",
        "license": "Apache-2.0",
        "model_type": "Dense Transformer LLM",
        "description": "High-capability reasoning model",
        "intended_purpose": ["Reasoning", "Coding"],
        "limitations": ["Context limited to 128k"],
    }
    
    eval_records = [
        {
            "task_id": "mmlu",
            "name": "MMLU",
            "domain": "General Knowledge & Reasoning",
            "metric": "Accuracy",
            "score": 88.4,
            "score_str": "88.4%",
            "baseline_str": "84.1%",
            "delta_val": 4.3,
            "delta_str": "▲ +4.3%",
            "shots": "5-shot",
            "description": "General reasoning across 57 subjects"
        }
    ]

    html_output = HTMLCardRenderer.render(
        manifest=manifest,
        evaluation_records=eval_records,
        evaluation_metadata={"timestamp": "2026-08-17 12:00:00 UTC", "baseline_model": "Nexus-70B-v1.1"},
        raw_markdown="# Markdown Content"
    )

    assert "<!DOCTYPE html>" in html_output
    assert "Nexus-70B-Instruct" in html_output
    assert "MMLU" in html_output
    assert "88.4%" in html_output
    assert "Outfit" in html_output
    assert "JetBrains Mono" in html_output
