# SuperDocs Builds

**Credit Line:** I built this for the SuperDocs engineering task.

This folder contains two integrations built ON the SuperDocs API (Task 2):
1. **Screening to Clearance Letter Pack** (`superdocs_client.py`): The assigned build for the fitness/wellness use case.
2. **The Continuity Keeper** (`continuity_keeper_client.py`): The ambitious original tool (Extra Credit) designed for authors writing 1,000-page novels.

## Screenshots
![Continuity Keeper Demo](../docs/continuity_keeper_demo.png)
*(Note: Replace with actual screenshot link when uploading to GitHub)*

## Ambiguities and Assumptions
- **Mocking the API:** Since the real API endpoint `api.superdocs.app` was unavailable during development, I mocked the `requests` calls to strictly adhere to the contract (Upload -> Chat -> Approve -> Export). 
- **Formats and Domains:** These integrations accept `.txt` and `.docx` files. The domain for the Assigned Build is **Fitness/Medical Clearance**, and for the Extra Credit it is **Literary Editing / Novel Writing**.

## How to Run
Ensure your `.env` file at the root contains:
`SUPERDOCS_API_KEY=your_api_key_here`

Run the assigned build:
```bash
python superdocs_client.py
```

Run the Extra Credit build:
```bash
python continuity_keeper_client.py
```
