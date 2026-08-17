# Task 2A — Short-Term Rental House Manual & Listing Pack

## 1. Overview

This project demonstrates how a single property record acts as the source of truth to generate multiple artifacts for short-term rental operations.

Using the canonical property content, the project generates:
* Guest Manual
* Listing Description
* Welcome Card

Core design principle:

```text
Property-specific content
        +
Reusable shared blocks
        ↓
Canonical property content
        ↓
Document generation
        ↓
SuperDocs MCP
        ↓
Exported document
```

## 2. Problem Being Solved

Property-management operators often maintain the same rules and policies (e.g., quiet hours, checkout procedures, and no-smoking policies) across multiple properties. Maintaining these rules individually across each property's documentation leads to inconsistencies and duplicated effort.

This project solves this by using **shared blocks**. Updating a single shared block (e.g., changing quiet hours from 7 AM to 8 AM) automatically updates every property manual referencing that block. 

Meanwhile, bespoke property-specific information (such as Wi-Fi credentials, appliance instructions, photographs, and local recommendations) remains completely independent.

## 3. Architecture

The architecture separates local content generation from remote SuperDocs MCP operations.

```text
Mock Property Data
        │
        ▼
Canonical Content Generator
        │
        ├──────────────┐
        ▼              ▼
 Guest Manual       Listing
        │
        ▼
 Welcome Card
        │
        ▼
 HTML Document
        │
        ▼
 SuperDocs MCP
        │
        ├── Upload / Ingest
        ├── Async Chat / Editing
        ├── Approval
        └── Export
        │
        ▼
       PDF
```

### Offline Python responsibilities
* Data models
* Mock property records
* Shared blocks
* Canonical content assembly
* Document generation (HTML/text artifacts)
* Image embedding (Base64)
* Validation and offline tests

### SuperDocs responsibilities
* Document ingestion
* AI-assisted async editing
* Human approval
* Document export to PDF

## 4. Data Model

The project strictly separates property data from shared blocks:

* `Property`: Holds property-specific information, references to `Appliance`, `LocalRecommendation`, `Photo`, `MapDiagram`, and references to `SharedBlock` IDs.
* `SharedBlock`: Holds reusable rules/policies, version tracking, and language variants.
* `Appliance`: Holds instructions for specific appliances.
* `LocalRecommendation`: Holds location recommendations.
* `Photo`: Represents a real property photograph.
* `MapDiagram`: Represents a printable local wayfinding diagram.
* `PropertyCatalog`: In-memory source of truth combining properties and shared blocks.

```text
Property
 ├── property-specific information
 ├── appliances
 ├── recommendations
 ├── photos
 ├── map
 └── references to SharedBlocks

SharedBlock
 ├── reusable rule/policy
 ├── version
 └── language variants
```

## 5. Example Properties

The repository contains two mock properties demonstrating the shared-block architecture. 

**Note: All passwords and credentials included in the source code are MOCK/DEMO data.**

### Green Residency
A 2-bedroom apartment in Bangalore showcasing standard property-specific data including mock Wi-Fi credentials, appliances (e.g., washing machine, air conditioner), emergency contacts, and mock property photographs.

### Blue Residency
A 3-bedroom villa in Mysore. It exists to demonstrate that two different properties can reference the exact same shared blocks (like quiet hours and checkout policies) while retaining independent property-specific content (different Wi-Fi, appliances, and photos).

## 6. Shared Block Propagation

When a shared block is updated, the canonical content is assembled dynamically using the updated block, ensuring changes propagate without touching property-specific data.

```text
Shared Block:
Quiet hours = 10 PM – 7 AM

        ↓ update once

Quiet hours = 10 PM – 8 AM

        ↓

Green Residency → updated
Blue Residency  → updated

Green Wi-Fi     → unchanged
Blue Wi-Fi      → unchanged
```

## 7. Generated Outputs

The offline preview command writes generated artifacts to the local directory:

```text
output/
└── preview/
    ├── manual.html
    ├── listing.txt
    └── welcome_card.html
```

* `manual.html`: The HTML representation of the branded guest house manual, which is ultimately uploaded to SuperDocs.
* `listing.txt`: The platform-ready plain-text listing description.
* `welcome_card.html`: A printable HTML welcome card containing essential arrival data.

The live MCP workflow generates the final PDF directly from SuperDocs (not saved locally).

## 8. Images and Map

The Guest Manual includes real property photographs and a local wayfinding map diagram.

All images are embedded directly into the HTML as **Base64 data URIs**. This is critical because the final document is sent to the remote SuperDocs MCP service, meaning the HTML cannot rely on local filesystem references (`assets/green_residency/exterior.jpg`).

*Note: By embedding valid base64 data URIs, the HTML is completely self-contained.*

## 9. Multilingual Generation

The architecture supports dynamic multilingual document generation. The mock catalog includes support for:

* English (`en`)
* Kannada (`kn`)

```text
same property
      ↓
language="en"
      ↓
English manual

same property
      ↓
language="kn"
      ↓
Kannada manual
```

When a translated language is requested, the canonical generator overrides English fields with the matching localized variants. Structural data, images, and non-localized fields fall back safely.

## 10. SuperDocs MCP Workflow

The live workflow utilizes SuperDocs MCP tools to process the generated manual:

```text
1. Generate canonical content
2. Generate HTML (embedding base64 images)
3. Upload/ingest through SuperDocs (`upload_document_base64`)
4. Request an async AI edit (`chat_async`)
5. Wait for approval when using human-in-the-loop mode
6. Approve the proposed change (`approve_change`)
7. Export the final document (`export_document`)
```

The actual SuperDocs MCP tools used are:
* `upload_document_base64`
* `chat_async`
* `approve_change`
* `export_document`

## 11. Human-in-the-Loop Example

The SuperDocs client implementation demonstrates an asynchronous, human-in-the-loop editing pattern:

```text
Original:
Quiet hours are from 10 PM to 7 AM.

Proposed:
Quiet hours are from 10 PM to 8 AM.

       ↓

awaiting_approval (PendingChange)

       ↓

approve_change (explicit human action)

       ↓

completed
```

The document remains unchanged until the pending proposal is explicitly approved.

## 12. Installation

* Python 3.x
* SuperDocs MCP access for live operations

Create and activate a virtual environment (depending on your OS):

**macOS / Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
```

**Windows PowerShell:**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## 13. Environment Variables

Running the live SuperDocs workflow requires an API key. 


```env
SUPERDOCS_API_KEY=your-superdocs-api-key
```

Preview mode works entirely offline and requires no environment variables.

## 14. Running Offline Preview

To generate the canonical content, embed images, and write the artifacts locally (without contacting SuperDocs):

```bash
python generate_all.py --preview
```

This ensures the generated HTML, listing, and welcome card are built and validated offline.

## 15. Running the Live SuperDocs Workflow

To run a live upload and export using a configured MCP invoker:

```bash
python generate_all.py --live --mcp-invoker your_module:your_invoker_function
```

This requires an active MCP connection and `SUPERDOCS_API_KEY` to be set. It outputs the document ID, session ID, version, and the final PDF export result.

## 16. Tests

Run the test suite using pytest:

```bash
pytest
```

The tests cover:
* Canonical content generation
* Shared block resolution
* Property-specific data assembly
* Document generation logic
* Base64 Image and Map embedding validation
* Models structure

## 17. Example End-to-End Workflow

```text
Green Residency
       ↓
canonical content
       ↓
manual.html
listing.txt
welcome_card.html
       ↓
SuperDocs MCP
       ↓
document session
       ↓
AI edit (async)
       ↓
human approval
       ↓
export
       ↓
PDF
```

## 18. Project Structure

```text
task2a/
├── assets/
│   ├── blue_residency/
│   └── green_residency/
├── output/
│   └── preview/
├── tests/
│   ├── test_content_generator.py
│   ├── test_document_generator.py
│   ├── test_embedded_images_are_valid_images.py
│   └── test_models.py
├── content_generator.py
├── document_generator.py
├── generate_all.py
├── generate_listing.py
├── generate_manual.py
├── generate_welcome_card.py
├── listing_generator.py
├── mock_data.py
├── models.py
├── shared_content_demo.py
├── superdocs_client.py
├── welcome_card_generator.py
└── workflow.py
```

## 19. Known Limitations

* Uses mock property data in-memory rather than connecting to a production property database.
* Uses demo photographs instead of full-size production assets.
* Live SuperDocs export requires active API credentials.
* The local preview generation provides HTML files, but the final PDF must be exported from the SuperDocs workflow.

## 20. SuperDocs Features Demonstrated

| Feature                          | Demonstrated |
| -------------------------------- | ------------ |
| Document ingestion               | Yes          |
| Chat editing                     | No           |
| Async editing                    | Yes          |
| Human approval                   | Yes          |
| Export                           | Yes          |
| MCP                              | Yes          |
| Multilingual document generation | Yes          |
| Multi-document generation        | Yes          |
| Image handling                   | Yes          |
| Shared content propagation       | Yes          |

## 21. Demo / Deployment

> Demo: Local Python/MCP workflow. No public deployment is required for this use-case.

## 22. Security

* Never commit API keys or bearer tokens.
* Mock credentials used in `mock_data.py` are clearly labelled as demonstration data.
* Use placeholders in documentation.
* The workflow relies on secure backend communication and does not persist secrets locally.

## 23. License / Attribution

This project is licensed under the MIT License.
