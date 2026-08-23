# Material-Change Analysis Between Versions

Built for the SuperDocs task.

## Use Case
**Legal & Procurement** — Automated detection of substantive contractual changes between two versions of an agreement.

## Overview
Reviewing redlines across lengthy contracts is time-consuming and error-prone. This application automates legal risk and obligation comparisons across two contract versions:

- **Distinguishes Material Changes from Formatting**: Filters out styling, typographical, or cosmetic edits to focus exclusively on substantive legal clauses (e.g., liability caps, indemnification, payment terms, intellectual property, termination rights).
- **Determines Party Advantage**: Identifies which party benefits from each material change and details the specific risk shift.
- **Generates Pushback Points**: Formulates concrete negotiation talking points and redline counter-proposals for the disadvantaged party.
- **Dual Pipeline Integration**: Provides full implementations via both the **SuperDocs MCP Server** (`main_mcp.py`) and the **SuperDocs REST API** (`main.py`).

---

## The 4-Step Pipeline

| Step | MCP Tool / REST Endpoint | Purpose |
| :--- | :--- | :--- |
| **1. Upload** | `upload` / `POST /documents/upload` | Ingests baseline (`contract_v1.txt`) and revised (`contract_v2.txt`) agreements. |
| **2. Chat** | `chat` / `POST /chat` | Dispatches instructions to compare versions, isolate legal risk shifts, and structure findings. |
| **3. Approve** | `approve` / `POST /approve` | Programmatically confirms and commits the proposed findings. |
| **4. Export** | `export` / `POST /export` | Generates the final structured legal brief (`final_material_change_brief.md`). |

---

## Handling Founder Traps & Edge Cases

1. **The JSON Double-Parse Trap**:
   SuperDocs API/MCP responses may contain nested JSON-encoded strings within dictionary or list fields. Both pipelines use `deep_parse()` to recursively unwrap stringified JSON objects at any arbitrary depth, preventing unexpected `KeyError` or type errors.

2. **The Timeout Trap**:
   Deep document analysis can take anywhere from 30 seconds to several minutes on large agreements. The clients avoid aggressive HTTP read timeouts, employing patient status polling (`poll_until_ready`) with a generous 10-minute ceiling.

3. **Budget Guard & Loop Control**:
   `SMALL_SAMPLE_MODE` and `MAX_TOOL_CALLS` / `MAX_OPERATIONS` enforce a strict upper limit on API operations during development and testing to prevent burning token budgets.

---

## Setup & Installation

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy the environment template and insert your `SUPERDOCS_API_KEY`:
```bash
cp .env.example .env
```

`.env` configuration options:
```ini
SUPERDOCS_API_KEY=your_actual_api_key_here
SUPERDOCS_MCP_URL=https://api.superdocs.app/mcp/sse
SUPERDOCS_BASE_URL=https://docs.superdocs.app/api
SMALL_SAMPLE_MODE=true
MAX_TOOL_CALLS=5
MAX_OPERATIONS=5
```

### 3. Provide Sample Contracts
Sample synthetic contracts are provided in `sample_data/`:
- `sample_data/contract_v1.txt`: Baseline MSA (Net 30, 1x liability cap, standard gross negligence indemnity).
- `sample_data/contract_v2.txt`: Revised MSA (Net 60, 3x liability cap, strict indemnity).

---

## Execution

### Run via Model Context Protocol (MCP) [Recommended]
```bash
python main_mcp.py
```

### Run via REST API
```bash
python main.py
```

The final analysis deliverable will be generated and saved to `final_material_change_brief.md`.

---

## Submitter Information
- **Submitter**: Saket Bhadada
- **Use Case**: Material-change analysis between versions (Legal & Procurement)
- **Folder**: `use-cases/saket-bhadada-material-change/`
- Built for the SuperDocs task.
