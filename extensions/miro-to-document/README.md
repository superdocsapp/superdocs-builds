# Miro Board to Structured Document

A SuperDocs extension that reads a Miro board through the Miro REST API and converts workshop content into a structured, traceable, styled document.

The extension preserves the relationship between generated content and the original Miro items, supports incremental updates, handles Miro images, generates Markdown and HTML output, and can publish a public document link back to the Miro board.

## What it does

The extension:

1. Fetches items from a Miro board using the Miro REST API.
2. Supports processing the entire board or a selected frame.
3. Groups sticky notes by their parent Miro frame.
4. Detects semantic section names from the content.
5. Removes duplicate sticky notes.
6. Preserves original Miro item IDs for traceability.
7. Preserves vote information when available.
8. Detects and downloads Miro image items.
9. Generates a structured Markdown workshop summary.
10. Generates a styled HTML document.
11. Reuses unchanged sections between runs.
12. Regenerates only sections affected by board changes.
13. Serves the generated HTML through FastAPI.
14. Supports exposing the local document through ngrok.
15. Publishes the generated document URL back onto the Miro board.

## Example

A Miro board containing:

* Customer Problems
* Ideas
* Questions

is converted into:

```text
# Miro Workshop Summary

## Customer Problems

- Checkout is extremely slow
  - Source: Miro sticky note `3458764681061461126`

- Payment sometimes fails
  - Source: Miro sticky note `3458764681061461276`

## Questions

- Why are payments failing?
  - Source: Miro sticky note `3458764681062252495`

## Ideas

- Add Apple Pay
  - Source: Miro sticky note `3458764681061823482`
```

## Architecture

```text
                         Miro Board
                             |
                             v
                       Miro REST API
                             |
                             v
                      miro_parser.py
                             |
                             v
                     Parsed Miro Items
                             |
              +--------------+--------------+
              |                             |
              v                             v
       document_builder.py           Image Extraction
              |                             |
              v                             v
      Structured Sections             output/images/
              |
       +------+------+
       |             |
       v             v
section_detector   Incremental Cache
       |             |
       +------+------+
              |
              v
    document_generator.py
              |
       +------+------+
       |             |
       v             v
    Markdown        HTML
       |             |
       |             v
       |          FastAPI
       |             |
       |             v
       |           ngrok
       |             |
       |             v
       |      Public Document URL
       |             |
       +-------------+
              |
              v
       miro_publisher.py
              |
              v
         Miro Board Link
```

## Project files

### `miro_parser.py`

Fetches Miro board items and converts the API response into a simplified internal representation.

It handles:

* Miro authentication
* API pagination
* HTML cleanup
* item types
* source IDs
* parent frame IDs
* vote information when available
* image-item detection
* image URL extraction

### `document_builder.py`

Builds the structured document.

It:

* collects frames
* attaches sticky notes to their parent frames
* removes duplicate content
* detects semantic section titles
* preserves source IDs
* preserves image information
* builds the internal document structure

### `section_detector.py`

Determines a meaningful section name from the sticky-note content.

Examples:

* Customer Problems
* Questions
* Ideas

This allows generic Miro frame names such as `Frame 1`, `Frame 2`, and `Frame 3` to become meaningful document sections.

### `document_generator.py`

Controls the complete document-generation workflow.

Process the entire board:

```text
python document_generator.py
```

Process a specific frame:

```text
python document_generator.py FRAME_ID
```

The generator:

1. Fetches the Miro board.
2. Parses the board items.
3. Builds structured sections.
4. Detects changed sections.
5. Reuses unchanged sections.
6. Downloads available Miro images.
7. Generates Markdown.
8. Generates styled HTML.

### `html_exporter.py`

Generates the styled HTML version of the workshop document.

The HTML document includes:

* document header
* section cards
* formatted sticky notes
* Miro source IDs
* vote information when available
* embedded/local Miro images
* responsive styling
* generated-document footer

### `miro_publisher.py`

Publishes a generated document URL back onto the configured Miro board.

It creates a Miro text item containing a link to the generated document.

The public URL is supplied through:

```text
DOCUMENT_PUBLIC_URL
```

### `server.py`

Runs a local FastAPI server that serves the generated HTML document.

The generated document can be accessed locally at:

```text
http://127.0.0.1:8000/miro_document.html
```

### `miro_writer.py`

Provides Miro writing functionality used by the extension for writing generated information back to the board.

### `group_items.py`

Provides grouping functionality for board items.

### `board_structure.py`

Provides utilities for inspecting and displaying the Miro board structure.

### `models.py`

Contains simple internal data models.

### `test_miro.py`

Contains basic tests for the Miro extension.

## Incremental updates

The extension stores a section cache at:

```text
output/.section_cache.json
```

Each section receives a SHA-256 fingerprint based on:

* Miro frame ID
* section title
* sticky-note source IDs
* sticky-note content

If a section has not changed, the previously generated content is reused.

Example:

```text
First run:

Customer Problems → generated
Questions         → generated
Ideas             → generated


Second run:

Customer Problems → reused
Questions         → reused
Ideas             → reused


After changing one Customer Problems sticky:

Customer Problems → generated
Questions         → reused
Ideas             → reused
```

This prevents unnecessary regeneration when only a small part of a large workshop board changes.

## Traceability

Every generated sticky note retains its original Miro item ID.

Example:

```text
- Checkout is extremely slow
  - Source: Miro sticky note `3458764681061461126`
```

This allows users to trace generated content back to the exact Miro item from which it originated.

## Image handling

The parser detects Miro image items and extracts their image URLs.

Images are downloaded into:

```text
output/images/
```

Example:

```text
output/
└── images/
    └── 3458764681107614026.jpg
```

The generated HTML document uses the downloaded image so that the document can display the original Miro visual content.

## Configuration

Create a `.env` file in the extension directory:

```text
MIRO_ACCESS_TOKEN=your_miro_access_token
MIRO_BOARD_ID=your_miro_board_id
```

For publishing the generated document:

```text
DOCUMENT_PUBLIC_URL=https://your-public-url/miro_document.html
```

The `.env` file must never be committed to Git.

## Running locally

Activate the Python environment and install the required dependencies.

Then generate the document:

```text
python document_generator.py
```

For a selected frame:

```text
python document_generator.py FRAME_ID
```

To inspect the Miro board structure:

```text
python miro_parser.py
```

## Serving the generated document

Start the FastAPI server:

```text
uvicorn server:app --reload
```

The document is then available locally at:

```text
http://127.0.0.1:8000/miro_document.html
```

## Exposing the document publicly

For a Miro board link to open the generated document from outside the local machine, the local FastAPI server can be exposed using ngrok.

Start the server:

```text
uvicorn server:app --reload
```

In another terminal:

```text
ngrok http 8000
```

ngrok provides a public URL similar to:

```text
https://example.ngrok-free.dev
```

The generated document URL becomes:

```text
https://example.ngrok-free.dev/miro_document.html
```

## Publishing the document link back to Miro

Set the public document URL:

```powershell
$env:DOCUMENT_PUBLIC_URL="https://example.ngrok-free.dev/miro_document.html"
```

Then run:

```text
python miro_publisher.py
```

The extension creates a text item on the configured Miro board containing a link to the generated document.

The resulting workflow is:

```text
Miro Board
    ↓
Generate Document
    ↓
FastAPI
    ↓
ngrok
    ↓
Public URL
    ↓
miro_publisher.py
    ↓
Link added back to Miro
```

## Output

Generated files are written to:

```text
output/
```

The main outputs are:

```text
output/
├── miro_document.md
├── miro_document.html
├── .section_cache.json
└── images/
```

### Markdown

The Markdown document is:

```text
output/miro_document.md
```

### HTML

The styled document is:

```text
output/miro_document.html
```

The HTML version is intended to be the primary human-readable document for the demo.

## Miro API

The extension uses the Miro REST API to:

* retrieve board items
* inspect frames and sticky notes
* retrieve image information
* create text items containing the generated document link

Authentication is performed using a Miro access token stored in `.env`.

## Voting

The parser preserves vote information when it is exposed by the Miro API response.

If the API does not provide vote information for an item, the extension does not fabricate a vote count.

## Current limitations

### Miro authentication

A valid Miro access token and board ID are required.

### Public hosting

The FastAPI server is intended for local development and demonstration.

ngrok is used to temporarily expose the generated document publicly.

For production usage, the generated document should be hosted using a persistent deployment instead of a local ngrok tunnel.

### Vote availability

Generic board voting information is not always exposed as a standard field in the Miro `/items` API response.

The extension therefore preserves vote information when available but does not invent missing values.

## Security

Credentials are loaded from environment variables.

Never commit:

```text
.env
```

or any Miro access token.

The repository `.gitignore` excludes:

```text
.env
.venv/
__pycache__/
*.pyc
output/
```

Generated documents, downloaded images, caches, Python environments, and credentials therefore remain outside the Git repository.

## End-to-end demo

The complete demonstrated workflow is:

```text
1. Create/update content in Miro
             ↓
2. Fetch board through Miro REST API
             ↓
3. Parse and structure board items
             ↓
4. Detect semantic sections
             ↓
5. Deduplicate content
             ↓
6. Detect changed sections
             ↓
7. Reuse unchanged sections
             ↓
8. Download Miro images
             ↓
9. Generate Markdown + styled HTML
             ↓
10. Serve HTML with FastAPI
             ↓
11. Expose through ngrok
             ↓
12. Publish public document URL to Miro
             ↓
13. Open generated document directly from Miro
```

This provides an end-to-end Miro-to-structured-document workflow with traceability, incremental updates, visual content support, and publish-back integration.
