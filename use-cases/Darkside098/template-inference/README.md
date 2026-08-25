# SuperDocs Template Inference

## Overview

This project infers document families, shared structure, fixed sections, variable fields, section ordering, conditional sections, and conditional rules from finished documents rather than relying on predefined templates or benchmark labels. The system works from observed document structure and content, then normalizes those observations into a machine-readable template representation.

## Current Status

The inference pipeline and the DOCX regeneration/fidelity layers are implemented and validated.

- 304 tests passing
- DOCX ingestion implemented
- DOCX regeneration implemented
- formatting-aware regeneration implemented
- fidelity comparison implemented

This branch does not currently implement PDF ingestion or a dedicated template-inference API endpoint.

## Architecture

Finished Documents
→ Document Ingestion
→ Normalized Document
→ Document Profiling
→ Family Compatibility
→ Family Clustering
→ Template Inference
→ Evaluation
→ DOCX Regeneration
→ Fidelity Comparison

Each stage contributes evidence and structure to the next stage:

- Document Ingestion converts source files into a normalized, format-independent representation.
- Document Profiling extracts structural, content, formatting, and section-boundary signals.
- Family Compatibility measures how similar two documents are based on observable evidence.
- Family Clustering groups compatible documents into candidate families.
- Template Inference derives shared sections, variables, ordering, and conditional rules from family-level evidence.
- Evaluation measures inference quality separately from the inference pipeline.
- DOCX Regeneration turns an inferred template and explicit values into a source-specific output document.
- Fidelity Comparison evaluates how closely the regenerated output aligns with the source-related expectations and calls out unsupported or unknown formatting explicitly.

## Repository Structure

The repository is organized around a modular Python package and a small benchmark/test surface:

- superdocs_template_inference/
  - ingestion/
  - models/
  - profiling/
  - compatibility/
  - clustering/
  - template_inference/
  - evaluation/
- tests/
- corpus/
- evaluation/

The major modules are organized by purpose: ingestion and normalization, profiling, compatibility, clustering, template inference, evaluation, and regeneration.

## Core Capabilities

### Document Ingestion

The ingestion layer reads DOCX documents and converts them into a normalized document representation that is independent of the original file format. It preserves paragraph order, extracts table content, identifies headings when reasonably detectable, preserves list-related metadata when available, and returns a consistent internal model for downstream stages.

### Document Profiling

The profiling layer produces structured observations about each normalized document, including structural statistics, text content signals, formatting metadata, and generic section boundaries. The goal is to capture useful evidence without assuming benchmark-specific families or section names.

### Family Compatibility and Clustering

Compatibility scoring compares two document profiles using multiple observable signals, such as structure, headings, section patterns, vocabulary overlap, tables, and document length. Clustering then groups compatible documents into candidate families without relying on filenames as the primary identification mechanism.

### Template Inference

The template inference layer derives a reusable template from clustered family documents. It identifies:

- semantic sections
- document-aware sections
- deduplicated section boundaries
- ordering and placement
- required and optional classification
- variable fields
- semantic roles for variables
- variable type inference
- conditional sections and rules

These inferences are evidence-based and are normalized before they become part of the final inferred template.

### Evaluation

Evaluation remains separate from the inference pipeline. Ground-truth files are used only for assessment and are not part of the inference logic or template generation path. The design keeps evaluation distinct from the underlying inference process and does not hard-code benchmark answers into the implementation.

### DOCX Regeneration

The DOCX regeneration component consumes a TemplateInferenceResult and a values dictionary generated for a source-specific document. It uses the inferred template to generate content in the correct section order, respects conditional logic for true/false branches, preserves required sections, and reports missing or unsafe values instead of inventing them. If template information is insufficient, regeneration is skipped with explicit warnings rather than fabricating content.

### Formatting Preservation

Available formatting metadata can be carried through regeneration when it is present in the normalized document model. This includes:

- heading style and level
- font name and size where available
- bold, italic, and underline where available
- alignment
- spacing and indentation where available
- list and table-related structure where available

This is conservative formatting preservation, not a claim of pixel-perfect Word rendering.

### Fidelity Comparison

The fidelity layer compares regenerated output against source-related expectations using structured signals and explicitly reports unsupported or unknown formatting rather than fabricating missing details. The comparison is designed to be conservative and honest: it compares what the normalized representation can support instead of asserting perfect visual equivalence.

## Running the Project

Use the repository’s Python environment and project dependencies, then run:

```bash
python -m pytest -q
```

The project relies on a Python virtual environment and the repository’s requirements.txt for dependency management. There is currently no dedicated template-inference API application entry point in this branch.

## Validation

The current repository validation status is:

```text
304 passed
```

The validation set includes the project’s test suite, benchmark and integration checks, and regeneration-specific regression coverage. The repository also keeps `git diff --check` clean.

## Limitations

- PDF loader is not currently implemented.
- No dedicated template-inference API endpoint is currently implemented.
- Formatting preservation depends on metadata available through the normalized document model.
- Unsupported deep Word formatting is not fabricated.
- Fidelity comparison should be interpreted as structured and conservative rather than pixel-perfect visual equivalence.

## Ground Truth and Security

- Ground-truth files are evaluation-only and are not part of the inference pipeline.
- Inference must not use ground-truth JSON as an input dependency.
- Benchmark answers are not hard-coded into inference logic.
- `.env` must not be committed.
- `.venv` must not be committed.
- API secrets or other sensitive values must never be exposed in source code.

## Development Principles

The implementation follows a conservative and maintainable engineering approach:

- modular
- deterministic where practical
- testable
- explainable
- conservative when information is unavailable

These principles help preserve the separation between observation, inference, evaluation, and regeneration while keeping the project robust to document variation.
