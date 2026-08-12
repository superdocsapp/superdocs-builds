# eCTD Module 2 Summary Assembler

An orchestration script that automates the drafting of clinical summaries (eCTD Module 2) by extracting and citing facts from Module 5 study reports. 

## Features Used
- SuperDocs REST API (Upload, Chat Async, Approve, Export)
- Multi-document sessions and attachments
- Human-in-the-loop (HITL) review

## Setup and Running
1. Create virtual environment: `python3 -m venv venv`
2. Activate it: `source venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Generate test data: `python generate_test_data.py`
5. *(Coming soon: run the orchestrator script)*
