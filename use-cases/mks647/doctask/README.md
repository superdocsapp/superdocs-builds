# DocTask

## Open-Source Governance Pack Generator

DocTask is a full-stack web application that helps open-source project maintainers create and manage a basic governance document pack from one place.

Instead of creating common governance files one by one, a user can enter project information, generate the documents, review them, and download the files individually or as a ZIP archive.

## What It Does

DocTask provides a simple workflow:

1. Create a governance project.
2. Enter and validate project information.
3. Generate the governance documents.
4. Review the generated documents.
5. Download individual Markdown files.
6. Download the complete governance pack as a ZIP file.
7. Delete projects when they are no longer needed.

## Key Features

- Create governance projects
- Store projects in a database
- Validate project information
- Prevent duplicate project names
- Generate governance documents
- View generated documents
- Download individual Markdown documents
- Download the complete governance pack as a ZIP file
- Delete projects with confirmation
- Responsive web interface

## Generated Governance Documents

For each project, DocTask can generate:

- `CODE_OF_CONDUCT.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `MAINTAINERS.md`
- `CLA.md`
- `RELEASE_POLICY.md`

These documents provide a reusable starting point for common open-source project governance needs.

## Why DocTask?

When a project is opened to external contributors, maintainers often need several governance documents.

Creating these files manually can be repetitive and may result in missing or inconsistent information.

DocTask collects the basic project information once and uses it to generate a consistent set of governance documents.

## Technology Stack

### Frontend

- React
- Axios
- CSS

### Backend

- Python
- FastAPI
- SQLAlchemy
- Pydantic

### Database

- SQLite

### Document Generation

- Python-based document generation
- Markdown documents
- ZIP archive export

## Architecture

```text
                         User
                           |
                           v
                   React Frontend
                           |
                         Axios
                           |
                           v
                    FastAPI Backend
                           |
                  +--------+--------+
                  |                 |
                  v                 v
              SQLite DB     Document Generator
                                    |
                                    v
                           Governance Documents
                                    |
                           +--------+--------+
                           |                 |
                           v                 v
                       Markdown             ZIP