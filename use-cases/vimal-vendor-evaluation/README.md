# Vendor Response Evaluation Report Pipeline

**Built for the SuperDocs Round 2 Engineering Task.**
**Candidate:** Vimal Anand

## Overview
This use-case demonstrates how to build a Multi-Vendor RFP Evaluation Engine ON the SuperDocs platform. It utilizes the core SuperDocs API contract (Upload -> Chat/Instruct -> Approve -> Export) to automatically compare vendor responses against a master requirement set.

## Features
- **Anti-Hallucination:** Explicitly instructed to flag missing answers as gaps rather than inferring compliance.
- **Human-in-the-Loop (HITL):** Pauses for human approval on the comparison matrix before finalizing the export.
- **Traceability:** Forces the agent to cite the exact vendor wording for every score.

## My Complete Task 1 Architecture
While this script demonstrates the integration against the SuperDocs API (Task 2), my complete, fully-dockerized orchestration engine with LangGraph, PostgreSQL (pgvector), and a FastMCP server is hosted in my private repository (`doctask-vimal-anand`) as per the Task 1 instructions. 

*Omkar, an invite to the private repository has been sent to your GitHub account (o-kadam).*