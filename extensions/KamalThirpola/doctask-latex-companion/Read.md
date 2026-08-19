# DocTask — Agentic LaTeX Editing System

DocTask is an agentic LaTeX editing system built for the SuperDocs engineering task.

It allows a user to select a LaTeX section, analyze the document structure, generate an editing proposal, review the proposed changes, approve or reject them, apply approved changes, and export the resulting document.

## What it demonstrates

- Section-aware LaTeX editing
- Preservation of equations, citations, labels, and references
- Analyze → propose → validate → review → apply → export workflow
- Human approval before applying edits
- Persistent workflow state
- Concurrent-edit protection
- Prompt-injection detection for document data
- React review interface
- FastAPI backend
- PostgreSQL/SQLAlchemy persistence
- SuperDocs extension integration

## Project repository

https://github.com/KamalThirpola/docktask-kamal-thirpola

## Demo

The project includes a recorded demonstration showing the main editing and review workflow.

## Status

The core assigned workflow has been implemented and tested. The project includes the backend, frontend, and SuperDocs extension components.

Built for the SuperDocs engineering task.
